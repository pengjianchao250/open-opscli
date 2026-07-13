"""ops-dataset-query 本地查询规划器（query_plan 组合入口）的回归测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


SKILL_ROOT = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
)
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan  # noqa: E402
import scoped_metadata_index  # noqa: E402

RULES_PATH = SKILL_ROOT / "data" / "intent_rules.json"


def _write_ready_metadata(data_dir: Path) -> None:
    """写入一套最小的 data_state=ready 元数据（含公式指标与快照指标）。"""
    data_dir.mkdir(parents=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dataset-query", "version": "v1.2.3", "data_state": "ready"}),
        encoding="utf-8",
    )
    (data_dir / "datasets.csv").write_text(
        "table_id,dataset_alias,dataset_name,dataset_category,inner_where_enabled,description,remarks\n"
        "1,ds_ads,广告数据集,normal,0,SP广告数据集,\n"
        "2,ds_inv,库存数据集,normal,0,库存快照数据集,\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_fields.csv").write_text(
        "table_id,dataset_alias,dataset_name,field_name,verbose_name,global_alias,field_type,"
        "summary_expression,detail_expression,description,remarks,snapshot_metric,has_formula_config\n"
        "1,ds_ads,广告数据集,date_id,日期,f_date_id,dimension,,,,,0,0\n"
        "1,ds_ads,广告数据集,acos,ACOS,f_acos,metric,ads_cost / sales,,广告成本销售比,,0,1\n"
        "2,ds_inv,库存数据集,sku,SKU,f_sku,dimension,,,,,0,0\n"
        "2,ds_inv,库存数据集,stock_qty,库存量,f_stock_qty,metric,,,,,1,0\n",
        encoding="utf-8",
    )
    (data_dir / "dataset_select_columns.csv").write_text(
        "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
        "ds_ads,platform_name,平台,ds_ads\n",
        encoding="utf-8",
    )


def test_query_plan_selects_acos_with_formula_policy(tmp_path: Path):
    """显式点名数据集 + 公式指标：应定表并给出公式聚合口径。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    cards = scoped_metadata_index.build_cards(data_dir)
    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert {card["dataset_alias"] for card in cards} == {"ds_ads", "ds_inv"}
    assert result["status"] == "planned"
    assert result["model_view"]["dataset_name_zh"] == "SP广告数据集"
    assert "ACOS" in result["model_view"]["metrics"]
    assert result["execution_ref"]["user_visible"] is False
    acos = next(
        item
        for item in result["execution_ref"]["metrics"]
        if item["field_name"] == "acos"
    )
    assert acos["is_formula"] is True
    assert acos["aggregation_policy"] == "formula_expression_without_extra_aggregation"


def test_snapshot_metric_gets_snapshot_aggregation_policy(tmp_path: Path):
    """快照类指标（snapshot_metric=1）必须带最新快照聚合口径。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "库存快照数据集 库存量",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "planned"
    stock = next(
        item
        for item in result["execution_ref"]["metrics"]
        if item["field_name"] == "stock_qty"
    )
    assert stock["is_snapshot"] is True
    assert stock["aggregation_policy"] == "latest_snapshot_no_period_aggregation"


def test_unsupported_platform_scope_is_blocked_explicitly(tmp_path: Path):
    """请求了不支持的平台（如沃尔玛）时应明确阻断为平台范围不支持，而非枚举歧义。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS 只看沃尔玛平台",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "blocked"
    assert result["model_view"]["next_action"] == "block_platform_scope_unsupported"
