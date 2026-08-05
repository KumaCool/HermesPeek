from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "hermes-peek-preview" / "SKILL.md"
REFERENCE = ROOT / "skills" / "hermes-peek-preview" / "references" / "delivery-contract.md"


def _content() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_preview_skill_has_valid_frontmatter_and_reference() -> None:
    raw = _content()
    assert raw.startswith("---\n")
    match = re.match(r"---\n(.*?)\n---\n(.+)", raw, re.DOTALL)
    assert match
    metadata = yaml.safe_load(match.group(1))
    assert metadata["name"] == "hermes-peek-preview"
    assert metadata["description"]
    assert match.group(2).strip()
    assert REFERENCE.is_file()


def test_preview_skill_defines_trigger_and_near_miss_boundaries() -> None:
    text = _content()
    for phrase in ("发我看下", "给我看文档", "预览文件", "上下文唯一", "给我看下"):
        assert phrase in text
    for phrase in ("修改", "总结", "解释", "在哪里", "复制到聊天"):
        assert phrase in text


def test_preview_skill_defines_file_resolution_without_guessing() -> None:
    text = _content()
    assert "唯一" in text
    assert "多匹配" in text
    assert "无明确目标" in text
    assert "不要从 Git diff、修改时间或整个工作区猜测" in text


def test_preview_skill_defines_single_tool_and_completion_semantics() -> None:
    text = _content()
    assert "只调用一次 `hermes_peek_send_preview`" in text
    assert "成功" in text and "`NO_REPLY`" in text
    assert "失败" in text and "简短" in text
    assert "不要自动改用 `terminal`" in text
