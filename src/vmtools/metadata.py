"""ISO / media metadata cache under ~/.local/share/vmtools/metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import read_json, write_json
from .layout import LAYOUT, ensure


def _path(media_id: str) -> Path:
    ensure()
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in media_id)
    return LAYOUT.data / "metadata" / f"{safe}.json"


def save_media(meta: dict[str, Any]) -> Path:
    ensure()
    meta = dict(meta)
    meta.setdefault("downloaded_at", datetime.now(UTC).isoformat())
    path = _path(str(meta["id"]))
    write_json(path, meta)
    return path


def load_media(media_id: str) -> dict[str, Any] | None:
    path = _path(media_id)
    if not path.is_file():
        return None
    return read_json(path)


def list_media(prefix: str | None = None) -> list[dict[str, Any]]:
    ensure()
    out = []
    meta_dir = LAYOUT.data / "metadata"
    if not meta_dir.is_dir():
        return out
    for path in sorted(meta_dir.glob("*.json")):
        data = read_json(path, {})
        if not data:
            continue
        if prefix and not str(data.get("id", "")).startswith(prefix):
            continue
        out.append(data)
    return out
