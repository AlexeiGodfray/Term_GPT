# TerGPT v0.1 — ChatGPT in your terminal 🧪💬

A tiny, tabbed, keyboard-first ChatGPT wrapper for your terminal — built with Textual.

I’m literally using this app right now to write some of this README. Meta enough? 😅

- Fast, minimal, and cozy
- Multiple chats in tabs
- Sidebar chat list
- Persistent JSONL history
- Copy-friendly transcript mode
- Works with your OpenAI API key

> Version: 0.1 (early + playful — expect some rough edges)
> 

---

## ✨ Features

- Multiple chats via tabs and a sidebar tree
- Persistent chat history in `chat_history/*.jsonl`
- Copy Mode for clean, selectable transcripts
- Rename tabs (F2 or slash command)
- Dark mode toggle
- Keyboard-focused UX

---

## ⌨️ Key Bindings

- Ctrl+Enter — Send
- Ctrl+N — New chat
- Ctrl+W — Close current chat (and delete its JSON history)
- F2 — Rename current chat (uses the input box as the title)
- Ctrl+Shift+C — Copy Mode (read-only transcript window)
- Ctrl+T — Toggle dark mode

---

## 🧵 Slash Commands

Type these in the input box:

- `/rename New Title` — Rename current chat
- `/new` — Create a new chat
- `/close` — Close current chat (and delete its JSON history)
- `/delete` — Permanently delete current chat (safe even if it’s the last tab)

---

## 📦 Installation

Prereqs:

- Python 3.10+ recommended
- A terminal that can run Textual apps
- An OpenAI API key
1. Clone this repo:

```bash
git clone <https://github.com/yourname/tergpt.git>
cd tergpt

```

1. (Optional) Create & activate a virtual environment:

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
.venv\\Scripts\\Activate.ps1

```

1. Install dependencies:

```bash
pip install textual openai python-dotenv

```

---

## 🔑 Configure your API key

The app uses `python-dotenv`. Put your key in a `.env` file in the project root:

```
OPENAI_API_KEY=sk-your-key-here

```

Alternatively, export it in your shell:

- macOS/Linux:
    
    ```bash
    export OPENAI_API_KEY=sk-your-key-here
    
    ```
    
- Windows PowerShell:
    
    ```powershell
    setx OPENAI_API_KEY "sk-your-key-here"
    # (Then reopen your terminal)
    
    ```
    

---

## ▶️ Run it

```bash
python main.py

```

- New chats will be created as `chat_001.jsonl`, `chat_002.jsonl`, etc., in `chat_history/`.
- Press Ctrl+Enter to send your first message.
- Use the sidebar buttons or shortcuts to manage chats.

---

## 🧠 Model notes

The code currently calls:

```python
response = client.responses.create(
    model="gpt-5",
    input=[ ... ],
)

```

- If your account doesn’t have access to that model (or it’s not available), change `"gpt-5"` to a model you can use.
- You’ll find this inside `model_response()`.

---

## 🗃️ Where stuff lives

- Chat history: `chat_history/chat_XXX.jsonl` (one JSON object per line)
    - Each record has: `ts`, `role`, `content`
- Styling: `style.tcss` (optional — tweak Textual styles if you like)

---

## 📋 Copy Mode tips

- Ctrl+Shift+C opens a read-only transcript window.
- “Copy All” tries to copy to your clipboard via Textual; some terminals may not support clipboard access — you’ll get a friendly warning if so.

---

## 🧰 Troubleshooting

- “No response” or “Error”: Check your `OPENAI_API_KEY` and model name.
- Clipboard doesn’t work: Your terminal may not expose clipboard APIs.
- History didn’t load: Check the JSONL files in `chat_history/` and file permissions.

---

## 🗺️ Roadmap (a tiny peek)

- Configurable model via env or settings
- Streaming responses
- Better theming + status indicators
- Export to Markdown

---

## 💌 Thanks

Made for terminal people who love fast chats and keyboard shortcuts.

If you build something cool on top of this, I’d love to hear about it!
