import subprocess


import pytest

from hermes_peek.lifecycle import LifecycleError
from hermes_peek.service_backend import SystemdUserBackend


class FakeRunner:
    def __init__(self, unavailable=False):
        self.commands = []
        self.unavailable = unavailable

    def __call__(self, command):
        self.commands.append(tuple(command))
        code = 1 if self.unavailable else 0
        return subprocess.CompletedProcess(command, code, "active\n", "offline" if code else "")


class ProbeRunner:
    def __init__(self, *, active=True, enabled=True, pid=321, listen="127.0.0.1:8765", health=True):
        self.commands=[]; self.active=active; self.enabled=enabled; self.pid=pid; self.listen=listen; self.health=health
    def __call__(self, command):
        command=tuple(command); self.commands.append(command)
        if "is-active" in command: return subprocess.CompletedProcess(command, 0 if self.active else 3, "active\n", "")
        if "is-enabled" in command: return subprocess.CompletedProcess(command, 0 if self.enabled else 1, "enabled\n", "")
        if "show" in command: return subprocess.CompletedProcess(command, 0, str(self.pid)+"\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

def fake_port_probe(runner):
    return lambda host, port: {"listening": bool(runner.listen), "address": runner.listen, "pid": runner.pid}

def fake_health_probe(runner):
    return lambda url: {"ok": runner.health, "status": 200 if runner.health else 503}


def test_systemd_backend_preflight_fails_without_fallback():
    runner = FakeRunner(unavailable=True)
    with pytest.raises(LifecycleError):
        SystemdUserBackend(runner).preflight()
    assert runner.commands == [("systemctl", "--user", "show-environment")]


def test_systemd_backend_exposes_service_operations():
    runner = FakeRunner()
    backend = SystemdUserBackend(runner)
    backend._run("show-environment")
    backend.start()
    backend.restart()
    backend.stop()
    assert backend.status() == {"active": True, "enabled": True}
    assert backend.logs() == "active\n"


def test_service_verification_requires_matching_pid_loopback_port_and_health():
    runner = ProbeRunner()
    result = SystemdUserBackend(runner, port_probe=fake_port_probe(runner), health_probe=fake_health_probe(runner)).verify_running()
    assert result == {"active": True, "enabled": True, "pid": 321, "port": {"listening": True, "address": "127.0.0.1:8765", "pid": 321}, "health": {"ok": True, "status": 200}}


@pytest.mark.parametrize("listen,pid,health", [("0.0.0.0:8765",321,True), ("127.0.0.1:8765",999,True), ("127.0.0.1:8765",321,False)])
def test_service_verification_rejects_public_wrong_pid_or_unhealthy_listener(listen, pid, health):
    runner = ProbeRunner(listen=listen, health=health)
    port = fake_port_probe(runner)
    if pid != runner.pid:
        port = lambda host, port: {"listening": True, "address": listen, "pid": pid}
    with pytest.raises(LifecycleError):
        SystemdUserBackend(runner, port_probe=port, health_probe=fake_health_probe(runner)).verify_running()


def test_stop_verification_requires_pid_and_port_to_exit():
    runner = ProbeRunner(active=False, enabled=True, pid=0, listen="")
    result = SystemdUserBackend(runner, port_probe=fake_port_probe(runner), health_probe=fake_health_probe(runner)).verify_stopped()
    assert result["active"] is False and result["pid"] == 0 and result["port"]["listening"] is False


def test_port_preflight_rejects_unrelated_occupant():
    runner = ProbeRunner(pid=0, listen="127.0.0.1:8765")
    with pytest.raises(LifecycleError, match="port"):
        SystemdUserBackend(runner, port_probe=lambda h,p: {"listening": True,"address":"127.0.0.1:8765","pid":777}, health_probe=fake_health_probe(runner)).preflight_port()
