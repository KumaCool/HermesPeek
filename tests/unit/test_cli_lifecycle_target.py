from __future__ import annotations

from pathlib import Path

import pytest

from hermes_peek import cli
from hermes_peek.lifecycle import LifecycleError


def test_lifecycle_commands_use_committed_target_when_hermes_home_is_omitted(
    tmp_path: Path, monkeypatch
) -> None:
    committed = (tmp_path / "committed-hermes").resolve()
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: committed)

    assert cli._resolve_lifecycle_home(None) == committed


def test_explicit_mismatched_target_is_rejected_with_actionable_omit_hint(
    tmp_path: Path, monkeypatch
) -> None:
    committed = (tmp_path / "committed-hermes").resolve()
    requested = tmp_path / "wrong-hermes"
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: committed)

    with pytest.raises(LifecycleError, match="omit --hermes-home"):
        cli._resolve_lifecycle_home(requested)
