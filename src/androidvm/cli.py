"""androidvm — Docker-Android-Pro manager (sponsor access required for pulls)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from vmtools.app import Parser, add_global_flags, main as app_main, topic
from vmtools.layout import LAYOUT, config, ensure
from vmtools.proc import which
from vmtools.ui import EXIT_ACCESS, EXIT_OK, EXIT_PREREQ, Fail, OUT, STYLE, SYM_BAD, SYM_OK

from .access import access_configured, credentials, docker_login, require_access
from .ports import allocate


FUTURE = (
    "list", "create", "launch", "start", "stop", "restart", "delete", "info",
    "gui", "adb", "logcat", "shell", "screenshot", "record", "images", "pull", "reset",
)


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="androidvm",
        description="Manage Android emulators via Docker-Android-Pro (requires legitimate Pro access).",
    )
    add_global_flags(p)
    p.add_argument("--version", action="version", version="androidvm 0.1.0")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(handler=handler)
        return sp

    add("help", "show help", lambda a: (p.print_help(), EXIT_OK)[1])
    add("status", "show backend status", cmd_status)
    add("setup", "verify host + configure Pro login", cmd_setup)
    add("doctor", "host + access checks", cmd_doctor)
    add("config", "show config", cmd_config).add_argument("key", nargs="?")
    # Future commands: report not configured / not implemented until access
    for name in FUTURE:
        sp = add(name, f"(requires Pro access) {name}", cmd_future)
        if name in ("launch", "start", "stop", "restart", "delete", "info", "gui", "adb", "logcat", "shell", "screenshot", "record", "reset", "pull"):
            sp.add_argument("name", nargs="?")
    return p


def banner() -> None:
    OUT.say()
    OUT.say(topic("Android VM Manager"))
    OUT.say()
    OUT.say("Backend:")
    OUT.say("  Docker-Android-Pro")
    OUT.say()
    configured = access_configured()
    OUT.say("Status:")
    OUT.say("  CONFIGURED" if configured else "  NOT CONFIGURED")
    OUT.say()
    if not configured:
        OUT.say("Reason:")
        OUT.say("  Docker-Android-Pro requires active GitHub sponsorship/access.")
        OUT.say("  No attempt has been made to access sponsor-only images")
        OUT.say("  until credentials are provided via environment.")
        OUT.say()
    OUT.say("Commands:")
    OUT.say("  androidvm doctor")
    OUT.say("  androidvm setup")
    OUT.say("  androidvm status")
    OUT.say("  androidvm help")


def cmd_status(args) -> int:
    payload = {
        "backend": "docker-android-pro",
        "configured": access_configured(),
        "user_env_set": bool(credentials()[0]),
        "token_env_set": bool(credentials()[1]),
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
        raise Fail("docker not found", EXIT_PREREQ, "enable virtualisation.docker on NixOS")
    OUT.ok("docker present")

    OUT.step("Checking /dev/kvm")
    kvm = Path("/dev/kvm")
    if not kvm.exists():
        raise Fail("/dev/kvm missing", EXIT_PREREQ)
    if not os.access(kvm, os.R_OK | os.W_OK):
        raise Fail("/dev/kvm not accessible", EXIT_PREREQ, "join the kvm group and re-login")
    OUT.ok("/dev/kvm OK")

    user, token = credentials()
    if not user or not token:
        OUT.warn("Pro registry credentials not found in environment.")
        OUT.note("Export ANDROIDVM_DOCKER_USER and ANDROIDVM_DOCKER_TOKEN (Docker Hub PAT).")
        OUT.note("Do not put the token in git, config.toml, or chat logs.")
        raise Fail("Pro access is not configured", EXIT_ACCESS)

    OUT.step("docker login (legitimate credentials only)")
    docker_login()
    OUT.ok("Setup complete. Image pulls can proceed with androidvm pull once catalog is enabled.")
    OUT.note("Viewer/ADB ports bind to 127.0.0.1 by default.")
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
    row("Pro credentials", bool(credentials()[0] and credentials()[1]), "env ANDROIDVM_DOCKER_*")
    row("Pro access state", access_configured(), "androidvm setup")
    # port allocator smoke
    try:
        ports = allocate(6080, 2)
        row("Port allocator", True, f"sample {ports}")
    except Exception as exc:
        row("Port allocator", False, str(exc))
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
    blocking = not all(r["ok"] for r in rows if r["name"] != "Pro access state")
    if not access_configured():
        return EXIT_ACCESS
    return EXIT_PREREQ if blocking else EXIT_OK


def cmd_config(args) -> int:
    cfg = config()
    OUT.say(json.dumps(cfg.values, indent=2))
    return EXIT_OK


def cmd_future(args) -> int:
    require_access()
    raise Fail(
        f"androidvm {args.command} is scaffolded but not fully implemented yet",
        EXIT_ACCESS,
        "Pro access is configured; implementation of container lifecycle is next",
    )


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from vmtools.app import apply_global_flags
        apply_global_flags(argparse.Namespace(verbose=False, debug=False, quiet=False, json=False))
        banner()
        return EXIT_ACCESS if not access_configured() else EXIT_OK
    return app_main(build_parser, argv)


if __name__ == "__main__":
    raise SystemExit(main())
