"""MintProvider — official source resolver (basic)."""

from __future__ import annotations

import re
import ssl
import urllib.request

from .base import DistroProvider, MediaInfo


class MintProvider(DistroProvider):
    id = "mint"
    name = "Mint"
    SOURCE = "https://linuxmint.com/download.php"
    INDEX = "https://mirrors.kernel.org/linuxmint/stable/"

    def latest(self, edition: str = "default", arch: str = "x86_64") -> MediaInfo:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(self.INDEX, headers={"User-Agent": "vmtools/0.1"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                html = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            from vmtools.ui import EXIT_DOWNLOAD, Fail
            raise Fail(f"could not fetch {self.INDEX}: {exc}", EXIT_DOWNLOAD, self.SOURCE) from exc
        # Prefer https links ending in .iso on same host tree
        isos = re.findall(r'href="([^"]+\.iso)"', html)
        abs_urls = []
        for href in isos:
            if href.startswith("https://"):
                abs_urls.append(href)
            elif href.startswith("http://"):
                continue
            elif href.startswith("/"):
                from urllib.parse import urljoin
                abs_urls.append(urljoin(self.INDEX, href))
            else:
                from urllib.parse import urljoin
                abs_urls.append(urljoin(self.INDEX, href))
        if not abs_urls:
            from vmtools.ui import EXIT_DOWNLOAD, Fail
            raise Fail(
                "no ISO links found for mint",
                EXIT_DOWNLOAD,
                f"open {self.SOURCE} and use --iso",
            )
        url = abs_urls[0]
        filename = url.rsplit("/", 1)[-1]
        return MediaInfo(
            id=f"mint-{filename}",
            distro="mint",
            edition=edition,
            version="latest",
            arch=arch,
            filename=filename,
            url=url,
            source_page=self.SOURCE,
        )
