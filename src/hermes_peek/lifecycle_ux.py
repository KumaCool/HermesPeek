from __future__ import annotations
import json
from typing import Any
from .lifecycle import InstallPaths
from .service_backend import Runner, SystemdUserBackend

def status(paths: InstallPaths, runner: Runner) -> dict[str, Any]:
    manifest = None
    if paths.manifest_file.is_file():
        try: manifest = json.loads(paths.manifest_file.read_text(encoding="utf-8"))
        except ValueError: manifest = None
    service = SystemdUserBackend(runner).status()
    return {"schema_version": 1, "target": {"hermes_home": str(paths.hermes_home)},
            "manifest": {"present": manifest is not None}, "service": service,
            "plugin": {"installed": paths.plugin_dir.is_dir()},
            "data": {"state_directory_present": paths.state_dir.is_dir()}}

def doctor(paths: InstallPaths, runner: Runner) -> dict[str, Any]:
    report = status(paths, runner)
    checks = [{"name": "manifest", "ok": report["manifest"]["present"]},
              {"name": "service", "ok": report["service"]["active"]}]
    return {"schema_version": 1, "checks": checks,
            "suggestions": ["run setup" for check in checks if not check["ok"]]}
