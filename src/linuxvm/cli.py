"""linuxvm — Linux QEMU/KVM/libvirt manager."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vmtools.app import Parser, add_global_flags, main as app_main, topic
from vmtools import libvirt as lv
from vmtools.config import validate_name
from vmtools.doctor import doctor_libvirt
from vmtools.layout import LAYOUT, config, ensure
from vmtools.menu import confirm, menu, prompt
from vmtools.ui import EXIT_CHECKSUM, EXIT_OK, EXIT_USAGE, Fail, OUT

from .create import interactive_create
from .providers import get, list_providers


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="linuxvm", description="Manage Linux VMs with QEMU/KVM/libvirt.")
    add_global_flags(p)
    p.add_argument("--version", action="version", version="linuxvm 0.1.0")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(handler=handler)
        return sp

    add("help", "show help", lambda a: (p.print_help(), EXIT_OK)[1])
    add("list", "list VMs", cmd_list)
    c = add("create", "create a Linux VM", cmd_create)
    c.add_argument("--name")
    c.add_argument("--iso")
    c.add_argument("--distro")
    c.add_argument("--cpus", type=int)
    c.add_argument("--ram", type=int)
    c.add_argument("--disk", type=int)
    c.add_argument("--offline", action="store_true")
    c.add_argument("--network", default=None)
    c.add_argument("--edition", default=None)
    c.add_argument("--arch", default=None)
    c.add_argument("-y", "--yes", action="store_true", help="noninteractive confirm")
    c.add_argument("--no-launch", action="store_true")

    for name, h, fn in [
        ("launch", "start a VM", cmd_start),
        ("start", "start a VM", cmd_start),
        ("stop", "force stop", cmd_stop),
        ("shutdown", "ACPI shutdown", cmd_shutdown),
        ("reboot", "reboot", cmd_reboot),
        ("pause", "pause", cmd_pause),
        ("resume", "resume", cmd_resume),
        ("delete", "delete", cmd_delete),
        ("info", "info", cmd_info),
        ("console", "console", cmd_console),
    ]:
        sp = add(name, h, fn)
        sp.add_argument("name")
        if name == "delete":
            sp.add_argument("--keep-disk", action="store_true")
            sp.add_argument("-y", "--yes", action="store_true")

    g = add("gui", "open virt-manager", cmd_gui)
    g.add_argument("name", nargs="?")

    sp = add("snapshot", "create snapshot", cmd_snapshot)
    sp.add_argument("name"); sp.add_argument("snapshot")
    sp = add("snapshots", "list snapshots", cmd_snapshots)
    sp.add_argument("name")
    sp = add("restore", "restore snapshot", cmd_restore)
    sp.add_argument("name"); sp.add_argument("snapshot"); sp.add_argument("-y", "--yes", action="store_true")
    sp = add("clone", "clone VM", cmd_clone)
    sp.add_argument("source"); sp.add_argument("destination")

    d = sub.add_parser("distro", help="distro catalog")
    ds = d.add_subparsers(dest="distro_cmd")
    x = ds.add_parser("list"); x.set_defaults(handler=cmd_distro_list)
    x = ds.add_parser("info"); x.add_argument("distro"); x.set_defaults(handler=cmd_distro_info)

    iso = sub.add_parser("iso", help="ISO cache")
    iso_s = iso.add_subparsers(dest="iso_cmd")
    for n, fn in [("list", cmd_iso_list), ("download", cmd_iso_download), ("verify", cmd_iso_verify), ("refresh", cmd_iso_refresh)]:
        isp = iso_s.add_parser(n)
        isp.set_defaults(handler=fn)
        if n == "download":
            isp.add_argument("distro")
            isp.add_argument("--edition", default="default")
        if n == "verify":
            isp.add_argument("file"); isp.add_argument("--expect")

    add("doctor", "host checks", cmd_doctor)
    cfgp = add("config", "show/set config", cmd_config)
    cfgp.add_argument("key", nargs="?"); cfgp.add_argument("value", nargs="?")
    return p


def cmd_list(args):
    domains = lv.list_domains()
    if args.json:
        OUT.say(json.dumps([d.__dict__ for d in domains], indent=2)); return EXIT_OK
    if not domains:
        OUT.say("No VMs defined."); return EXIT_OK
    OUT.say(f"{'NAME':<24} {'STATE':<12} vCPU")
    for d in domains:
        OUT.say(f"{d.name:<24} {d.state:<12} {d.cpu}")
    return EXIT_OK


def cmd_create(args):
    return interactive_create(args)


def cmd_start(args):
    lv.start(validate_name(args.name)); return EXIT_OK


def cmd_stop(args):
    lv.shutdown(validate_name(args.name), force=True); return EXIT_OK


def cmd_shutdown(args):
    lv.shutdown(validate_name(args.name), force=False); return EXIT_OK


def cmd_reboot(args):
    lv.reboot(validate_name(args.name)); return EXIT_OK


def cmd_pause(args):
    lv.pause(validate_name(args.name)); return EXIT_OK


def cmd_resume(args):
    lv.resume(validate_name(args.name)); return EXIT_OK


def cmd_delete(args):
    name = validate_name(args.name)
    lv.require_domain(name)
    OUT.say(f"VM definition: {name}")
    OUT.say(f"Disk: {LAYOUT.data / 'disks' / (name + '.qcow2')}")
    OUT.say("ISO cache: NOT DELETED")
    if not args.yes and not confirm("Delete?", default=False):
        OUT.warn("cancelled"); return EXIT_OK
    lv.undefine(name, keep_disk=args.keep_disk)
    (LAYOUT.data / "metadata" / f"vm-{name}.json").unlink(missing_ok=True)
    return EXIT_OK


def cmd_info(args):
    name = validate_name(args.name)
    info = lv.domain_info(name)
    if not info:
        raise Fail(f"VM not found: {name}", 6)
    meta = {}
    mp = LAYOUT.data / "metadata" / f"vm-{name}.json"
    if mp.is_file():
        meta = json.loads(mp.read_text())
    payload = {**info.__dict__, **meta, "snapshots": len(lv.snapshot_list(name))}
    if args.json:
        OUT.say(json.dumps(payload, indent=2)); return EXIT_OK
    for k, v in payload.items():
        OUT.say(f"{str(k):<14} {v}")
    return EXIT_OK


def cmd_gui(args):
    lv.open_gui(args.name); return EXIT_OK


def cmd_console(args):
    return lv.console(validate_name(args.name))


def cmd_snapshot(args):
    lv.snapshot_create(validate_name(args.name), args.snapshot); return EXIT_OK


def cmd_snapshots(args):
    rows = lv.snapshot_list(validate_name(args.name))
    if args.json:
        OUT.say(json.dumps(rows, indent=2)); return EXIT_OK
    for r in rows:
        OUT.say(f"{r['name']:<24} {r['created']:<28} {r['state']}")
    return EXIT_OK


def cmd_restore(args):
    if not args.yes and not confirm("Discard current state and restore?", default=False):
        OUT.warn("cancelled"); return EXIT_OK
    lv.snapshot_revert(validate_name(args.name), args.snapshot); return EXIT_OK


def cmd_clone(args):
    lv.clone_domain(validate_name(args.source), validate_name(args.destination)); return EXIT_OK


def cmd_distro_list(args):
    rows = [{"id": p.id, "name": p.name, "editions": list(p.editions())} for p in list_providers()]
    if args.json:
        OUT.say(json.dumps(rows, indent=2)); return EXIT_OK
    for r in rows:
        OUT.say(f"{r['id']:<12} {r['name']:<16} editions={','.join(r['editions'])}")
    return EXIT_OK


def cmd_distro_info(args):
    p = get(args.distro)
    try:
        m = p.latest()
        payload = m.__dict__
    except Exception as exc:
        payload = {"id": p.id, "name": p.name, "error": str(exc)}
    if args.json:
        OUT.say(json.dumps(payload, indent=2)); return EXIT_OK
    for k, v in payload.items():
        OUT.say(f"{k:<16} {v}")
    return EXIT_OK


def cmd_iso_list(args):
    ensure()
    base = LAYOUT.data / "isos/linux"
    files = sorted(base.glob("*.iso")) if base.is_dir() else []
    for f in files:
        OUT.say(f"{f.stat().st_size:>12}  {f}")
    if not files:
        OUT.say("No cached Linux ISOs.")
    return EXIT_OK


def cmd_iso_download(args):
    ensure()
    p = get(args.distro)
    edition = args.edition
    if edition == "default":
        edition = list(p.editions())[0]
    m = p.latest(edition)
    dest = LAYOUT.data / "isos/linux" / m.filename
    from vmtools.download import download
    download(m.url, dest, expected_sha256=m.sha256, label=m.filename)
    return EXIT_OK


def cmd_iso_verify(args):
    from vmtools.checksum import sha256_file, verification_label
    path = Path(args.file).expanduser().resolve()
    actual = sha256_file(path)
    OUT.say(f"actual: {actual}")
    if args.expect:
        ok = actual.lower() == args.expect.strip().lower()
        OUT.say("VERIFIED" if ok else "FAILED")
        if not ok:
            raise Fail("CHECKSUM FAILED", EXIT_CHECKSUM)
        OUT.say(verification_label(user=True))
    else:
        OUT.say(verification_label(local_only=True))
    return EXIT_OK


def cmd_iso_refresh(args):
    for p in list_providers():
        try:
            m = p.latest()
            OUT.ok(f"{p.id}: {m.filename} ({m.version})")
        except Exception as exc:
            OUT.warn(f"{p.id}: {exc}")
    return EXIT_OK


def cmd_doctor(args):
    rows, blocking = doctor_libvirt()
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
    return 3 if blocking else EXIT_OK


def cmd_config(args):
    cfg = config()
    if args.key and args.value is not None:
        cfg.set(args.key, args.value); OUT.ok(f"set {args.key}"); return EXIT_OK
    OUT.say(json.dumps(cfg.values if not args.key else {args.key: cfg.get(args.key)}, indent=2))
    return EXIT_OK


def interactive_root() -> int:
    ensure()
    domains = lv.list_domains()
    OUT.say(); OUT.say(topic("Linux VM Manager")); OUT.say("VMs"); OUT.say("─" * 28)
    if domains:
        for i, d in enumerate(domains, 1):
            OUT.say(f"{i}. {d.name:<20} {d.state}")
    else:
        OUT.say("(none)")

    def do_create():
        interactive_create(argparse.Namespace(name=None, iso=None, cpus=None, ram=None, disk=None, offline=False, json=False))

    menu("Actions", [
        ("1", "Launch VM", lambda: lv.start(validate_name(prompt("VM name"))) or lv.open_gui(prompt("open gui for (enter name again)"))),
        ("2", "Create VM", do_create),
        ("3", "Distro list", lambda: cmd_distro_list(argparse.Namespace(json=False))),
        ("4", "Open virt-manager", lambda: lv.open_gui(None)),
        ("5", "Doctor", lambda: cmd_doctor(argparse.Namespace(json=False))),
    ])
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
