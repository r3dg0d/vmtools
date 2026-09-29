"""Shared on-disk layout under ~/.local/share/vmtools."""

from __future__ import annotations

from .config import Config
from .paths import Layout

SUBDIRS = (
    "isos",
    "isos/windows",
    "isos/windows/drivers",
    "isos/linux",
    "disks",
    "cache",
    "metadata",
    "logs",
    "android",
)

LAYOUT = Layout("vmtools", SUBDIRS)

DEFAULTS = {
    "libvirt_uri": "qemu:///session",
    "default_viewer": "virt-manager",
    "windows_default_ram_gib": 8,
    "windows_default_cpus": 4,
    "windows_default_disk_gib": 80,
    "linux_default_ram_gib": 4,
    "linux_default_cpus": 4,
    "linux_default_disk_gib": 40,
    "android_backend": "docker-android-pro",
    "android_registry": "budtmo",
    "network_default": "default",
    "network_lab": "vm-lab",
}


def config() -> Config:
    return Config(LAYOUT.config_file, DEFAULTS)


def ensure() -> Layout:
    LAYOUT.ensure()
    # nested isos paths: Layout.ensure only creates top-level subdirs listed;
    # nested ones with slashes need explicit mkdir
    for d in SUBDIRS:
        (LAYOUT.data / d).mkdir(parents=True, exist_ok=True)
    return LAYOUT
