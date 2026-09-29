"""DistroProvider interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class MediaInfo:
    id: str
    distro: str
    edition: str
    version: str
    arch: str
    filename: str
    url: str
    sha256: str | None = None
    checksum_url: str | None = None
    signature_url: str | None = None
    source_page: str = ""
    verified_publisher: bool = False


class DistroProvider:
    id: str = ""
    name: str = ""
    priority: int = 100

    def editions(self) -> Sequence[str]:
        return ("default",)

    def architectures(self) -> Sequence[str]:
        return ("x86_64",)

    def latest(self, edition: str = "default", arch: str = "x86_64") -> MediaInfo:
        raise NotImplementedError

    def list_media(self) -> list[MediaInfo]:
        out = []
        for ed in self.editions():
            for arch in self.architectures():
                try:
                    out.append(self.latest(ed, arch))
                except Exception:
                    continue
        return out
