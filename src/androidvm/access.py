"""Detect legitimate Docker-Android-Pro registry access.

Credentials must come from environment or a secret store — never from the repo:

  ANDROIDVM_DOCKER_USER
  ANDROIDVM_DOCKER_TOKEN

Optional:
  ANDROIDVM_DOCKER_REGISTRY (default docker.io)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from vmtools.layout import LAYOUT, ensure
from vmtools.ui import EXIT_ACCESS, Fail, OUT


STATE_FILE = "android/access.json"


def _load_secrets_file() -> None:
    """Load ~/.config/vmtools/secrets.env into os.environ if keys missing.

    File must be mode 0600. Never store this file in git.
    """
    path = Path.home() / ".config" / "vmtools" / "secrets.env"
    if not path.is_file():
        return
    try:
        if path.stat().st_mode & 0o077:
            OUT.warn(f"{path} permissions are too open; expected 0600")
    except OSError:
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def credentials() -> tuple[str | None, str | None]:
    _load_secrets_file()
    user = os.environ.get("ANDROIDVM_DOCKER_USER") or os.environ.get("DOCKER_ANDROID_USER")
    token = os.environ.get("ANDROIDVM_DOCKER_TOKEN") or os.environ.get("DOCKER_ANDROID_TOKEN")
    return user, token


def access_configured() -> bool:
    user, token = credentials()
    if user and token:
        return True
    ensure()
    path = LAYOUT.data / STATE_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            return bool(data.get("configured")) and not data.get("token_present_in_repo")
        except Exception:
            return False
    return False


def mark_configured(user: str) -> None:
    ensure()
    path = LAYOUT.data / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "configured": True,
                "user": user,
                "backend": "docker-android-pro",
                "note": "token held in environment / docker credential store only",
            },
            indent=2,
        )
        + "\n"
    )


def require_access() -> None:
    if not access_configured():
        raise Fail(
            "Docker-Android-Pro access is not configured.",
            EXIT_ACCESS,
            "set ANDROIDVM_DOCKER_USER and ANDROIDVM_DOCKER_TOKEN, then run: androidvm setup",
        )


def docker_login() -> None:
    user, token = credentials()
    if not user or not token:
        raise Fail(
            "Missing ANDROIDVM_DOCKER_USER / ANDROIDVM_DOCKER_TOKEN",
            EXIT_ACCESS,
            "export them in your shell or secret store; never commit the token",
        )
    # login via stdin so token is not in process argv listing as clearly
    proc = subprocess.run(
        ["docker", "login", "-u", user, "--password-stdin"],
        input=token + "\n",
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise Fail(
            "docker login failed",
            EXIT_ACCESS,
            (proc.stderr or proc.stdout or "").strip()[:200],
        )
    mark_configured(user)
    OUT.ok(f"docker login succeeded as {user}")
