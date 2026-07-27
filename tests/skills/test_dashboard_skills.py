"""仪表盘双 Skills 模板契约测试。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from opscli.skills.manager import SkillsManager
from opscli.skills.packaging import selected_skill_names


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "opscli" / "skills" / "templates"
SKILL_VERSIONS = {
    "ops-dashboard-data-analysis": "1.0.5",
    "ops-dashboard-ai-bridge": "1.0.17",
}
SKILL_LIST_DESCRIPTIONS = {
    "ops-dashboard-data-analysis": "只读分析当前仪表盘的趋势、对比、异常、排名、贡献和业务原因。",
    "ops-dashboard-ai-bridge": "按用户目标新增或调整仪表盘图表，并在每次页面写入后核验结果。",
}


def _frontmatter_value(skill_md: Path, key: str) -> str:
    """读取 SKILL.md 顶层 frontmatter 字段。"""
    content = skill_md.read_text(encoding="utf-8")
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", content)
    assert match is not None, f"{skill_md} 缺少 frontmatter.{key}"
    return match.group(1).strip().strip('"\'')


def _listed_description(description: str) -> str:
    """按 SkillsManager 的列表规则生成预期简介。"""
    return description[:30] + ("…" if len(description) > 30 else "")


@pytest.mark.parametrize(("skill_name", "version"), SKILL_VERSIONS.items())
def test_dashboard_skill_metadata_is_consistent(skill_name: str, version: str):
    """目录、frontmatter 与 VERSION.json 的名称和版本必须一致。"""
    skill_dir = TEMPLATES_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    version_payload = json.loads((skill_dir / "data" / "VERSION.json").read_text(encoding="utf-8"))

    assert skill_md.exists()
    assert (skill_dir / "agents" / "openai.yaml").exists()
    assert _frontmatter_value(skill_md, "name") == skill_name
    assert _frontmatter_value(skill_md, "version").lstrip("vV") == version
    assert version_payload == {"name": skill_name, "version": f"v{version}"}


def test_dashboard_bridge_keeps_progressive_references():
    """Bridge 必须保留三份渐进加载规范并使用新 Skill 名称。"""
    skill_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    references = {
        "bridge-result-protocol.md",
        "dashboard-operation-standards.md",
        "tool-flow.md",
    }

    assert {path.name for path in (skill_dir / "references").glob("*.md")} == references
    content = "\n".join(path.read_text(encoding="utf-8") for path in skill_dir.rglob("*.md"))
    assert "dashboard_session_get_context" in content
    assert "dashboard-tools.v2" in content
    assert not re.search(r"(?<!ops-)dashboard-ai-bridge", content)


def test_dashboard_bridge_declares_batch_creation_contract():
    """组合创建必须先读字段，再使用统一数据集一次批量创建。"""
    skill_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    content = "\n".join(path.read_text(encoding="utf-8") for path in skill_dir.rglob("*.md"))

    assert "dashboard_session_get_dataset_fields" in content
    assert "dashboard_editor_batch_create_charts" in content
    assert "同一个数据集" in content
    assert "未指定类型的默认组合" in content
    assert "增长/机会" in content
    assert "营销/转化" in content
    assert "营销/转化组合固定为 5 张" in content
    assert "不得缩减为单图或部分组合" in content
    assert "禁止调用逐字段写工具" in content
    assert "禁止先创建空图再试字段" in content
    assert "供应链" in content
    assert "问题/售后" in content
    assert "性能/健康" in content
    assert "部门兜底" in content


def test_dashboard_bridge_declares_balanced_marketing_layout_contract():
    """营销默认组合必须冻结精确五型、动态布局、字段基数和逐张核验。"""
    skill_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    content = "\n".join(
        path.read_text(encoding="utf-8") for path in skill_dir.rglob("*.md")
    )

    assert (
        "`indicator`、`pie_circle`、`combo_bar_line`、`hbar_basic`、`detail_table`"
        in content
    )
    assert "summaryWidth = floor(gridColumn / 3)" in content
    assert '`{"w": summaryWidth, "h": 16}`' in content
    assert '`{"w": gridColumn - summaryWidth, "h": 16}`' in content
    assert '`{"w": gridColumn, "h": 30}`' in content
    assert "只调用一次 `dashboard_editor_batch_create_charts`" in content
    assert "x+w=gridColumn" in content
    assert "`indicator` 只配置 1 个度量" in content
    assert "`pie_circle` 只配置 1 个类别维度和 1 个度量" in content
    assert "逐张核验精确 `chartId/viewType/title/layout/fieldLists`" in content
    assert "只核验聚合 `chartIds/changed/refreshed` 不足以完成交付" in content
    assert "不得先调用 `dashboard_drag_select_chart`" in content


def test_dashboard_bridge_requires_selection_tool_for_real_candidates():
    """多个真实候选必须通过人在回路选择工具确认，禁止正文代替交互。"""
    skill_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    content = "\n".join(path.read_text(encoding="utf-8") for path in skill_dir.rglob("*.md"))

    assert "ask_user_question" in content
    assert "2 到 4 个真实候选" in content
    assert "禁止只在正文中列选项" in content
    assert "替用户选择" in content
    assert "页面处于编辑偏好时" in content
    assert "不调用 `ops-dataset-query` 获取真实数据" in content


def test_dashboard_bridge_declares_field_roles_and_targeted_chart_mutations():
    """Bridge 应约束字段角色，并声明标题、局部样式和位置工具。"""
    skill_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    content = "\n".join(path.read_text(encoding="utf-8") for path in skill_dir.rglob("*.md"))

    assert "真实角色" in content
    assert "dashboard_drag_set_chart_title" in content
    assert "dashboard_drag_patch_chart_style" in content
    assert "dashboard_drag_move_chart" in content
    assert "gridColumn" in content
    assert "不硬编码" in content


def test_dashboard_skills_declare_runtime_and_query_boundaries():
    """两个 Skill 必须声明页面上下文、查询依赖和无上下文停止策略。"""
    analysis = (TEMPLATES_DIR / "ops-dashboard-data-analysis" / "SKILL.md").read_text(encoding="utf-8")
    bridge = (TEMPLATES_DIR / "ops-dashboard-ai-bridge" / "SKILL.md").read_text(encoding="utf-8")

    for content in (analysis, bridge):
        assert "dashboard_session_get_context" in content
        assert "ops-dataset-query" in content
        assert "仪表盘编辑页" in content
        assert "停止" in content
    assert "ops-dashboard-ai-bridge" in analysis
    assert "禁止选择或修改图表" in analysis
    assert "不得组合任何页面写能力" in analysis


def test_dashboard_skills_do_not_embed_direct_network_clients_or_local_paths():
    """模板不得携带直连网络命令、真实 URL 或本机绝对路径。"""
    contents = []
    for skill_name in SKILL_VERSIONS:
        skill_dir = TEMPLATES_DIR / skill_name
        contents.extend(path.read_text(encoding="utf-8") for path in skill_dir.rglob("*") if path.suffix in {".md", ".yaml", ".json"})
    content = "\n".join(contents)

    assert not re.search(r"https?://", content, flags=re.IGNORECASE)
    assert not re.search(r"(?i)\b(?:curl|wget)\s+", content)
    assert not re.search(r"(?i)\b(?:requests|httpx)\.", content)
    assert not re.search(r"[A-Za-z]:[\\/]", content)
    assert "/Users/" not in content
    assert "userEmail" not in content
    assert "query.from.table" not in content


def test_dashboard_skills_are_discoverable_and_installable(tmp_path: Path):
    """通用 SkillsManager 应能发现并完整安装两个模板。"""
    manager = SkillsManager(registry_path=tmp_path / "registry.json")
    templates = {item["name"]: item for item in manager.list_templates()}

    for skill_name, version in SKILL_VERSIONS.items():
        assert templates[skill_name]["version"] == f"v{version}"
        assert templates[skill_name]["description"] == _listed_description(SKILL_LIST_DESCRIPTIONS[skill_name])
        result = manager.install(skill_name, skills_dir=str(tmp_path / "skills"))
        installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
        assert (installed_path / "SKILL.md").exists()
        assert (installed_path / "agents" / "openai.yaml").exists()
        assert not any(
            "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
            for path in installed_path.rglob("*")
        )

    bridge_path = tmp_path / "skills" / "ops-dashboard-ai-bridge"
    assert (bridge_path / "references" / "tool-flow.md").exists()


def test_dashboard_skills_follow_release_profile_matrix():
    """Python 与完整二进制包含模板，最小二进制必须排除。"""
    expected = set(SKILL_VERSIONS)

    wheel_skills = set(selected_skill_names(profile="python-release", artifact="wheel", templates_dir=TEMPLATES_DIR))
    full_binary_skills = set(selected_skill_names(profile="binary-full", artifact="binary", templates_dir=TEMPLATES_DIR))
    minimal_binary_skills = set(selected_skill_names(profile="binary-minimal", artifact="binary", templates_dir=TEMPLATES_DIR))

    assert expected <= wheel_skills
    assert expected <= full_binary_skills
    assert expected.isdisjoint(minimal_binary_skills)
