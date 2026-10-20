"""darwin-vm firmware sets: bootkc, dtree, ramdisk.dmg, ramdisk.tc (+ sptm/txm on newer chips).

`fetch` is a Python port of darwin-vm's get_files.sh: it uses the `ipsw` tool to pull single files
out of a restore IPSW — remotely from Apple's own CDN (updates.cdn-apple.com) or from an IPSW you
imported — unwraps the IMG4 payloads and fixes up the device tree with darwin-vm's dt_fixup.py.
The last step (patching the ramdisk with a shell + building ramdisk.tc) needs hdiutil/codesign,
so it runs on a Mac; import the finished firmware/ folder with `iosvm import`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from vmtools.proc import which
from vmtools.ui import EXIT_PREREQ, EXIT_USAGE, OUT, Fail

REQUIRED = ("bootkc", "dtree", "ramdisk.dmg")
# darwin-vm's default: iPhone 16 (iPhone17,3) on iOS 27.0 (24A437), straight from Apple's CDN.
DEFAULT_DEVICE = "iPhone17,3"
DEFAULT_URL = "https://updates.cdn-apple.com/2026FallFCS/5130b3f9-3b4e-469a-b60e-93f6b310cdd9/iPhone17,3_27.0_24A437_Restore.ipsw"
APPLE_HOSTS = ("updates.cdn-apple.com", "appldnld.apple.com", "updates-http.cdn-apple.com", "secure-appldnld.apple.com")


def inspect(path: Path) -> dict:
    files = {f: (path / f).is_file() for f in (*REQUIRED, "ramdisk.tc", "sptm", "txm")}
    missing = [f for f in REQUIRED if not files[f]]
    info = (path / "info").read_text().split() if (path / "info").is_file() else []
    return {
        "files": files, "missing": missing,
        "patched": files["ramdisk.tc"],  # trustcache only exists once the Mac-side patch ran
        "sptm": files["sptm"] and files["txm"],
        "device": info[0] if info else None, "url": info[1] if len(info) > 1 else None,
    }


def validate(path: Path) -> dict:
    if not path.is_dir():
        raise Fail(f"{path} is not a folder", EXIT_USAGE, "import darwin-vm's firmware/ folder, or an .ipsw")
    r = inspect(path)
    if r["missing"]:
        raise Fail(f"{path}: missing {', '.join(r['missing'])}", EXIT_USAGE, "is this darwin-vm's firmware/ folder? (get_files.sh output)")
    if r["files"]["sptm"] != r["files"]["txm"]:
        raise Fail("sptm and txm must come together", EXIT_USAGE)
    return r


def _ipsw(*args: str) -> str:
    proc = subprocess.run(["ipsw", *args], check=False, capture_output=True, text=True)
    if proc.returncode:
        raise Fail(f"ipsw {args[0]} failed: {(proc.stderr or proc.stdout).strip()[-400:]}")
    return proc.stdout


def fetch(out: Path, *, device: str, source: str, darwin_vm: Path, remote: bool) -> dict:
    for tool in ("ipsw", "jq"):
        if not which(tool):
            raise Fail(f"{tool} not found", EXIT_PREREQ, f"nix shell nixpkgs#{tool} (the packaged iosvm pins it)")
    if remote and not any(f"//{h}/" in source for h in APPLE_HOSTS):
        raise Fail("refusing a non-Apple URL", EXIT_USAGE, "IPSWs must come from Apple's CDN (updates.cdn-apple.com); or import a local .ipsw")
    out.mkdir(parents=True, exist_ok=True)
    info = json.loads(_ipsw("device-info", "-j", "-d", device))
    entry = info[0] if isinstance(info, list) else next(iter(info.values()))
    boards = entry.get("boards", {})
    board = next((k for k in boards if "DEV" not in k), "").lower()
    dev = next((v for k, v in boards.items() if "DEV" in k), {})
    kc, chip, sdk = dev.get("kc_type"), dev.get("platform"), entry.get("sdk")
    if not (board and kc and chip and sdk):
        raise Fail(f"could not identify {device} (board={board} kc={kc} chip={chip} sdk={sdk})")
    OUT.note(f"{device}: board {board}, kernel {kc}, chip {chip}, sdk {sdk}")
    (out / "info").write_text(f"{device}\n{source}\n")
    src_args = ["--remote", source] if remote else [source]
    with tempfile.TemporaryDirectory() as td:
        def extract(*pattern: str) -> Path:
            res = json.loads(_ipsw("extract", *src_args, "--output", td, "--flat", "-j", *pattern) or "[]")
            if not res or not Path(res[0]).is_file():
                raise Fail(f"{' '.join(pattern)}: not found in the IPSW")
            return Path(res[0])

        def get(pattern: str, name: str) -> None:
            OUT.step(f"{name}  <-  {pattern}")
            _ipsw("img4", "im4p", "extract", str(extract("--pattern", pattern)), "-o", str(out / name))

        listing = _ipsw("info", *src_args, "--list")
        get(f"kernelcache.release.{kc}", "bootkc")
        if f"sptm.{chip}.release" in listing:
            get(f"sptm.{chip}.release", "sptm")
            get(f"txm.{sdk}.release", "txm")
        get(f"DeviceTree.{board}", "dtree")
        OUT.step("ramdisk.dmg  <-  restore ramdisk")
        rd = extract("--dmg", "rdisk")
        if rd.suffix != ".dmg":
            raise Fail(f"ramdisk {rd.name} is not a .dmg (encrypted .aea?)")
        _ipsw("img4", "im4p", "extract", str(rd), "-o", str(out / "ramdisk.dmg"))
    OUT.step("device tree fixup (darwin-vm dt_fixup.py)")
    subprocess.run(["python3", str(darwin_vm / "dt_fixup.py"), "-nvram", str(darwin_vm / "nvram.bin"),
                    str(out / "dtree"), str(out / "dtree.patch")], check=True)
    shutil.move(out / "dtree.patch", out / "dtree")
    return inspect(out)
