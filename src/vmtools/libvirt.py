"""Thin wrappers around virsh / virt-install / virt-viewer / qemu-img."""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .layout import config as load_config
from .proc import run
from .ui import EXIT_NOT_FOUND, EXIT_PREREQ, EXIT_STATE, OUT, Fail


def uri() -> str:
    return str(load_config().get("libvirt_uri", "qemu:///system"))


def _virsh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["virsh", "-c", uri(), *args]
    return run(cmd, check=check)


def domain_exists(name: str) -> bool:
    r = _virsh("dominfo", name, check=False)
    return r.returncode == 0


def require_domain(name: str) -> None:
    if not domain_exists(name):
        raise Fail(f"VM not found: {name}", EXIT_NOT_FOUND, "run `list` to see defined VMs")


@dataclass
class DomInfo:
    name: str
    state: str
    cpu: str = ""
    memory_kib: int = 0
    uuid: str = ""


def list_domains() -> list[DomInfo]:
    r = _virsh("list", "--all", "--name", check=False)
    if r.returncode != 0:
        raise Fail("virsh list failed", EXIT_PREREQ, r.stderr.strip() or "is libvirtd running?")
    names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
    out: list[DomInfo] = []
    for name in names:
        info = domain_info(name)
        if info:
            out.append(info)
    return out


def domain_info(name: str) -> DomInfo | None:
    r = _virsh("dominfo", name, check=False)
    if r.returncode != 0:
        return None
    data: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    mem = 0
    raw = data.get("Max memory", "0")
    m = re.match(r"(\d+)", raw.replace(",", ""))
    if m:
        mem = int(m.group(1))
    return DomInfo(
        name=data.get("Name", name),
        state=data.get("State", "unknown").lower(),
        cpu=data.get("CPU(s)", ""),
        memory_kib=mem,
        uuid=data.get("UUID", ""),
    )


def start(name: str) -> None:
    require_domain(name)
    info = domain_info(name)
    if info and "running" in info.state:
        OUT.warn(f"{name} is already running")
        return
    _virsh("start", name)
    OUT.ok(f"started {name}")


def shutdown(name: str, *, force: bool = False) -> None:
    require_domain(name)
    if force:
        _virsh("destroy", name)
        OUT.ok(f"forced stop {name}")
    else:
        r = _virsh("shutdown", name, check=False)
        if r.returncode != 0:
            OUT.warn("ACPI shutdown failed; try stop --force")
            raise Fail(r.stderr.strip() or "shutdown failed", EXIT_STATE)
        OUT.ok(f"shutdown requested for {name}")


def reboot(name: str) -> None:
    require_domain(name)
    _virsh("reboot", name)
    OUT.ok(f"reboot requested for {name}")


def pause(name: str) -> None:
    require_domain(name)
    _virsh("suspend", name)
    OUT.ok(f"paused {name}")


def resume(name: str) -> None:
    require_domain(name)
    _virsh("resume", name)
    OUT.ok(f"resumed {name}")


def undefine(name: str, *, remove_storage: bool = True, keep_disk: bool = False) -> None:
    require_domain(name)
    info = domain_info(name)
    if info and "running" in info.state:
        _virsh("destroy", name, check=False)
    args = ["undefine", name, "--nvram"]
    if remove_storage and not keep_disk:
        args.append("--remove-all-storage")
    _virsh(*args)
    OUT.ok(f"deleted {name}")


def snapshot_create(name: str, snap: str, description: str = "") -> None:
    require_domain(name)
    args = ["snapshot-create-as", name, snap]
    if description:
        args.extend(["--description", description])
    r = _virsh(*args, check=False)
    if r.returncode != 0:
        # UEFI pflash NVRAM often blocks internal snapshots; disk-only is the workable path.
        OUT.warn("internal snapshot failed; trying --disk-only")
        args2 = ["snapshot-create-as", name, snap, "--disk-only", "--quiesce"]
        # quiesce may fail without guest agent; retry without it
        r2 = _virsh(*args2, check=False)
        if r2.returncode != 0:
            args3 = ["snapshot-create-as", name, snap, "--disk-only"]
            if description:
                args3.extend(["--description", description])
            _virsh(*args3)
            OUT.ok(f"disk-only snapshot {snap} created for {name}")
            return
        OUT.ok(f"disk-only snapshot {snap} created for {name}")
        return
    OUT.ok(f"snapshot {snap} created for {name}")


