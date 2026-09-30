"""vmtools — umbrella CLI / TUI for windowsvm, linuxvm, androidvm.

Wraps the existing sibling CLIs (stdlib menu UX matching apple-vm-tools).
Does not replace iosvm/macosvm; those stay on apple-vm-tools.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence

from . import __version__
from .app import Parser, add_global_flags, apply_global_flags, topic
from .app import main as app_main
from .menu import menu
from .ui import EXIT_OK, OUT, STYLE, Fail

SIBLINGS = (
    ("windowsvm", "Windows Construct (QEMU/KVM/libvirt)"),
    ("linuxvm", "Linux Construct (QEMU/KVM/libvirt)"),
    ("androidvm", "Android Construct (Docker-Android-Pro)"),
)

APPLE = (
    ("iosvm", "iOS VM Manager (apple-vm-tools / Inferno)"),
    ("macosvm", "macOS VM Manager (apple-vm-tools / OSX-KVM)"),
)


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="vmtools",
        description="Umbrella for windowsvm / linuxvm / androidvm. Follow the white rabbit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Matrix construct suite — sibling of iosvm/macosvm.\n"
            "  vmtools            interactive TUI\n"
            "  vmtools tui        same\n"
            "  vmtools doctor     host checks (read-only)\n"
            "  vmtools list       list VMs across tools\n"
            "  windowsvm tui | linuxvm tui | androidvm tui"
        ),
    )
    add_global_flags(p)
    p.add_argument("--version", action="version", version=f"vmtools {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(handler=handler)
        return sp

    add("help", "show this help", lambda a: (p.print_help(), EXIT_OK)[1])
    add("tui", "interactive suite menu", cmd_tui)
    add("doctor", "run windowsvm/linuxvm/androidvm doctor (read-only)", cmd_doctor)
    add("list", "list VMs across windowsvm/linuxvm/androidvm", cmd_list)
    add("status", "short suite status", cmd_status)

    for name, label in SIBLINGS:
        sp = add(name, f"dispatch to {name} (pass remaining args)", cmd_dispatch)
        sp.add_argument("tool_args", nargs=argparse.REMAINDER, help=f"args for {name}")

    return p


def _run_tool(tool: str, args: Sequence[str]) -> int:
    """Run a sibling on PATH, or fall back to in-tree module."""
    exe = shutil.which(tool)
    if exe:
        return subprocess.call([exe, *args])
    # Dev / source tree: import the module CLI
    mod = __import__(f"{tool}.cli", fromlist=["main"])
    return int(mod.main(list(args)) or EXIT_OK)


def cmd_tui(args=None) -> int:
    """Suite picker — wraps per-tool interactive roots / tui."""
    OUT.say()
    OUT.say(topic("VM Construct"))
    OUT.say(STYLE.dim("windowsvm · linuxvm · androidvm  |  iosvm/macosvm are apple-vm-tools"))
    OUT.say("─" * 40)

    def open_windows():
        from windowsvm.cli import interactive_root
        interactive_root()

    def open_linux():
        from linuxvm.cli import interactive_root
        interactive_root()

    def open_android():
        from androidvm.cli import interactive_root
        interactive_root()

    def do_doctor():
        cmd_doctor(argparse.Namespace(json=False))

    def do_list():
        cmd_list(argparse.Namespace(json=False))

    menu(
        "Choose a construct",
        [
            ("1", "Windows Construct  (windowsvm)", open_windows),
            ("2", "Linux Construct    (linuxvm)", open_linux),
            ("3", "Android Construct  (androidvm)", open_android),
            ("d", "Doctor (all three)", do_doctor),
            ("l", "List VMs", do_list),
        ],
    )
    return EXIT_OK


def cmd_doctor(args) -> int:
    """Read-only host checks; does not stop running VMs."""
    if getattr(args, "json", False):
        OUT.warn("vmtools doctor --json: running each tool with --json separately")
    code = EXIT_OK
    for tool, label in SIBLINGS:
        OUT.say()
        OUT.say(topic(f"doctor · {tool}"))
        OUT.say(STYLE.dim(label))
        sys.stdout.flush()
        rc = _run_tool(tool, ["doctor"] + (["--json"] if getattr(args, "json", False) else []))
        if rc not in (0, None):
            code = rc
    OUT.say()
    OUT.say(STYLE.dim("Note: iosvm/macosvm doctor are separate (apple-vm-tools). pixel15 left running."))
    return code


def cmd_list(args) -> int:
    code = EXIT_OK
    for tool, _label in SIBLINGS:
        OUT.say()
        OUT.say(topic(f"list · {tool}"))
        sys.stdout.flush()
        rc = _run_tool(tool, ["list"] + (["--json"] if getattr(args, "json", False) else []))
        if rc not in (0, None):
            code = rc
    return code


def cmd_status(args) -> int:
    OUT.say()
    OUT.say(topic("VM Construct status"))
    for tool, label in SIBLINGS:
        path = shutil.which(tool) or "(dev import)"
        OUT.say(f"  {STYLE.bold(tool):<24} {label}")
        OUT.note(path)
    OUT.say()
    OUT.say(STYLE.dim("Apple siblings (not managed here):"))
    for tool, label in APPLE:
        path = shutil.which(tool) or "(missing)"
        OUT.say(f"  {tool:<24} {label}")
        OUT.note(path)
    return EXIT_OK


def cmd_dispatch(args) -> int:
    tool = args.command
    rest = list(getattr(args, "tool_args", []) or [])
    # argparse REMAINDER keeps a leading '--' sometimes
    if rest and rest[0] == "--":
        rest = rest[1:]
    return _run_tool(tool, rest)


def interactive_root() -> int:
    return cmd_tui(None)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        apply_global_flags(argparse.Namespace(verbose=False, debug=False, quiet=False, json=False))
        try:
            return interactive_root()
        except Fail as exc:
            OUT.error(str(exc))
            if exc.hint:
                OUT.hint(exc.hint)
            return exc.code
    return app_main(build_parser, argv)


if __name__ == "__main__":
    raise SystemExit(main())
