"""Docker-Android-Pro image catalog (authenticated Hub API)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from .access import credentials, require_access
from vmtools.ui import EXIT_ACCESS, EXIT_DOWNLOAD, Fail, OUT


DEFAULT_REPO = "budtmo2/docker-android-pro"


def _hub_token() -> str:
    user, token = credentials()
    if not user or not token:
        raise Fail("Pro credentials missing", EXIT_ACCESS)
    ctx = ssl.create_default_context()
    payload = json.dumps({"username": user, "password": token}).encode()
    req = urllib.request.Request(
        "https://hub.docker.com/v2/users/login/",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "vmtools/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise Fail(f"Docker Hub login failed: HTTP {exc.code}", EXIT_ACCESS) from exc
    jwt = data.get("token")
    if not jwt:
        raise Fail("Docker Hub login returned no token", EXIT_ACCESS)
    return jwt


def list_tags(repo: str = DEFAULT_REPO, *, page_size: int = 100) -> list[dict[str, Any]]:
    require_access()
    jwt = _hub_token()
    ctx = ssl.create_default_context()
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size={page_size}&ordering=last_updated"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"JWT {jwt}", "User-Agent": "vmtools/0.1"},
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise Fail(f"tag list failed for {repo}: HTTP {exc.code}", EXIT_DOWNLOAD) from exc
    return list(data.get("results") or [])


def preferred_emulator_tags(tags: list[dict[str, Any]]) -> list[str]:
    """Prefer short emulator_* tags (no _v version suffix), newest Android first."""
    names = [t.get("name", "") for t in tags if t.get("name")]
    short = [n for n in names if n.startswith("emulator_") and "_v" not in n and "headless" not in n]
    # sort by android version number in tag
    def key(n: str) -> float:
        try:
            return float(n.split("_", 1)[1])
        except Exception:
            return 0.0
    short = sorted(set(short), key=key, reverse=True)
    return short


def image_ref(tag: str, repo: str = DEFAULT_REPO) -> str:
    return f"{repo}:{tag}"
