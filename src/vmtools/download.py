"""HTTPS downloads with resume, progress, and .part staging."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .checksum import verify_sha256
from .ui import EXIT_CHECKSUM, EXIT_DOWNLOAD, OUT, Fail


class _HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Enforce HTTPS at every redirect, before contacting the next endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            fp.close()
            raise Fail("download failed: refusing non-HTTPS redirect", EXIT_DOWNLOAD)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _url_key(url: str) -> str:
    # Do not persist raw URLs, which can contain signed credentials or query data.
    return hashlib.sha256(url.encode()).hexdigest()


def _public_url(url: str) -> str:
    """Scheme, host, and path only. Drop userinfo, query, and fragment."""
    parts = urllib.parse.urlsplit(url)
    hostname = parts.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port:
        netloc = f"{hostname}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _strong_etag(value: str | None) -> str | None:
    if value and len(value) <= 4096 and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', value):
        return value
    return None


def _resume_state(path: Path, url: str) -> dict | None:
    try:
        if path.stat().st_size > 8192:
            return None
        state = json.loads(path.read_text())
        if (isinstance(state, dict) and state.get("version") == 1
                and state.get("url") == _url_key(url)
                and isinstance(state.get("final_url"), str)
                and isinstance(state.get("etag"), str) and _strong_etag(state["etag"])):
            return state
    except (OSError, ValueError):
        pass
    return None


def _save_resume_state(path: Path, url: str, final_url: str, etag: str | None) -> None:
    if not etag:
        path.unlink(missing_ok=True)
        return
    # Atomic replacement and private permissions avoid incomplete metadata and
    # prevent exposing even the opaque ETag to other users.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as fh:
        temporary = Path(fh.name)
        try:
            json.dump({"version": 1, "url": _url_key(url), "final_url": _url_key(final_url), "etag": etag}, fh)
            fh.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _discard_resume_state(path: Path) -> None:
    # Once the part is gone, stale metadata cannot cause a resume; cleanup must
    # not turn a successful promotion or checksum error into a different error.
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _format_bytes(n: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.1f} {u}" if u != "B" else f"{int(v)} {u}"
        v /= 1024
    return f"{n} B"


def _format_eta(seconds: float) -> str:
    if seconds < 0 or math.isnan(seconds) or math.isinf(seconds):
        return "--:--"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def download(
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    label: str | None = None,
    progress: bool = True,
) -> Path:
    """Download url to dest via HTTPS. Stages as dest.name + '.part' until complete."""
    if not url.startswith("https://"):
        raise Fail(
            f"refusing non-HTTPS URL: {_public_url(url)}",
            EXIT_DOWNLOAD,
            "only https:// sources are allowed",
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    metadata = part.with_name(part.name + ".json")
    label = label or dest.name

    if dest.is_file() and expected_sha256 and verify_sha256(dest, expected_sha256):
        OUT.ok(f"cached and verified: {dest}")
        return dest
    if dest.is_file() and not expected_sha256:
        OUT.ok(f"using cached file: {dest}")
        return dest

    existing = part.stat().st_size if part.is_file() else 0
    state = _resume_state(metadata, url) if existing else None
    if existing and not state and not expected_sha256:
        # Keep old bytes until a valid fresh response is ready to replace them.
        existing = 0
    headers = {"User-Agent": f"vmtools/{__version__} (NixOS host suite)"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
        if state:
            headers["If-Range"] = state["etag"]

    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _HTTPSRedirectHandler())
    req = urllib.request.Request(url, headers=headers)

    try:
        try:
            resp = opener.open(req, timeout=120)
        except urllib.error.HTTPError as exc:
            if exc.code != 416 or not existing:
                raise
            exc.close()
            # A range rejection alone does not prove the staged image is complete.
            if expected_sha256 and verify_sha256(part, expected_sha256):
                part.replace(dest)
                _discard_resume_state(metadata)
                OUT.ok(f"cached and verified: {dest}")
                return dest
            req = urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]})
            resp = opener.open(req, timeout=120)
            existing = 0
    except urllib.error.HTTPError as exc:
        exc.close()
        raise Fail(f"download failed: HTTP {exc.code}", EXIT_DOWNLOAD, _public_url(url)) from exc
    except urllib.error.URLError as exc:
        raise Fail(f"download failed: {exc.reason}", EXIT_DOWNLOAD) from exc

    # Validate framing before opening the staging file, preserving it on bad ranges.
    try:
        status = getattr(resp, "status", None) or resp.getcode()
        if status not in (200, 206):
            raise Fail(f"download failed: unexpected HTTP {status}", EXIT_DOWNLOAD)
        final_url = resp.geturl()
        etag = _strong_etag(resp.headers.get("ETag"))
        if status == 206 and existing and state:
            if etag != state["etag"] or _url_key(final_url) != state["final_url"]:
                raise Fail("download failed: resumed source identity changed; staging file retained", EXIT_DOWNLOAD)
        mode = "ab" if status == 206 and existing else "wb"
        if status == 200:
            existing = 0
        total_hdr = resp.headers.get("Content-Length")
        response_n = int(total_hdr) if total_hdr is not None else None
        if response_n is not None and response_n < 0:
            raise ValueError("negative Content-Length")
        total_n = response_n
        if status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", resp.headers.get("Content-Range", ""))
            if not match:
                raise ValueError("missing or invalid Content-Range")
            start, end, total_n = map(int, match.groups())
            if start != existing or end < start or end >= total_n:
                raise ValueError("Content-Range does not match staged download")
            range_n = end - start + 1
            if response_n is not None and response_n != range_n:
                raise ValueError("Content-Length does not match Content-Range")
            response_n = range_n
    except (ValueError, Fail) as exc:
        resp.close()
        if isinstance(exc, Fail):
            raise
        raise Fail(f"download failed: {exc}", EXIT_DOWNLOAD) from exc

    OUT.step(f"Downloading {label}")
    started = time.monotonic()
    written = existing
    last_draw = 0.0

    try:
        with resp, open(part, mode) as fh:
            # Truncate a fresh staging file before publishing its new validator.
            # A crash cannot pair old bytes with metadata from a new response.
            # Hash-backed legacy resumes have an unvalidated prefix. Do not
            # attach the tail's ETag to it before the whole-file hash is checked.
            _save_resume_state(metadata, url, final_url, etag if mode == "wb" or state else None)
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                if progress and not OUT.quiet and not OUT.json and (now - last_draw) >= 0.2:
                    last_draw = now
                    elapsed = max(now - started, 1e-3)
                    speed = (written - existing) / elapsed
                    pct = (written / total_n * 100) if total_n else 0.0
                    bar_w = 24
                    filled = int(bar_w * written / total_n) if total_n else 0
                    filled = min(bar_w, filled)
                    bar = "█" * filled + "░" * (bar_w - filled)
                    eta = ((total_n - written) / speed) if total_n and speed > 0 else -1
                    msg = (
                        f"{chr(13)}{bar} {pct:5.1f}%  {_format_bytes(written)}"
                        + (f" / {_format_bytes(total_n)}" if total_n else "")
                        + f"  {_format_bytes(speed)}/s  ETA {_format_eta(eta)}   "
                    )
                    print(msg, end="", flush=True)
    except (OSError, http.client.HTTPException) as exc:
        raise Fail("download interrupted; staging file retained for retry", EXIT_DOWNLOAD) from exc
    if progress and not OUT.quiet and not OUT.json:
        print()

    if ((response_n is not None and written - existing != response_n)
            or (total_n is not None and written != total_n)):
        raise Fail("download incomplete; staging file retained for retry", EXIT_DOWNLOAD)

    # Verify the staging file before replacing any existing destination.
    try:
        _maybe_verify(part, expected_sha256)
    except Fail:
        _discard_resume_state(metadata)
        raise
    part.replace(dest)
    _discard_resume_state(metadata)
    OUT.ok(f"DOWNLOAD COMPLETE ({_format_bytes(dest.stat().st_size)})")
    return dest


def _maybe_verify(dest: Path, expected_sha256: str | None) -> Path:
    if not expected_sha256:
        return dest
    OUT.step("SHA-256 VERIFYING")
    if not verify_sha256(dest, expected_sha256):
        dest.unlink(missing_ok=True)
        raise Fail("CHECKSUM FAILED", EXIT_CHECKSUM)
    OUT.ok("SHA-256 VERIFIED")
    return dest
