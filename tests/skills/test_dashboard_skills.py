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
    "ops-dashboard-data-analysis": "1.0.6",
    "ops-dashboard-ai-bridge": "1.0.23",
}
SKILL_LIST_DESCRIPTIONS = {
    "ops-dashboard-data-analysis": "只读分析当前仪表盘的趋势、对比、异常、排名、贡献和业务原因。",
    "ops-dashboard-ai-bridge": "按用户目标新增或调整仪表盘图表。业务规则和操作流程由本 Skill 负责，页面工具只负责执行与返回结果。",
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


def _skill_markdown(skill_name: str) -> list[Path]:
    """返回 Skill 内全部 Markdown，供大小和冲突门禁复用。"""
    return sorted((TEMPLATES_DIR / skill_name).rglob("*.md"))


@pytest.mark.parametrize(("skill_name", "version"), SKILL_VERSIONS.items())
def test_dashboard_skill_metadata_is_consistent(skill_name: str, version: str):
    """目录、frontmatter 与 VERSION.json 的名称和版本必须一致。"""
    skill_dir = TEMPLATES_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"
    version_payload = json.loads(
        (skill_dir / "data" / "VERSION.json").read_text(encoding="utf-8")
    )

    assert skill_md.exists()
    assert (skill_dir / "agents" / "openai.yaml").exists()
    assert _frontmatter_value(skill_md, "name") == skill_name
    assert _frontmatter_value(skill_md, "version").lstrip("vV") == version
    assert version_payload == {"name": skill_name, "version": f"v{version}"}


def test_dashboard_skills_keep_compact_progressive_content():
    """编辑规范合并后不得膨胀，分析 Skill 必须保持短小。"""
    bridge_files = _skill_markdown("ops-dashboard-ai-bridge")
    bridge_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    assert {path.name for path in (bridge_dir / "references").glob("*.md")} == {
        "dashboard-operation-standards.md",
        "dashboard-tool-contract.md",
    }
    assert sum(len(path.read_bytes()) for path in bridge_files) <= 14_000

    analysis = (
        TEMPLATES_DIR / "ops-dashboard-data-analysis" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert len([line for line in analysis.splitlines() if line.strip()]) <= 50


def test_dashboard_bridge_has_one_batch_creation_flow():
    """新建图表只保留一个批量流程，参数不再包含布局坐标或宽度。"""
    bridge_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    skill = (bridge_dir / "SKILL.md").read_text(encoding="utf-8")
    standards = (bridge_dir / "references" / "dashboard-operation-standards.md").read_text(
        encoding="utf-8"
    )
    contract = (bridge_dir / "references" / "dashboard-tool-contract.md").read_text(
        encoding="utf-8"
    )

    assert skill.count("## 新建图表") == 1
    creation = skill.split("## 新建图表", 1)[1].split("## 修改已有图表", 1)[0]
    assert "调用一次 `dashboard_session_get_dataset_fields`" in creation
    assert "有序 `charts`" in creation
    assert "已确认的 `datasetId`" in creation
    assert "只调用一次 `dashboard_editor_batch_create_charts`" in creation
    assert "数据集绑定、字段配置和刷新" in creation
    assert "结束本次新建流程" in creation
    for forbidden in (
        "dashboard_editor_add_component",
        "dashboard_drag_select_dataset",
        "dashboard_drag_move_chart",
    ):
        assert forbidden not in creation

    batch_contract = contract.split("## 批量创建合同", 1)[1].split("## 已有图表工具", 1)[0]
    assert '"height"' in batch_contract
    assert '"layout"' not in batch_contract
    assert '"x"' not in batch_contract
    assert '"y"' not in batch_contract
    assert '"w"' not in batch_contract
    assert "模型不计算坐标或宽度" in standards
    assert "页面按计划队列自动落位" in standards
    assert "字段计划必须来自所选数据集在本轮返回的完整字段目录" in standards
    assert "仅为规划建议，不构成页面固定模板" in standards

    chart_selection = standards.split("## 图表选择", 1)[1].split("## 修改安全", 1)[0]
    priorities = (
        "增长与机会",
        "营销与转化",
        "供应链执行",
        "问题与售后",
        "绩效与健康监控",
        "部门工作台兜底",
    )
    assert [chart_selection.index(priority) for priority in priorities] == sorted(
        chart_selection.index(priority) for priority in priorities
    )
    for category in (
        "销售",
        "市场",
        "广告",
        "流量",
        "活动",
        "库存",
        "物流",
        "退款",
        "客服",
        "监控提醒",
        "平台报告",
        "运营监控",
        "部门数据",
    ):
        assert category in chart_selection

    expected_view_types = {
        "metric_trend",
        "hbar_basic",
        "hbar_stacked_percent",
        "crosstab_table",
        "indicator",
        "combo_bar_line",
        "bar_stacked_percent",
        "pivot_table",
        "detail_table",
        "bar_stacked",
        "line_basic",
        "bar_basic",
        "progress_chart",
        "funnel_basic",
        "pie_circle",
        "hbar_stacked",
    }
    assert set(re.findall(r"`([a-z][a-z0-9_]*)`", chart_selection)) == expected_view_types
    for unavailable_view_type in (
        "scatter_basic",
        "radar_basic",
        "indicator_trend",
        "matrix_table",
    ):
        assert f"`{unavailable_view_type}`" not in chart_selection
    for field_guard in (
        "日期或连续时间字段",
        "离散对象和数值指标",
        "部分—整体且类别不超过 5–8 个",
        "多系列共同分类轴",
        "同群体严格有序阶段",
        "目标、预算、阈值或 SLA",
        "记录主键和处理字段",
        "不为凑满 5 张伪造分析关系",
    ):
        assert field_guard in chart_selection


def test_dashboard_bridge_keeps_real_dataset_and_field_guards():
    """业务规范必须拦截猜测字段和创建后试错。"""
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _skill_markdown("ops-dashboard-ai-bridge")
    )

    assert "数据集和字段必须来自本轮页面工具结果" in content
    assert "完整字段目录" in content
    assert "真实角色" in content
    assert "整批计划任一字段不合法时不得创建任何图表" in content
    assert "VALIDATION_ERROR" in content
    assert "修正一次" in content
    assert "ask_user_question" in content
    assert "2 到 4 个真实候选" in content


def test_dashboard_select_tool_and_skill_boundaries_do_not_conflict():
    """选图只属于 editor，编辑和分析 Skill 不得混用流程。"""
    bridge = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _skill_markdown("ops-dashboard-ai-bridge")
    )
    analysis = (
        TEMPLATES_DIR / "ops-dashboard-data-analysis" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "dashboard_editor_select_chart" in bridge
    assert "dashboard_drag_select_chart" not in bridge
    assert "opscli query" not in bridge
    assert "ops-dataset-query" in analysis
    assert "只读工具" in analysis
    assert "设置面板" in analysis
    for forbidden in (
        "dashboard_editor_",
        "dashboard_drag_",
        "selectChart",
        "ops-dashboard-ai-bridge",
    ):
        assert forbidden not in analysis


def test_dashboard_skills_do_not_embed_direct_network_clients_or_local_paths():
    """模板不得携带直连网络命令、真实 URL 或本机绝对路径。"""
    contents = []
    for skill_name in SKILL_VERSIONS:
        skill_dir = TEMPLATES_DIR / skill_name
        contents.extend(
            path.read_text(encoding="utf-8")
            for path in skill_dir.rglob("*")
            if path.suffix in {".md", ".yaml", ".json"}
        )
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
        assert templates[skill_name]["description"] == _listed_description(
            SKILL_LIST_DESCRIPTIONS[skill_name]
        )
        result = manager.install(skill_name, skills_dir=str(tmp_path / "skills"))
        installed_path = Path(result.to_dict()["installed_paths"][0]["path"])
        assert (installed_path / "SKILL.md").exists()
        assert (installed_path / "agents" / "openai.yaml").exists()
        assert not any(
            "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
            for path in installed_path.rglob("*")
        )

    bridge_path = tmp_path / "skills" / "ops-dashboard-ai-bridge"
    assert (bridge_path / "references" / "dashboard-tool-contract.md").exists()
    assert not (bridge_path / "data" / "dashboard-runtime-contract.json").exists()


def test_dashboard_skills_follow_release_profile_matrix():
    """Python 与完整二进制包含模板，最小二进制必须排除。"""
    expected = set(SKILL_VERSIONS)

    wheel_skills = set(
        selected_skill_names(
            profile="python-release", artifact="wheel", templates_dir=TEMPLATES_DIR
        )
    )
    full_binary_skills = set(
        selected_skill_names(
            profile="binary-full", artifact="binary", templates_dir=TEMPLATES_DIR
        )
    )
    minimal_binary_skills = set(
        selected_skill_names(
            profile="binary-minimal", artifact="binary", templates_dir=TEMPLATES_DIR
        )
    )

    assert expected <= wheel_skills
    assert expected <= full_binary_skills
    assert expected.isdisjoint(minimal_binary_skills)
