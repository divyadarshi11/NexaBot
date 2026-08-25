"""Core chatbot engine: manages conversation state and calls the Anthropic API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

import anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant running in a terminal chat."
HISTORY_DIR = Path.home() / ".ai_chatbot_cli" / "sessions"


@dataclass
class ChatSession:
    """Holds conversation state for a single chat session."""

    model: str = DEFAULT_MODEL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tokens: int = 1024
    messages: list[dict] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def reset(self) -> None:
        self.messages.clear()

    def save(self) -> Path:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = HISTORY_DIR / f"{self.session_id}.json"
        payload = {
            "model": self.model,
            "system_prompt": self.system_prompt,
            "messages": self.messages,
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "ChatSession":
        data = json.loads(Path(path).read_text())
        session = cls(
            model=data.get("model", DEFAULT_MODEL),
            system_prompt=data.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
        )
        session.messages = data.get("messages", [])
        return session


class ChatBot:
    """Wraps the Anthropic client and handles streaming replies."""

    def __init__(self, api_key: str | None = None, session: ChatSession | None = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "No API key found. Set the ANTHROPIC_API_KEY environment variable "
                "or pass one explicitly (see README for setup)."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.session = session or ChatSession()

    def send(self, user_text: str) -> Iterator[str]:
        """Send a message and yield the assistant's reply in streamed chunks."""
        self.session.add_user_message(user_text)

        full_reply = []
        with self.client.messages.stream(
            model=self.session.model,
            max_tokens=self.session.max_tokens,
            system=self.session.system_prompt,
            messages=self.session.messages,
        ) as stream:
            for text in stream.text_stream:
                full_reply.append(text)
                yield text

        self.session.add_assistant_message("".join(full_reply))
