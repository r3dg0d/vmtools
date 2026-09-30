"""Terminal output: colour, symbols, spinners, progress bars, exit codes.

Shared by iosvm and macosvm so both tools look and behave identically.

Colour is emitted only when stdout is a TTY that plausibly understands ANSI and
NO_COLOR is unset (https://no-color.org). Every decorated symbol degrades to
plain ASCII, so piping into a file or a pager stays readable.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

# Exit codes. Anything a caller might branch on gets its own value.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_PREREQ = 3  # dependency missing
EXIT_DOWNLOAD = 4
EXIT_CHECKSUM = 5
EXIT_NOT_FOUND = 6  # VM not found
EXIT_PERM = 7
EXIT_BACKEND = 8
EXIT_ACCESS = 9  # android pro access not configured
EXIT_STATE = 10  # wrong VM state
EXIT_GENERIC = EXIT_ERROR


def _colour_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return os.environ.get("TERM", "") not in ("", "dumb")


class Style:
    def __init__(self, stream=None) -> None:
        self.enabled = _colour_enabled(stream or sys.stdout)

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def blue(self, t: str) -> str:
        return self._wrap("34", t)

    def cyan(self, t: str) -> str:
        return self._wrap("36", t)


STYLE = Style()

# Unicode where the terminal can take it, ASCII where it cannot. A UTF-8 locale
# is the signal; this avoids mojibake on a plain C-locale console.
_UTF8 = "utf" in (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or os.environ.get("LANG") or "").lower()

SYM_OK = "✓" if _UTF8 else "+"  # check mark
SYM_BAD = "✗" if _UTF8 else "x"  # ballot x
SYM_WARN = "!"
SYM_STEP = "◆" if _UTF8 else ">"  # black diamond
SYM_DOT = "·" if _UTF8 else "-"


class Out:
    """Output sink honouring --quiet / --verbose / --debug / --json."""

    def __init__(self) -> None:
        self.verbose = False
        self.debug = False
        self.quiet = False
        self.json = False

    # -- plain lines ------------------------------------------------------
    def say(self, text: str = "") -> None:
        if not self.quiet and not self.json:
            print(text)

    def step(self, text: str) -> None:
        self.say(f"{STYLE.blue(SYM_STEP)} {text}")

    def ok(self, text: str) -> None:
        self.say(f"{STYLE.green(SYM_OK)} {text}")

    def warn(self, text: str) -> None:
        self.say(f"{STYLE.yellow(SYM_WARN)} {text}")

    def bad(self, text: str) -> None:
        self.say(f"{STYLE.red(SYM_BAD)} {text}")

    def note(self, text: str) -> None:
        self.say(f"  {STYLE.dim(text)}")

    def vsay(self, text: str) -> None:
        if self.verbose or self.debug:
            self.say(STYLE.dim(text))

    def dsay(self, text: str) -> None:
        if self.debug:
            print(STYLE.dim(f"debug: {text}"), file=sys.stderr)

    # -- errors -----------------------------------------------------------
    # stdout is block-buffered when redirected, so it is flushed first: without
    # that, a diagnostic on stderr overtakes the progress lines it refers to.
    def error(self, text: str) -> None:
        sys.stdout.flush()
        print(f"{STYLE.red('error:')} {text}", file=sys.stderr)

    def hint(self, text: str) -> None:
        sys.stdout.flush()
        print(f"{STYLE.dim('hint: ' + text)}", file=sys.stderr)

    # -- machine-readable -------------------------------------------------
    def emit_json(self, payload: Any) -> None:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")


OUT = Out()


class Fail(Exception):
    """A user-facing failure. Carries an exit code and an optional hint."""

    def __init__(self, message: str, code: int = EXIT_ERROR, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


@contextmanager
def spinner(label: str) -> Iterator[None]:
    """Show an animated label while a slow operation runs.

    Silent when output is not a TTY (or under --quiet/--json/--debug), so logs
    and pipelines do not fill up with control characters. The cursor is always
    restored, including on exception.
    """
    interactive = sys.stdout.isatty() and not OUT.quiet and not OUT.json and not OUT.debug
    if not interactive:
        OUT.vsay(f"{label}...")
        yield
        return

    frames = itertools.cycle("⠹⠸⠴⠦⠎⠏" if _UTF8 else "|/-\\")
    stop = threading.Event()

    def spin() -> None:
        sys.stdout.write("\033[?25l")  # hide cursor
        try:
            while not stop.is_set():
                sys.stdout.write(f"\r{STYLE.blue(next(frames))} {label}")
                sys.stdout.flush()
                stop.wait(0.09)
        finally:
            sys.stdout.write("\r\033[2K\033[?25h")  # clear line, show cursor
            sys.stdout.flush()

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


class Progress:
    """A download/copy progress bar that degrades to periodic lines."""

    def __init__(self, label: str, total: int | None) -> None:
        self.label = label
        self.total = total
        self.done = 0
        self.started = time.monotonic()
        self.interactive = sys.stdout.isatty() and not OUT.quiet and not OUT.json
        self._last = 0.0

    def advance(self, amount: int) -> None:
        self.done += amount
        now = time.monotonic()
        if now - self._last < 0.1:
            return
        self._last = now
        self._render()

    def _render(self) -> None:
        if not self.interactive:
            return
        width = max(20, min(shutil.get_terminal_size((80, 24)).columns - 34, 48))
        if self.total:
            frac = min(1.0, self.done / self.total)
            filled = int(frac * width)
            bar = ("█" if _UTF8 else "#") * filled + ("░" if _UTF8 else ".") * (width - filled)
            text = f"\r{self.label} {bar} {frac * 100:5.1f}% {human_size(self.done)}"
        else:
            text = f"\r{self.label} {human_size(self.done)}"
        sys.stdout.write(text[: shutil.get_terminal_size((80, 24)).columns - 1])
        sys.stdout.flush()

    def finish(self) -> None:
        if self.interactive:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        OUT.ok(f"{self.label} ({human_size(self.done)})")


def human_size(num: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PiB"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Left-aligned fixed-width table, matching the tool's plain-text style."""
    cols = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(row[i])))
    line = "  ".join(STYLE.bold(str(headers[i]).ljust(widths[i])) for i in range(cols))
    out = [line.rstrip()]
    for row in rows:
        out.append("  ".join(str(row[i]).ljust(widths[i]) for i in range(cols)).rstrip())
    return "\n".join(out)
