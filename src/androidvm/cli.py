"""androidvm — Docker-Android-Pro manager (requires legitimate Pro access)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from vmtools.app import Parser, add_global_flags, topic
from vmtools.app import main as app_main
from vmtools.config import validate_name
from vmtools.layout import config, ensure
from vmtools.menu import confirm, menu, prompt
from vmtools.proc import which
from vmtools.ui import EXIT_ACCESS, EXIT_OK, EXIT_PREREQ, OUT, STYLE, SYM_BAD, SYM_OK, Fail

from . import __version__
from . import images as img
from . import runtime as rt
from .access import access_configured, credentials, docker_login, require_access
from .ports import allocate


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="androidvm",
        description="Android Construct: Docker-Android-Pro emulators (requires legitimate Pro access).",
    )
    add_global_flags(p)
    p.add_argument("--version", action="version", version=f"androidvm {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(handler=handler)
        return sp

    add("help", "show help", lambda a: (p.print_help(), EXIT_OK)[1])
    add("tui", "interactive terminal menu", lambda a: interactive_root())
    add("status", "show backend status", cmd_status)
    add("setup", "verify host + configure Pro login", cmd_setup)
    add("doctor", "host + access checks", cmd_doctor)
    cfg = add("config", "show config", cmd_config)
    cfg.add_argument("key", nargs="?")

    add("list", "list Android VMs", cmd_list)
    add("images", "list Pro image tags", cmd_images)
    pull = add("pull", "pull a Pro image tag", cmd_pull)
    pull.add_argument("tag", nargs="?", default="emulator_15.0")

    c = add("create", "create an Android VM definition", cmd_create)
    c.add_argument("--name")
    c.add_argument("--tag", default="emulator_15.0")
    c.add_argument("--device", default="Samsung Galaxy S10")
    c.add_argument("--no-pull", action="store_true")
    c.add_argument("-y", "--yes", action="store_true")

    for name, h, fn in [
        ("launch", "start VM", cmd_start),
        ("start", "start VM", cmd_start),
        ("stop", "stop VM", cmd_stop),
        ("restart", "restart VM", cmd_restart),
        ("delete", "delete VM", cmd_delete),
        ("info", "VM info", cmd_info),
        ("gui", "open noVNC in browser", cmd_gui),
        ("adb", "adb connect", cmd_adb),
        ("shell", "adb shell", cmd_shell),
        ("logcat", "adb logcat", cmd_logcat),
        ("screenshot", "not yet implemented", cmd_stub),
        ("record", "not yet implemented", cmd_stub),
        ("reset", "delete persisted volume data", cmd_reset),
    ]:
        sp = add(name, h, fn)
        if name != "screenshot" and name != "record":
            sp.add_argument("name")
        else:
            sp.add_argument("name", nargs="?")
        if name == "delete":
            sp.add_argument("--keep-data", action="store_true")
            sp.add_argument("-y", "--yes", action="store_true")
        if name == "reset":
            sp.add_argument("-y", "--yes", action="store_true")
    return p


def banner() -> None:
    OUT.say()
    OUT.say(topic("Android Construct"))
    OUT.say()
    OUT.say("Backend:")
    OUT.say("  Docker-Android-Pro (budtmo2/docker-android-pro)")
    OUT.say()
    configured = access_configured()
    OUT.say("Status:")
    OUT.say("  CONFIGURED" if configured else "  NOT CONFIGURED")
    OUT.say()
    if not configured:
        OUT.say("Reason:")
        OUT.say("  Docker-Android-Pro requires active GitHub sponsorship/access.")
        OUT.say("  Credentials via ANDROIDVM_DOCKER_* or ~/.config/vmtools/secrets.env")
        OUT.say()
    OUT.say("Commands:")
    OUT.say("  androidvm doctor | setup | status | images | create | launch | gui | adb")


def cmd_status(args) -> int:
    payload = {
        "backend": "docker-android-pro",
        "repo": img.DEFAULT_REPO,
        "configured": access_configured(),
        "user_env_set": bool(credentials()[0]),
        "token_env_set": bool(credentials()[1]),
        "vms": len(rt.list_vms()),
    }
    if args.json:
        OUT.say(json.dumps(payload, indent=2))
        return EXIT_OK
    banner()
    return EXIT_OK if payload["configured"] else EXIT_ACCESS


def cmd_setup(args) -> int:
    ensure()
    OUT.step("Checking Docker")
    if not which("docker"):
        raise Fail("docker not found", EXIT_PREREQ)
    OUT.ok("docker present")
    OUT.step("Checking /dev/kvm")
    kvm = Path("/dev/kvm")
    if not kvm.exists() or not os.access(kvm, os.R_OK | os.W_OK):
        raise Fail("/dev/kvm missing or not accessible", EXIT_PREREQ)
    OUT.ok("/dev/kvm OK")
    user, token = credentials()
    if not user or not token:
        raise Fail("Pro access is not configured", EXIT_ACCESS, "set ANDROIDVM_DOCKER_USER/TOKEN or secrets.env")
    OUT.step("docker login (legitimate credentials only)")
    docker_login()
    OUT.ok("Setup complete.")
    return EXIT_OK


def cmd_doctor(args) -> int:
    rows = []
    def row(name, ok, detail):
        mark = STYLE.green(SYM_OK) if ok else STYLE.red(SYM_BAD)
        OUT.say(f"{mark} {name:<22} {'OK' if ok else 'FAIL':<6} {detail}")
        rows.append({"name": name, "ok": ok, "detail": detail})

    row("Docker", bool(which("docker")), which("docker") or "missing")
    kvm = Path("/dev/kvm")
    row("KVM", kvm.exists() and os.access(kvm, os.R_OK | os.W_OK), str(kvm))
    row("Pro credentials", bool(credentials()[0] and credentials()[1]), "env/secrets.env")
    row("Pro access state", access_configured(), "androidvm setup")
    row("adb", bool(which("adb")), which("adb") or "optional")
    try:
        ports = allocate(18080, 2)
        row("Port allocator", True, f"sample {ports}")
    except Exception as exc:
        row("Port allocator", False, str(exc))
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
    if not access_configured():
        return EXIT_ACCESS
    return EXIT_OK


def cmd_config(args) -> int:
    OUT.say(json.dumps(config().values, indent=2))
    return EXIT_OK


def cmd_list(args) -> int:
    require_access()
    rows = []
    for vm in rt.list_vms():
        st = rt.status_of(vm["name"])
        rows.append(st)
    if args.json:
        OUT.say(json.dumps(rows, indent=2)); return EXIT_OK
    if not rows:
        OUT.say("No Android VMs."); return EXIT_OK
    OUT.say(f"{'NAME':<20} {'STATE':<12} VIEWER")
    for r in rows:
        OUT.say(f"{r['name']:<20} {r.get('state','?'):<12} http://{r.get('viewer')}")
    return EXIT_OK


def cmd_images(args) -> int:
    tags = img.list_tags()
    preferred = img.preferred_emulator_tags(tags)
    if args.json:
        OUT.say(json.dumps({"repo": img.DEFAULT_REPO, "preferred": preferred, "all": [t.get("name") for t in tags]}, indent=2))
        return EXIT_OK
    OUT.say(f"Repo: {img.DEFAULT_REPO}")
    OUT.say("Preferred emulator tags:")
    for n in preferred[:20]:
        OUT.say(f"  {n}")
    OUT.note(f"{len(tags)} tags total (showing preferred short tags)")
    return EXIT_OK


def cmd_pull(args) -> int:
    rt.docker_pull(args.tag)
    return EXIT_OK


def cmd_create(args) -> int:
    name = args.name or (None if args.yes else prompt("VM name", "pixel15"))
    if not name:
        raise Fail("name required", EXIT_PREREQ)
    if not args.yes and not confirm(f"Create {name} with {args.tag}?", default=True):
        OUT.warn("cancelled"); return EXIT_OK
    rt.create(name, tag=args.tag, device=args.device, pull=not args.no_pull)
    return EXIT_OK


def cmd_start(args) -> int:
    rt.start(validate_name(args.name)); return EXIT_OK


def cmd_stop(args) -> int:
    rt.stop(validate_name(args.name)); return EXIT_OK


def cmd_restart(args) -> int:
    name = validate_name(args.name)
    rt.stop(name); rt.start(name); return EXIT_OK


def cmd_delete(args) -> int:
    name = validate_name(args.name)
    meta = rt.load_vm(name)
    OUT.say(f"Container: {meta['container']}")
    OUT.say(f"Volume:    {meta['volume']}")
    if not args.yes and not confirm("Delete?", default=False):
        OUT.warn("cancelled"); return EXIT_OK
    rt.delete(name, keep_data=args.keep_data); return EXIT_OK


def cmd_info(args) -> int:
    st = rt.status_of(validate_name(args.name))
    if args.json:
        OUT.say(json.dumps(st, indent=2)); return EXIT_OK
    for k, v in st.items():
        OUT.say(f"{k:<14} {v}")
    return EXIT_OK


def cmd_gui(args) -> int:
    rt.open_gui(validate_name(args.name)); return EXIT_OK


def cmd_adb(args) -> int:
    rt.adb_connect(validate_name(args.name)); return EXIT_OK


def cmd_shell(args) -> int:
    name = validate_name(args.name)
    rt.adb_connect(name)
    import subprocess
    meta = rt.load_vm(name)
    return subprocess.call(["docker", "exec", "-it", meta["container"], "adb", "shell"])


def cmd_logcat(args) -> int:
    name = validate_name(args.name)
    rt.adb_connect(name)
    import subprocess
    meta = rt.load_vm(name)
    return subprocess.call(["docker", "exec", "-it", meta["container"], "adb", "logcat"])


def cmd_stub(args) -> int:
    raise Fail(f"androidvm {args.command} is not implemented yet", EXIT_PREREQ)


def cmd_reset(args) -> int:
    name = validate_name(args.name)
    meta = rt.load_vm(name)
    OUT.warn(f"This deletes docker volume {meta['volume']}")
    if not args.yes and not confirm("Reset persisted data?", default=False):
        OUT.warn("cancelled"); return EXIT_OK
    rt.stop(name)
    run = __import__("vmtools.proc", fromlist=["run"]).run
    run(["docker", "volume", "rm", "-f", meta["volume"]], check=False)
    OUT.ok("volume removed; next start recreates empty data")
    return EXIT_OK

def interactive_root() -> int:
    """Lightweight TUI wrapping existing androidvm commands (no destroy)."""
    ensure()
    banner()
    OUT.say()
    vms = rt.list_vms()
    OUT.say("VMs")
    OUT.say("─" * 28)
    if vms:
        for i, v in enumerate(vms, 1):
            name = v.get("name", "?")
            try:
                st = rt.status_of(name)
                state = st.get("state", "?")
            except Exception:
                state = "?"
            OUT.say(f"{i}. {name:<20} {state}")
    else:
        OUT.say("(none)")

    def do_launch():
        name = prompt("VM name")
        if name:
            rt.start(validate_name(name))
            rt.open_gui(name)

    def do_gui():
        name = prompt("VM name")
        if name:
            rt.open_gui(validate_name(name))

    def do_list():
        cmd_list(argparse.Namespace(json=False))

    def do_status():
        cmd_status(argparse.Namespace(json=False))

    def do_doctor():
        cmd_doctor(argparse.Namespace(json=False))

    def do_create():
        cmd_create(argparse.Namespace(name=None, tag="emulator_15.0", device="Samsung Galaxy S10", no_pull=False, yes=False, json=False))

    menu(
        "Actions",
        [
            ("1", "Launch + open noVNC", do_launch),
            ("2", "Open noVNC (gui)", do_gui),
            ("3", "List VMs", do_list),
            ("4", "Status", do_status),
            ("5", "Doctor", do_doctor),
            ("6", "Create VM", do_create),
        ],
    )
    return EXIT_OK


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from vmtools.app import apply_global_flags
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
