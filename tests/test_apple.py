import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = [sys.executable, str(ROOT / "bin" / "run-tool.py")]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VMTOOLS_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("VMTOOLS_SHARE", raising=False)
    return tmp_path


def run(*args, ok=True):
    p = subprocess.run([*RUN, *args], capture_output=True, text=True, env=os.environ.copy())
    if ok:
        assert p.returncode == 0, p.stderr
    return p


def test_classify():
    from macosvm.media import classify

    cases = {"BaseSystem.dmg": "basesystem", "RecoveryImage.dmg": "basesystem", "InstallAssistant.pkg": "installer-pkg",
             "SharedSupport.dmg": "shared-support", "OVMF_CODE_4M.fd": "ovmf-code", "OVMF_VARS-1920x1080.fd": "ovmf-vars",
             "OpenCore.qcow2": "opencore", "config.plist": "opencore-config", "Sonoma.img": "installer-image",
             "UniversalMac_26.0_Restore.ipsw": "ipsw"}
    for name, kind in cases.items():
        assert classify(Path(name)) == kind, name


def test_macos_import_create_start_dry(home):
    for n in ("OpenCore.qcow2", "OVMF_CODE_4M.fd", "OVMF_VARS.fd", "BaseSystem.img"):
        (home / n).write_bytes(b"x")
        run("macosvm", "-q", "import", str(home / n))
    data = json.loads(run("macosvm", "--json", "imports").stdout)
    assert {e["kind"] for e in data} == {"opencore", "ovmf-code", "ovmf-vars", "basesystem"}
    assert all(len(e["sha256"]) == 64 for e in data)
    run("macosvm", "create", "--name", "m", "--disk", "1")
    out = run("macosvm", "start", "m", "--dry-run").stdout
    assert "isa-applesmc" in out and "BaseSystem.img" in out and "-daemonize" in out
    assert json.loads(run("macosvm", "--json", "list").stdout)[0]["state"] == "stopped"


def test_macos_app_with_basesystem(home):
    app = home / "Install macOS Catalina.app" / "Contents" / "SharedSupport"
    app.mkdir(parents=True)
    (app / "BaseSystem.dmg").write_bytes(b"x")
    e = json.loads(run("macosvm", "--json", "import", str(home / "Install macOS Catalina.app")).stdout)
    assert e["kind"] == "basesystem"


def test_docker_osx_dry(home):
    out = run("macosvm", "create", "--name", "d", "--backend", "docker-osx", "--dry-run").stdout
    assert "sickcodes/docker-osx:sonoma" in out and "--device /dev/kvm" in out


def test_ios_firmware_flow(home):
    fw = home / "firmware"
    fw.mkdir()
    for f in ("bootkc", "dtree", "ramdisk.dmg"):
        (fw / f).write_bytes(b"x")
    run("iosvm", "import", str(fw), "--name", "fw1")
    assert json.loads(run("iosvm", "--json", "imports").stdout)[0]["patched"] is False
    (Path(os.environ["VMTOOLS_HOME"]) / "apple/ios/imports/fw1/ramdisk.tc").write_bytes(b"x")
    run("iosvm", "create", "--name", "p")
    out = run("iosvm", "start", "p", "--dry-run").stdout
    assert "-M darwin" in out and "ramdisk.tc" in out


def test_ios_rejects_incomplete_and_non_apple(home):
    (home / "fw").mkdir()
    assert run("iosvm", "import", str(home / "fw"), ok=False).returncode == 2
    from iosvm.firmware import fetch
    from vmtools.ui import Fail

    with pytest.raises(Fail):
        import shutil
        if not (shutil.which("ipsw") and shutil.which("jq")):
            raise Fail("tools missing")
        fetch(home / "o", device="iPhone17,3", source="https://evil.example/x.ipsw", darwin_vm=home, remote=True)


def test_doctor_json(home):
    for t in ("iosvm", "macosvm"):
        p = run(t, "--json", "doctor", ok=False)
        assert "summary" in json.loads(p.stdout)
