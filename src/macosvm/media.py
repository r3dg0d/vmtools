"""Classify user-supplied macOS files and turn them into something QEMU can boot."""

from __future__ import annotations

import subprocess
from pathlib import Path

from vmtools.proc import which
from vmtools.ui import EXIT_PREREQ, EXIT_USAGE, OUT, Fail

# kind -> what it is / how it is used
KINDS = {
    "basesystem": "recovery image (BaseSystem.dmg / RecoveryImage.dmg or its .img) — boots the online installer",
    "installer-image": "full bootable installer disk (createinstallmedia + hdiutil convert -format UDRW) — offline install",
    "installer-app": "'Install macOS *.app' bundle — needs conversion (see README), or BaseSystem is pulled out of it",
    "installer-pkg": "InstallAssistant.pkg — expands to the installer app; convert on the Mac or try `macosvm extract`",
    "shared-support": "SharedSupport.dmg from an installer app — holds the BaseSystem asset; try `macosvm extract`",
    "opencore": "OpenCore boot disk (OpenCore.qcow2 / .img)",
    "opencore-config": "OpenCore config.plist (recorded; rebuild the OpenCore disk with OSX-KVM's opencore-image-ng.sh)",
    "ovmf-code": "OVMF firmware code (OVMF_CODE*.fd)",
    "ovmf-vars": "OVMF NVRAM template (OVMF_VARS*.fd)",
    "ipsw": "Apple-silicon macOS restore IPSW — not bootable under x86 KVM; use it with iosvm (darwin-vm Mac targets)",
}
BOOT_MEDIA = ("basesystem", "installer-image")


def classify(path: Path) -> str:
    n = path.name.lower()
    if path.is_dir():
        if n.endswith(".app") and n.startswith("install"):
            return "installer-app"
        if (path / "EFI").is_dir():
            return "opencore"
        raise Fail(f"{path}: don't know what this folder is", EXIT_USAGE, "pass --kind, see `macosvm import --help`")
    if n.endswith(".ipsw"):
        return "ipsw"
    if n.endswith(".pkg"):
        return "installer-pkg"
    if n == "sharedsupport.dmg":
        return "shared-support"
    if n.endswith(".plist"):
        return "opencore-config"
    if n.endswith(".fd"):
        return "ovmf-vars" if "vars" in n else "ovmf-code"
    if "opencore" in n and n.endswith((".qcow2", ".img")):
        return "opencore"
    if n.startswith(("basesystem", "recoveryimage")) and n.endswith((".dmg", ".img", ".chunklist")):
        if n.endswith(".chunklist"):
            raise Fail("that is the .chunklist; import the .dmg next to it", EXIT_USAGE)
        return "basesystem"
    if n.endswith((".img", ".cdr", ".dmg", ".iso", ".raw")):
        return "installer-image"
    raise Fail(f"{path.name}: unrecognised file type", EXIT_USAGE, "pass --kind " + "|".join(KINDS))


def app_basesystem(app: Path) -> Path | None:
    """Pre-Big Sur installers carry BaseSystem.dmg in Contents/SharedSupport directly."""
    for cand in ("Contents/SharedSupport/BaseSystem.dmg", "Contents/SharedSupport/BaseSystem/BaseSystem.dmg"):
        if (app / cand).is_file():
            return app / cand
    return None


def dmg_to_img(dmg: Path, out: Path) -> Path:
    """UDZO/ULFO BaseSystem.dmg -> raw .img (what OSX-KVM boots)."""
    if not which("dmg2img"):
        raise Fail("dmg2img not found", EXIT_PREREQ, "nix shell nixpkgs#dmg2img, or use the packaged macosvm")
    OUT.step(f"dmg2img {dmg.name} -> {out.name}")
    subprocess.run(["dmg2img", "-i", str(dmg), "-o", str(out)], check=True,
                   stdout=subprocess.DEVNULL if OUT.quiet else None)
    return out


def extract_basesystem(src: Path, work: Path) -> Path:
    """Best-effort: pull BaseSystem.dmg out of InstallAssistant.pkg / SharedSupport.dmg with 7-Zip.

    Apple's formats shift between releases, so this may fail; the reliable route is on the Mac
    (README: createinstallmedia + hdiutil convert, or copy BaseSystem out of the app).
    """
    seven = which("7zz") or which("7z")
    if not seven:
        raise Fail("7-Zip (7zz) not found", EXIT_PREREQ, "nix shell nixpkgs#_7zz, or convert on the Mac (README)")
    work.mkdir(parents=True, exist_ok=True)

    def x(archive: Path, *patterns: str) -> None:
        subprocess.run([seven, "x", "-y", "-aos", f"-o{work}", str(archive), *patterns, "-r"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def find(*names: str) -> Path | None:
        for name in names:
            hits = sorted(work.rglob(name))
            if hits:
                return hits[0]
        return None

    done = {src}
    x(src)
    for _ in range(8):  # pkg -> Payload -> SharedSupport.dmg -> asset zip -> BaseSystem.dmg
        if find("BaseSystem.dmg", "RecoveryImage.dmg"):
            break
        layer = next((p for pat in ("SharedSupport.dmg", "*.zip", "Payload*") for p in sorted(work.rglob(pat))
                      if p.is_file() and p not in done), None)
        if layer is None:
            break
        done.add(layer)
        x(layer)
    hit = find("BaseSystem.dmg", "RecoveryImage.dmg")
    if not hit:
        raise Fail("could not find BaseSystem.dmg inside it", hint="convert on the Mac instead (see README: 'From an installer app')")
    return hit
