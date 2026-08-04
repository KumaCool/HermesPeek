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


def test_systemd_backend_preflight_fails_without_fallback():
    runner = FakeRunner(unavailable=True)
    with pytest.raises(LifecycleError):
        SystemdUserBackend(runner).preflight()
    assert runner.commands == [("systemctl", "--user", "show-environment")]


def test_systemd_backend_exposes_service_operations():
    runner = FakeRunner()
    backend = SystemdUserBackend(runner)
    backend.preflight()
    backend.start()
    backend.restart()
    backend.stop()
    assert backend.status() == {"active": True, "enabled": True}
    assert backend.logs() == "active\n"
