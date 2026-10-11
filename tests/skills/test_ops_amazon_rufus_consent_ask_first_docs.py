"""Rufus Skill「远程授权偏好先询问后修改」文档契约测试（QA 第三轮 E2E 问题 N7）。

事故形态：QA 两轮 E2E 中 Agent 在用户未同意时执行 `remote-consent set US --allow`，
擅自把用户的 Rufus 远程授权偏好改为允许；末条回复又声称「未改动账号或授权状态」。
旧文档只写「用户回复“允许”时调用 allowed=true」，没有写明这是改状态操作、
未设置时不能默认允许、暂不继续/未回复时不得修改，也没有切断
`RUFUS_SECRET_NOT_READY`（缺登录态）与授权偏好之间的误联想。
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL_DIRS = [
    Path("opscli/skills/templates/ops-amazon-rufus-or-alexa"),
    Path(".agents/skills/ops-amazon-rufus-or-alexa"),
]

# 本次改动涉及的文档，模板与 .agents/skills 安装副本必须逐字节一致
SYNCED_FILES = [
    "SKILL.md",
    "README.md",
    "references/rufus-mcp-workflow.md",
]


def _section(text: str, heading: str) -> str:
    """截取二级标题下的正文，直到下一个二级标题。"""
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_skill_defines_remote_consent_change_boundary(skill_dir: Path):
    """SKILL.md 必须有独立的授权修改边界小节，覆盖只在明确同意后设为允许的全部约束。"""
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    section = _section(skill_text, "远程授权偏好修改边界")

    # 明确这是改状态操作，MCP 与 CLI 两种入口都受约束
    assert "改状态操作" in section
    assert "`amazon_rufus_remote_consent_set(country, allowed=true)`" in section
    assert "CLI `amazon-rufus remote-consent set <COUNTRY> --allow`" in section
    # 设为允许的唯一前提：用户对保存并复用登录态的询问明确回复“允许”
    assert "只能在用户对“是否允许保存并复用该站点的亚马逊 Rufus 登录状态”明确回复“允许”之后执行" in section
    # 未设置不等于默认允许，必须先问
    assert "状态为 `unknown` 或 `invalid`" in section
    assert "必须先按主流程第 5 步询问并等待用户回复" in section
    assert "不得把未设置当作默认允许" in section
    # 暂不继续 / 未回复 / 回复不明确时不得设为允许
    assert "暂不继续" in section
    assert "未回复" in section
    assert "不得调用 `amazon_rufus_remote_consent_set(country, allowed=true)` 或 CLI `amazon-rufus remote-consent set <COUNTRY> --allow`" in section
    # 切断「缺登录态 → 改授权偏好」的误联想（G4 实际触发点）
    assert "`RUFUS_SECRET_NOT_READY` 表示缺少可用的亚马逊 Rufus 登录态，不是授权偏好未设置" in section
    assert "修改远程授权偏好不能解决该错误" in section
    # 如实披露：改过就不能说没改
    assert "如实说明本次是否修改过远程授权偏好" in section
    assert "不得声称“未改动账号或授权状态”" in section


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_main_flow_asks_before_setting_allow(skill_dir: Path):
    """主流程第 5、6 步必须先询问后设置，且暂不继续时停止而不是改状态。"""
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    main_flow = _section(skill_text, "主流程")

    assert "5. 如果状态为 `unknown` 或 `invalid`（含从未设置），先询问用户并等待明确回复" in main_flow
    assert "回复前不得调用 `amazon_rufus_remote_consent_set`，也不得继续后续获取步骤" in main_flow
    assert "6. 用户对第 5 步询问明确回复“允许”时，调用 `amazon_rufus_remote_consent_set(country, allowed=true)`" in main_flow
    assert "用户选择暂不继续、未回复或回复不明确时，不调用 `amazon_rufus_remote_consent_set`，保持原状态并停止本次获取" in main_flow
    assert "](#远程授权偏好修改边界)" in main_flow
    # 询问文案要让用户知道「不决定就不改」
    assert "如果暂不决定或不回复，本次获取将停止，不会修改授权设置。" in main_flow
    # 旧的无前提措辞必须移除
    assert "6. 用户回复“允许”时，调用" not in main_flow


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_cli_fallback_never_changes_remote_consent(skill_dir: Path):
    """G4 走的是 CLI 路径：CLI fallback 边界必须声明不修改远程授权偏好。"""
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    section = _section(skill_text, "CLI fallback 边界")

    assert "CLI fallback 路径不修改远程授权偏好，不得执行 CLI `amazon-rufus remote-consent set`" in section


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_workflow_reference_gates_allow_on_explicit_reply(skill_dir: Path):
    """reference 的示例命令旁必须写明前提，避免 Agent 只看示例就直接调用。"""
    workflow_text = (skill_dir / "references" / "rufus-mcp-workflow.md").read_text(encoding="utf-8")
    section = _section(workflow_text, "远程授权偏好")

    assert "保存允许（仅限用户对上述询问明确回复“允许”之后；用户暂不继续、未回复或回复不明确时不得调用）：" in section
    assert "状态为 `unknown` 或 `invalid` 时必须先询问并等待回复，不得先保存允许" in section
    assert "与远程授权偏好无关" in section
    assert "](../SKILL.md#远程授权偏好修改边界)" in section
    assert "如果暂不决定或不回复，本次获取将停止，不会修改授权设置。" in section
    assert "| `amazon_rufus_remote_consent_set` | 保存允许或拒绝远程授权偏好；允许只能在用户明确回复“允许”后保存 |" in workflow_text


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.parts[0])
def test_readme_points_to_consent_boundary(skill_dir: Path):
    """README 安全小节必须提示授权偏好修改边界。"""
    readme_text = (skill_dir / "README.md").read_text(encoding="utf-8")
    section = _section(readme_text, "报告与安全")

    assert "明确回复“允许”后才能保存为允许" in section
    assert "](SKILL.md#远程授权偏好修改边界)" in section


@pytest.mark.parametrize("relative", SYNCED_FILES)
def test_template_and_installed_copy_are_byte_identical(relative: str):
    """模板与 .agents/skills 安装副本逐字节一致，避免两份文档约束不同。"""
    template = SKILL_DIRS[0] / relative
    installed = SKILL_DIRS[1] / relative

    assert template.read_bytes() == installed.read_bytes()
