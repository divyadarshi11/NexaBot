"""Web front end for the chatbot.

A thin Flask layer over the same `ChatBot` the CLI uses — no model logic lives
here, only transport. Replies are streamed to the browser over SSE so the page
fills in token-by-token, exactly like the terminal version.

Run it with:

    python -m chatbot.web

This is a local, single-user app: one conversation is held in memory on the
server. That's deliberate — it keeps the code readable. See `_STATE` below for
what you'd change to support several people at once.
"""

from __future__ import annotations

import json
import time
import webbrowser
from pathlib import Path
from threading import Lock, Timer

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

from . import __version__
from .core import (
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    HISTORY_DIR,
    ChatBot,
    ChatSession,
)

app = Flask(__name__)

# Single in-memory conversation. To go multi-user you'd key this dict by a
# signed cookie instead of holding one bot, and everything else would stand.
_STATE: dict = {"bot": None, "error": None}
_LOCK = Lock()


def get_bot() -> ChatBot:
    """Build the bot lazily so a missing API key surfaces in the UI, not the console."""
    with _LOCK:
        if _STATE["bot"] is None:
            _STATE["bot"] = ChatBot(session=ChatSession())
        return _STATE["bot"]


def session_payload(session: ChatSession) -> dict:
    return {
        "model": session.model,
        "system_prompt": session.system_prompt,
        "max_tokens": session.max_tokens,
        "messages": session.messages,
        "session_id": session.session_id,
    }


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


@app.get("/")
def index():
    return render_template("index.html", version=__version__)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@app.get("/api/state")
def state():
    try:
        bot = get_bot()
    except EnvironmentError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200
    return jsonify({"ok": True, "session": session_payload(bot.session)})


@app.post("/api/chat")
def chat():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is empty."}), 400

    try:
        bot = get_bot()
    except EnvironmentError as exc:
        return jsonify({"error": str(exc)}), 400

    model = bot.session.model

    def stream():
        started = time.perf_counter()
        try:
            for chunk in bot.send(message):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as exc:  # noqa: BLE001
            # Drop the half-finished turn so history doesn't desync.
            if bot.session.messages and bot.session.messages[-1]["role"] == "user":
                bot.session.messages.pop()
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        meta = {"model": model, "seconds": round(time.perf_counter() - started, 1)}
        yield f"data: {json.dumps({'done': meta})}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/new")
def new_chat():
    bot = get_bot()
    bot.session = ChatSession(
        model=bot.session.model,
        system_prompt=bot.session.system_prompt,
        max_tokens=bot.session.max_tokens,
    )
    return jsonify({"ok": True, "session": session_payload(bot.session)})


@app.post("/api/settings")
def settings():
    data = request.get_json(silent=True) or {}
    bot = get_bot()
    bot.session.model = (data.get("model") or DEFAULT_MODEL).strip()
    bot.session.system_prompt = (data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    try:
        bot.session.max_tokens = max(1, int(data.get("max_tokens", 1024)))
    except (TypeError, ValueError):
        return jsonify({"error": "Max tokens must be a whole number."}), 400
    return jsonify({"ok": True, "session": session_payload(bot.session)})


@app.post("/api/save")
def save():
    bot = get_bot()
    if not bot.session.messages:
        return jsonify({"error": "Nothing to save yet."}), 400
    path = bot.session.save()
    return jsonify({"ok": True, "path": str(path)})


@app.get("/api/sessions")
def list_sessions():
    """List saved transcripts, newest first, with the opening question as a label."""
    items = []
    if HISTORY_DIR.exists():
        for path in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text())
                messages = data.get("messages", [])
                opener = next(
                    (m["content"] for m in messages if m.get("role") == "user"), ""
                )
            except Exception:  # noqa: BLE001
                continue
            items.append(
                {
                    "path": str(path),
                    "name": path.stem,
                    "preview": opener[:80] or "Empty transcript",
                    "turns": sum(1 for m in messages if m.get("role") == "user"),
                }
            )
    return jsonify({"sessions": items, "dir": str(HISTORY_DIR)})


@app.post("/api/load")
def load():
    path = (request.get_json(silent=True) or {}).get("path", "")
    if not path:
        return jsonify({"error": "No transcript selected."}), 400

    # Only ever read from the sessions directory, whatever the client sends.
    target = Path(path).resolve()
    if HISTORY_DIR.resolve() not in target.parents:
        return jsonify({"error": "That file is outside the transcripts folder."}), 400

    try:
        bot = get_bot()
        bot.session = ChatSession.load(target)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Couldn't read that transcript: {exc}"}), 400
    return jsonify({"ok": True, "session": session_payload(bot.session)})


def main() -> int:
    load_dotenv()
    url = "http://127.0.0.1:5000"
    print(f"chatbot web UI running at {url}  (ctrl+c to stop)")
    Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
