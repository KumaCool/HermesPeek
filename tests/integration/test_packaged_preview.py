from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_stage_plan_records_offline_acceptance_without_claiming_live_telegram() -> None:
    plan = (ROOT / "docs" / "plan" / "04-conversational-preview-delivery-rollout.md").read_text()
    assert "TASK 9.6 | 全量离线与新会话验收 | `OFFLINE_ACCEPTED`" in plan
    assert "TASK 9.7 | 真实 Telegram 单消息验收 | `BLOCKED_PENDING_APPROVAL`" in plan
    assert "离线验收不得冒充真实 Telegram" in plan


def test_built_wheel_contains_skill_reference_and_plugin_runtime(tmp_path: Path) -> None:
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "hermes_peek/skills/hermes-peek-preview/SKILL.md" in names
    assert "hermes_peek/skills/hermes-peek-preview/references/delivery-contract.md" in names
    assert "hermes_peek/hermes_plugin/preview_tool.py" in names


def test_fresh_process_discovers_installed_skill_and_registered_tool(tmp_path: Path) -> None:
    hermes_home = tmp_path / "profile"
    plugin = hermes_home / "plugins" / "hermes-peek"
    skill = hermes_home / "skills" / "hermes-peek-preview"
    plugin.mkdir(parents=True); skill.mkdir(parents=True)
    for name in ("__init__.py", "collector.py", "handler.py", "preview_tool.py"):
        (plugin / name).write_bytes((ROOT / "src" / "hermes_peek" / "hermes_plugin" / name).read_bytes())
    (skill / "SKILL.md").write_bytes((ROOT / "skills" / "hermes-peek-preview" / "SKILL.md").read_bytes())
    script = """
import importlib.util, json, pathlib, sys
home=pathlib.Path(sys.argv[1]); package=home/'plugins'/'hermes-peek'
spec=importlib.util.spec_from_file_location('fresh_preview_plugin', package/'__init__.py', submodule_search_locations=[str(package)])
module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
class Context:
 def __init__(self): self.tools=[]; self.hooks=[]
 def register_hook(self,name,callback): self.hooks.append(name)
 def register_tool(self,**kwargs): self.tools.append(kwargs['name'])
ctx=Context(); module.register(ctx)
print(json.dumps({'skill': (home/'skills'/'hermes-peek-preview'/'SKILL.md').is_file(), 'tools':ctx.tools, 'hooks':ctx.hooks}))
"""
    result = subprocess.run([sys.executable, "-c", script, str(hermes_home)], cwd=tmp_path,
                            check=True, capture_output=True, text=True)
    discovered = json.loads(result.stdout)
    assert discovered["skill"] is True
    assert discovered["tools"] == ["hermes_peek_send_preview"]
    assert discovered["hooks"] == ["post_tool_call", "final_message_actions"]
