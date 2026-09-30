"""Container lifecycle for Docker-Android-Pro emulators."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from vmtools.config import read_json, validate_name, write_json
from vmtools.layout import LAYOUT, ensure
from vmtools.proc import run, which
from vmtools.ui import EXIT_BACKEND, EXIT_NOT_FOUND, EXIT_STATE, OUT, Fail

from .access import require_access
from .images import DEFAULT_REPO, image_ref
from .ports import allocate, save_ports


def _state_path(name: str) -> Path:
    ensure()
    return LAYOUT.data / "android" / f"{name}.json"


def load_vm(name: str) -> dict[str, Any]:
    path = _state_path(name)
    data = read_json(path)
    if not data:
        raise Fail(f"Android VM not found: {name}", EXIT_NOT_FOUND)
    return data


def list_vms() -> list[dict[str, Any]]:
    ensure()
    out = []
    for path in sorted((LAYOUT.data / "android").glob("*.json")):
        if path.name.endswith("-ports.json") or path.name == "access.json":
            continue
        data = read_json(path, {})
        if data and data.get("name"):
            out.append(data)
    return out


def container_name(name: str) -> str:
    return f"androidvm-{name}"


def docker_pull(tag: str, repo: str = DEFAULT_REPO) -> None:
    require_access()
    if not which("docker"):
        raise Fail("docker not found", EXIT_BACKEND)
    ref = image_ref(tag, repo)
    OUT.step(f"Pulling {ref}")
    # stream pull
    proc = subprocess.run(["docker", "pull", ref], check=False)
    if proc.returncode != 0:
        raise Fail(f"docker pull failed: {ref}", EXIT_BACKEND)
    OUT.ok(f"pulled {ref}")


def create(
    name: str,
    *,
    tag: str = "emulator_15.0",
    repo: str = DEFAULT_REPO,
    device: str = "Samsung Galaxy S10",
    pull: bool = True,
) -> dict[str, Any]:
    require_access()
    name = validate_name(name)
    if _state_path(name).is_file():
        raise Fail(f"Android VM already exists: {name}", EXIT_STATE)
    if pull:
        docker_pull(tag, repo)
    viewer, adb = allocate(6080, 2)
    # bump adb away from default 5555 collisions: use 5555+offset style via second port
    # docker-android maps 5555 inside; we publish to localhost:adb
    save_ports(name, viewer, adb)
    meta = {
        "name": name,
        "container": container_name(name),
        "image": image_ref(tag, repo),
        "tag": tag,
        "repo": repo,
        "device": device,
        "viewer": f"127.0.0.1:{viewer}",
        "adb": f"127.0.0.1:{adb}",
        "volume": f"androidvm-data-{name}",
        "bind": "127.0.0.1",
    }
    write_json(_state_path(name), meta)
    OUT.ok(f"created {name} (image cached, not started)")
    OUT.note(f"Viewer {meta['viewer']}  ADB {meta['adb']}")
    return meta


def start(name: str) -> None:
    require_access()
    meta = load_vm(name)
    cname = meta["container"]
    # already running?
    r = run(["docker", "inspect", "-f", "{{.State.Running}}", cname], check=False)
    if r.returncode == 0 and r.stdout.strip() == "true":
        OUT.warn(f"{name} already running")
        return
    # remove stopped container with same name
    run(["docker", "rm", "-f", cname], check=False)
    viewer_port = meta["viewer"].split(":")[-1]
    adb_port = meta["adb"].split(":")[-1]
    # console port = adb_port - 1 when possible (emulator pairs 5554/5555)
    try:
        console_port = str(int(adb_port) - 1)
    except ValueError:
        console_port = None
    cmd = [
        "docker", "run", "-d",
        "--name", cname,
        "--device", "/dev/kvm",
        "--shm-size", "2g",
        "-e", f"EMULATOR_DEVICE={meta.get('device', 'Samsung Galaxy S10')}",
        "-e", "WEB_VNC=true",
        "-p", f"127.0.0.1:{viewer_port}:6080",
        "-p", f"127.0.0.1:{adb_port}:5555",
    ]
    if console_port and console_port != viewer_port:
        cmd.extend(["-p", f"127.0.0.1:{console_port}:5554"])
    cmd.extend([
        "-v", f"{meta['volume']}:/home/androidusr",
        meta["image"],
    ])
    OUT.vsay(" ".join(cmd))
    run(cmd, capture=True)
    OUT.ok(f"started {name}")
    OUT.note(f"GUI http://{meta['viewer']}")
    OUT.note(f"ADB  adb connect {meta['adb']}")


def stop(name: str) -> None:
    meta = load_vm(name)
    run(["docker", "stop", meta["container"]], check=False)
    OUT.ok(f"stopped {name}")


def delete(name: str, *, keep_data: bool = False) -> None:
    meta = load_vm(name)
    run(["docker", "rm", "-f", meta["container"]], check=False)
    if not keep_data:
        run(["docker", "volume", "rm", "-f", meta["volume"]], check=False)
    _state_path(name).unlink(missing_ok=True)
    ports = LAYOUT.data / "android" / f"{name}-ports.json"
    ports.unlink(missing_ok=True)
    OUT.ok(f"deleted {name}")


def status_of(name: str) -> dict[str, Any]:
    meta = load_vm(name)
    r = run(["docker", "inspect", "-f", "{{.State.Status}}", meta["container"]], check=False)
    state = r.stdout.strip() if r.returncode == 0 else "absent"
    return {**meta, "state": state}


def open_gui(name: str) -> None:
    meta = load_vm(name)
    url = f"http://{meta['viewer']}"
    subprocess.Popen(["xdg-open", url], start_new_session=True)
    OUT.ok(f"opened {url}")


def adb_connect(name: str) -> None:
    """Ensure the guest is reachable via in-container adb (reliable path).

    Host `adb connect` to the published 5555 mapping is best-effort with
    Docker-Android; the emulator often only exposes a local transport.
    """
    meta = load_vm(name)
    cname = meta["container"]
    r = run(["docker", "exec", cname, "adb", "devices"], check=False)
    if r.returncode != 0:
        raise Fail("adb inside container failed — is the VM running?", EXIT_BACKEND)
    OUT.ok(f"adb ready inside {cname}")
    OUT.note(f"use: androidvm shell {name}   (or: docker exec -it {cname} adb ...)")
    # best-effort host connect for users who want platform-tools on the host
    if which("adb"):
        host = run(["adb", "connect", meta["adb"]], check=False)
        if host.returncode == 0 and "connected" in (host.stdout + host.stderr).lower():
            OUT.note(f"host adb connect {meta['adb']} attempted")


def adb_exec(name: str, *adb_args: str, check: bool = True):
    meta = load_vm(name)
    return run(["docker", "exec", "-i", meta["container"], "adb", *adb_args], check=check)
