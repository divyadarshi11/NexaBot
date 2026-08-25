"""Unit tests for chatbot.core. No network calls — ChatBot init is mocked."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chatbot.core import ChatBot, ChatSession  # noqa: E402


def test_chat_session_defaults():
    session = ChatSession()
    assert session.messages == []
    assert session.model
    assert session.system_prompt


def test_add_user_and_assistant_message():
    session = ChatSession()
    session.add_user_message("hello")
    session.add_assistant_message("hi there")
    assert session.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_reset_clears_messages():
    session = ChatSession()
    session.add_user_message("hello")
    session.reset()
    assert session.messages == []


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    import chatbot.core as core_module

    monkeypatch.setattr(core_module, "HISTORY_DIR", tmp_path)

    session = ChatSession(session_id="unit_test")
    session.add_user_message("hello")
    session.add_assistant_message("hi")
    path = session.save()

    loaded = ChatSession.load(path)
    assert loaded.messages == session.messages
    assert loaded.model == session.model


def test_chatbot_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        ChatBot(api_key=None)
        assert False, "expected EnvironmentError"
    except EnvironmentError:
        pass


@patch("chatbot.core.anthropic.Anthropic")
def test_chatbot_send_streams_and_records_history(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_stream_cm = MagicMock()
    mock_stream_cm.__enter__.return_value.text_stream = iter(["Hello", ", ", "world!"])
    mock_client.messages.stream.return_value = mock_stream_cm

    bot = ChatBot(api_key="fake-key")
    chunks = list(bot.send("hi"))

    assert chunks == ["Hello", ", ", "world!"]
    assert bot.session.messages[-1] == {"role": "assistant", "content": "Hello, world!"}
    assert bot.session.messages[0] == {"role": "user", "content": "hi"}
