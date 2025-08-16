import os
import re
import json
import inspect
import asyncio
from datetime import datetime
from glob import glob
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets._tree import TreeNode
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Markdown,
    TabbedContent,
    TabPane,
    TextArea,
    Tree,
)

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI()

HISTORY_DIR = "chat_history"

# ---------- Utilities ----------
SESSION_PATTERN = re.compile(r"^chat_(\d{3})\.jsonl$")


def ensure_history_dir() -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)


def list_session_ids() -> list[str]:
    ensure_history_dir()
    ids = []
    for path in glob(os.path.join(HISTORY_DIR, "chat_*.jsonl")):
        name = os.path.basename(path)
        m = SESSION_PATTERN.match(name)
        if m:
            ids.append(f"chat_{m.group(1)}")
    ids.sort(key=lambda s: int(s.split("_")[1]))
    return ids


def next_session_id() -> str:
    ids = list_session_ids()
    if not ids:
        return "chat_001"
    last = ids[-1]
    n = int(last.split("_")[1]) + 1
    return f"chat_{n:03d}"


def session_file(session_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{session_id}.jsonl")


class CopyScreen(ModalScreen[None]):
    """Read-only viewer for selecting & copying chat text."""

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title = title
        self._text = text

    def compose(self):
        from textual.containers import Vertical, Horizontal
        from textual.widgets import Label, Button, TextArea

        with Vertical(id="copy_modal"):
            yield Label(f"Copy from: {self._title}", id="copy_title")
            yield TextArea(id="copy_area")  # we’ll set read_only in on_mount
            with Horizontal(id="copy_buttons"):
                yield Button("Copy All", id="copy_all")
                yield Button("Close", id="copy_close")

    async def on_mount(self) -> None:
        ta = self.query_one("#copy_area", TextArea)
        ta.read_only = True  # keyboard selection works; no edits
        ta.text = self._text
        ta.focus()

    async def on_button_pressed(self, event) -> None:
        bid = event.button.id or ""
        if bid == "copy_all":
            # Use Textual’s clipboard API (may be unsupported in some terminals)
            try:
                self.app.copy_to_clipboard(self._text)  # may no-op on some terminals
                self.app.notify("All text copied to clipboard.")
            except Exception as exc:
                self.app.notify(f"Clipboard not supported here: {exc}", severity="warning")
        elif bid == "copy_close":
            self.dismiss()


class TerGptApp(App):
    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("ctrl+t", "toggle_dark", "Toggle dark mode"),
        ("ctrl+enter", "send", "Send"),
        ("ctrl+n", "new_tab", "New Chat"),
        ("ctrl+w", "close_tab", "Close Chat"),
        ("f2", "rename_tab", "Rename Chat"),
        ("ctrl+shift+c", "copy_mode", "Copy mode"),
    ]

    views: dict[str, VerticalScroll]      # session_id -> chat view
    tree_nodes: dict[str, "TreeNode"]     # session_id -> tree node (runtime only)
    _last_tree_sid: Optional[str] = None  # last selected in tree (for Delete)

    # Guard for *programmatic* Tree selection so it won't retrigger our handler
    _syncing_ui: bool = False

    # ---------- Layout ----------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Tree("Chats", id="chat_tree")
                with Horizontal(id="sidebar_buttons"):
                    # labels + theme variants
                    yield Button("new", id="btn_new", variant="success")
                    yield Button("delete", id="btn_delete", variant="error")
            with Vertical(id="main"):
                yield TabbedContent(id="tabs")
                yield TextArea(id="in")
        yield Footer()

    async def on_mount(self) -> None:
        self.views = {}
        self.tree_nodes = {}
        ensure_history_dir()

        tabs = self.query_one("#tabs", TabbedContent)
        tree: Tree[str] = self.query_one("#chat_tree", Tree)
        tree.root.expand()

        existing = list_session_ids()

        # Silence Tree handler while we wire up initial state
        self._syncing_ui = True
        try:
            if existing:
                for sid in existing:
                    await self._create_tab_for_session(sid, switch=False, load_history=True)
                    self._add_tree_node_for_session(sid, label=sid)
                tabs.active = existing[-1]
                self._select_tree_node(existing[-1])  # silent due to _syncing_ui
            else:
                sid = next_session_id()
                open(session_file(sid), "a", encoding="utf-8").close()
                await self._create_tab_for_session(sid, switch=True, load_history=False, welcome=True)
                self._add_tree_node_for_session(sid, label=sid)
                self._select_tree_node(sid)  # silent due to _syncing_ui
        finally:
            self._syncing_ui = False

    # ---------- Modifier helper ----------
    @staticmethod
    def _has_ctrl(event: events.Key) -> bool:
        if getattr(event, "ctrl", False) or getattr(event, "control", False):
            return True
        mods = getattr(event, "modifiers", None)
        if isinstance(mods, (set, list, tuple)):
            mods = {str(m).lower() for m in mods}
            return "ctrl" in mods or "control" in mods
        return False

    # ---------- Keys ----------
    async def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "return") and self._has_ctrl(event):
            event.stop()
            await self.action_send()

    # ---------- Tree (single source of truth) ----------
    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        # Ignore root and any *programmatic* selections
        if event.node.is_root or self._syncing_ui:
            return

        sid = (event.node.data or "").strip() if hasattr(event.node, "data") else ""
        if not sid:
            return

        self._last_tree_sid = sid
        tabs = self.query_one("#tabs", TabbedContent)
        if tabs.active == sid:  # already active, nothing to do
            return

        # If pane doesn't exist (was closed), recreate from history
        if self.get_pane(sid) is None:
            await self._create_tab_for_session(sid, switch=True, load_history=True)
        else:
            tabs.active = sid

        # DO NOT reselect the tree here; Tree is the one that initiated the change

    # ---------- Buttons ----------
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn_new":
            await self.action_new_tab()
        elif bid == "btn_delete":
            sid = self._last_tree_sid or self._active_session_id()
            if sid:
                await self._permanently_delete_chat(sid)

    # ---------- Tab management ----------
    async def action_new_tab(self) -> None:
        sid = next_session_id()
        open(session_file(sid), "a", encoding="utf-8").close()
        await self._create_tab_for_session(sid, switch=True, load_history=False, welcome=True)
        self._add_tree_node_for_session(sid, label=sid)
        # Set Tree selection *silently* (won't re-trigger handler)
        self._syncing_ui = True
        try:
            self._select_tree_node(sid)
        finally:
            self._syncing_ui = False

    async def action_close_tab(self) -> None:
        """Ctrl+W: permanently delete the current chat (tab, tree node, and JSON)."""
        sid = self._active_session_id()
        if sid:
            await self._permanently_delete_chat(sid)


    async def action_rename_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        sid = tabs.active
        if not sid:
            return
        ta = self.query_one("#in", TextArea)
        raw = ta.text.strip()
        new_title = raw if raw else f"Chat {datetime.now().strftime('%b %d, %H:%M')}"
        if raw:
            ta.clear()
        pane = self.get_pane(sid)
        if pane is not None:
            try:
                pane.title = new_title
                node = self.tree_nodes.get(sid)
                if node:
                    node.set_label(new_title)
            except Exception:
                self._system_bubble(sid, f"_Rename not supported. Suggested name: **{new_title}**_")

    def get_pane(self, session_id: str) -> Optional[TabPane]:
        tabs = self.query_one("#tabs", TabbedContent)
        for p in tabs.query(TabPane):
            if p.id == session_id:
                return p
        return None

    async def _create_tab_for_session(
        self,
        session_id: str,
        *,
        switch: bool,
        load_history: bool,
        welcome: bool = False,
        title: Optional[str] = None,
    ) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        pane = TabPane(title or session_id, id=session_id)
        try:
            result = tabs.add_pane(pane)  # may be awaitable
            if inspect.isawaitable(result):
                await result
        except Exception:
            await tabs.mount(pane)

        view = VerticalScroll(id=f"view_{session_id}", classes="chat")
        await pane.mount(view)

        if switch:
            tabs.active = session_id

        self.views[session_id] = view

        if load_history:
            await self.load_history(session_id)
        elif welcome:
            self.add_message("system", "_New chat started. Press Ctrl+Enter to send._", session_id=session_id)

    # ---------- Tree helpers ----------
    def _add_tree_node_for_session(self, session_id: str, label: str) -> None:
        tree: Tree[str] = self.query_one("#chat_tree", Tree)
        node = tree.root.add_leaf(label, data=session_id)  # Tree API
        self.tree_nodes[session_id] = node
        tree.root.expand()

    def _select_tree_node(self, session_id: str) -> None:
        """Programmatically select node (caller must set _syncing_ui around this)."""
        tree: Tree[str] = self.query_one("#chat_tree", Tree)
        node = self.tree_nodes.get(session_id)
        if node:
            tree.select_node(node)
            self._last_tree_sid = session_id

    async def _remove_tree_node(self, session_id: str) -> None:
        node = self.tree_nodes.pop(session_id, None)
        if node:
            try:
                node.remove()
            except Exception:
                pass
        tree: Tree[str] = self.query_one("#chat_tree", Tree)
        children = list(tree.root.children)
        if children:
            # Programmatic select next one silently
            self._syncing_ui = True
            try:
                tree.select_node(children[0])
                self._last_tree_sid = children[0].data or children[0].label
            finally:
                self._syncing_ui = False
        else:
            self._syncing_ui = True
            try:
                tree.select_node(None)
                self._last_tree_sid = None
            finally:
                self._syncing_ui = False

    # ---------- Close vs. Permanent delete ----------
    async def _close_tab_only(self, session_id: str) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        panes = list(tabs.query(TabPane))
        if len(panes) <= 1:
            self._system_bubble(session_id, "_Can't close the last chat. Create a new one first (Ctrl+N)._")
            return

        try:
            idx = next(i for i, p in enumerate(panes) if p.id == session_id)
        except StopIteration:
            idx = 0
        new_idx = idx + 1 if idx < len(panes) - 1 else idx - 1
        new_active = panes[new_idx].id

        try:
            result = getattr(tabs, "remove_pane")(session_id)
            if inspect.isawaitable(result):
                await result
        except Exception:
            pane = next((p for p in panes if p.id == session_id), None)
            if pane is not None:
                try:
                    pane.remove()
                except Exception:
                    pass

        self.views.pop(session_id, None)

        remaining = [p.id for p in tabs.query(TabPane)]
        if remaining:
            active_id = new_active if new_active in remaining else remaining[0]
            tabs.active = active_id
            # Programmatically sync the Tree (silent)
            self._syncing_ui = True
            try:
                self._select_tree_node(active_id)
            finally:
                self._syncing_ui = False

        try:
            self.query_one("#in", TextArea).focus()
        except Exception:
            pass

    async def _permanently_delete_chat(self, session_id: str) -> None:
        """Delete the chat everywhere: close its tab, remove its tree node, and delete its JSON file.

        If it's the last remaining tab, first create a fresh empty chat so the UI stays valid.
        """
        tabs = self.query_one("#tabs", TabbedContent)

        # If this is the only tab, create a new empty chat first so we can safely remove the old one.
        panes = list(tabs.query(TabPane))
        if len(panes) <= 1:
            new_sid = next_session_id()
            open(session_file(new_sid), "a", encoding="utf-8").close()
            # create + switch to the new chat
            await self._create_tab_for_session(new_sid, switch=True, load_history=False, welcome=True)
            self._add_tree_node_for_session(new_sid, label=new_sid)
            # silently align the tree selection to the new chat
            self._syncing_ui = True
            try:
                self._select_tree_node(new_sid)
            finally:
                self._syncing_ui = False

        # Now close the pane for the session we are deleting (neighbor will become active)
        await self._close_tab_only(session_id)

        # Remove the JSON file on disk
        path = session_file(session_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            active = self._active_session_id()
            if active:
                self._system_bubble(active, f"_Warning: couldn't delete **{os.path.basename(path)}**_")

        # Remove the node from the Tree (this also selects a neighbor or clears selection)
        await self._remove_tree_node(session_id)


    # ---------- Bubbles & persistence ----------
    def add_message(self, role: str, content: str, *, session_id: Optional[str] = None):
        view = self._current_view(session_id)
        md = Markdown(content, classes=f"bubble {role}")
        view.mount(md)
        view.scroll_end(animate=False)
        return md

    def _system_bubble(self, session_id: str, text: str):
        self.add_message("system", text, session_id=session_id)

    def save_message(self, role: str, content: str, *, session_id: str) -> None:
        record = {"ts": datetime.utcnow().isoformat() + "Z", "role": role, "content": content}
        path = session_file(session_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def load_history(self, session_id: str) -> None:
        path = session_file(session_id)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    role = rec.get("role", "assistant")
                    content = rec.get("content", "")
                    self.add_message(role, content, session_id=session_id)
        except Exception as e:
            self.add_message("system", f"_Couldn’t load history for {session_id}: {e}_", session_id=session_id)

    def _active_session_id(self) -> Optional[str]:
        tabs = self.query_one("#tabs", TabbedContent)
        return tabs.active

    def _current_view(self, session_id: Optional[str] = None) -> VerticalScroll:
        sid = session_id or self._active_session_id()
        assert sid is not None, "No active session"
        view = self.views.get(sid)
        if view is None:
            view = VerticalScroll(id=f"view_{sid}", classes="chat")
            pane = self.get_pane(sid)
            if pane:
                pane.mount(view)
            self.views[sid] = view
        return view

    # ---------- Send / model ----------
    async def action_send(self) -> None:
        await self.model_response()

    async def model_response(self):
        sid = self._active_session_id()
        if not sid:
            return

        ta = self.query_one("#in", TextArea)
        prompt_input = ta.text.strip()
        if not prompt_input:
            return

        if prompt_input.startswith("/rename "):
            new_title = prompt_input[len("/rename ") :].strip()
            ta.clear()
            pane = self.get_pane(sid)
            if pane is not None:
                try:
                    pane.title = new_title or pane.title
                    node = self.tree_nodes.get(sid)
                    if node and new_title:
                        node.set_label(new_title)
                except Exception:
                    self._system_bubble(sid, f"_Rename not supported. Suggested name: **{new_title}**_")
            return
        if prompt_input == "/new":
            ta.clear()
            await self.action_new_tab()
            return
        if prompt_input == "/close":
            ta.clear()
            await self.action_close_tab()
            return
        if prompt_input == "/delete":
            ta.clear()
            await self._permanently_delete_chat(sid)
            return

        self.add_message("user", prompt_input, session_id=sid)
        self.save_message("user", prompt_input, session_id=sid)
        ta.clear()

        typing_md = self.add_message("status", "_Thinking…_", session_id=sid)

        try:
            response = await asyncio.to_thread(
                client.responses.create,
                model="gpt-5",
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Make sure to respond in valid Markdown format. "
                            "If you include code, format it within triple backticks and "
                            "specify the language."
                        ),
                    },
                    {"role": "user", "content": prompt_input},
                ],
            )
            output = response.output_text
        except Exception as e:
            output = f"**Error:** `{e}`"

        typing_md.remove()
        self.add_message("assistant", output, session_id=sid)
        self.save_message("assistant", output, session_id=sid)

    # ---------- Copy mode ----------
    async def action_copy_mode(self) -> None:
        """Open a read-only viewer with the current chat so keyboard selection works."""
        sid = self._active_session_id()
        if not sid:
            return

        # Build a plain text transcript from the session file.
        path = session_file(sid)
        lines = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        rec = json.loads(line)
                        role = rec.get("role", "")
                        content = rec.get("content", "")
                        # simple plain-text transcript; keep Markdown as-is
                        lines.append(f"{role.upper()}: {content}")
            except Exception as e:
                self.notify(f"Couldn’t read history: {e}", severity="error")

        text = "\n\n".join(lines) if lines else "(empty)"
        title = self._pane_title_str(sid)
        await self.push_screen(CopyScreen(title, text))

    def _pane_title_str(self, pane_id: str) -> str:
        """Return the visible title for a TabPane ID across Textual versions."""
        # Try TabbedContent tab label
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tab = tabs.get_tab(pane_id)  # Tab object
            if hasattr(tab, "label_text") and tab.label_text:
                return tab.label_text
            label = getattr(tab, "label", None)
            if label is not None:
                return str(label)
        except Exception:
            pass
        # Fallback to the Tree node label (if present)
        try:
            node = self.tree_nodes.get(pane_id)
            if node is not None and getattr(node, "label", None):
                return str(node.label)
        except Exception:
            pass
        # Last resort: the session id
        return pane_id

    # ---------- Theme ----------
    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


if __name__ == "__main__":
    app = TerGptApp()
    app.run()
