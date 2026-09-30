"""Distro media providers."""

from __future__ import annotations

from .arch import ArchProvider
from .base import DistroProvider, MediaInfo  # noqa: F401  (re-exported for callers)
from .cachyos import CachyOSProvider
from .debian import DebianProvider
from .fedora import FedoraProvider
from .kali import KaliProvider
from .mint import MintProvider
from .nixos import NixOSProvider
from .opensuse import OpenSUSEProvider
from .ubuntu import UbuntuProvider

PROVIDERS: dict[str, DistroProvider] = {}

def _reg(p: DistroProvider) -> None:
    PROVIDERS[p.id] = p

for cls in (
    CachyOSProvider, DebianProvider, FedoraProvider, NixOSProvider,
    UbuntuProvider, ArchProvider, MintProvider, OpenSUSEProvider, KaliProvider,
):
    _reg(cls())

def get(distro_id: str) -> DistroProvider:
    key = distro_id.lower().replace(" ", "")
    aliases = {
        "cachy": "cachyos",
        "deb": "debian",
        "ubu": "ubuntu",
        "suse": "opensuse",
        "tumbleweed": "opensuse",
    }
    key = aliases.get(key, key)
    if key not in PROVIDERS:
        from vmtools.ui import EXIT_USAGE, Fail
        known = ", ".join(sorted(PROVIDERS))
        raise Fail(f"unknown distro {distro_id!r}", EXIT_USAGE, f"known: {known}")
    return PROVIDERS[key]

def list_providers() -> list[DistroProvider]:
    return [PROVIDERS[k] for k in sorted(PROVIDERS)]
