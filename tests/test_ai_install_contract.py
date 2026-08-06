from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGLISH_README = ROOT / "README.md"
CHINESE_README = ROOT / "README.zh-CN.md"
AGENT_GUIDE = ROOT / "AGENTS.md"
RELEASE_INSTALLER_URL = "releases/latest/download/install.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_terms(text: str, groups: tuple[tuple[str, ...], ...]) -> None:
    lowered = text.lower()
    for alternatives in groups:
        assert any(term.lower() in lowered for term in alternatives), alternatives


def test_bilingual_readmes_publish_copyable_ai_install_prompts_with_fixed_release_command() -> None:
    required_links = (
        "docs/08-one-click-ai-telegram-onboarding.md",
        "docs/06-installation-uninstallation.md",
        "docs/plan/05-one-click-ai-telegram-onboarding-rollout.md",
    )
    for path in (ENGLISH_README, CHINESE_README):
        text = read(path)
        assert "<!-- ai-install-prompt:start -->" in text
        assert "<!-- ai-install-prompt:end -->" in text
        assert "```text" in text
        assert all(link in text for link in required_links)
        assert RELEASE_INSTALLER_URL not in text
        assert "releases/download/v0.2.0/install.sh" in text
        assert_terms(
            text,
            (
                ("authoritative", "权威"),
                ("read-only discovery", "只读现场发现"),
                ("redacted plan", "脱敏计划"),
                ("restricted local file", "本机受限权限文件"),
                ("secure local input", "本机安全输入"),
                ("do not send", "不要发送"),
                ("install.sh",),
                ("hermes-peek setup",),
                ("release asset", "release 资产"),
                ("v0.2.0 release",),
            ),
        )


def test_bilingual_readmes_contain_a_complete_operator_quickstart() -> None:
    for path in (ENGLISH_README, CHINESE_README):
        text = read(path)
        assert_terms(
            text,
            (
                ("operator quickstart", "普通用户快速开始"),
                ("releases/download/v0.2.0/install.sh",),
                ("sha256sums",),
                ("hermes-peek setup",),
                ("status --json",),
                ("doctor --json",),
                ("botfather",),
                ("allowed users", "允许用户"),
                ("new hermes session", "新的 hermes 会话"),
                ("default uninstall", "默认卸载"),
                ("preview data", "preview 数据"),
                ("--purge --dry-run",),
                ("rollback", "回滚"),
                ("upgrade", "升级"),
            ),
        )


def test_repository_agent_guide_enforces_discovery_secret_confirmation_and_completion_contracts() -> None:
    text = read(AGENT_GUIDE)
    assert_terms(
        text,
        (
            ("authoritative sources",),
            ("live discovery",),
            ("redacted plan",),
            ("never ask the user to paste secrets into chat",),
            ("restricted local file",),
            ("secure local input",),
            ("every side effect",),
            ("real hermes profile",),
            ("service",),
            ("gateway restart",),
            ("telegram menu",),
            ("network",),
            ("separate confirmation",),
            ("release installer",),
            ("hermes-peek setup",),
            ("do not copy internal",),
            ("installation complete",),
            ("hermes loading complete",),
            ("telegram acceptance complete",),
            ("verification checklist",),
        ),
    )
    assert RELEASE_INSTALLER_URL not in text


def test_agent_guide_contains_no_machine_specific_or_secret_values() -> None:
    text = read(AGENT_GUIDE)
    forbidden = (
        r"/home/[A-Za-z0-9._-]+",
        r"(?<![<\w])-100\d{6,}",
        r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
        r"https://(?:preview|peek)\.(?!example\.)[A-Za-z0-9.-]+",
    )
    for pattern in forbidden:
        assert re.search(pattern, text) is None, pattern
