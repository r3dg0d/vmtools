"""CachyOS official media resolver."""

from __future__ import annotations

import html as htmlmod
import json
import re
import ssl
import urllib.request

from .base import DistroProvider, MediaInfo


class CachyOSProvider(DistroProvider):
    id = "cachyos"
    name = "CachyOS"
    priority = 10
    SOURCE = "https://cachyos.org/download/"

    def editions(self):
        return ("desktop",)

    def latest(self, edition: str = "desktop", arch: str = "x86_64") -> MediaInfo:
        ctx = ssl.create_default_context()
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/CachyOS/distribution/releases/latest",
                headers={"User-Agent": "vmtools/0.1", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "latest")
            for asset in data.get("assets") or []:
                name = asset.get("name", "")
                if name.endswith(".iso") and "desktop" in name.lower():
                    url = asset.get("browser_download_url", "")
                    if url.startswith("https://"):
                        return MediaInfo(
                            id=f"cachyos-{tag}-{arch}",
                            distro="cachyos",
                            edition=edition,
                            version=tag,
                            arch=arch,
                            filename=name,
                            url=url,
                            source_page=self.SOURCE,
                        )
        except Exception:
            pass

        req = urllib.request.Request(self.SOURCE, headers={"User-Agent": "vmtools/0.1"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            text = htmlmod.unescape(resp.read().decode("utf-8", "replace"))

        candidates = re.findall(
            r"https://(?:cdn77\.cachyos\.org|[a-z0-9.-]+\.cachyos\.org)/ISO/desktop/\d+/cachyos-desktop-linux-\d+\.iso",
            text,
        )
        if not candidates:
            candidates = re.findall(r"https://[a-zA-Z0-9._/-]+/cachyos-desktop-linux-\d+\.iso", text)
        # Dedupe preserving order; prefer cdn77
        seen = []
        for u in candidates:
            if u not in seen:
                seen.append(u)
        if not seen:
            from vmtools.ui import EXIT_DOWNLOAD, Fail
            raise Fail(
                "could not resolve CachyOS ISO metadata",
                EXIT_DOWNLOAD,
                f"open {self.SOURCE} and use linuxvm create --iso PATH",
            )
        seen.sort(key=lambda u: (0 if "cdn77.cachyos.org" in u else 1, u))
        url = seen[0]
        filename = url.rsplit("/", 1)[-1]
        version = "latest"
        m = re.search(r"cachyos-desktop-linux-(\d+)\.iso", filename)
        if m:
            version = m.group(1)
        sha = self._sha256(url, ctx)
        return MediaInfo(
            id=f"cachyos-{version}-{arch}",
            distro="cachyos",
            edition=edition,
            version=version,
            arch=arch,
            filename=filename,
            url=url,
            sha256=sha,
            source_page=self.SOURCE,
            verified_publisher=bool(sha),
        )

    def _sha256(self, iso_url: str, ctx) -> str | None:
        for suffix in (".sha256", ".sha256sum", ".sha256.txt"):
            try:
                req = urllib.request.Request(iso_url + suffix, headers={"User-Agent": "vmtools/0.1"})
                with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                    text = resp.read().decode("utf-8", "replace")
                token = text.split()[0].strip().lower()
                if re.fullmatch(r"[0-9a-f]{64}", token):
                    return token
            except Exception:
                continue
        return None