def snapshot_list(name: str) -> list[dict[str, str]]:
    require_domain(name)
    r = _virsh("snapshot-list", name, "--name")
    names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
    rows = []
    for sn in names:
        info = _virsh("snapshot-info", name, sn, check=False)
        created = ""
        state = ""
        desc = ""
        for line in info.stdout.splitlines():
            if line.startswith("Creation Time:"):
                created = line.split(":", 1)[1].strip()
            elif line.startswith("State:"):
                state = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                desc = line.split(":", 1)[1].strip()
        rows.append({"name": sn, "created": created, "state": state, "description": desc})
    return rows


def snapshot_revert(name: str, snap: str) -> None:
    require_domain(name)
    _virsh("snapshot-revert", name, snap)
    OUT.ok(f"restored {name} to snapshot {snap}")


def open_gui(name: str | None = None) -> None:
    import subprocess as sp
    if name:
        info = domain_info(name)
        if info and "running" in info.state:
            sp.Popen(["virt-viewer", "--connect", uri(), "--attach", name], start_new_session=True)
            OUT.ok(f"opened virt-viewer for {name}")
            return
        sp.Popen(
            ["virt-manager", "--connect", uri(), "--show-domain-console", name],
            start_new_session=True,
        )
        OUT.ok(f"opened virt-manager for {name}")
        return
    sp.Popen(["virt-manager", "--connect", uri()], start_new_session=True)
    OUT.ok("opened virt-manager")


def console(name: str) -> int:
    require_domain(name)
    # interactive
    return subprocess.call(["virsh", "-c", uri(), "console", name])


def qemu_img_create(path: Path, size_gib: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["qemu-img", "create", "-f", "qcow2", str(path), f"{size_gib}G"])
    OUT.ok(f"created disk {path} ({size_gib} GiB)")


def find_ovmf() -> tuple[Path | None, Path | None]:
    """Locate OVMF CODE/VARS firmware files."""
    candidates = [
        Path("/run/current-system/sw/share/qemu"),
        Path("/usr/share/OVMF"),
        Path("/usr/share/edk2/ovmf"),
    ]
    # also search nix store lightly via common qemu path
    import glob
    for pat in (
        "/nix/store/*-qemu-*/share/qemu",
        "/nix/store/*-OVMF*/FV",
    ):
        candidates.extend(Path(p) for p in glob.glob(pat)[:5])

    code = vars_ = None
    for base in candidates:
        if not base.is_dir():
            continue
        for cname in ("edk2-x86_64-code.fd", "OVMF_CODE.fd", "OVMF_CODE.secboot.fd"):
            p = base / cname
            if p.is_file():
                code = p
                break
        for vname in ("edk2-i386-vars.fd", "OVMF_VARS.fd"):
            p = base / vname
            if p.is_file():
                vars_ = p
                break
        if code:
            break
    return code, vars_


def network_list() -> list[dict[str, str]]:
    r = _virsh("net-list", "--all")
    rows = []
    for line in r.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append({"name": parts[0], "state": parts[1], "autostart": parts[2] if len(parts) > 2 else ""})
    return rows


def ensure_lab_network() -> None:
    """Create isolated vm-lab network if missing."""
    name = str(load_config().get("network_lab", "vm-lab"))
    r = _virsh("net-info", name, check=False)
    if r.returncode == 0:
        OUT.ok(f"network {name} already exists")
        return
    xml = f"""<network>
  <name>{name}</name>
  <bridge name="virbr-vmlab" stp="on" delay="0"/>
  <ip address="192.168.200.1" netmask="255.255.255.0">
    <dhcp>
      <range start="192.168.200.10" end="192.168.200.200"/>
    </dhcp>
  </ip>
</network>
"""
    # no forward mode = isolated
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
        fh.write(xml)
        path = fh.name
    try:
        _virsh("net-define", path)
        _virsh("net-start", name)
        _virsh("net-autostart", name)
        OUT.ok(f"created isolated network {name}")
    finally:
        Path(path).unlink(missing_ok=True)


def clone_domain(source: str, dest: str) -> None:
    require_domain(source)
    if domain_exists(dest):
        raise Fail(f"destination already exists: {dest}", EXIT_STATE)
    # virt-clone handles new UUID/MAC
    run(["virt-clone", "--connect", uri(), "--original", source, "--name", dest, "--auto-clone"])
    OUT.ok(f"cloned {source} -> {dest}")


def virt_install(args: Sequence[str]) -> None:
    cmd = ["virt-install", "--connect", uri(), *args]
    OUT.vsay(" ".join(shlex.quote(a) for a in cmd))
    run(cmd)
