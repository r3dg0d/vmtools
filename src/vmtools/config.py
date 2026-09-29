"""JSON configuration and per-machine metadata, written atomically."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .ui import EXIT_USAGE, Fail

# Machine names become directory names, socket paths and QEMU ids.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise Fail(
            f"invalid VM name {name!r}",
            EXIT_USAGE,
            "names may contain letters, digits, dot, dash and underscore, "
            "must start with a letter or digit, and be at most 64 characters",
        )
    return name


def write_json(path: Path, payload: Any) -> None:
    """Write via a temporary file in the same directory, then rename.

    A half-written machine.json would make a VM unusable, and these files are
    rewritten on every start/stop.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise Fail(f"{path} is not valid JSON: {exc}") from exc


class Config:
    """Tool-level defaults, backed by <config_home>/<tool>/config.json."""

    def __init__(self, path: Path, defaults: dict[str, Any]) -> None:
        self.path = path
        self.defaults = defaults
        self.values: dict[str, Any] = dict(defaults)
        self.values.update(read_json(path, {}) or {})

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.values.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        if key not in self.defaults:
            known = ", ".join(sorted(self.defaults))
            raise Fail(f"unknown configuration key {key!r}", EXIT_USAGE, f"known keys: {known}")
        # Keep the declared type of the default; JSON from the CLI is a string.
        current = self.defaults[key]
        if isinstance(current, bool):
            value = str(value).lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int) and not isinstance(current, bool):
            try:
                value = int(value)
            except ValueError as exc:
                raise Fail(f"{key} must be an integer", EXIT_USAGE) from exc
        self.values[key] = value
        write_json(self.path, self.values)
