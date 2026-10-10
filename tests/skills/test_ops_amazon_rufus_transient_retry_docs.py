"""Rufus Skill「瞬时错误同路径重试」文档契约测试（Bug 12133）。

事故形态：OPS 网关读登录态偶发 504，旧 Skill 规定「CLI fallback 失败直接返回错误」，
Agent 一次瞬时故障就硬失败；而同类反馈中用户手动重试后全部成功。
新规则要求：对 RUFUS_PLATFORM_COOKIE_UNAVAILABLE / 旧版 RUFUS_BAD_REMOTE_JSON
同路径只重试 1 次，不切换 MCP/CLI、不触发重新登录。
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_DIRS = [
    Path("opscli/skills/templates/ops-amazon-rufus-or-alexa"),
    Path(".agents/skills/ops-amazon-rufus-or-alexa"),
]


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_skill_retries_transient_platform_cookie_error_once_on_same_path(skill_dir: Path):
    """SKILL.md 必须给出瞬时错误同路径重试 1 次的规则，且 CLI fallback 收尾措辞不再与之矛盾。"""
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    section = skill_text.split("## 瞬时错误同路径重试\n", 1)[1].split("\n## ", 1)[0]

    assert "`RUFUS_PLATFORM_COOKIE_UNAVAILABLE`" in section
    assert "`retryable=true`" in section
    assert "`RUFUS_BAD_REMOTE_JSON`" in section
    assert "重试 1 次" in section
    assert "最多重试 1 次" in section
    assert "不切换 MCP/CLI" in section
    assert "不触发 `amazon_rufus_logout`、`amazon_rufus_watch_login`" in section
    assert "不是 Amazon Rufus" in section
    # 规则边界：只覆盖登录态读取的两个错误码，旧码只说「可能」，不得外溢到报告与 headless 错误
    assert "适用错误仅限两种" in section
    assert "可能为同一接口临时不可用" in section
    assert "本规则不适用于报告下载失败、`RUFUS_REPORT_*`、`RUFUS_HEADLESS_*`" in section
    assert "仅 `RUFUS_PLATFORM_COOKIE_UNAVAILABLE` 与旧版 `RUFUS_BAD_REMOTE_JSON` 按[瞬时错误同路径重试]" in skill_text
    assert "`RUFUS_PLATFORM_COOKIE_UNAVAILABLE` 等瞬时错误" not in skill_text
    # 原「CLI fallback 失败时直接返回错误」绝对措辞会让 Agent 一错即停，必须改为先按瞬时规则重试
    assert "5. CLI fallback 失败时直接返回错误" not in skill_text
    assert "瞬时错误先按[瞬时错误同路径重试](#瞬时错误同路径重试)在 CLI 路径重试 1 次" in skill_text
    assert "瞬时错误按[瞬时错误同路径重试](#瞬时错误同路径重试)在原路径重试，不属于 CLI fallback" in skill_text


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_workflow_keeps_transient_error_out_of_login_recovery(skill_dir: Path):
    """reference 必须声明瞬时错误不进入登录采集恢复，避免误触发重新登录。"""
    workflow_text = (skill_dir / "references" / "rufus-mcp-workflow.md").read_text(encoding="utf-8")

    assert "或旧版 `RUFUS_BAD_REMOTE_JSON`（可能为同一接口临时不可用）" in workflow_text
    assert "不进入登录采集入口" in workflow_text
    assert "不进入登录采集恢复" in workflow_text
    assert "](../SKILL.md#瞬时错误同路径重试)" in workflow_text
