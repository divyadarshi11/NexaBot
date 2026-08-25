"""Presentation layer for the chatbot CLI.

Everything that decides how the terminal *looks* lives here, so `cli.py` can stay
a thin REPL and `core.py` stays pure logic. Two renderers are provided:

* ``RichUI``  - panels, colour, live Markdown streaming. Used on a real terminal.
* ``PlainUI`` - bare ``print`` calls. Used when output is piped or ``--plain``
  is passed, so ``chatbot -m "..." > out.txt`` stays clean and parseable.
"""

from __future__ import annotations

import sys
import time
from typing import Iterable, Protocol

from rich.box import HEAVY, ROUNDED
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
# One accent per speaker, everything else muted. Keeping the palette this small
# is what stops a terminal UI from looking like a Christmas tree.

INK = "#c8cbd4"  # default body text
MUTED = "#6b7280"  # timestamps, hints, borders
USER = "#e0a458"  # warm amber  -> the human
BOT = "#7c9cf5"  # cool blue   -> the assistant
OK = "#7cc79a"
WARN = "#e0736d"

THEME = Theme(
    {
        "ink": INK,
        "muted": MUTED,
        "user": USER,
        "user.border": "#8a6531",
        "bot": BOT,
        "bot.border": "#3f5490",
        "ok": OK,
        "warn": WARN,
        "cmd": f"bold {BOT}",
        "markdown.code": f"bold {OK}",
        "markdown.item.bullet": BOT,
        "markdown.h1": f"bold {BOT}",
        "markdown.h2": f"bold {BOT}",
        "markdown.h3": f"bold {INK}",
    }
)

# Pure-ASCII on purpose: renders identically in cmd.exe, PowerShell, iTerm, tmux.
BANNER = r"""  ___ _         _   ___      _
 / __| |_  __ _| |_| _ ) ___| |_
| (__| ' \/ _` |  _| _ \/ _ \  _|
 \___|_||_\__,_|\__|___/\___/\__|"""


def _gradient(text: str, start: str, end: str) -> Text:
    """Fade a block of text line-by-line from `start` to `end`."""
    lines = text.splitlines()
    s = tuple(int(start[i : i + 2], 16) for i in (1, 3, 5))
    e = tuple(int(end[i : i + 2], 16) for i in (1, 3, 5))
    out = Text()
    span = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        r, g, b = (round(s[c] + (e[c] - s[c]) * i / span) for c in range(3))
        out.append(line + "\n", style=f"bold #{r:02x}{g:02x}{b:02x}")
    return out


class UI(Protocol):
    """The surface `cli.py` talks to. Both renderers implement this."""

    def welcome(self, session, version: str) -> None: ...
    def ask(self) -> str: ...
    def stream_reply(self, chunks: Iterable[str], model: str) -> str: ...
    def help(self, commands: list[tuple[str, str]]) -> None: ...
    def notice(self, text: str) -> None: ...
    def error(self, text: str) -> None: ...
    def goodbye(self) -> None: ...


# --------------------------------------------------------------------------- #
# Rich renderer
# --------------------------------------------------------------------------- #


