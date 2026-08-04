from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from .lifecycle import LifecycleError
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

class SystemdUserBackend:
    """Explicit backend which never falls back to an unmanaged process."""
    def __init__(self, runner: Runner) -> None: self.runner = runner
    def _run(self, *args: str):
        result = self.runner(("systemctl", "--user", *args))
        if result.returncode: raise LifecycleError("systemd user backend unavailable")
        return result
    def preflight(self) -> None: self._run("show-environment")
    def start(self) -> None: self._run("start", "hermes-peek.service")
    def stop(self) -> None: self._run("stop", "hermes-peek.service")
    def restart(self) -> None: self._run("restart", "hermes-peek.service")
    def status(self) -> dict[str, bool]:
        active = self.runner(("systemctl", "--user", "is-active", "hermes-peek.service"))
        enabled = self.runner(("systemctl", "--user", "is-enabled", "hermes-peek.service"))
        return {"active": active.returncode == 0, "enabled": enabled.returncode == 0}
    def logs(self) -> str:
        result = self.runner(("journalctl", "--user", "-u", "hermes-peek.service", "--no-pager"))
        if result.returncode: raise LifecycleError("service logs unavailable")
        return result.stdout
