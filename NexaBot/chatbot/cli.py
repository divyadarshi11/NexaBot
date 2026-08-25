"""Command-line interface for the AI chatbot.

This module only handles argument parsing and the REPL loop. How things *look*
lives in `chatbot/ui.py`; how things *work* lives in `chatbot/core.py`.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from . import __version__
from .core import ChatBot, ChatSession, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT
from .ui import make_ui

COMMANDS: list[tuple[str, str]] = [
    ("/new", "start a new conversation (clears history)"),
    ("/save", "save the current conversation to disk"),
    ("/load <path>", "load a previous conversation from a saved JSON file"),
    ("/system <text>", "change the system prompt for the rest of the session"),
    ("/help", "show this table"),
    ("/exit", "leave the chat (/quit works too)"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chatbot",
        description="A terminal chatbot powered by the Anthropic API.",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--system",
        default=DEFAULT_SYSTEM_PROMPT,
        help="System prompt to steer the assistant's behavior.",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=1024, help="Max tokens per reply (default: 1024)"
    )
    parser.add_argument(
        "--message",
        "-m",
        help="Send a single message non-interactively and print the reply, then exit.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable panels and colour. Applied automatically when output is piped.",
    )
    return parser


def handle_command(bot: ChatBot, ui, user_input: str) -> bool:
    """Run a slash-command. Returns False if the REPL should stop."""
    command, _, argument = user_input.partition(" ")
    argument = argument.strip()

    if command in ("/exit", "/quit"):
        return False

    if command == "/help":
        ui.help(COMMANDS)
    elif command == "/new":
        bot.session.reset()
        ui.notice("conversation cleared")
    elif command == "/save":
        ui.notice(f"saved to {bot.session.save()}")
    elif command == "/load":
        if not argument:
            ui.error("usage: /load <path-to-session.json>")
        else:
            try:
                bot.session = ChatSession.load(argument)
                ui.notice(f"loaded {argument} ({len(bot.session.messages)} messages)")
            except Exception as exc:  # noqa: BLE001
                ui.error(f"failed to load: {exc}")
    elif command == "/system":
        if not argument:
            ui.error("usage: /system <new system prompt>")
        else:
            bot.session.system_prompt = argument
            ui.notice("system prompt updated")
    else:
        ui.error(f"unknown command {command} — try /help")

    return True


def run_interactive(bot: ChatBot, ui) -> None:
    ui.welcome(bot.session, __version__)

    while True:
        try:
            user_input = ui.ask().strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if not handle_command(bot, ui, user_input):
                break
            continue

        try:
            ui.stream_reply(bot.send(user_input), bot.session.model)
        except KeyboardInterrupt:
            ui.notice("reply interrupted")
        except Exception as exc:  # noqa: BLE001
            ui.error(str(exc))

    ui.goodbye()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    ui = make_ui(plain=args.plain)

    session = ChatSession(
        model=args.model, system_prompt=args.system, max_tokens=args.max_tokens
    )

    try:
        bot = ChatBot(session=session)
    except EnvironmentError as exc:
        ui.error(str(exc))
        return 1

    if args.message:
        try:
            ui.stream_reply(bot.send(args.message), session.model)
        except Exception as exc:  # noqa: BLE001
            ui.error(str(exc))
            return 1
    else:
        run_interactive(bot, ui)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
