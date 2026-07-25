"""选表引擎移植对拍：adapter → 决策卡片 → 选表结果。

验证 scoped_metadata_index.build_cards 与 agent_query_planner.plan_query 迁入内核后
签名改为消费 MetadataAdapter，选表语义（候选就绪/需澄清）保持不变。
"""

import json
from importlib.resources import files

from opscli.query.services.planner.metadata_adapter import MetadataAdapter
from opscli.query.services.planner import scoped_metadata_index, agent_query_planner


def _rules():
    """从内核静态资源加载领域意图规则。"""
    return json.loads(
        (files("opscli.query.services.planner.resources") / "intent_rules.json").read_text(
            "utf-8"
        )
    )


def test_build_cards_from_adapter():
    """build_cards 从 adapter 聚合出含目标数据集的决策卡片。"""
    payload = {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "销售即时综合",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [],
    }
    cards = scoped_metadata_index.build_cards(MetadataAdapter(payload))
    assert any(c.get("dataset_alias") == "ds_sales" for c in cards)


def test_plan_query_selects_sales_dataset():
    """给出销售额诉求 → 选表引擎给出候选或澄清（非硬失败）。"""
    payload = {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "dataset_category": "normal",
                "description": "销售即时综合数据集",
                "remarks": "",
                "select_columns": [],
            }
        ],
        "fields": [
            {
                "table_id": 1,
                "dataset_alias": "ds_sales",
                "dataset_name": "即时综合数据集",
                "field_name": "sales_amount",
                "verbose_name": "销售额",
                "global_alias": "f_s",
                "field_type": "metric",
                "summary_expression": "sum(x)",
                "detail_expression": "x",
                "has_formula_config": 0,
            }
        ],
    }
    adapter = MetadataAdapter(payload)
    cards = agent_query_planner.load_authorized_cards(adapter)
    # 真实签名：plan_query(query, cards, rules, top_n=3, ...)
    sel = agent_query_planner.plan_query("查销售额", cards, _rules())
    # 返回 planner_contract_v2，选表结果在 planner_status
    assert sel.get("contract") == "planner_contract_v2"
    assert sel.get("planner_status") in ("candidate_ready", "clarify_required")
