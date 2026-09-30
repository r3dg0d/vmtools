"""Windows media catalog. Resolvers prefer publisher pages; CDN URLs are not hardcoded forever."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WindowsMedia:
    id: str
    title: str
    version: str
    arch: str = "x64"
    source: str = "Microsoft"
    evaluation: bool = False
    evaluation_days: int | None = None
    # Official landing pages — resolvers fetch current download metadata from these.
    source_page: str = ""
    notes: str = ""
    # Optional direct URL if currently known; empty means interactive/local only.
    download_url: str | None = None
    sha256: str | None = None
    filename: str | None = None


def catalog() -> list[WindowsMedia]:
    return [
        WindowsMedia(
            id="windows-11-25h2-x64",
            title="Windows 11 25H2",
            version="25H2",
            source_page="https://www.microsoft.com/software-download/windows11",
            notes="Consumer ISO via Microsoft download flow. Automated CDN resolution may fail; use Existing ISO or open the official page.",
        ),
        WindowsMedia(
            id="windows-11-enterprise-eval-x64",
            title="Windows 11 Enterprise Evaluation",
            version="Enterprise Eval",
            evaluation=True,
            evaluation_days=90,
            source_page="https://www.microsoft.com/evalcenter/evaluate-windows-11-enterprise",
            notes="90-DAY EVALUATION. Official Eval Center.",
        ),
        WindowsMedia(
            id="windows-11-enterprise-ltsc-eval-x64",
            title="Windows 11 Enterprise LTSC Evaluation",
            version="Enterprise LTSC Eval",
            evaluation=True,
            evaluation_days=90,
            source_page="https://www.microsoft.com/evalcenter",
            notes="90-DAY EVALUATION where officially available.",
        ),
        WindowsMedia(
            id="windows-11-iot-enterprise-ltsc-2024-eval-x64",
            title="Windows 11 IoT Enterprise LTSC 2024 Evaluation",
            version="IoT Enterprise LTSC 2024",
            evaluation=True,
            evaluation_days=90,
            source_page="https://www.microsoft.com/evalcenter/evaluate-windows-11-iot-enterprise-ltsc",
            notes="90-DAY EVALUATION. x64. Not a perpetual license.",
        ),
    ]


VIRTIO_WIN = WindowsMedia(
    id="virtio-win",
    title="Fedora virtio-win drivers",
    version="latest",
    source="Fedora Project",
    source_page="https://fedoraproject.org/wiki/Windows_Virtio_Drivers",
    # Stable "latest" redirect from Fedora
    download_url="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso",
    filename="virtio-win.iso",
    notes="Official Fedora virtio-win ISO for Windows guests.",
)
