"""Localhost port allocation for Android containers."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from vmtools.layout import LAYOUT, ensure


def _in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def allocate(start: int = 6080, count: int = 2) -> list[int]:
    """Allocate `count` free localhost ports starting near `start`."""
    ports: list[int] = []
    p = start
    while len(ports) < count and p < start + 500:
        if not _in_use(p):
            ports.append(p)
        p += 1
    if len(ports) < count:
        raise RuntimeError("could not allocate ports")
    return ports


def save_ports(name: str, viewer: int, adb: int) -> Path:
    ensure()
    path = LAYOUT.data / "android" / f"{name}-ports.json"
    path.write_text(json.dumps({"viewer": viewer, "adb": adb, "bind": "127.0.0.1"}, indent=2) + "\n")
    return path
