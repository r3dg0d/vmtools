"""Shared host doctor checks for QEMU/KVM/libvirt stack."""

from __future__ import annotations

import os
from pathlib import Path

from . import libvirt as lv
from .proc import which
from .ui import OUT, STYLE, SYM_BAD, SYM_OK, SYM_WARN


def _row(name: str, ok: bool | None, detail: str) -> dict:
    if ok is True:
        mark = STYLE.green(SYM_OK)
        status = "OK"
    elif ok is False:
        mark = STYLE.red(SYM_BAD)
        status = "FAIL"
    else:
        mark = STYLE.yellow(SYM_WARN)
        status = "WARN"
    OUT.say(f"{mark} {name:<22} {status:<6} {detail}")
    return {"name": name, "ok": ok, "status": status, "detail": detail}


def doctor_libvirt(*, json_mode: bool = False) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    blocking = False
    from .layout import config as load_config
    uri = str(load_config().get("libvirt_uri", "qemu:///session"))
    rows.append(_row("Libvirt URI", True, uri))
    if "system" in uri:
        rows.append(_row(
            "Home path access",
            None,
            "system URI cannot read ~/.local unless pool uses /var/lib/libvirt/images or home is searchable",
        ))

    kvm = Path("/dev/kvm")
    if kvm.exists() and os.access(kvm, os.R_OK | os.W_OK):
        rows.append(_row("KVM", True, str(kvm)))
    elif kvm.exists():
        rows.append(_row("KVM", False, f"{kvm} exists but not accessible — add user to kvm group"))
        blocking = True
    else:
        rows.append(_row("KVM", False, "/dev/kvm missing — enable VT-x/AMD-V in firmware"))
        blocking = True

    if which("virsh"):
        r = lv._virsh("version", check=False)
        if r.returncode == 0:
            rows.append(_row("libvirtd", True, "virsh reachable"))
        else:
            rows.append(_row("libvirtd", False, (r.stderr or "virsh failed").strip()[:80]))
            blocking = True
    else:
        rows.append(_row("libvirtd", False, "virsh not on PATH"))
        blocking = True

    rows.append(_row("virt-manager", bool(which("virt-manager")), which("virt-manager") or "not found"))
    rows.append(_row("virt-install", bool(which("virt-install")), which("virt-install") or "not found"))
    rows.append(_row("virt-viewer", bool(which("virt-viewer")), which("virt-viewer") or "not found"))
    q = which("qemu-system-x86_64")
    rows.append(_row("QEMU", bool(q), q or "not found"))
    if not q:
        blocking = True

    code, vars_ = lv.find_ovmf()
    if code:
        rows.append(_row("UEFI firmware", True, str(code)))
    else:
        rows.append(_row("UEFI firmware", False, "OVMF not found — install OVMFFull / qemu ovmf"))
        blocking = True

    rows.append(_row("swtpm", bool(which("swtpm")), which("swtpm") or "missing (needed for Win11 TPM)"))

    try:
        from .layout import config as load_config
        uri_now = str(load_config().get("libvirt_uri", "qemu:///session"))
        if "session" in uri_now:
            rows.append(_row("Default network", True, "session URI uses user networking by default"))
        else:
            nets = lv.network_list()
            default = next((n for n in nets if n["name"] == "default"), None)
            if default and default.get("state") == "active":
                rows.append(_row("Default network", True, "default active"))
            elif default:
                rows.append(_row("Default network", False, "default defined but not active"))
                blocking = True
            else:
                rows.append(_row("Default network", False, "no default network"))
                blocking = True
    except Exception as exc:  # noqa: BLE001
        rows.append(_row("Default network", False, str(exc)[:80]))
        blocking = True

    import grp
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    try:
        groups = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
        groups.add(pwd.getpwuid(os.getuid()).pw_name)
        # also primary
        groups.add(grp.getgrgid(pwd.getpwuid(os.getuid()).pw_gid).gr_name)
    except Exception:
        groups = set()
    # parse /proc for actual
    try:
        import subprocess
        g = subprocess.check_output(["id", "-nG"], text=True).split()
        groups = set(g)
    except Exception:
        pass
    libvirt_ok = "libvirtd" in groups or "libvirt" in groups
    kvm_ok = "kvm" in groups
    detail = f"groups: {', '.join(sorted(groups)[:12])}"
    rows.append(_row("User libvirt access", libvirt_ok, detail if libvirt_ok else "join libvirtd group; re-login"))
    if not libvirt_ok:
        blocking = True
    rows.append(_row("User kvm access", kvm_ok, "ok" if kvm_ok else "join kvm group"))

    if json_mode:
        return rows, blocking
    if blocking:
        OUT.say()
        OUT.warn("Blocking issues found. On NixOS ensure virtualisation.libvirtd.enable = true")
        OUT.note("and users.users.<you>.extraGroups includes libvirtd and kvm (see docs/NIXOS.md).")
    return rows, blocking
