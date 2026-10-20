"""Docker-OSX backend (sickcodes/docker-osx): the route in
https://dev.to/ianito/how-to-emulate-ios-on-linux-with-docker-4gj3 — QEMU+KVM inside a container,
whose image fetches the recovery image from Apple's servers on first boot. Runs on rootless Docker
(`--device /dev/kvm`); the display is X11 (Xwayland) passthrough, SSH is published on localhost.
The container is kept between runs (`docker start`), so the installed disk persists.
"""

from __future__ import annotations

import os
import subprocess

from vmtools.proc import which
from vmtools.ui import EXIT_PREREQ, Fail

IMAGE = "sickcodes/docker-osx"
TAGS = {"big-sur": "big-sur", "monterey": "monterey", "ventura": "ventura", "sonoma": "sonoma", "sequoia": "sequoia",
        "catalina": "catalina", "high-sierra": "high-sierra"}


def env() -> dict[str, str]:
    e = dict(os.environ)
    e.setdefault("DOCKER_HOST", f"unix://{os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')}/docker.sock")
    return e


def docker(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    if not which("docker"):
        raise Fail("docker not found", EXIT_PREREQ, "install ~/rice-staging/r3dg0d-docker.nix (rootless Docker) and re-login")
    p = subprocess.run(["docker", *args], env=env(), capture_output=capture, text=True, check=False)
    if check and p.returncode:
        raise Fail(f"docker {args[0]} failed: {(p.stderr or p.stdout).strip()[-300:]}")
    return p


def container(name: str) -> str:
    return f"macosvm-{name}"


def run_argv(name: str, meta: dict) -> list[str]:
    tag = TAGS.get(meta.get("version", "sonoma"), meta.get("version", "sonoma"))
    return [
        "run", "-d", "--name", container(name), "--device", "/dev/kvm",
        "-p", f"127.0.0.1:{meta['ssh_port']}:10022",
        "-v", "/tmp/.X11-unix:/tmp/.X11-unix", "-e", f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
        "-e", "GENERATE_UNIQUE=true", "-e", f"RAM={meta['ram_gib']}", "-e", f"CORES={meta['cpus']}",
        "-e", "WIDTH=1920", "-e", "HEIGHT=1080",
        "-e", "MASTER_PLIST_URL=https://raw.githubusercontent.com/sickcodes/osx-serial-generator/master/config-custom.plist",
        f"{IMAGE}:{tag}",
    ]


def state(name: str) -> str:
    p = docker("inspect", "-f", "{{.State.Status}}", container(name), check=False)
    return p.stdout.strip() if p.returncode == 0 else "absent"
