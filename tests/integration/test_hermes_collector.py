from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_PATH = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "collector.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("hermes_peek_collector", PLUGIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_successful_write_and_patch_are_collected_and_deduplicated(tmp_path: Path) -> None:
    collector = load_collector()
    root = tmp_path / "workspace"
    root.mkdir()
    document = root / "result.md"
    document.write_text("done", encoding="utf-8")
    spool = tmp_path / "spool"

    collector.collect_tool_result(
        tool_name="write_file", args={"path": str(document)}, result={"success": True},
        session_id="session-1", task_id="task-1", spool_dir=spool, allowed_roots=(root,),
    )
    collector.collect_tool_result(
        tool_name="patch", args={"path": str(document)}, result='{"success": true}',
        session_id="session-1", task_id="task-1", spool_dir=spool, allowed_roots=(root,),
    )

    record = json.loads(next(spool.glob("*.json")).read_text())
    assert record == {"session_id": "session-1", "task_id": "task-1", "paths": [str(document)]}


def test_failed_unsupported_root_external_sensitive_and_missing_files_are_ignored(tmp_path: Path) -> None:
    collector = load_collector()
    root = tmp_path / "workspace"
    root.mkdir()
    valid = root / "valid.md"
    valid.write_text("ok", encoding="utf-8")
    sensitive = root / ".env"
    sensitive.write_text("SECRET=x", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    missing = root / "missing.md"
    spool = tmp_path / "spool"

    cases = [
        ("write_file", {"path": str(valid)}, {"success": False}),
        ("terminal", {"command": f"touch {valid}"}, {"success": True}),
        ("write_file", {"path": str(sensitive)}, {"success": True}),
        ("patch", {"path": str(outside)}, {"success": True}),
        ("write_file", {"path": str(missing)}, {"success": True}),
    ]
    for tool, args, result in cases:
        collector.collect_tool_result(
            tool_name=tool, args=args, result=result, session_id="s", task_id="t",
            spool_dir=spool, allowed_roots=(root,),
        )
    assert not spool.exists() or not list(spool.iterdir())


def test_patch_payload_extracts_each_updated_file_but_not_deleted_file(tmp_path: Path) -> None:
    collector = load_collector()
    root = tmp_path / "workspace"
    root.mkdir()
    first = root / "a.py"
    second = root / "b.py"
    deleted = root / "gone.py"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    spool = tmp_path / "spool"
    patch_text = f"""*** Begin Patch
*** Update File: {first}
@@
-a
+A
*** Add File: {second}
+b
*** Delete File: {deleted}
*** End Patch"""

    collector.collect_tool_result(
        tool_name="patch", args={"patch": patch_text}, result={"success": True},
        session_id="s", task_id="", spool_dir=spool, allowed_roots=(root,),
    )
    record = json.loads(next(spool.glob("*.json")).read_text())
    assert record["paths"] == sorted([str(first), str(second)])


def test_plugin_registers_supported_hooks() -> None:
    package = PLUGIN_PATH.parent
    spec = importlib.util.spec_from_file_location(
        "hermes_peek_plugin", package / "__init__.py",
        submodule_search_locations=[str(package)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    hooks: list[tuple[str, object]] = []

    class Context:
        def register_hook(self, name, callback):
            hooks.append((name, callback))

    module.register(Context())
    assert [name for name, _ in hooks] == ["post_tool_call", "final_message_actions"]
