"""argparse scaffolding and the main() wrapper both tools share."""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Callable, Sequence

from .ui import EXIT_ERROR, EXIT_OK, EXIT_USAGE, OUT, STYLE, Fail


class Parser(argparse.ArgumentParser):
    """ArgumentParser that exits 2 on usage errors and keeps help readable."""

    def error(self, message: str) -> None:  # type: ignore[override]
        OUT.error(message)
        OUT.hint(f"run `{self.prog} --help`")
        raise SystemExit(EXIT_USAGE)


def add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true", help="show the steps being taken")
    parser.add_argument("--debug", action="store_true", help="echo every command that is run")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--json", action="store_true", help="machine-readable output, where the command supports it")


def apply_global_flags(args: argparse.Namespace) -> None:
    OUT.verbose = bool(getattr(args, "verbose", False))
    OUT.debug = bool(getattr(args, "debug", False))
    OUT.quiet = bool(getattr(args, "quiet", False))
    OUT.json = bool(getattr(args, "json", False))


def main(build_parser: Callable[[], argparse.ArgumentParser], argv: Sequence[str] | None = None) -> int:
    """Parse, dispatch and turn Fail into a clean message plus exit code."""
    # Die quietly on a closed pipe (`iosvm list | head`) rather than dumping a
    # BrokenPipeError traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass

    parser = build_parser()
    args = parser.parse_args(argv)
    apply_global_flags(args)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_OK

    try:
        return handler(args) or EXIT_OK
    except Fail as exc:
        OUT.error(str(exc))
        if exc.hint:
            OUT.hint(exc.hint)
        return exc.code
    except KeyboardInterrupt:
        OUT.say()
        OUT.warn("interrupted")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - last resort, keeps tracebacks behind --debug
        if OUT.debug:
            raise
        OUT.error(f"{type(exc).__name__}: {exc}")
        OUT.hint("re-run with --debug for a traceback")
        return EXIT_ERROR


def topic(title: str) -> str:
    return STYLE.bold(title)
