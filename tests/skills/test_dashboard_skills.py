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
    "ops-dashboard-ai-bridge": "1.0.31",
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
    """核心编辑规范与数据集指南分别受体积门禁约束。"""
    bridge_files = _skill_markdown("ops-dashboard-ai-bridge")
    bridge_dir = TEMPLATES_DIR / "ops-dashboard-ai-bridge"
    assert {path.name for path in (bridge_dir / "references").glob("*.md")} == {
        "dashboard-dataset-guide.md",
        "dashboard-operation-standards.md",
        "dashboard-tool-contract.md",
    }
    dataset_guide = bridge_dir / "references" / "dashboard-dataset-guide.md"
    core_files = [path for path in bridge_files if path != dataset_guide]
    assert sum(len(path.read_bytes()) for path in core_files) <= 14_500
    assert len(dataset_guide.read_bytes()) <= 13_500

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
    dataset_guide = (bridge_dir / "references" / "dashboard-dataset-guide.md").read_text(
        encoding="utf-8"
    )

    assert skill.count("## 意图路由") == 1
    routing = skill.split("## 意图路由", 1)[1].split("## 新建图表", 1)[0]
    for intent in (
        "场景分析建图",
        "明确新建图表",
        "修改已有图表",
        "分析主题、总览、趋势、对比或复盘目标",
        "明确创建、添加或批量创建",
        "移动、改名、换数据集、增删替换或重排字段",
    ):
        assert intent in skill
    assert "禁止新建图表代替修改" in routing

    creation = skill.split("## 新建图表", 1)[1].split("## 修改已有图表", 1)[0]
    assert "未要求数据集或字段" not in creation
    assert "按计划创建未配置图表" not in creation
    assert "识别用户意图" in creation
    assert "拆成 5 个不重复的问题" in creation
    assert "每项明确标题、`viewType` 和字段需求" in creation
    assert "写入前锁定恰好 5 张的有序计划" in creation
    assert "指定数量不是 5 张时先询问" in creation
    assert "不得用重复问题或无依据图表凑数" in creation
    assert "普通建图均读取 `dashboard-dataset-guide.md` 自动判断候选" in creation
    assert "未指定时筛出 1 到 3 个语义候选" in creation
    assert "已指定时作为优先候选" in creation
    assert "唯一或明显最佳时自动选定" in creation
    assert "锁定唯一数据集后读取完整字段目录" in creation
    assert "普通数据图表不得创建未配置图表" in creation
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
    assert "没有业务场景固定组合或兜底" in standards
    assert "用户指定的类型或标题必须纳入计划" in standards
    assert "恰好 5 张是创建硬门禁" in standards
    assert "未确认不写入" in creation
    assert "字段无法支撑 5 张有意义的图表时询问或停止" in standards
    assert "不得重复问题、无依据凑数、少建或多建" in standards
    assert "普通新建都先用 `dashboard-dataset-guide.md` 按意图自动判断语义候选" in standards
    assert "4 到 6" not in skill + standards + dataset_guide + contract
    assert "不存在默认图表组合、默认数量或业务分类兜底" not in standards
    assert "场景组合模板" not in skill + standards + dataset_guide + contract
    assert "分析场景通常选 4 到 5 张" not in standards
    assert "指标卡只配置 1 个度量" not in standards
    assert "环形图只配置 1 个类别维度和 1 个度量" not in standards

    assert "dashboard-dataset-guide.md" in skill
    assert "指南不代表授权或可用性" in standards
    assert "推荐图表只作候选，不构成默认组合" in standards

    chart_selection = standards.split("## 图表选择", 1)[1].split("## 修改安全", 1)[0]
    expected_view_types = {
        "bar_basic",
        "bar_stacked",
        "bar_stacked_percent",
        "hbar_basic",
        "hbar_stacked",
        "hbar_stacked_percent",
        "line_basic",
        "area_basic",
        "area_stacked",
        "pie_basic",
        "pie_circle",
        "combo_bar_line",
        "combo_bar_line_stacked",
        "combo_bar_line_group",
        "metric_trend",
        "detail_table",
        "pivot_table",
        "crosstab_table",
        "indicator",
        "progress_chart",
        "funnel_basic",
    }
    assert set(re.findall(r"`([a-z][a-z0-9_]*)`", chart_selection)) == expected_view_types
    for unavailable_view_type in (
        "line_stacked",
        "scatter_basic",
        "radar_basic",
        "combo_bar_line_stacked_percent",
        "indicator_trend",
        "matrix_table",
    ):
        assert f"`{unavailable_view_type}`" not in chart_selection
    for chart_trait in (
        "每张图只回答一个明确问题",
        "分类比较或排名",
        "长标签、类别较多或排名用横向条形",
        "绝对构成",
        "占比结构",
        "横轴必须有序",
        "部分与整体",
        "规模与比率",
        "记录明细与精确值",
        "行列交叉比较",
        "真实目标、预算、阈值或 SLA",
        "同一流程和群体",
        "用户指定类型不兼容时不得静默替换",
    ):
        assert chart_trait in chart_selection


def test_dashboard_bridge_dataset_guide_keeps_runtime_metadata_as_gate():
    """数据集导航只提供语义候选，执行仍以页面实时元数据为准。"""
    guide = (
        TEMPLATES_DIR
        / "ops-dashboard-ai-bridge"
        / "references"
        / "dashboard-dataset-guide.md"
    ).read_text(encoding="utf-8")

    for boundary in (
        "本指南只生成语义候选",
        "未返回的候选不可使用",
        "不可据此手写字段 key、ID 或类型",
        "不照搬数据集推荐组成固定套图",
        "待本表补充",
    ):
        assert boundary in guide

    for dataset_name in (
        "即时综合数据集",
        "SP+SD+SB广告数据集",
        "客诉分析数据集",
        "ASIN运营事件数据集",
        "海运在途SKU明细",
        "SKU仓租库龄明细",
        "亚马逊SC设备流量转化率数据集",
        "活动数据集",
        "Shopify退货退款",
    ):
        assert dataset_name in guide

    for view_type in (
        "crosstab_table",
        "metric_trend",
        "bar_stacked_percent",
        "detail_table",
        "funnel_basic",
        "progress_chart",
    ):
        assert f"`{view_type}`" in guide

    for excluded_rule in ("聚合口径", "快照口径", "币种口径", "时间范围", "Top N"):
        assert excluded_rule not in guide


def test_dashboard_bridge_keeps_real_dataset_and_field_guards():
    """业务规范必须拦截猜测数据集、字段、筛选和创建后试错。"""
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _skill_markdown("ops-dashboard-ai-bridge")
    )

    assert "数据集和字段仅取本轮页面工具结果" in content
    assert "完整字段目录" in content
    assert "真实角色" in content
    assert "字段写入前必须完成整批校验" in content
    assert "任一字段不合法时不得提交字段配置" in content
    assert "VALIDATION_ERROR" in content
    assert "修正一次" in content
    assert "ask_user_question" in content
    assert "2 到 4 个真实候选" in content
    assert "中文名称、说明、业务粒度和字段覆盖" in content
    assert "完整技术标识只作精确匹配" in content
    assert "`query_component` 仅用于筛选或关联，不作图表数据源" in content
    assert "多义时询问" in content
    assert "组织角色（部门、小组、大组、销售、开发）" in content
    assert "平台、渠道、店铺、国家均独立" in content
    assert "唯一完整等值时使用原值" in content
    assert "禁止子串扩张" in content
    assert "不加默认值" in content


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
    assert (bridge_path / "references" / "dashboard-dataset-guide.md").exists()
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
