"""macosvm — macOS Construct: macOS guests on QEMU/KVM with OpenCore (the OSX-KVM recipe).

Apple media is always user-supplied (`import`, usually copied from your own Mac) or pulled on
request from Apple's public recovery servers (`fetch-recovery`, OSX-KVM's fetch-macOS-v2.py).
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from vmtools import checks as ck
from vmtools.app import Parser, add_global_flags
from vmtools.app import main as app_main
from vmtools.apple import Store, asset_dir, fmt_uptime, free_port
from vmtools.config import validate_name
from vmtools.layout import config
from vmtools.proc import run, which
from vmtools.ui import EXIT_PREREQ, EXIT_STATE, EXIT_USAGE, OUT, STYLE, Fail, table

from . import __version__
from . import dockerosx as dox
from .media import BOOT_MEDIA, KINDS, app_basesystem, classify, dmg_to_img, extract_basesystem

STORE = Store("macos")
VERSIONS = ("high-sierra", "mojave", "catalina", "big-sur", "monterey", "ventura", "sonoma", "sequoia", "tahoe")
CPU_MODELS = {
    "modern": "Skylake-Client,-hle,-rtm,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on",  # Sequoia/Tahoe
    "penryn": "Penryn,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on",                     # <= Sonoma
}
# The SMC key every QEMU/OSX-KVM macOS guest uses (published in OSX-KVM and QEMU's docs).
OSK = "ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc"


def osx_kvm() -> Path | None:
    return asset_dir("VMTOOLS_OSX_KVM", "osx-kvm", str(config().get("macos_osx_kvm_dir", "")))


def qemu_bin() -> str:
    return str(config().get("macos_qemu", "qemu-system-x86_64"))


# ---------------------------------------------------------------- doctor ---
def cmd_doctor(args) -> int:
    rep = ck.Report()
    host = rep.section("Host")
    host.add(ck.check_cpu_virt())
    for c in ck.check_kvm_device():
        host.add(c)
    try:
        ignore = Path("/sys/module/kvm/parameters/ignore_msrs").read_text().strip()
    except OSError:
        ignore = "?"
    host.add(ck.Check("kvm ignore_msrs", ck.OK if ignore in ("Y", "1") else ck.WARN, ignore,
                      "boot.extraModprobeConfig = \"options kvm ignore_msrs=1 report_ignored_msrs=0\"; (macOS trips unhandled MSRs)"))
    host.add(ck.check_memory(8))
    host.add(ck.check_disk_space(STORE.root if STORE.root.exists() else Path.home(), 64))
    tools = rep.section("Tools")
    tools.add(ck.check_binary("QEMU x86_64", qemu_bin(), hint="nix profile install nixpkgs#qemu_kvm (packaged macosvm pins it)"))
    tools.add(ck.check_binary("qemu-img", "qemu-img"))
    tools.add(ck.check_binary("dmg2img (BaseSystem.dmg -> .img)", "dmg2img", required=False, hint="nix shell nixpkgs#dmg2img"))
    tools.add(ck.check_binary("7-Zip (InstallAssistant.pkg extract)", "7zz", required=False, hint="nix shell nixpkgs#_7zz"))
    tools.add(ck.check_binary("VNC viewer (display)", "remote-viewer", required=False, hint="virt-viewer provides remote-viewer"))
    assets = rep.section("OpenCore / firmware")
    kit = osx_kvm()
    assets.add(ck.Check("OSX-KVM assets (OpenCore.qcow2, OVMF, fetch script)", ck.OK if kit else ck.WARN, str(kit or "not found"),
                        "nix-build nix/apple-assets.nix -o ~/.local/share/vmtools/apple/assets  (or import your own OpenCore/OVMF)"))
    man = STORE.manifest()
    kinds = {e["kind"] for e in man.values()}
    assets.add(ck.Check("OpenCore disk", ck.OK if kit or "opencore" in kinds else ck.FAIL,
                        "imported" if "opencore" in kinds else ("OSX-KVM" if kit else "none"), "macosvm import OpenCore.qcow2"))
    assets.add(ck.Check("OVMF code", ck.OK if kit or "ovmf-code" in kinds else ck.FAIL,
                        "imported" if "ovmf-code" in kinds else ("OSX-KVM" if kit else "none"), "macosvm import OVMF_CODE_4M.fd"))
    dk = rep.section("Docker-OSX backend (optional)")
    dk.add(ck.check_binary("docker CLI", "docker", required=False, hint="install ~/rice-staging/r3dg0d-docker.nix, rebuild, re-login"))
    sock = Path(dox.env()["DOCKER_HOST"].removeprefix("unix://"))
    dk.add(ck.Check("rootless docker socket", ck.OK if sock.exists() else ck.WARN, str(sock), "systemctl --user enable --now docker"))
    media = rep.section("macOS media (user-supplied)")
    boot = [e for e in man.values() if e["kind"] in BOOT_MEDIA]
    media.add(ck.Check("install media", ck.OK if boot else ck.WARN, ", ".join(e["id"] for e in boot) or "none imported",
                       "copy BaseSystem.dmg / an installer image from your Mac and `macosvm import` it, or `macosvm fetch-recovery sonoma`"))
    pending = [e["id"] for e in man.values() if e["kind"] in ("installer-pkg", "installer-app", "shared-support")]
    if pending:
        media.add(ck.Check("installers needing conversion", ck.WARN, ", ".join(pending), "macosvm extract <id>, or convert on the Mac (README)"))
    if OUT.json:
        OUT.emit_json(rep.as_dict())
    else:
        rep.render("macOS Construct — host check")
    return 1 if rep.counts()[2] else 0


# ---------------------------------------------------------------- imports ---
def cmd_import(args) -> int:
    src = Path(args.path).expanduser()
    kind = args.kind or classify(src)
    if kind not in KINDS:
        raise Fail(f"unknown kind {kind!r}", EXIT_USAGE, "one of: " + ", ".join(KINDS))
    if kind == "installer-app" and (bs := app_basesystem(src)):
        OUT.note(f"found {bs.relative_to(src)} inside the app; importing that as the recovery image")
        src, kind = bs, "basesystem"
    entry = STORE.add_import(src, kind, name=args.name, move=args.move, link=args.link, hash_it=not args.no_hash)
    if kind == "basesystem" and entry["path"].lower().endswith(".dmg") and which("dmg2img") and not args.link:
        img = Path(entry["path"]).with_suffix(".img")
        dmg_to_img(Path(entry["path"]), img)
        Path(entry["path"]).unlink()
        entry["path"] = str(img)
        STORE.record(entry)
    if OUT.json:
        OUT.emit_json(entry)
        return 0
    OUT.ok(f"imported {entry['id']} as {kind}: {KINDS[kind]}")
    if kind in ("installer-pkg", "installer-app", "shared-support"):
        OUT.note(f"next: macosvm extract {entry['id']}  (best effort), or convert on the Mac — see README")
    elif kind == "ipsw":
        OUT.note("IPSWs are Apple-silicon images; x86 KVM can't boot them. iosvm can (darwin-vm Mac targets).")
    return 0


def cmd_imports(args) -> int:
    if getattr(args, "rm", None):
        STORE.remove_import(args.rm)
        OUT.ok(f"removed import {args.rm}")
        return 0
    rows = sorted(STORE.manifest().values(), key=lambda e: e["id"])
    if OUT.json:
        OUT.emit_json(rows)
    elif not rows:
        OUT.say("no imports yet — `macosvm import <file>` (see `macosvm help import`)")
    else:
        OUT.say(table(["ID", "KIND", "SHA256", "PATH"], [[e["id"], e["kind"], (e.get("sha256") or "-")[:12], e["path"]] for e in rows]))
    return 0


def cmd_extract(args) -> int:
    entry = STORE.get_import(args.id, ("installer-pkg", "installer-app", "shared-support"))
    src = Path(entry["path"])
    if entry["kind"] == "installer-app":
        src = src / "Contents/SharedSupport/SharedSupport.dmg"
    with tempfile.TemporaryDirectory(dir=STORE.imports) as td:
        bs = extract_basesystem(src, Path(td))
        name = args.name or f"{entry['id']}-basesystem"
        out = STORE.add_import(bs, "basesystem", name=name, move=True, extra={"from": entry["id"]})
    if out["path"].lower().endswith(".dmg") and which("dmg2img"):
        img = Path(out["path"]).with_suffix(".img")
        dmg_to_img(Path(out["path"]), img)
        Path(out["path"]).unlink()
        out["path"] = str(img)
        STORE.record(out)
    OUT.ok(f"extracted recovery image {out['id']}")
    return 0


def cmd_fetch(args) -> int:
    """Download a recovery BaseSystem from Apple's servers (osrecovery.apple.com) via OSX-KVM's script."""
    kit = osx_kvm()
    if not kit:
        raise Fail("OSX-KVM assets not found", EXIT_PREREQ, "nix-build nix/apple-assets.nix -o ~/.local/share/vmtools/apple/assets")
    name = validate_name(args.name or f"recovery-{args.version}")
    out = STORE.ensure().imports / f".fetch-{name}"
    argv = ["python3", str(kit / "fetch-macOS-v2.py"), "-s", args.version, "-o", str(out), "-n", "BaseSystem"]
    if args.dry_run:
        OUT.say(" ".join(argv))
        return 0
    out.mkdir(exist_ok=True)
    OUT.step(f"fetching macOS {args.version} recovery from Apple (osrecovery.apple.com)")
    subprocess.run(argv, check=True)
    entry = STORE.add_import(out / "BaseSystem.dmg", "basesystem", name=name, move=True, extra={"fetched": args.version})
    if which("dmg2img"):
        img = Path(entry["path"]).with_suffix(".img")
        dmg_to_img(Path(entry["path"]), img)
        Path(entry["path"]).unlink()
        entry["path"] = str(img)
        STORE.record(entry)
    shutil.rmtree(out, ignore_errors=True)
    OUT.ok(f"recovery image ready: {entry['id']}  ->  macosvm create --name mac --media {entry['id']}")
    return 0


# ----------------------------------------------------------------- guests ---
def _resolve(kind: tuple[str, ...], ident: str | None, kit_file: str | None) -> str | None:
    if ident:
        if Path(ident).expanduser().exists():
            return str(Path(ident).expanduser().resolve())
        return STORE.get_import(ident, kind)["path"]
    man = [e for e in STORE.manifest().values() if e["kind"] in kind]
    if man:
        return sorted(man, key=lambda e: e["imported"])[-1]["path"]
    kit = osx_kvm()
    if kit and kit_file and (kit / kit_file).exists():
        return str(kit / kit_file)
    return None


def cmd_create(args) -> int:
    cfg = config()
    name = validate_name(args.name or "mac")
    d = STORE.ensure().vm_dir(name)
    if (d / "vm.json").exists():
        raise Fail(f"{name} already exists", EXIT_STATE)
    if args.backend == "docker-osx":
        meta = {"os": "macos", "backend": "docker-osx", "version": args.version, "cpus": args.cpus or cfg.get("macos_default_cpus"),
                "ram_gib": args.ram or cfg.get("macos_default_ram_gib"), "ssh_port": free_port(50922, 51022), "media": None}
        if args.dry_run:
            OUT.say("docker " + " ".join(dox.run_argv(name, meta)))
            return 0
        d.mkdir(parents=True)
        from vmtools.apple import Guest

        g = Guest(d)
        g.meta = meta
        g.save()
        OUT.ok(f"created {name} (Docker-OSX {args.version}); first `macosvm start {name}` pulls {dox.IMAGE} and installs from Apple")
        return 0
    media = _resolve(BOOT_MEDIA, args.media, None) if args.media != "none" else None
    meta = {
        "os": "macos", "version": args.version, "cpus": args.cpus or cfg.get("macos_default_cpus"),
        "ram_gib": args.ram or cfg.get("macos_default_ram_gib"), "disk_gib": args.disk or cfg.get("macos_default_disk_gib"),
        "cpu_model": args.cpu_model or ("penryn" if args.version in VERSIONS[:7] else "modern"),
        "media": media,
        "opencore": _resolve(("opencore",), args.opencore, "OpenCore/OpenCore.qcow2"),
        "ovmf_code": _resolve(("ovmf-code",), args.ovmf_code, "OVMF_CODE_4M.fd"),
        "ovmf_vars_template": _resolve(("ovmf-vars",), args.ovmf_vars, "OVMF_VARS-1920x1080.fd"),
        "vnc_display": None, "backend": "qemu",
    }
    missing = [k for k in ("opencore", "ovmf_code", "ovmf_vars_template") if not meta[k]]
    if missing:
        raise Fail("missing " + ", ".join(missing), EXIT_PREREQ, "run `macosvm doctor`; import them or build nix/apple-assets.nix")
    if args.dry_run:
        OUT.emit_json(meta) if OUT.json else [OUT.say(f"  {k:20} {v}") for k, v in meta.items()]
        OUT.ok(f"dry run: would create {d}")
        return 0
    d.mkdir(parents=True)
    shutil.copy2(meta["ovmf_vars_template"], d / "OVMF_VARS.fd")
    os.chmod(d / "OVMF_VARS.fd", 0o644)
    run(["qemu-img", "create", "-f", "qcow2", str(d / "disk.qcow2"), f"{meta['disk_gib']}G"])
    from vmtools.apple import Guest

    g = Guest(d)
    g.meta = meta
    g.save()
    OUT.ok(f"created {name}: {meta['cpus']} vCPU, {meta['ram_gib']} GiB, {meta['disk_gib']} GiB disk")
    OUT.note(f"next: macosvm start {name} && macosvm display {name}  (pick the install media in OpenCore's picker)")
    return 0


def qemu_argv(g) -> list[str]:
    m = g.meta
    argv = [
        qemu_bin(), "-name", f"macosvm-{g.name}", "-enable-kvm", "-m", f"{m['ram_gib']}G",
        "-cpu", CPU_MODELS.get(m.get("cpu_model", "modern"), m.get("cpu_model")),
        "-machine", "q35", "-smp", f"{m['cpus']},cores={m['cpus']},sockets=1",
        "-device", "qemu-xhci,id=xhci", "-device", "usb-kbd,bus=xhci.0", "-device", "usb-tablet,bus=xhci.0",
        "-device", f"isa-applesmc,osk={OSK}",
        "-drive", f"if=pflash,format=raw,readonly=on,file={m['ovmf_code']}",
        "-drive", f"if=pflash,format=raw,file={g.path / 'OVMF_VARS.fd'}",
        "-smbios", "type=2", "-device", "ich9-intel-hda", "-device", "hda-duplex", "-device", "ich9-ahci,id=sata",
        "-drive", f"id=OpenCoreBoot,if=none,snapshot=on,format={'qcow2' if m['opencore'].endswith('.qcow2') else 'raw'},file={m['opencore']}",
        "-device", "ide-hd,bus=sata.2,drive=OpenCoreBoot",
    ]
    if m.get("media"):
        argv += ["-drive", f"id=InstallMedia,if=none,readonly=on,format={'dmg' if m['media'].lower().endswith('.dmg') else 'raw'},file={m['media']}",
                 "-device", "ide-hd,bus=sata.3,drive=InstallMedia"]
    argv += ["-drive", f"id=MacHDD,if=none,file={g.path / 'disk.qcow2'},format=qcow2", "-device", "ide-hd,bus=sata.4,drive=MacHDD",
             "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{m.get('ssh_port') or 10022}-:22",
             "-device", "virtio-net-pci,netdev=net0,id=net0,mac=52:54:00:c9:18:27", "-device", "vmware-svga",
             "-vnc", f"127.0.0.1:{(m.get('vnc_display') or 0)}", "-serial", f"unix:{g.serial_sock},server=on,wait=off"]
    return argv


def cmd_start(args) -> int:
    g = STORE.vm(args.name)
    if g.meta.get("backend") == "docker-osx":
        st = "absent" if args.dry_run else dox.state(g.name)
        argv = ["start", dox.container(g.name)] if st != "absent" else dox.run_argv(g.name, g.meta)
        if args.dry_run:
            OUT.say("docker " + " ".join(argv))
            return 0
        if st == "running":
            raise Fail(f"{g.name} is already running", EXIT_STATE)
        dox.docker(*argv)
        OUT.ok(f"{g.name} up (container {dox.container(g.name)}) · window on your desktop · ssh -p {g.meta['ssh_port']} user@localhost")
        return 0
    if args.no_media:
        g.meta["media"] = None
    if not args.dry_run:
        g.meta["vnc_display"] = free_port(5900, 5999) - 5900
        g.meta["ssh_port"] = free_port(10022, 10122)
    argv = g.launch(qemu_argv(g), dry_run=args.dry_run)
    if args.dry_run:
        OUT.say(shlex.join(argv))
        return 0
    g.save()
    OUT.ok(f"{g.name} running (pid {g.pid()}) · VNC 127.0.0.1:{5900 + g.meta['vnc_display']} · ssh -p {g.meta['ssh_port']} localhost")
    OUT.note(f"macosvm display {g.name}")
    return 0


def cmd_stop(args) -> int:
    g = STORE.vm(args.name)
    if g.meta.get("backend") == "docker-osx":
        dox.docker("stop", dox.container(g.name), check=False)
        OUT.ok(f"{g.name} stopped (container kept)")
        return 0
    OUT.ok(f"{g.name} stopped") if g.kill() else OUT.say(f"{g.name} is not running")
    return 0


def cmd_shutdown(args) -> int:
    g = STORE.vm(args.name)
    if not g.running():
        raise Fail(f"{g.name} is not running", EXIT_STATE)
    g.powerdown()
    OUT.ok(f"ACPI power button sent to {g.name}")
    return 0


def cmd_display(args) -> int:
    g = STORE.vm(args.name)
    if not g.running():
        raise Fail(f"{g.name} is not running", EXIT_STATE, f"macosvm start {g.name}")
    url = f"vnc://127.0.0.1:{5900 + int(g.meta.get('vnc_display') or 0)}"
    viewer = which("remote-viewer") or which("vncviewer")
    if not viewer or args.print:
        OUT.say(url)
        return 0
    subprocess.Popen([viewer, url if viewer.endswith("remote-viewer") else url[6:]], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    OUT.ok(f"opened {url}")
    return 0


def cmd_console(args) -> int:
    g = STORE.vm(args.name)
    if not which("socat"):
        raise Fail("socat not found", EXIT_PREREQ, f"nix shell nixpkgs#socat -c socat -,raw,echo=0 UNIX-CONNECT:{g.serial_sock}")
    os.execvp("socat", ["socat", "-,raw,echo=0,escape=0x1d", f"UNIX-CONNECT:{g.serial_sock}"])


def cmd_list(args) -> int:
    rows = [_status(g) for g in STORE.guests()]
    if OUT.json:
        OUT.emit_json(rows)
    elif not rows:
        OUT.say("no macOS VMs yet — `macosvm create --name mac`")
    else:
        OUT.say(table(["NAME", "STATE", "CPU", "RAM", "UPTIME", "MEDIA"],
                      [[r["name"], STYLE.green(r["state"]) if r["state"] == "running" else r["state"], str(r["cpus"]),
                        f"{r['ram_gib']}G", fmt_uptime(r["uptime_s"]), Path(r["media"]).name if r.get("media") else "-"] for r in rows]))
    return 0


def cmd_info(args) -> int:
    s = _status(STORE.vm(args.name))
    if OUT.json:
        OUT.emit_json(s)
    else:
        for k, v in s.items():
            OUT.say(f"  {k:20} {v}")
    return 0


def _status(g) -> dict:
    s = g.status()
    if g.meta.get("backend") == "docker-osx":
        st = dox.state(g.name) if which("docker") else "unknown"
        s["state"] = "running" if st == "running" else "stopped"
        s["container"] = st
    return s


def cmd_delete(args) -> int:
    g = STORE.vm(args.name)
    if _status(g)["state"] == "running":
        raise Fail(f"{g.name} is running", EXIT_STATE, f"macosvm stop {g.name}")
    if not args.yes:
        from vmtools.menu import confirm

        if not confirm(f"delete {g.name} and its disk?", default=False):
            return 0
    if g.meta.get("backend") == "docker-osx":
        dox.docker("rm", "-f", dox.container(g.name), check=False)
    shutil.rmtree(g.path)
    OUT.ok(f"deleted {g.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="macosvm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="macOS Construct — sibling of iosvm/windowsvm/linuxvm/androidvm. Apple media is user-supplied.")
    add_global_flags(p)
    p.add_argument("--version", action="version", version=f"macosvm {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, help, fn, aliases=()):
        sp = sub.add_parser(name, help=help, description=help, aliases=list(aliases))
        sp.set_defaults(handler=fn)
        return sp

    add("help", "show this help", lambda a: (p.print_help(), 0)[1])
    add("doctor", "check host, tools, OpenCore/OVMF and imported media", cmd_doctor)
    i = add("import", "import a file you supplied (BaseSystem.dmg, installer image/.app/.pkg, OpenCore, OVMF, config.plist, IPSW)", cmd_import)
    i.add_argument("path")
    i.add_argument("--kind", choices=list(KINDS))
    i.add_argument("--name", help="import id (default: from the file name)")
    g = i.add_mutually_exclusive_group()
    g.add_argument("--move", action="store_true", help="move instead of copy")
    g.add_argument("--link", action="store_true", help="symlink instead of copy (e.g. a mounted share)")
    i.add_argument("--no-hash", action="store_true", help="skip sha256 (large installers)")
    ims = add("imports", "list imports (--rm ID to remove one)", cmd_imports)
    ims.add_argument("--rm", metavar="ID")
    e = add("extract", "pull BaseSystem out of an imported InstallAssistant.pkg / installer app (best effort)", cmd_extract)
    e.add_argument("id")
    e.add_argument("--name")
    f = add("fetch-recovery", "download a recovery image from Apple's osrecovery servers (OSX-KVM fetch-macOS-v2.py)", cmd_fetch)
    f.add_argument("version", choices=VERSIONS)
    f.add_argument("--name")
    f.add_argument("--dry-run", action="store_true")
    c = add("create", "create a macOS VM (disk + per-VM NVRAM)", cmd_create)
    c.add_argument("--name")
    c.add_argument("--version", choices=VERSIONS, default="sonoma", help="picks the CPU model (default sonoma)")
    c.add_argument("--media", help="import id or path of install media ('none' to skip; default: newest import)")
    c.add_argument("--opencore")
    c.add_argument("--ovmf-code")
    c.add_argument("--ovmf-vars")
    c.add_argument("--cpus", type=int)
    c.add_argument("--ram", type=int, help="GiB")
    c.add_argument("--disk", type=int, help="GiB")
    c.add_argument("--cpu-model", help="modern | penryn | a raw -cpu string")
    c.add_argument("--backend", choices=["qemu", "docker-osx"], default="qemu",
                   help="qemu: direct QEMU+OpenCore with your media (default); docker-osx: sickcodes/docker-osx container")
    c.add_argument("--dry-run", action="store_true")
    s = add("start", "boot a VM headless (VNC on localhost)", cmd_start, ["launch"])
    s.add_argument("name")
    s.add_argument("--no-media", action="store_true", help="boot without the install media")
    s.add_argument("--dry-run", action="store_true", help="print the QEMU command line")
    for name, h, fn in [("stop", "force stop", cmd_stop), ("shutdown", "ACPI power button", cmd_shutdown),
                        ("status", "show state", cmd_info), ("info", "show VM details", cmd_info),
                        ("console", "attach to the serial console (Ctrl+] quits)", cmd_console)]:
        add(name, h, fn).add_argument("name")
    dsp = add("display", "open the VNC display (remote-viewer)", cmd_display, ["gui"])
    dsp.add_argument("name")
    dsp.add_argument("--print", action="store_true", help="just print the vnc:// URL")
    add("list", "list macOS VMs", cmd_list)
    from vmtools.applecfg import add_config

    add_config(sub, "macos")
    dl = add("delete", "delete a VM", cmd_delete)
    dl.add_argument("name")
    dl.add_argument("-y", "--yes", action="store_true")
    return p


def main(argv=None) -> int:
    return app_main(build_parser, argv)


if __name__ == "__main__":
    raise SystemExit(main())
