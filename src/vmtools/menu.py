"""Simple interactive terminal menus (no third-party deps)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .ui import OUT, STYLE


def menu(title: str, actions: Sequence[tuple[str, str, Callable[[], None]]]) -> None:
    """actions: (key, label, callback). 'q' always quits."""
    while True:
        OUT.say()
        OUT.say(STYLE.bold(title))
        OUT.say("─" * 28)
        for key, label, _ in actions:
            OUT.say(f"[{key}] {label}")
        OUT.say("[q] Quit")
        try:
            choice = input("> ").strip().lower()
        except EOFError:
            return
        if choice in ("q", "quit", "exit"):
            return
        for key, _label, cb in actions:
            if choice == key.lower():
                cb()
                break
        else:
            OUT.warn("unknown choice")


def prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        return default or ""
    return value if value else (default or "")


def confirm(question: str, *, default: bool = False) -> bool:
    yn = "Y/n" if default else "y/N"
    try:
        value = input(f"{question} [{yn}]: ").strip().lower()
    except EOFError:
        return default
    if not value:
        return default
    return value in ("y", "yes")
