"""SHA-256 helpers and verification status labels."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from .ui import OUT


def sha256_file(path: Path, *, progress: bool = True) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    last = 0.0

    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            now = time.monotonic()
            if progress and not OUT.quiet and not OUT.json and size and (now - last) >= 0.2:
                last = now
                pct = done / size * 100
                print(f"{chr(13)}  hashing {pct:5.1f}%", end="", flush=True)
    if progress and not OUT.quiet and not OUT.json:
        print()
    return h.hexdigest()


def verify_sha256(path: Path, expected: str) -> bool:
    expected = expected.strip().lower()
    actual = sha256_file(path).lower()
    return actual == expected


def verification_label(*, publisher: bool = False, user: bool = False, local_only: bool = False) -> str:
    if publisher:
        return "VERIFIED AGAINST PUBLISHER"
    if user:
        return "VERIFIED AGAINST USER HASH"
    if local_only:
        return "LOCAL HASH ONLY"
    return "UNVERIFIED"
