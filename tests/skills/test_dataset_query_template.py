"""ops-dataset-query 模板结构守卫：规划器「内核唯一」切换后的不变量。

2026-09-07 起 Skill 不再携带任何本地规划/执行脚本，取数只能经内核入口
（CLI `opscli query plan/flow`、MCP `query_plan/query_flow`）。本文件把这次切换的
结果固化为可回归的断言，防止旧脚本或旧文档引用在后续合并中悄悄回流。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TEMPLATE = Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-dataset-query"

# 切换后允许保留的脚本：只剩图表映射/异常检测/Excel 导出与证据合同等消费端能力
RETAINED_SCRIPTS = {
    "chart_analyze.py",
    "chart_analyze_core.py",
    "chart_analyze_mcp.py",
    "chart_data_loader.py",
    "chart_map.py",
    "chart_map_core.py",
    "chart_map_mcp.py",
    "core.py",
    "evidence_contract.py",
    "excel_export.py",
    "excel_export_core.py",
    "excel_export_mcp.py",
}

# 文档里不允许再出现的旧脚本/旧数据/旧参数引用（`local_fallback` 单独作为
# `--selection-source` 的服务端枚举值仍合法，所以这里只匹配脚本文件名）
REMOVED_MARKERS = (
    "query_plan.py",
    "run_query.py",
    "query_flow.py",
    "local_fallback.py",
    "route_intent",
    "search.py",
    "scripts/query.py",
    "updater.py",
    "updater_mcp",
    "agent_query_planner",
    "dataset_guidance.py",
    "field_semantics.py",
    "intent_taxonomy",
    "field_semantic_index",
    "query_plan.schema",
    "cli-simple-guide",
    "--authorized-platform-value",
    "--output-mode",
    "备选执行通道",
)


def _doc_files() -> list[Path]:
    """模板内全部面向 Agent 的文档：SKILL.md、QUERY_SPEC.md、references/*.md、data/*.md。"""
    return [
        TEMPLATE / "SKILL.md",
        TEMPLATE / "QUERY_SPEC.md",
        *sorted((TEMPLATE / "references").glob("*.md")),
        *sorted((TEMPLATE / "data").glob("*.md")),
    ]


def test_skill_version_matches_version_json():
    """SKILL.md frontmatter 版本必须与 data/VERSION.json 一致，且 data 仍声明为占位符。"""
    frontmatter = (TEMPLATE / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r"^version:\s*(\S+)\s*$", frontmatter, flags=re.MULTILINE)
    assert match, "SKILL.md frontmatter 缺少 version"
    payload = json.loads((TEMPLATE / "data" / "VERSION.json").read_text(encoding="utf-8"))
    assert payload["version"] == match.group(1)
    # 真实元数据靠 upgrade 拉取，模板 data/ 必须继续声明占位符，否则 install 会覆盖用户元数据
    assert payload["data_state"] == "placeholder"


def test_scripts_dir_only_keeps_consumer_side_scripts():
    """scripts/ 只允许消费端脚本，本地规划器/执行器/检索脚本不得回流。"""
    present = {path.name for path in (TEMPLATE / "scripts").glob("*.py")}
    assert present == RETAINED_SCRIPTS


def test_docs_have_no_local_planner_references():
    """所有文档不得再引用已删除的本地规划器脚本、旧数据文件与旧参数。"""
    offenders = []
    for path in _doc_files():
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}: {marker}" for marker in REMOVED_MARKERS if marker in text)
    assert not offenders, offenders


def test_main_entry_is_kernel_flow():
    """主线入口必须是内核一体化命令，且降级路径只依赖 opscli 命令。"""
    skill_md = (TEMPLATE / "SKILL.md").read_text(encoding="utf-8")
    assert 'opscli query flow "$USER_REQUEST" --result-dir "$RESULT_DIR"' in skill_md
    assert "opscli query metadata --pretty" in skill_md  # 降级 L2b 走内核元数据命令
    cli_md = (TEMPLATE / "references" / "cli.md").read_text(encoding="utf-8")
    assert "opscli query plan" in cli_md
    # 图表/Excel 消费端脚本仍由图表指南承接
    assert "scripts/chart_map.py" in (TEMPLATE / "references" / "chart-excel-guide.md").read_text(encoding="utf-8")
