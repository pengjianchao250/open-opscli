"""快照指标（snapshot_metric=1）的时间窗口口径：多日窗口收敛为最新完整快照日。

背景（2026-09-07 本地后端 E2E 实测）：后端 SimpleQueryBuilder 对不带 aggregation 的
指标默认 SUM，规划器只是"不传 aggregation"并不能阻止跨日累加——「近7天各渠道总库存」
返回的是 7 天库存之和（147590 = 各日 300+22090+27384+…）。快照指标只反映某一天的切面，
必须在模板层把多日窗口收敛为一个快照日，并强制披露。
"""

from __future__ import annotations

from datetime import date, timedelta

from opscli.query.services.planner import query_plan, time_scope
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


def _field(field_name, verbose_name, field_type, snapshot="0"):
    return {
        "table_id": 1,
        "dataset_alias": "ds_inv",
        "dataset_name": "order_sale_trend_adv_traffic_inv_set",
        "field_name": field_name,
        "verbose_name": verbose_name,
        "global_alias": f"f_{field_name}",
        "field_type": field_type,
        "has_formula_config": 0,
        "snapshot_metric": snapshot,
    }


def _adapter():
    dataset = {
        "table_id": 1,
        "dataset_alias": "ds_inv",
        "dataset_name": "order_sale_trend_adv_traffic_inv_set",
        "dataset_category": "normal",
        "description": "即时综合数据集",
        "remarks": "销售 库存 综合",
        "select_columns": [],
    }
    fields = [
        _field("date_id", "日期", "dimension"),
        _field("channel_name", "渠道", "dimension"),
        _field("price", "销售额", "metric"),
        _field("total_qty", "总库存", "metric", snapshot="1"),
    ]
    return MetadataAdapter({"datasets": [dataset], "fields": fields})


def _plan(query):
    return query_plan.build_model_query_plan(
        _adapter(), query, requested_fields=[], refresh_fn=None, enum_fn=lambda *_a, **_k: []
    )


def _date_filters(template):
    return {
        item["operator"]: item["value"]
        for item in template["filters"]
        if item["field"] == "date_id"
    }


def test_multi_day_window_collapses_to_latest_complete_snapshot_day():
    """「近7天各渠道总库存」：不按日期分组时窗口收敛为昨天（今天的快照不完整），且强制披露。"""
    contract = _plan("近7天各渠道总库存")
    assert contract["status"] == "planned"
    template = contract["execution_ref"]["query_template"]
    reference = date.fromisoformat(contract["execution_ref"]["time_scope"]["reference_date"])
    expected_day = (reference - timedelta(days=1)).isoformat()
    assert _date_filters(template) == {">=": expected_day, "<=": expected_day}
    assert template["metrics"] == [{"field": "total_qty", "alias": "total_qty"}]
    policy = contract["execution_ref"]["snapshot_policy"]
    assert policy["snapshot_day"] == expected_day
    assert policy["requested_window"]["end"] == reference.isoformat()
    disclosures = " ".join(contract["answer_contract"]["required_disclosures_zh"])
    assert expected_day in disclosures and "快照" in disclosures
    assert expected_day in contract["model_view"]["time_scope_zh"]


def test_single_day_window_is_left_unchanged():
    """「各渠道总库存 昨天」本就是单日窗口，不做改写也不额外披露快照收敛。"""
    contract = _plan("各渠道总库存 昨天")
    assert contract["status"] == "planned"
    yesterday = (date.fromisoformat(contract["execution_ref"]["time_scope"]["reference_date"]) - timedelta(days=1)).isoformat()
    assert _date_filters(contract["execution_ref"]["query_template"]) == {">=": yesterday, "<=": yesterday}
    assert "snapshot_policy" not in contract["execution_ref"]


def test_daily_series_keeps_full_window():
    """按日期分组（「每天的」）时是快照序列，保留完整窗口，不收敛。"""
    contract = _plan("近7天各渠道每天的总库存")
    assert contract["status"] == "planned"
    assert "日期" in contract["model_view"]["dimensions"]
    filters = _date_filters(contract["execution_ref"]["query_template"])
    assert filters[">="] != filters["<="]
    assert "snapshot_policy" not in contract["execution_ref"]


def test_mixed_snapshot_and_flow_metrics_require_clarification():
    """销售额（流量）与总库存（快照）混查且未按日分组：两种口径无法共存，必须澄清。"""
    contract = _plan("近7天各渠道销售额和总库存")
    assert contract["status"] == "clarify_required"
    assert "snapshot_metric_window_conflict" in contract["model_view"]["clarification_reason_codes"]
    assert "query_template" not in contract["execution_ref"]


def test_comparison_uses_each_period_end_snapshot_day():
    """「上月各渠道总库存 环比」：主周期取上月末快照日，对比周期取上上月末快照日。"""
    contract = _plan("上月各渠道总库存 环比")
    assert contract["status"] == "planned"
    template = contract["execution_ref"]["query_template"]
    scope = time_scope.parse("上月各渠道总库存 环比")
    assert _date_filters(template) == {">=": scope["end"], "<=": scope["end"]}
    assert template["dataComparison"]["startDate"] == scope["comparison"]["end"]
    assert template["dataComparison"]["endDate"] == scope["comparison"]["end"]
