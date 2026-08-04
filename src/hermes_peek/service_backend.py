from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from .lifecycle import LifecycleError

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
PortProbe = Callable[[str, int], dict[str, Any]]
HealthProbe = Callable[[str], dict[str, Any]]


def _port_probe(host: str, port: int) -> dict[str, Any]:
    """Conservative listener probe; production PID attribution is delegated to ss."""
    try:
        with socket.create_connection((host, port), timeout=0.25):
            pass
    except OSError:
        return {"listening": False, "address": None, "pid": None}
    result = subprocess.run(("ss", "-H", "-ltnp", f"sport = :{port}"), text=True,
                            capture_output=True, check=False)
    line = (result.stdout or "").splitlines()
    text = line[0] if line else f"{host}:{port}"
    pid = None
    if "pid=" in text:
        try:
            pid = int(text.split("pid=", 1)[1].split(",", 1)[0])
        except ValueError:
            pass
    address = text.split()[3] if len(text.split()) > 3 else f"{host}:{port}"
    return {"listening": True, "address": address, "pid": pid}


def _health_probe(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            payload = json.loads(response.read(4096))
            return {"ok": response.status == 200 and payload.get("status") == "ok", "status": response.status}
    except (OSError, ValueError, urllib.error.URLError):
        return {"ok": False, "status": None}


class SystemdUserBackend:
    """Explicit backend which never falls back to an unmanaged process."""

    def __init__(self, runner: Runner, *, port_probe: PortProbe = _port_probe,
                 health_probe: HealthProbe = _health_probe, host: str = "127.0.0.1",
                 port: int = 8765) -> None:
        self.runner = runner
        self.port_probe = port_probe
        self.health_probe = health_probe
        self.host = host
        self.port = port

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.runner(("systemctl", "--user", *args))
        if result.returncode:
            raise LifecycleError("systemd user backend unavailable")
        return result

    def preflight(self) -> None:
        self._run("show-environment")
        self.preflight_port()

    def preflight_port(self) -> None:
        occupant = self.port_probe(self.host, self.port)
        service = self.status()
        pid = self.pid()
        if occupant.get("listening") and (not service["active"] or occupant.get("pid") != pid):
            raise LifecycleError("service port is occupied by an unrelated process")

    def start(self) -> None:
        self._run("start", "hermes-peek.service")

    def stop(self) -> None:
        self._run("stop", "hermes-peek.service")

    def restart(self) -> None:
        self._run("restart", "hermes-peek.service")

    def status(self) -> dict[str, bool]:
        active = self.runner(("systemctl", "--user", "is-active", "hermes-peek.service"))
        enabled = self.runner(("systemctl", "--user", "is-enabled", "hermes-peek.service"))
        return {"active": active.returncode == 0, "enabled": enabled.returncode == 0}

    def pid(self) -> int:
        result = self.runner(("systemctl", "--user", "show", "hermes-peek.service", "--property=MainPID", "--value"))
        try:
            return int((result.stdout or "0").strip()) if result.returncode == 0 else 0
        except ValueError:
            return 0

    def inspect(self) -> dict[str, Any]:
        state = self.status(); pid = self.pid(); port = self.port_probe(self.host, self.port)
        health = self.health_probe(f"http://{self.host}:{self.port}/healthz")
        return {**state, "pid": pid, "port": port, "health": health}

    def verify_running(self) -> dict[str, Any]:
        result = self.inspect()
        address = str(result["port"].get("address") or "")
        loopback = address.startswith("127.") or address.startswith("[::1]") or address.startswith("::1")
        if not (result["active"] and result["pid"] > 0 and result["port"].get("listening")
                and result["port"].get("pid") == result["pid"] and loopback and result["health"].get("ok")):
            raise LifecycleError("service failed PID, loopback port, or health verification")
        return result

    def verify_stopped(self) -> dict[str, Any]:
        result = self.inspect()
        if result["active"] or result["pid"] != 0 or result["port"].get("listening"):
            raise LifecycleError("service PID or listening port did not exit")
        return result

    def logs(self) -> str:
        result = self.runner(("journalctl", "--user", "-u", "hermes-peek.service", "--no-pager"))
        if result.returncode:
            raise LifecycleError("service logs unavailable")
        return result.stdout
