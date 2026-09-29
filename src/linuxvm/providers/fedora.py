"""Fedora Workstation/Server resolver via productmd-style releasemeta mirrors."""

from __future__ import annotations

import json
import ssl
import urllib.request

from .base import DistroProvider, MediaInfo


class FedoraProvider(DistroProvider):
    id = "fedora"
    name = "Fedora"
    priority = 30

    def editions(self):
        return ("workstation", "server")

    def architectures(self):
        return ("x86_64", "aarch64")

    def latest(self, edition: str = "workstation", arch: str = "x86_64") -> MediaInfo:
        ctx = ssl.create_default_context()
        # https://docs.fedoraproject.org/en-US/fedora/ - releases JSON
        meta_url = "https://getfedora.org/releases.json"
        req = urllib.request.Request(meta_url, headers={"User-Agent": "vmtools/0.1"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            releases = json.loads(resp.read().decode())
        edition_l = edition.lower()
        arch_l = arch.lower()
        candidates = []
        for rel in releases:
            if str(rel.get("version", "")).lower() in ("rawhide",):
                continue
            if rel.get("arch", "").lower() != arch_l:
                continue
            variant = (rel.get("variant") or rel.get("subvariant") or "").lower()
            link = rel.get("link") or ""
            if edition_l == "workstation" and "workstation" in variant and link.endswith(".iso"):
                candidates.append(rel)
            if edition_l == "server" and "server" in variant and "dvd" in (rel.get("link") or "").lower():
                candidates.append(rel)
        if not candidates:
            # broader match
            for rel in releases:
                link = rel.get("link") or ""
                if rel.get("arch", "").lower() != arch_l:
                    continue
                if edition_l in (rel.get("variant") or "").lower() and link.endswith(".iso"):
                    candidates.append(rel)
        if not candidates:
            from vmtools.ui import EXIT_DOWNLOAD, Fail
            raise Fail(f"no Fedora {edition}/{arch} in releases.json", EXIT_DOWNLOAD)

        def verkey(r):
            try:
                return int(str(r.get("version", "0")).split(".")[0])
            except ValueError:
                return 0

        best = sorted(candidates, key=verkey, reverse=True)[0]
        url = best["link"]
        filename = url.rsplit("/", 1)[-1]
        sha = (best.get("sha256") or best.get("checksum") or None)
        if isinstance(sha, str) and sha.startswith("sha256:"):
            sha = sha.split(":", 1)[1]
        return MediaInfo(
            id=f"fedora-{best.get('version')}-{edition}-{arch}",
            distro="fedora",
            edition=edition,
            version=str(best.get("version")),
            arch=arch,
            filename=filename,
            url=url,
            sha256=sha.lower() if isinstance(sha, str) else None,
            source_page="https://fedoraproject.org/workstation/download" if edition == "workstation" else "https://fedoraproject.org/server/download",
            verified_publisher=bool(sha),
        )
