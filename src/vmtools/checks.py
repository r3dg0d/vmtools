"""Host capability probes, and the report they render into.

These are the building blocks of `iosvm doctor` and `macosvm doctor`. Each
probe returns a Check; a Check is either ok, a warning (an optional component
is missing, the tool still works) or a failure (something required is absent).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .proc import which
from .ui import OUT, STYLE, SYM_BAD, SYM_OK, SYM_WARN

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    @property
    def symbol(self) -> str:
        return {OK: STYLE.green(SYM_OK), WARN: STYLE.yellow(SYM_WARN), FAIL: STYLE.red(SYM_BAD)}[self.status]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "hint": self.hint}


@dataclass
class Section:
    title: str
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check


class Report:
    def __init__(self) -> None:
        self.sections: list[Section] = []

    def section(self, title: str) -> Section:
        section = Section(title)
        self.sections.append(section)
        return section

    @property
    def all_checks(self) -> list[Check]:
        return [c for s in self.sections for c in s.checks]

    def counts(self) -> tuple[int, int, int]:
        checks = self.all_checks
        return (
            sum(1 for c in checks if c.status == OK),
            sum(1 for c in checks if c.status == WARN),
            sum(1 for c in checks if c.status == FAIL),
        )

    def render(self, headline: str) -> None:
        OUT.say(STYLE.bold(headline))
        OUT.say()
        for section in self.sections:
            if not section.checks:
                continue
            OUT.say(f"  {STYLE.bold(section.title)}")
            for check in section.checks:
                line = f"    {check.symbol} {check.name}"
                if check.detail:
                    line += f"  {STYLE.dim(check.detail)}"
                OUT.say(line)
            OUT.say()

        good, warned, failed = self.counts()
        OUT.say(STYLE.bold("Result:"))
        if failed:
            OUT.say(f"  {STYLE.red(str(failed) + ' required component(s) missing')}, {warned} optional, {good} ok.")
        elif warned:
            OUT.say(f"  {STYLE.yellow(str(warned) + ' optional component(s) require setup')}, {good} ok.")
        else:
            OUT.say(f"  {STYLE.green('Host ready')} ({good} checks passed).")

        hints = [c for c in self.all_checks if c.hint and c.status != OK]
        if hints:
            OUT.say()
            OUT.say(STYLE.bold("Next steps:"))
            for check in hints:
                OUT.say(f"  {STYLE.dim('-')} {check.name}: {check.hint}")

    def as_dict(self) -> dict[str, Any]:
        good, warned, failed = self.counts()
        return {
            "sections": [{"title": s.title, "checks": [c.as_dict() for c in s.checks]} for s in self.sections],
            "summary": {"ok": good, "warnings": warned, "failures": failed},
        }


# --------------------------------------------------------------- probes ---


def find_kernel_module(base: Path, name: str) -> Path | None:
    """Look for <name>.ko* under a modules tree, following symlinks.

    On NixOS a modules tree is symlinks all the way down: the tree root, and
    each of kernel/, updates/ and extra/ inside it, point into separate store
    paths. Neither Path.rglob nor a plain os.walk descends through those by
    default, so a naive search reports "not available for this kernel" while
    the module sits one directory away.
    """
    try:
        root = base.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    try:
        for directory, _subdirs, files in os.walk(root, followlinks=True):
            for filename in files:
                if filename == f"{name}.ko" or filename.startswith(f"{name}.ko."):
                    return Path(directory) / filename
    except OSError:
        return None
    return None


def check_binary(label: str, binary: str, *, required: bool = True, hint: str = "") -> Check:
    path = which(binary)
    if path:
        return Check(label, OK, path)
    return Check(label, FAIL if required else WARN, f"{binary} not found", hint)


def check_cpu_virt() -> Check:
    """Detect the vendor rather than assuming one: vmx is Intel VT-x, svm is
    AMD-V. Both end up at the same /dev/kvm, but the flag and the kernel module
    differ, and the wrong one in a report is worse than none."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
    except OSError:
        return Check("hardware virtualization", WARN, "cannot read /proc/cpuinfo")

    model = ""
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break

    flags = ""
    for line in cpuinfo.splitlines():
        if line.startswith("flags"):
            flags = line
            break

    if " vmx" in flags:
        return Check("hardware virtualization", OK, f"Intel VT-x ({model})")
    if " svm" in flags:
        return Check("hardware virtualization", OK, f"AMD-V ({model})")
    return Check(
        "hardware virtualization",
        FAIL,
        f"neither vmx nor svm on {model or 'this CPU'}",
        "enable VT-x/AMD-V in firmware; without it QEMU can only emulate, not accelerate",
    )


def check_kvm_device() -> list[Check]:
    checks: list[Check] = []
    dev = Path("/dev/kvm")
    if not dev.exists():
        checks.append(
            Check(
                "/dev/kvm present",
                FAIL,
                "missing",
                "load kvm_intel or kvm_amd; check that virtualization is enabled in firmware",
            )
        )
        return checks
    checks.append(Check("/dev/kvm present", OK))

    # Access is what actually matters: group membership only takes effect in
    # sessions started after usermod, which is the usual trap.
    if os.access(dev, os.R_OK | os.W_OK):
        checks.append(Check("/dev/kvm accessible", OK, "no root required"))
    else:
        checks.append(
            Check(
                "/dev/kvm accessible",
                FAIL,
                "permission denied",
                "your user must be in the 'kvm' group; log out and back in for a new group list to apply",
            )
        )
    return checks