class RichUI:
    # Chat is prose. Letting panels run the full width of an ultrawide terminal
    # makes lines too long to track, so cap the column at a readable measure.
    MAX_WIDTH = 88

    def __init__(self, console: Console | None = None):
        self.console = console or Console(theme=THEME)
        self.turn = 0
        self.width = min(self.console.width, self.MAX_WIDTH)
        unicode_ok = (self.console.encoding or "").lower().startswith("utf")
        self.arrow = "\u203a" if unicode_ok else ">"
        self.dot = "\u2022" if unicode_ok else "*"

    # -- chrome ------------------------------------------------------------- #

    def welcome(self, session, version: str) -> None:
        c = self.console
        c.print()
        c.print(Padding(_gradient(BANNER, BOT, USER), (0, 0, 0, 2)))

        meta = Table.grid(padding=(0, 2))
        meta.add_column(style="muted", justify="right")
        meta.add_column(style="ink")
        meta.add_row("model", session.model)
        meta.add_row("max tokens", str(session.max_tokens))
        meta.add_row("system", _truncate(session.system_prompt, 58))

        c.print(
            Panel(
                meta,
                box=ROUNDED,
                border_style="muted",
                title=f"[muted]ai-chatbot-cli v{version}[/]",
                title_align="left",
                subtitle="[muted]/help for commands · /exit to quit[/]",
                subtitle_align="right",
                padding=(1, 2),
                width=self.width,
            )
        )

    def ask(self) -> str:
        # A blank line before each turn does more for readability than any colour.
        self.console.print()
        # console.input (rather than Prompt.ask) keeps readline history and
        # arrow-key editing, and doesn't append Rich's default ": " suffix.
        return self.console.input(f"[bold user]you[/] [muted]{self.arrow}[/] ")

    # -- the main event ----------------------------------------------------- #

    def stream_reply(self, chunks: Iterable[str], model: str) -> str:
        """Render tokens into a live Markdown panel as they arrive."""
        started = time.perf_counter()
        buf: list[str] = []

        def frame(body, subtitle: str) -> Panel:
            return Panel(
                body,
                box=ROUNDED,
                border_style="bot.border",
                title="[bold bot]claude[/]",
                title_align="left",
                subtitle=f"[muted]{subtitle}[/]",
                subtitle_align="right",
                padding=(1, 2),
                width=self.width,
            )

        spinner = Spinner("dots", text=Text(" thinking…", style="muted"), style="bot")

        with Live(
            frame(spinner, model),
            console=self.console,
            refresh_per_second=12,
            vertical_overflow="visible",
        ) as live:
            for chunk in chunks:
                buf.append(chunk)
                live.update(frame(Markdown("".join(buf), code_theme="nord"), model))

            elapsed = time.perf_counter() - started
            text = "".join(buf)
            body = Markdown(text, code_theme="nord") if text else Text("(empty reply)", style="muted")
            live.update(frame(body, f"{model} · {elapsed:.1f}s"))

        self.turn += 1
        return "".join(buf)

    # -- messages ----------------------------------------------------------- #

    def help(self, commands: list[tuple[str, str]]) -> None:
        table = Table(
            box=ROUNDED,
            border_style="muted",
            show_header=True,
            header_style="muted",
            padding=(0, 2),
            width=self.width,
        )
        table.add_column("command", style="cmd", no_wrap=True)
        table.add_column("what it does", style="ink")
        for name, desc in commands:
            table.add_row(name, desc)
        self.console.print()
        self.console.print(table)

    def notice(self, text: str) -> None:
        self.console.print(f"  [ok]{self.dot}[/] [muted]{text}[/]")

    def error(self, text: str) -> None:
        self.console.print(
            Panel(
                Text(text, style="ink"),
                box=HEAVY,
                border_style="warn",
                title="[bold warn]error[/]",
                title_align="left",
                padding=(0, 2),
                width=self.width,
            )
        )

    def goodbye(self) -> None:
        turns = self.turn
        word = "turn" if turns == 1 else "turns"
        self.console.print()
        self.console.print(f"  [muted]{turns} {word} this session — bye.[/]")
        self.console.print()


# --------------------------------------------------------------------------- #
# Plain renderer (pipes, CI, --plain)
# --------------------------------------------------------------------------- #


class PlainUI:
    def welcome(self, session, version: str) -> None:
        print(f"ai-chatbot-cli v{version} — model: {session.model}")
        print("Type /help for commands, /exit to quit.\n")

    def ask(self) -> str:
        return input("you> ")

    def stream_reply(self, chunks: Iterable[str], model: str) -> str:
        buf: list[str] = []
        for chunk in chunks:
            buf.append(chunk)
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return "".join(buf)

    def help(self, commands: list[tuple[str, str]]) -> None:
        width = max(len(c) for c, _ in commands)
        for name, desc in commands:
            print(f"  {name.ljust(width)}  {desc}")

    def notice(self, text: str) -> None:
        print(f"({text})")

    def error(self, text: str) -> None:
        print(f"[error] {text}", file=sys.stderr)

    def goodbye(self) -> None:
        print("Goodbye!")


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def make_ui(plain: bool = False) -> UI:
    """Pick a renderer. Plain wins if asked for, or if we're not on a terminal."""
    if plain or not sys.stdout.isatty():
        return PlainUI()
    return RichUI()
