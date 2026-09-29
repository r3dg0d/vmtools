"""Subprocess, PID-file and QMP helpers shared by iosvm and macosvm."""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from .ui import OUT, Fail


def run(
    argv: Sequence[str],
    *,
    check: bool = True,
    capture: bool = True,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command, echoing it under --debug and raising Fail on failure."""
    OUT.dsay("exec: " + " ".join(str(a) for a in argv))
    try:
        proc = subprocess.run(
            [str(a) for a in argv],
            check=False,
            capture_output=capture,
            text=True,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise Fail(f"{argv[0]}: command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise Fail(f"{argv[0]}: timed out after {timeout}s") from exc
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        message = f"{argv[0]} failed (exit {proc.returncode})"
        raise Fail(f"{message}: {detail}" if detail else message)
    return proc


def which(name: str) -> str | None:
    """Locate an executable on PATH. The Nix wrapper pins PATH, so a miss here
    means the component genuinely is not installed rather than not on PATH."""
    from shutil import which as _which

    return _which(name)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def read_pidfile(path: Path) -> int | None:
    """Return a live PID from a pidfile, cleaning the file up if it is stale."""
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    if pid_alive(pid):
        return pid
    try:
        path.unlink()
    except OSError:
        pass
    return None


def terminate(pid: int, timeout: float = 20.0) -> bool:
    """SIGTERM, wait, then SIGKILL. Returns True if the process is gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError as exc:
        raise Fail(f"not permitted to stop PID {pid}") from exc

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)

    OUT.warn(f"PID {pid} ignored SIGTERM; sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return False


class QMP:
    """Minimal QMP client -- enough to power a guest down and query status.

    QEMU's own python/ bindings are not shipped by the Inferno fork, and the
    handful of commands used here do not justify a dependency.
    """

    def __init__(self, path: Path, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._buf = b""

    def __enter__(self) -> "QMP":
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect(str(self.path))
        except OSError as exc:
            self.sock.close()
            self.sock = None
            raise Fail(f"cannot reach the QEMU monitor at {self.path}: {exc}") from exc
        self._read_json()  # server greeting
        self.command("qmp_capabilities")
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _read_json(self) -> dict[str, Any]:
        while True:
            newline = self._buf.find(b"\n")
            if newline >= 0:
                line, self._buf = self._buf[:newline], self._buf[newline + 1 :]
                if line.strip():
                    return json.loads(line)
                continue
            assert self.sock is not None
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Fail("the QEMU monitor closed the connection")
            self._buf += chunk

    def command(self, name: str, **arguments: Any) -> Any:
        assert self.sock is not None
        payload: dict[str, Any] = {"execute": name}
        if arguments:
            payload["arguments"] = arguments
        self.sock.sendall((json.dumps(payload) + "\r\n").encode())
        while True:
            message = self._read_json()
            if "event" in message:  # asynchronous event, not our reply
                OUT.dsay(f"qmp event: {message['event']}")
                continue
            if "error" in message:
                raise Fail(f"QMP {name}: {message['error'].get('desc', message['error'])}")
            return message.get("return")
