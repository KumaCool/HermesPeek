from __future__ import annotations

import shutil
from pathlib import Path


INTEGRATION = Path(__file__).resolve().parents[2] / "integrations" / "hermes"


def install(target_home: Path) -> None:
    plugin = target_home / "plugins" / "hermes-peek"
    hook = target_home / "hooks" / "hermes-peek"
    plugin.mkdir(parents=True, exist_ok=True)
    hook.mkdir(parents=True, exist_ok=True)
    for name in ("plugin.yaml", "__init__.py", "collector.py"):
        shutil.copy2(INTEGRATION / name, plugin / name)
    for name in ("HOOK.yaml", "handler.py"):
        shutil.copy2(INTEGRATION / name, hook / name)


def uninstall(target_home: Path) -> None:
    shutil.rmtree(target_home / "plugins" / "hermes-peek", ignore_errors=True)
    shutil.rmtree(target_home / "hooks" / "hermes-peek", ignore_errors=True)


def test_install_and_uninstall_in_temporary_hermes_home(tmp_path: Path) -> None:
    home = tmp_path / "hermes-home"
    config = home / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("plugins:\n  enabled: []\n", encoding="utf-8")
    before = config.read_bytes()

    install(home)
    assert (home / "plugins/hermes-peek/plugin.yaml").exists()
    assert (home / "plugins/hermes-peek/collector.py").exists()
    assert (home / "hooks/hermes-peek/HOOK.yaml").exists()
    assert (home / "hooks/hermes-peek/handler.py").exists()
    assert config.read_bytes() == before

    uninstall(home)
    assert not (home / "plugins/hermes-peek").exists()
    assert not (home / "hooks/hermes-peek").exists()
    assert config.read_bytes() == before
