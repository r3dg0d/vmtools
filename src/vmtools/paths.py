"""XDG base directories and per-tool layout."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


# A UNIX socket path cannot exceed sizeof(sun_path), which is 108 bytes on
# Linux (107 usable). QEMU rejects anything longer outright, and a data
# directory a few levels deep is enough to hit it, so control sockets go in the
# runtime directory -- which is both short and cleaned up at logout -- and fall
# back to the machine directory only when there is no runtime directory.
SUN_PATH_MAX = 107


def runtime_dir(tool: str) -> Path | None:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value:
        return None
    path = Path(value) / tool
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path


def socket_path(tool: str, name: str, filename: str, fallback_dir: Path) -> Path:
    """Pick a usable path for a control socket, preferring the runtime dir."""
    runtime = runtime_dir(tool)
    if runtime is not None:
        candidate = runtime / name / filename
        if len(str(candidate).encode()) <= SUN_PATH_MAX:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
    return fallback_dir / filename


class Layout:
    """Directory layout for one tool. Nothing is created until ensure()."""

    def __init__(self, tool: str, subdirs: tuple[str, ...]) -> None:
        self.tool = tool
        self.subdirs = subdirs
        # An explicit override keeps the test suite, and anyone juggling
        # several disks, out of $HOME.
        override = os.environ.get(f"{tool.upper()}_HOME")
        self.data = Path(override) if override else data_home() / tool
        self.config = config_home() / tool
        self.cache = cache_home() / tool

    def __getattr__(self, name: str) -> Path:
        # layout.machines, layout.logs, ... for anything in subdirs.
        if name in self.__dict__.get("subdirs", ()):
            return self.data / name
        raise AttributeError(name)

    @property
    def config_file(self) -> Path:
        return self.config / "config.json"

    def ensure(self) -> None:
        for path in (self.data, self.config, self.cache, *(self.data / d for d in self.subdirs)):
            path.mkdir(parents=True, exist_ok=True)


def install_doc(tool: str, destination: Path) -> Path | None:
    """Copy this build's README into the tool's data directory.

    The packaged documentation is the one that matches the installed version,
    so setup overwrites any older copy rather than leaving a stale file that
    describes different behaviour.
    """
    import shutil

    source_dir = os.environ.get("VMTOOLS_DOC")
    if not source_dir:
        return None
    source = Path(source_dir) / f"{tool}-README.md"
    if not source.is_file():
        return None
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "README.md"
    shutil.copyfile(source, target)
    target.chmod(0o644)
    return target
