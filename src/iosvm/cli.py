"""iosvm — iOS Construct: boot iOS (and Apple-silicon macOS) kernels to a root shell on jprx/qemu-sptm.

This follows https://github.com/jprx/darwin-vm: QEMU's `-M darwin` machine loads the kernelcache,
device tree, SPTM/TXM and a restore ramdisk patched with bash. It is NOT a full iPhone: no screen,
GPU, Wi-Fi or SpringBoard — you get a serial root shell (`iosvm console`).

Apple files are user-supplied (`import`, e.g. darwin-vm's firmware/ folder finished on your Mac)
or pulled on request from Apple's CDN (`fetch`, the same files get_files.sh downloads).
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from vmtools import checks as ck
from vmtools.app import Parser, add_global_flags
from vmtools.app import main as app_main
from vmtools.apple import Guest, Store, asset_dir, fmt_uptime
from vmtools.config import validate_name
from vmtools.layout import config
from vmtools.proc import which
from vmtools.ui import EXIT_NOT_FOUND, EXIT_PREREQ, EXIT_STATE, EXIT_USAGE, OUT, STYLE, Fail, table

from . import __version__
from . import firmware as fw

STORE = Store("ios")
BOOT_ARGS = "rd=md0 serial=3 -v -noprogress wdt=-1 wlan-olyhal-abort"


def darwin_vm() -> Path | None:
    return asset_dir("VMTOOLS_DARWIN_VM", "darwin-vm", str(config().get("ios_darwin_vm_dir", "")))


def qemu_bin() -> str:
    env = os.environ.get("VMTOOLS_QEMU_SPTM")
    return env or str(config().get("ios_qemu", "qemu-system-aarch64-sptm"))


def _sptm_machine_ok() -> tuple[bool, str]:
    q = which(qemu_bin()) or (qemu_bin() if Path(qemu_bin()).is_file() else None)
    if not q:
        return False, f"{qemu_bin()} not found"
    out = subprocess.run([q, "-M", "help"], capture_output=True, text=True, check=False).stdout
    return ("darwin" in out.split()), q


def cmd_doctor(args) -> int:
    rep = ck.Report()
    host = rep.section("Host")
    host.add(ck.check_memory(8))
    host.add(ck.check_disk_space(STORE.root if STORE.root.exists() else Path.home(), 20))
    host.add(ck.Check("acceleration", ck.OK, "TCG (aarch64 is emulated on x86; boots take minutes)"))
    tools = rep.section("Tools")
    ok, detail = _sptm_machine_ok()
    tools.add(ck.Check("qemu-sptm with -M darwin", ck.OK if ok else ck.FAIL, detail,
                       "nix-build nix/qemu-sptm.nix -o ~/.local/share/vmtools/apple/qemu-sptm && iosvm config ios_qemu ~/.local/share/vmtools/apple/qemu-sptm/bin/qemu-system-aarch64 (the packaged iosvm ships it)"))
    tools.add(ck.check_binary("ipsw (fetch)", "ipsw", required=False, hint="nix shell nixpkgs#ipsw"))
    tools.add(ck.check_binary("jq (fetch)", "jq", required=False, hint="nix shell nixpkgs#jq"))
    tools.add(ck.check_binary("socat (console)", "socat", required=False, hint="nix shell nixpkgs#socat"))
    dv = darwin_vm()
    tools.add(ck.Check("darwin-vm scripts (dt_fixup.py, nvram.bin)", ck.OK if dv else ck.WARN, str(dv or "not found"),
                       "nix-build nix/apple-assets.nix -o ~/.local/share/vmtools/apple/assets"))
    media = rep.section("Firmware (user-supplied)")
    sets = [e for e in STORE.manifest().values() if e["kind"] == "firmware"]
    ready = [e["id"] for e in sets if fw.inspect(Path(e["path"]))["patched"]]
    media.add(ck.Check("bootable firmware set (patched ramdisk + ramdisk.tc)", ck.OK if ready else ck.WARN, ", ".join(ready) or "none",
                       "on your Mac: darwin-vm ./get_files.sh && ./fix_perms.sh, copy firmware/ over, `iosvm import firmware/ --name ios27`"))
    unpatched = [e["id"] for e in sets if e["id"] not in ready]
    if unpatched:
        media.add(ck.Check("unpatched sets (fetched on Linux)", ck.WARN, ", ".join(unpatched), "finish the ramdisk patch on the Mac (README)"))
    if OUT.json:
        OUT.emit_json(rep.as_dict())
    else:
        rep.render("iOS Construct — host check")
    return 1 if rep.counts()[2] else 0


def cmd_import(args) -> int:
    src = Path(args.path).expanduser()
    if src.is_dir():
        r = fw.validate(src)
        entry = STORE.add_import(src, "firmware", name=args.name, move=args.move, link=args.link,
                                 extra={"device": r["device"], "patched": r["patched"]})
        if not r["patched"]:
            OUT.warn("no ramdisk.tc: the ramdisk isn't patched yet, so it boots but gives no shell (finish on the Mac)")
    elif src.suffix.lower() == ".ipsw":
        entry = STORE.add_import(src, "ipsw", name=args.name, move=args.move, link=args.link, hash_it=not args.no_hash)
        OUT.note(f"next: iosvm fetch --ipsw {entry['id']} --device <identifier, e.g. iPhone17,3>")
    else:
        raise Fail(f"{src.name}: expected darwin-vm's firmware/ folder or a .ipsw", EXIT_USAGE)
    OUT.emit_json(entry) if OUT.json else OUT.ok(f"imported {entry['id']} ({entry['kind']})")
    return 0


def cmd_imports(args) -> int:
    if args.rm:
        STORE.remove_import(args.rm)
        OUT.ok(f"removed import {args.rm}")
        return 0
    rows = sorted(STORE.manifest().values(), key=lambda e: e["id"])
    for e in rows:
        if e["kind"] == "firmware":
            e["patched"] = fw.inspect(Path(e["path"]))["patched"]
    if OUT.json:
        OUT.emit_json(rows)
    elif not rows:
        OUT.say("no imports yet — `iosvm import firmware/` or `iosvm fetch`")
    else:
        OUT.say(table(["ID", "KIND", "DEVICE", "SHELL-READY", "PATH"],
                      [[e["id"], e["kind"], e.get("device") or "-", {True: "yes", False: "no"}.get(e.get("patched"), "-"), e["path"]] for e in rows]))
    return 0


def cmd_fetch(args) -> int:
    dv = darwin_vm()
    if not dv:
        raise Fail("darwin-vm assets not found", EXIT_PREREQ, "nix-build nix/apple-assets.nix -o ~/.local/share/vmtools/apple/assets")
    if args.ipsw:
        source, remote = STORE.get_import(args.ipsw, ("ipsw",))["path"], False
    else:
        source, remote = args.url or fw.DEFAULT_URL, True
    name = validate_name(args.name or f"{args.device.replace(',', '-')}-fw")
    out = STORE.ensure().imports / name
    if out.exists():
        raise Fail(f"import {name} already exists", EXIT_STATE, "pass --name")
    if args.dry_run:
        OUT.say(f"device {args.device}\nsource {source} ({'Apple CDN, file-by-file' if remote else 'local IPSW'})\nout    {out}")
        return 0
    try:
        r = fw.fetch(out, device=args.device, source=source, darwin_vm=dv, remote=remote)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    STORE.record({"id": name, "kind": "firmware", "path": str(out), "source": source, "device": args.device,
                  "patched": r["patched"], "imported": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")})
    OUT.ok(f"firmware set {name} ready (unpatched ramdisk)")
    OUT.note("the bash ramdisk patch + ramdisk.tc need macOS (hdiutil/codesign): see README 'Finish on the Mac'")
    return 0


def cmd_create(args) -> int:
    name = validate_name(args.name or "iphone")
    d = STORE.ensure().vm_dir(name)
    if (d / "vm.json").exists():
        raise Fail(f"{name} already exists", EXIT_STATE)
    sets = [e for e in STORE.manifest().values() if e["kind"] == "firmware"]
    if args.firmware:
        entry = STORE.get_import(args.firmware, ("firmware",))
    elif sets:
        entry = sorted(sets, key=lambda e: e["imported"])[-1]
    else:
        raise Fail("no firmware imported", EXIT_NOT_FOUND, "iosvm import <darwin-vm firmware/>   (see `iosvm doctor`)")
    r = fw.inspect(Path(entry["path"]))
    meta = {"os": "ios", "firmware": entry["id"], "firmware_path": entry["path"], "device": r["device"],
            "ram_gib": args.ram or config().get("ios_default_ram_gib"), "boot_args": args.boot_args or BOOT_ARGS,
            "qemuports": bool(args.qemuports), "patched": r["patched"], "cpus": 1}
    if args.dry_run:
        OUT.emit_json(meta) if OUT.json else [OUT.say(f"  {k:14} {v}") for k, v in meta.items()]
        OUT.ok(f"dry run: would create {d}")
        return 0
    d.mkdir(parents=True)
    g = Guest(d)
    g.meta = meta
    g.save()
    OUT.ok(f"created {name} on firmware {entry['id']}")
    OUT.note(f"next: iosvm start {name} && iosvm console {name}")
    return 0


def qemu_argv(g: Guest) -> list[str]:
    m, f = g.meta, Path(g.meta["firmware_path"])
    argv = [qemu_bin(), "-name", f"iosvm-{g.name}", "-M", "darwin", "-bootkc", str(f / "bootkc"), "-dtree", str(f / "dtree")]
    if (f / "ramdisk.tc").is_file():
        argv += ["-tc", str(f / "ramdisk.tc")]
    argv += ["-ramdisk", str(f / "ramdisk.dmg"), "-args", m["boot_args"], "-display", "none", "-monitor", "none",
             "-serial", f"unix:{g.serial_sock},server=on,wait=off", "-m", f"{m['ram_gib']}G"]
    if (f / "sptm").is_file():
        argv += ["-sptm", str(f / "sptm"), "-txm", str(f / "txm")]
    if m.get("qemuports"):
        argv += ["-chardev", "socket,id=s0,host=127.0.0.1,server=on,wait=off,port=2100", "-serial", "chardev:s0"]
    return argv


def cmd_start(args) -> int:
    g = STORE.vm(args.name)
    argv = g.launch(qemu_argv(g), dry_run=args.dry_run)
    if args.dry_run:
        OUT.say(shlex.join(argv))
        return 0
    OUT.ok(f"{g.name} booting (pid {g.pid()}) — serial: iosvm console {g.name}")
    return 0


def cmd_stop(args) -> int:
    g = STORE.vm(args.name)
    OUT.ok(f"{g.name} stopped") if g.kill() else OUT.say(f"{g.name} is not running")
    return 0


def cmd_console(args) -> int:
    g = STORE.vm(args.name)
    if not g.running():
        raise Fail(f"{g.name} is not running", EXIT_STATE, f"iosvm start {g.name}")
    if not which("socat"):
        raise Fail("socat not found", EXIT_PREREQ, f"nix shell nixpkgs#socat -c socat -,raw,echo=0 UNIX-CONNECT:{g.serial_sock}")
    OUT.note("serial console — Ctrl+] to detach")
    os.execvp("socat", ["socat", "-,raw,echo=0,escape=0x1d", f"UNIX-CONNECT:{g.serial_sock}"])


def cmd_list(args) -> int:
    rows = [g.status() for g in STORE.guests()]
    if OUT.json:
        OUT.emit_json(rows)
    elif not rows:
        OUT.say("no iOS VMs yet — `iosvm create --name iphone`")
    else:
        OUT.say(table(["NAME", "STATE", "DEVICE", "RAM", "UPTIME", "FIRMWARE"],
                      [[r["name"], STYLE.green(r["state"]) if r["state"] == "running" else r["state"], r.get("device") or "-",
                        f"{r['ram_gib']}G", fmt_uptime(r["uptime_s"]), r["firmware"]] for r in rows]))
    return 0


def cmd_info(args) -> int:
    s = STORE.vm(args.name).status()
    if OUT.json:
        OUT.emit_json(s)
    else:
        for k, v in s.items():
            OUT.say(f"  {k:14} {v}")
    return 0


def cmd_delete(args) -> int:
    g = STORE.vm(args.name)
    if g.running():
        raise Fail(f"{g.name} is running", EXIT_STATE, f"iosvm stop {g.name}")
    shutil.rmtree(g.path)
    OUT.ok(f"deleted {g.name} (the firmware import is kept)")
    return 0


def cmd_sim(args) -> int:
    """Simulator backend: iOS apps via Xcode's Simulator inside a macOS guest (dev.to/ianito, Docker-OSX)."""
    meta = Store("macos").vm(args.mac).meta
    port = meta.get("ssh_port")
    if not port:
        raise Fail(f"{args.mac} has no SSH port yet", EXIT_STATE, f"macosvm start {args.mac}")
    sim = args.simctl or ["list", "devices", "available"]
    argv = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new", f"{args.user or os.environ.get('USER', 'user')}@127.0.0.1",
            "xcrun", "simctl", *sim]
    if OUT.verbose or OUT.debug:
        OUT.say(" ".join(argv))
    os.execvp("ssh", argv)


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="iosvm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="iOS Construct — sibling of macosvm/windowsvm/linuxvm/androidvm. Apple files are user-supplied.")
    add_global_flags(p)
    p.add_argument("--version", action="version", version=f"iosvm {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, fn, aliases=()):
        sp = sub.add_parser(name, help=help, description=help, aliases=list(aliases))
        sp.set_defaults(handler=fn)
        return sp

    add("help", "show this help", lambda a: (p.print_help(), 0)[1])
    add("doctor", "check qemu-sptm, fetch tools and firmware sets", cmd_doctor)
    i = add("import", "import darwin-vm's firmware/ folder (from your Mac) or a restore .ipsw", cmd_import)
    i.add_argument("path")
    i.add_argument("--name")
    g = i.add_mutually_exclusive_group()
    g.add_argument("--move", action="store_true")
    g.add_argument("--link", action="store_true")
    i.add_argument("--no-hash", action="store_true")
    ims = add("imports", "list imports (--rm ID to remove)", cmd_imports)
    ims.add_argument("--rm", metavar="ID")
    f = add("fetch", "extract a firmware set from an IPSW on Apple's CDN (or an imported .ipsw)", cmd_fetch)
    f.add_argument("--device", default=fw.DEFAULT_DEVICE, help=f"product identifier (default {fw.DEFAULT_DEVICE} = iPhone 16)")
    src = f.add_mutually_exclusive_group()
    src.add_argument("--url", help="restore IPSW URL on updates.cdn-apple.com (default: darwin-vm's iOS 27.0)")
    src.add_argument("--ipsw", metavar="ID", help="an imported .ipsw instead of downloading")
    f.add_argument("--name")
    f.add_argument("--dry-run", action="store_true")
    c = add("create", "create a VM from a firmware set", cmd_create)
    c.add_argument("--name")
    c.add_argument("--firmware", metavar="ID")
    c.add_argument("--ram", type=int, help="GiB (default 8)")
    c.add_argument("--boot-args")
    c.add_argument("--qemuports", action="store_true", help="extra UART on tcp 127.0.0.1:2100 (darwin-vm TCP tunnelling)")
    c.add_argument("--dry-run", action="store_true")
    s = add("start", "boot a VM in the background", cmd_start, ["launch"])
    s.add_argument("name")
    s.add_argument("--dry-run", action="store_true", help="print the QEMU command line")
    for name, h, fn, al in [("stop", "stop a VM", cmd_stop, ()), ("status", "show state", cmd_info, ()),
                            ("info", "show VM details", cmd_info, ()),
                            ("console", "attach to the serial root shell (Ctrl+] detaches)", cmd_console, ["display", "gui"]),
                            ("delete", "delete a VM (keeps firmware)", cmd_delete, ())]:
        add(name, h, fn, al).add_argument("name")
    add("list", "list iOS VMs", cmd_list)
    sm = add("sim", "run `xcrun simctl` in a macosvm guest with Xcode (the Docker-OSX/Xcode Simulator route)", cmd_sim)
    sm.add_argument("mac", help="macosvm VM name (must be running, Remote Login on, Xcode installed)")
    sm.add_argument("--user", default=None, help="macOS account (default: $USER)")
    sm.add_argument("simctl", nargs=argparse.REMAINDER, help="simctl args, default: list devices available")
    from vmtools.applecfg import add_config

    add_config(sub, "ios")
    return p


def main(argv=None) -> int:
    return app_main(build_parser, argv)


if __name__ == "__main__":
    raise SystemExit(main())
