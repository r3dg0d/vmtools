"""Shared plumbing for iosvm and macosvm: user-supplied Apple imports and direct-QEMU guests.

Nothing here downloads or bundles Apple binaries. Files arrive one of two ways:
  * `import`: the user copies files they obtained themselves (usually on their own Mac);
  * `fetch`:  an explicit command that pulls straight from Apple's public servers
              (osrecovery.apple.com for macOS recovery, updates.cdn-apple.com for IPSWs),
              the same way OSX-KVM's fetch-macOS-v2.py and darwin-vm's get_files.sh do.
Every imported file is hashed into a manifest so `info`/`doctor` can show what is in use.
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checksum import sha256_file
from .config import read_json, validate_name, write_json
from .paths import data_home
from .proc import QMP, pid_alive, read_pidfile, terminate, which
from .ui import EXIT_NOT_FOUND, EXIT_PREREQ, EXIT_STATE, EXIT_USAGE, OUT, Fail


def apple_root() -> Path:
    override = os.environ.get("VMTOOLS_HOME")
    return (Path(override) if override else data_home() / "vmtools") / "apple"


@dataclass
class Store:
    """~/.local/share/vmtools/apple/<os>/{imports,vms}."""

    os_name: str  # "macos" | "ios"

    @property
    def root(self) -> Path:
        return apple_root() / self.os_name

    @property
    def imports(self) -> Path:
        return self.root / "imports"

    @property
    def vms(self) -> Path:
        return self.root / "vms"

    @property
    def manifest_path(self) -> Path:
        return self.imports / "manifest.json"

    def ensure(self) -> Store:
        for p in (self.imports, self.vms):
            p.mkdir(parents=True, exist_ok=True)
        return self

    # -- imports -----------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        return read_json(self.manifest_path, {}) or {}

    def save_manifest(self, data: dict[str, Any]) -> None:
        write_json(self.manifest_path, data)

    def add_import(self, src: Path, kind: str, *, name: str | None = None, move: bool = False,
                   link: bool = False, extra: dict[str, Any] | None = None, hash_it: bool = True) -> dict[str, Any]:
        """Copy (or move / symlink) a user file or directory into imports/ and record it."""
        self.ensure()
        src = src.expanduser().resolve()
        if not src.exists():
            raise Fail(f"{src}: no such file or directory", EXIT_NOT_FOUND)
        ident = validate_name(name or _slug(src.name))
        dest = self.imports / ident
        if dest.exists() or dest.is_symlink():
            raise Fail(f"an import named {ident!r} already exists", EXIT_STATE, f"pick another --name, or `{self.tool} imports rm {ident}`")
        if link:
            dest.symlink_to(src)
        elif move:
            shutil.move(str(src), dest)
        elif src.is_dir():
            shutil.copytree(src, dest, symlinks=True)
        else:
            OUT.step(f"copying {src.name} ({_size(src)})")
            shutil.copy2(src, dest)
        entry: dict[str, Any] = {
            "id": ident, "kind": kind, "path": str(dest), "source": str(src),
            "imported": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {}),
        }
        if hash_it and dest.is_file():
            entry["sha256"] = sha256_file(dest, progress=not OUT.quiet and not OUT.json)
        data = self.manifest()
        data[ident] = entry
        self.save_manifest(data)
        return entry

    def record(self, entry: dict[str, Any]) -> None:
        data = self.manifest()
        data[entry["id"]] = entry
        self.save_manifest(data)

    def get_import(self, ident: str, kinds: tuple[str, ...] = ()) -> dict[str, Any]:
        entry = self.manifest().get(ident)
        if not entry:
            raise Fail(f"no import named {ident!r}", EXIT_NOT_FOUND, f"see `{self.tool} imports`")
        if kinds and entry["kind"] not in kinds:
            raise Fail(f"import {ident!r} is a {entry['kind']}, expected {' or '.join(kinds)}", EXIT_USAGE)
        return entry

    def remove_import(self, ident: str) -> None:
        entry = self.get_import(ident)
        p = Path(entry["path"])
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        data = self.manifest()
        data.pop(ident, None)
        self.save_manifest(data)

    @property
    def tool(self) -> str:
        return "iosvm" if self.os_name == "ios" else "macosvm"

    # -- vms -----------------------------------------------------------------
    def vm_dir(self, name: str) -> Path:
        return self.vms / validate_name(name)

    def vm(self, name: str) -> Guest:
        d = self.vm_dir(name)
        if not (d / "vm.json").is_file():
            raise Fail(f"no {self.tool} VM named {name!r}", EXIT_NOT_FOUND, f"see `{self.tool} list`")
        return Guest(d)

    def guests(self) -> list[Guest]:
        if not self.vms.is_dir():
            return []
        return [Guest(d) for d in sorted(self.vms.iterdir()) if (d / "vm.json").is_file()]


class Guest:
    """One direct-QEMU guest: vm.json + qemu.pid + qmp.sock + serial.sock + qemu.log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.meta: dict[str, Any] = read_json(path / "vm.json", {}) or {}

    def save(self) -> None:
        write_json(self.path / "vm.json", self.meta)

    pidfile = property(lambda s: s.path / "qemu.pid")
    qmp_sock = property(lambda s: s.path / "qmp.sock")
    serial_sock = property(lambda s: s.path / "serial.sock")
    log = property(lambda s: s.path / "qemu.log")

    def pid(self) -> int | None:
        pid = read_pidfile(self.pidfile)
        return pid if pid and pid_alive(pid) else None

    def running(self) -> bool:
        return self.pid() is not None

    def uptime(self) -> int | None:
        pid = self.pid()
        if not pid:
            return None
        try:
            ticks = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
            boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
            return int(time.time() - (boot + ticks / os.sysconf("SC_CLK_TCK")))
        except (OSError, ValueError, IndexError):
            return None

    def rss_mib(self) -> int | None:
        pid = self.pid()
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
        except (OSError, ValueError, TypeError):
            pass
        return None

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name, "state": "running" if self.running() else "stopped", "pid": self.pid(),
            "uptime_s": self.uptime(), "rss_mib": self.rss_mib(), **{k: v for k, v in self.meta.items() if k != "argv"},
        }

    # -- lifecycle -----------------------------------------------------------
    def launch(self, argv: list[str], *, dry_run: bool = False) -> list[str]:
        argv = [*argv, "-qmp", f"unix:{self.qmp_sock},server=on,wait=off", "-pidfile", str(self.pidfile), "-daemonize"]
        if dry_run:
            return argv
        if self.running():
            raise Fail(f"{self.name} is already running", EXIT_STATE)
        if not which(argv[0]) and not Path(argv[0]).is_file():
            raise Fail(f"{argv[0]}: not found", EXIT_PREREQ, "run `doctor` for the fix")
        for s in (self.qmp_sock, self.serial_sock):
            s.unlink(missing_ok=True)
        with self.log.open("a") as log:
            log.write(f"\n== {time.strftime('%F %T')} {shlex.join(argv)}\n")
            log.flush()
            proc = subprocess.run(argv, stdout=log, stderr=log, stdin=subprocess.DEVNULL, check=False)
        if proc.returncode != 0:
            tail = self.log.read_text(errors="replace").strip().splitlines()[-3:]
            raise Fail(f"QEMU exited with {proc.returncode}: {' | '.join(tail)}", hint=f"full log: {self.log}")
        return argv

    def powerdown(self) -> None:
        with QMP(self.qmp_sock) as q:
            q.command("system_powerdown")

    def kill(self) -> bool:
        pid = self.pid()
        if not pid:
            return False
        try:
            with QMP(self.qmp_sock, timeout=2) as q:
                q.command("quit")
            for _ in range(20):
                if not pid_alive(pid):
                    return True
                time.sleep(0.25)
        except Fail:
            pass
        return terminate(pid)


def free_port(start: int, end: int) -> int:
    for port in range(start, end):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise Fail(f"no free port in {start}-{end}")


def asset_dir(env: str, default_name: str, cfg_value: str = "") -> Path | None:
    """Pinned upstream assets (OSX-KVM, darwin-vm) shipped by nix/apple-assets.nix."""
    for cand in (os.environ.get(env, ""), cfg_value,
                 os.path.join(os.environ.get("VMTOOLS_SHARE", ""), default_name) if os.environ.get("VMTOOLS_SHARE") else "",
                 str(apple_root() / "assets" / default_name)):
        if cand and Path(cand).is_dir():
            return Path(cand)
    return None


def fmt_uptime(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    h, rem = divmod(seconds, 3600)
    return f"{h}h{rem // 60:02d}m" if h else f"{rem // 60}m{rem % 60:02d}s"


def _slug(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "._-" else "-" for c in name).strip("-.")
    return (keep or "import")[:64]


def _size(p: Path) -> str:
    from .ui import human_size

    try:
        return human_size(p.stat().st_size)
    except OSError:
        return "?"