def check_kernel_module(name: str, *, required: bool = False, hint: str = "") -> Check:
    """Loaded, available-but-unloaded, or absent."""
    try:
        loaded = Path("/proc/modules").read_text()
    except OSError:
        loaded = ""
    if any(line.split(" ", 1)[0] == name for line in loaded.splitlines()):
        return Check(f"{name} module", OK, "loaded")

    # Built into the kernel rather than modular.
    if Path(f"/sys/module/{name}").exists():
        return Check(f"{name} module", OK, "built in")

    release = os.uname().release
    candidate = find_kernel_module(Path(f"/run/booted-system/kernel-modules/lib/modules/{release}"), name)
    if candidate is not None:
        return Check(f"{name} module", WARN, f"available, not loaded ({candidate.parent.name})", hint)
    return Check(f"{name} module", FAIL if required else WARN, "not available for this kernel", hint)


def check_group(group: str) -> Check:
    import grp

    try:
        entry = grp.getgrnam(group)
    except KeyError:
        return Check(f"{group} group", WARN, "group does not exist on this host")

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    # The effective group list is what the kernel enforces; the passwd/group
    # database is only what a future session would get.
    effective = set(os.getgroups())
    if entry.gr_gid in effective:
        return Check(f"{group} group", OK, "active in this session")
    if user and user in entry.gr_mem:
        return Check(
            f"{group} group",
            WARN,
            "configured but not active in this session",
            "log out and back in (or run `newgrp " + group + "`) to pick it up",
        )
    return Check(f"{group} group", WARN, f"{user or 'this user'} is not a member")


def check_service(unit: str, *, required: bool = False, hint: str = "") -> Check:
    systemctl = which("systemctl")
    if not systemctl:
        return Check(unit, WARN, "systemctl not available")
    active = subprocess.run(
        [systemctl, "is-active", unit], capture_output=True, text=True, check=False
    ).stdout.strip()
    if active == "active":
        return Check(unit, OK, "running")
    enabled = subprocess.run(
        [systemctl, "is-enabled", unit], capture_output=True, text=True, check=False
    ).stdout.strip()
    if enabled in ("enabled", "static", "indirect"):
        return Check(unit, WARN, f"{active or 'inactive'} (enabled)", hint or f"start it with: systemctl start {unit}")
    return Check(unit, FAIL if required else WARN, active or "not found", hint)


def check_disk_space(path: Path, need_gb: int) -> Check:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1000**3)
    detail = f"{free_gb:.0f} GB free on {path}"
    if free_gb < need_gb:
        return Check(
            "disk space",
            WARN,
            detail,
            f"at least {need_gb} GB is recommended for a full install",
        )
    return Check("disk space", OK, detail)


def check_memory(need_gb: int) -> Check:
    total_kb = 0
    available_kb = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available_kb = int(line.split()[1])
    except OSError:
        return Check("memory", WARN, "cannot read /proc/meminfo")
    total_gb = total_kb / (1024**2)
    available_gb = available_kb / (1024**2)
    detail = f"{available_gb:.1f} GB available of {total_gb:.1f} GB"
    if total_gb < need_gb:
        return Check("memory", WARN, detail, f"{need_gb} GB or more is recommended")
    return Check("memory", OK, detail)


def check_forwarding() -> Check:
    try:
        value = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
    except OSError:
        return Check("IPv4 forwarding", WARN, "cannot read sysctl")
    if value == "1":
        return Check("IPv4 forwarding", OK, "enabled")
    return Check(
        "IPv4 forwarding",
        WARN,
        "disabled",
        "only needed when routing guest traffic by hand; libvirt's NAT network enables it on demand",
    )


def gpu_summary() -> list[str]:
    """PCI display controllers, from sysfs -- no nvidia-smi dependency."""
    gpus: list[str] = []
    base = Path("/sys/bus/pci/devices")
    if not base.exists():
        return gpus
    lspci = which("lspci")
    if lspci:
        result = subprocess.run([lspci, "-mm"], capture_output=True, text=True, check=False)
        for line in result.stdout.splitlines():
            if '"VGA compatible controller"' in line or '"3D controller"' in line or '"Display controller"' in line:
                fields = [f.strip('"') for f in line.split('" "')]
                if len(fields) >= 3:
                    gpus.append(f"{fields[2]} {fields[3] if len(fields) > 3 else ''}".strip())
        return gpus
    for device in sorted(base.iterdir()):
        try:
            if (device / "class").read_text().strip().startswith("0x0300"):
                gpus.append(device.name)
        except OSError:
            continue
    return gpus


def first_failure(report: Report) -> Check | None:
    for check in report.all_checks:
        if check.status == FAIL:
            return check
    return None
