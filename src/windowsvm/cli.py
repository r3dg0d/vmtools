"""windowsvm — Windows QEMU/KVM/libvirt manager."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vmtools import libvirt as lv
from vmtools.app import Parser, add_global_flags, topic
from vmtools.app import main as app_main
from vmtools.config import validate_name
from vmtools.doctor import doctor_libvirt
from vmtools.layout import LAYOUT, config, ensure
from vmtools.menu import confirm, menu, prompt
from vmtools.ui import EXIT_CHECKSUM, EXIT_OK, EXIT_USAGE, OUT, Fail

from . import __version__
from .catalog import catalog
from .create import interactive_create


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="windowsvm",
        description="Windows Construct: manage Windows VMs with QEMU/KVM/libvirt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Windows Construct — sibling of iosvm/macosvm/linuxvm/androidvm. Official Microsoft media only.",
    )
    add_global_flags(p)
    p.add_argument("--version", action="version", version=f"windowsvm {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(handler=handler)
        return sp

    add("help", "show this help", lambda a: (p.print_help(), EXIT_OK)[1])
    add("tui", "interactive terminal menu", lambda a: interactive_root())
    add("list", "list Windows/libvirt VMs", cmd_list)
    c = add("create", "create a Windows VM", cmd_create)
    c.add_argument("--name")
    c.add_argument("--iso")
    c.add_argument("--cpus", type=int)
    c.add_argument("--ram", type=int, help="RAM in GiB")
    c.add_argument("--disk", type=int, help="disk GiB")
    for name, h, fn in [
        ("launch", "start a VM", cmd_start),
        ("start", "start a VM", cmd_start),
        ("stop", "force stop a VM", cmd_stop),
        ("shutdown", "ACPI shutdown", cmd_shutdown),
        ("reboot", "reboot a VM", cmd_reboot),
        ("pause", "pause a VM", cmd_pause),
        ("resume", "resume a VM", cmd_resume),
        ("delete", "delete a VM", cmd_delete),
        ("info", "show VM info", cmd_info),
        ("console", "serial/virsh console", cmd_console),
    ]:
        sp = add(name, h, fn)
        sp.add_argument("name")
        if name == "stop":
            sp.add_argument("--force", action="store_true", default=True)
        if name == "delete":
            sp.add_argument("--keep-disk", action="store_true")
            sp.add_argument("-y", "--yes", action="store_true")

    g = add("gui", "open virt-manager / virt-viewer", cmd_gui)
    g.add_argument("name", nargs="?")

    sp = add("snapshot", "create a snapshot", cmd_snapshot)
    sp.add_argument("name")
    sp.add_argument("snapshot")
    sp = add("snapshots", "list snapshots", cmd_snapshots)
    sp.add_argument("name")
    sp = add("restore", "restore a snapshot", cmd_restore)
    sp.add_argument("name")
    sp.add_argument("snapshot")
    sp.add_argument("-y", "--yes", action="store_true")

    sp = add("clone", "clone a VM", cmd_clone)
    sp.add_argument("source")
    sp.add_argument("destination")

    iso = sub.add_parser("iso", help="ISO cache commands")
    iso_sub = iso.add_subparsers(dest="iso_cmd")
    for n, h, fn in [
        ("list", "list cached Windows ISOs", cmd_iso_list),
        ("download", "download catalog media / virtio", cmd_iso_download),
        ("verify", "verify an ISO SHA-256", cmd_iso_verify),
        ("delete", "delete cached ISO by name", cmd_iso_delete),
        ("refresh", "refresh media catalog notes", cmd_iso_refresh),
    ]:
        isp = iso_sub.add_parser(n, help=h)
        isp.set_defaults(handler=fn)
        if n == "verify":
            isp.add_argument("file")
            isp.add_argument("--expect", help="expected sha256")
        if n == "delete":
            isp.add_argument("id")
        if n == "download":
            isp.add_argument("--virtio", action="store_true")

    net = sub.add_parser("network", help="list/ensure networks")
    net_sub = net.add_subparsers(dest="net_cmd")
    np = net_sub.add_parser("list", help="list networks")
    np.set_defaults(handler=cmd_net_list)
    np = net_sub.add_parser("lab", help="ensure isolated vm-lab network")
    np.set_defaults(handler=cmd_net_lab)

    add("doctor", "check host prerequisites", cmd_doctor)
    add("config", "show or set config", cmd_config)
    # the config command takes an optional key/value
    for sp in sub._name_parser_map.values():
        if sp.prog.endswith("config"):
            sp.add_argument("key", nargs="?")
            sp.add_argument("value", nargs="?")
            break

    return p


def cmd_list(args) -> int:
    ensure()
    domains = lv.list_domains()
    # Prefer VMs we tagged as windows; still show all if none tagged
    tagged = set()
    meta_dir = LAYOUT.data / "metadata"
    if meta_dir.is_dir():
        for p in meta_dir.glob("vm-*.json"):
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if data.get("os") == "windows":
                tagged.add(data.get("name"))
    rows = [d for d in domains if not tagged or d.name in tagged] or domains
    if args.json:
        OUT.say(json.dumps([d.__dict__ for d in rows], indent=2))
        return EXIT_OK
    if not rows:
        OUT.say("No VMs defined.")
        return EXIT_OK
    OUT.say(f"{'NAME':<24} {'STATE':<12} {'vCPU':<6} MEMORY")
    for d in rows:
        mem = f"{d.memory_kib // 1024 // 1024} GiB" if d.memory_kib else "?"
        OUT.say(f"{d.name:<24} {d.state:<12} {d.cpu:<6} {mem}")
    return EXIT_OK


def cmd_create(args) -> int:
    return interactive_create(args)


def cmd_start(args) -> int:
    lv.start(validate_name(args.name))
    return EXIT_OK


def cmd_stop(args) -> int:
    lv.shutdown(validate_name(args.name), force=True)
    return EXIT_OK


def cmd_shutdown(args) -> int:
    lv.shutdown(validate_name(args.name), force=False)
    return EXIT_OK


def cmd_reboot(args) -> int:
    lv.reboot(validate_name(args.name))
    return EXIT_OK


def cmd_pause(args) -> int:
    lv.pause(validate_name(args.name))
    return EXIT_OK


def cmd_resume(args) -> int:
    lv.resume(validate_name(args.name))
    return EXIT_OK


def cmd_delete(args) -> int:
    name = validate_name(args.name)
    lv.require_domain(name)
    disk = LAYOUT.data / "disks" / f"{name}.qcow2"
    snaps = []
    try:
        snaps = lv.snapshot_list(name)
    except Exception:
        pass
    OUT.say("Will remove:")
    OUT.say(f"  VM definition: {name}")
    OUT.say(f"  Disk: {disk if disk.is_file() else '(libvirt storage)'}")
    OUT.say(f"  Snapshots: {len(snaps)}")
    OUT.say("  ISO cache: NOT DELETED")
    if not args.yes and not confirm("Delete this VM?", default=False):
        OUT.warn("cancelled")
        return EXIT_OK
    lv.undefine(name, keep_disk=args.keep_disk)
    meta = LAYOUT.data / "metadata" / f"vm-{name}.json"
    meta.unlink(missing_ok=True)
    return EXIT_OK


def cmd_info(args) -> int:
    name = validate_name(args.name)
    info = lv.domain_info(name)
    if not info:
        raise Fail(f"VM not found: {name}", 6)
    meta_path = LAYOUT.data / "metadata" / f"vm-{name}.json"
    meta = {}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text())
    snaps = lv.snapshot_list(name)
    payload = {
        "name": info.name,
        "state": info.state,
        "os": meta.get("os", "windows?"),
        "cpu": info.cpu,
        "memory_kib": info.memory_kib,
        "disk": meta.get("disk"),
        "firmware": "UEFI",
        "tpm": meta.get("tpm"),
        "network": meta.get("network"),
        "snapshots": len(snaps),
        "iso": meta.get("iso"),
        "uuid": info.uuid,
    }
    if args.json:
        OUT.say(json.dumps(payload, indent=2))
        return EXIT_OK
    for k, v in payload.items():
        OUT.say(f"{k.title():<14} {v}")
    return EXIT_OK


def cmd_gui(args) -> int:
    lv.open_gui(args.name)
    return EXIT_OK


def cmd_console(args) -> int:
    return lv.console(validate_name(args.name))


def cmd_snapshot(args) -> int:
    lv.snapshot_create(validate_name(args.name), args.snapshot)
    return EXIT_OK


def cmd_snapshots(args) -> int:
    rows = lv.snapshot_list(validate_name(args.name))
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
        return EXIT_OK
    OUT.say(f"{'NAME':<24} {'CREATED':<28} STATE")
    for r in rows:
        OUT.say(f"{r['name']:<24} {r['created']:<28} {r['state']}")
    return EXIT_OK


def cmd_restore(args) -> int:
    if not args.yes and not confirm("Restore will discard current state. Continue?", default=False):
        OUT.warn("cancelled")
        return EXIT_OK
    lv.snapshot_revert(validate_name(args.name), args.snapshot)
    return EXIT_OK


def cmd_clone(args) -> int:
    lv.clone_domain(validate_name(args.source), validate_name(args.destination))
    return EXIT_OK


def cmd_iso_list(args) -> int:
    ensure()
    base = LAYOUT.data / "isos/windows"
    files = sorted(base.rglob("*.iso")) if base.is_dir() else []
    if args.json:
        OUT.say(json.dumps([str(f) for f in files], indent=2))
        return EXIT_OK
    for f in files:
        OUT.say(f"{f.stat().st_size:>12}  {f}")
    if not files:
        OUT.say("No cached Windows ISOs.")
    return EXIT_OK


def cmd_iso_download(args) -> int:
    if args.virtio:
        from .create import _ensure_virtio
        _ensure_virtio()
        return EXIT_OK
    OUT.say("Microsoft consumer ISOs are not fetched via a hardcoded CDN.")
    OUT.say("Catalog entries and official pages:")
    for m in catalog():
        OUT.say(f"  {m.title}")
        OUT.note(m.source_page)
    OUT.hint("Download from Microsoft, then: windowsvm create --iso PATH")
    OUT.hint("Driver ISO: windowsvm iso download --virtio")
    return EXIT_OK


def cmd_iso_verify(args) -> int:
    from vmtools.checksum import sha256_file, verification_label
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        raise Fail(f"file not found: {path}", EXIT_USAGE)
    actual = sha256_file(path)
    OUT.say(f"actual:   {actual}")
    if args.expect:
        ok = actual.lower() == args.expect.strip().lower()
        OUT.say(f"expected: {args.expect.strip().lower()}")
        OUT.say("VERIFIED" if ok else "FAILED")
        if not ok:
            raise Fail("CHECKSUM FAILED", EXIT_CHECKSUM)
        OUT.say(verification_label(user=True))
    else:
        OUT.say(verification_label(local_only=True))
        OUT.hint("pass --expect <sha256> to compare against publisher/user hash")
    return EXIT_OK


def cmd_iso_delete(args) -> int:
    ensure()
    path = LAYOUT.data / "isos/windows" / args.id
    if not path.exists():
        path = LAYOUT.data / "isos/windows" / f"{args.id}.iso"
    if not path.exists():
        raise Fail(f"not found: {args.id}", 6)
    path.unlink()
    OUT.ok(f"deleted {path}")
    return EXIT_OK


def cmd_iso_refresh(args) -> int:
    OUT.ok("Catalog is code-defined; source pages:")
    for m in catalog():
        OUT.say(f"  {m.id}: {m.source_page}")
    return EXIT_OK


def cmd_net_list(args) -> int:
    rows = lv.network_list()
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
        return EXIT_OK
    for r in rows:
        OUT.say(f"{r['name']:<16} {r['state']:<10} autostart={r.get('autostart')}")
    return EXIT_OK


def cmd_net_lab(args) -> int:
    lv.ensure_lab_network()
    return EXIT_OK


def cmd_doctor(args) -> int:
    rows, blocking = doctor_libvirt(json_mode=False)
    if args.json:
        OUT.say(json.dumps(rows, indent=2))
    return 3 if blocking else EXIT_OK


def cmd_config(args) -> int:
    cfg = config()
    if args.key and args.value is not None:
        cfg.set(args.key, args.value)
        OUT.ok(f"set {args.key}={cfg.get(args.key)}")
        return EXIT_OK
    if args.key:
        OUT.say(json.dumps({args.key: cfg.get(args.key)}, indent=2))
        return EXIT_OK
    OUT.say(json.dumps(cfg.values, indent=2))
    return EXIT_OK


def interactive_root() -> int:
    ensure()
    domains = lv.list_domains()
    OUT.say()
    OUT.say(topic("Windows Construct"))
    OUT.say("VMs")
    OUT.say("─" * 28)
    if domains:
        for i, d in enumerate(domains, 1):
            OUT.say(f"{i}. {d.name:<20} {d.state}")
    else:
        OUT.say("(none)")

    def do_launch():
        name = prompt("VM name")
        if name:
            lv.start(validate_name(name))
            lv.open_gui(name)

    def do_create():
        interactive_create(argparse.Namespace(name=None, iso=None, cpus=None, ram=None, disk=None, json=False))

    menu(
        "Actions",
        [
            ("1", "Launch VM", do_launch),
            ("2", "Create VM", do_create),
            ("3", "Download virtio drivers", lambda: cmd_iso_download(argparse.Namespace(virtio=True, json=False))),
            ("4", "Open virt-manager", lambda: lv.open_gui(None)),
            ("5", "Doctor", lambda: cmd_doctor(argparse.Namespace(json=False))),
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
