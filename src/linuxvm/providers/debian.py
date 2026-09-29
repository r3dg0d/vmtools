"""Debian official media resolver."""

from __future__ import annotations

import re
import ssl
import urllib.request

from .base import DistroProvider, MediaInfo


class DebianProvider(DistroProvider):
    id = "debian"
    name = "Debian"
    priority = 20

    def editions(self):
        return ("netinst", "dvd")

    def latest(self, edition: str = "netinst", arch: str = "x86_64") -> MediaInfo:
        deb_arch = "amd64" if arch in ("x86_64", "amd64") else arch
        if edition == "netinst":
            base = f"https://cdimage.debian.org/debian-cd/current/{deb_arch}/iso-cd/"
            pattern = r'href="(debian-[^"]+-netinst\.iso)"'
        else:
            base = f"https://cdimage.debian.org/debian-cd/current/{deb_arch}/iso-dvd/"
            pattern = r'href="(debian-[^"]+-DVD-1\.iso)"'
        ctx = ssl.create_default_context()
        req = urllib.request.Request(base, headers={"User-Agent": "vmtools/0.1"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
        files = re.findall(pattern, html)
        if not files:
            from vmtools.ui import EXIT_DOWNLOAD, Fail
            raise Fail(f"no Debian {edition} ISO listed at {base}", EXIT_DOWNLOAD)
        filename = files[0]
        url = base + filename
        sha256 = self._sha256_from_sums(base, filename, ctx)
        ver_m = re.search(r"debian-(\d+(?:\.\d+)*)", filename)
        version = ver_m.group(1) if ver_m else "current"
        return MediaInfo(
            id=f"debian-{version}-{edition}-{deb_arch}",
            distro="debian",
            edition=edition,
            version=version,
            arch=deb_arch,
            filename=filename,
            url=url,
            sha256=sha256,
            checksum_url=base + "SHA256SUMS",
            signature_url=base + "SHA256SUMS.sign",
            source_page="https://www.debian.org/CD/http-ftp/",
            verified_publisher=bool(sha256),
        )

    def _sha256_from_sums(self, base: str, filename: str, ctx) -> str | None:
        try:
            req = urllib.request.Request(base + "SHA256SUMS", headers={"User-Agent": "vmtools/0.1"})
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                text = resp.read().decode()
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].endswith(filename):
                    return parts[0].lower()
        except Exception:
            return None
        return None
