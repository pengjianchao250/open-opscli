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
    "ops-dashboard-ai-bridge": "1.0.26",
}
SKILL_LIST_DESCRIPTIONS = {
    "ops-dashboard-data-analysis": "只读分析当前仪表盘的趋势、对比、异常、排名、贡献和业务原因。",
    "ops-dashboard-ai-bridge": "按用户目标新增或调整图表。Skill 负责流程，页面工具负责执行与返回结果。",
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


def test_dashboard_bridge_routes_intents_without_forcing_one_creation_tool():
    """编辑 Skill 必须按意图选择流程，不得把所有请求收敛为单一批量工具。"""
    bridge_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    skill = (bridge_dir / "SKILL.md").read_text(encoding="utf-8")
    standards = (bridge_dir / "references" / "dashboard-operation-standards.md").read_text(
        encoding="utf-8"
    )
    contract = (bridge_dir / "references" / "dashboard-tool-contract.md").read_text(
        encoding="utf-8"
    )

    assert skill.count("## 意图路由") == 1
    routing = skill.split("## 意图路由", 1)[1].split("## 新建图表", 1)[0]
    for intent in (
        "场景分析建图",
        "明确新建图表",
        "修改已有图表",
        "分析主题、总览、趋势、对比或复盘目标",
        "创建、添加、批量创建",
        "移动、改名、换数据集、增删替换或重排字段",
    ):
        assert intent in skill
    assert "禁止新建图表代替修改" in routing

    creation = skill.split("## 新建图表", 1)[1].split("## 修改已有图表", 1)[0]
    assert "未要求数据集或字段" in creation
    assert "未配置图表" in creation
    assert "指定数据集时" in creation
    assert "指定字段、填充方式" in creation
    assert "dashboard_editor_batch_create_charts" in creation
    assert "dashboard_editor_batch_configure_charts" in creation
    assert "不得编造 `templateUuid`" in creation
    assert "不强制使用唯一工具或固定次数" in routing
    for forbidden in ("只调用一次 `dashboard_editor_batch_create_charts`", "统一使用批量流程"):
        assert forbidden not in skill

    create_contract = contract.split("## 创建与配置合同", 1)[1].split("## 已有图表工具", 1)[0]
    assert create_contract.count('"datasetId": 101') == 2
    assert '"chart_id": "<createdChartId>"' in create_contract
    assert '"height"' in create_contract
    assert '"layout"' not in create_contract
    assert '"x"' not in create_contract
    assert '"y"' not in create_contract
    assert '"w"' not in create_contract
    for tool_name in (
        "dashboard_editor_add_component",
        "dashboard_editor_batch_create_charts",
        "dashboard_editor_batch_configure_charts",
        "dashboard_editor_add_chart_from_template",
        "dashboard_drag_move_chart",
        "dashboard_drag_set_chart_title",
        "dashboard_drag_replace_field_list",
    ):
        assert tool_name in contract
    assert "模型不计算坐标或宽度" in standards
    assert "位置和宽度由页面按计划队列处理" in standards
    assert "字段计划必须来自所选数据集在本轮返回的完整字段目录" in standards
    assert "仅为规划建议，不构成页面固定模板" in standards
    assert "用户指定类型和数量时服从用户" in standards
    assert "最终数量由目标和字段决定" in standards

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
        "时间趋势",
        "离散对象比较",
        "部分—整体且类别不超过 5–8 个",
        "多系列共同分类轴",
        "严格阶段",
        "目标、预算、阈值或 SLA",
        "记录级字段",
        "分析场景通常选 4 到 5 张",
        "不为凑数伪造关系",
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
    assert "字段写入前必须完成整批校验" in content
    assert "任一字段不合法时不得提交字段配置" in content
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
    assert "场景分析建图" in bridge
    assert "明确新建图表" in bridge
    assert "修改已有图表" in bridge
    assert "不要求切换模式" in bridge
    assert "提示切换到“数据分析”模式" not in bridge
    assert "停止页面写入" not in bridge
    assert "用户明确指向已有图表或使用移动、改名、换字段等修改动词" in bridge
    assert "修改请求必须保持图表 ID 集合不变" in bridge
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
