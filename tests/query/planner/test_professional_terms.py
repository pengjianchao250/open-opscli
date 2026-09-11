"""专业口径的回归测试（2026-09-10 同义词复测）。

事故形态：
1. 「近7天各平台的CPC」以 planned 下发零指标模板：CPC 只是「平均CPC」「CPC转化率」等
   多个字段名称的一部分，度量门禁把"是某个标签的片段"当成认得而放行。
2. 「近7天各平台的TACOS」被静默选成 ACOS：字段词匹配没有英文单词边界，
   「acos」在「tacos」里也算命中，而两者口径不同。
3. 「CTR」登记在多个物理字段名上（不同数据集的同一口径），完整性门禁按物理名
   逐个核对，只要有一个物理名不在本数据集就误报缺失。
4. MTD/YTD/QTD/WTD、月初至今、年初至今、上半年、下半年、近半年、近N个季度
   不识别，整句退回默认近 30 天。
"""

from __future__ import annotations

from datetime import date

import pytest

from opscli.query.services.planner import field_semantics, query_plan, time_scope
from opscli.query.services.planner.metadata_adapter import MetadataAdapter

TODAY = date(2026, 9, 10)  # 周四


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("MTD各平台销售额", "2026-09-01", "2026-09-10"),
        ("月初至今各平台销售额", "2026-09-01", "2026-09-10"),
        ("本月至今各平台销售额", "2026-09-01", "2026-09-10"),
        ("YTD各平台销售额", "2026-01-01", "2026-09-10"),
        ("年初至今各平台销售额", "2026-01-01", "2026-09-10"),
        ("QTD各平台销售额", "2026-07-01", "2026-09-10"),
        ("WTD各平台销售额", "2026-09-07", "2026-09-10"),
        ("上半年各平台销售额", "2026-01-01", "2026-06-30"),
        ("下半年各平台销售额", "2026-07-01", "2026-12-31"),
        ("去年下半年各平台销售额", "2025-07-01", "2025-12-31"),
        ("2025年上半年各平台销售额", "2025-01-01", "2025-06-30"),
        ("近半年各平台销售额", "2026-03-15", "2026-09-10"),
        ("近一个季度各平台销售额", "2026-06-13", "2026-09-10"),
        ("近2个季度各平台销售额", "2026-03-15", "2026-09-10"),
        # 回归守卫：既有口径不变
        ("本月各平台销售额", "2026-09-01", "2026-09-30"),
        ("今年各平台销售额", "2026-01-01", "2026-09-10"),
        ("第三季度各平台销售额", "2026-07-01", "2026-09-30"),
    ],
)
def test_professional_time_terms(text, start, end):
    scope = time_scope.parse(text, today=TODAY)

    assert (scope["start"], scope["end"]) == (start, end)
    assert scope["is_default"] is False


@pytest.mark.parametrize(
    ("term", "query", "expected"),
    [
        ("ACOS", "近7天各平台的TACOS", False),
        ("ACOS", "近7天各平台的ACOS", True),
        ("ACOS", "广告ACOS走势", True),
        ("SB", "近7天SBV的点击量", False),
        ("SB", "近7天SB广告的点击量", True),
        ("7日销量", "近17日销量", False),
        ("7日销量", "近7日销量", True),
        ("点击率", "各平台的视频点击率", True),
    ],
)
def test_ascii_field_terms_require_word_boundary(term, query, expected):
    """英文/数字字段词要落在单词边界上，中文字段词不受影响。"""
    assert field_semantics.has_standalone_term_occurrence(term, query) is expected


LABELS = {
    "dimensions": [{"field_name": "platform_name", "verbose_name": "平台"}],
    "metrics": [
        {"field_name": "ads_cpc_avg_cny", "verbose_name": "平均CPC"},
        {"field_name": "ads_cpc_percent", "verbose_name": "CPC转化率"},
        {"field_name": "ads_acos", "verbose_name": "ACOS"},
    ],
}


def test_partial_measure_name_without_selected_field_is_unmatched():
    """「CPC」只是多个字段名称的一部分且没选中任何字段时，不能算认得。"""
    assert query_plan._unmatched_measure_terms("近7天各平台的CPC", LABELS) == ["cpc"]


def test_partial_measure_name_resolved_to_selected_field_is_known():
    """片段名确实落到了已选字段上时照常放行。"""
    assert (
        query_plan._unmatched_measure_terms("近7天各平台的CPC", LABELS, (), ["平均CPC"]) == []
    )


def test_ascii_measure_containing_label_is_not_a_modifier_form():
    """「TACOS」包含「ACOS」的字母，但不是带修饰词的 ACOS。"""
    assert query_plan._unmatched_measure_terms("近7天各平台的TACOS", LABELS) == ["tacos"]


def _field(name: str, label: str, field_type: str) -> dict:
    return {
        "table_id": 1,
        "dataset_alias": "ds_ads",
        "dataset_name": "ads_detail",
        "field_name": name,
        "verbose_name": label,
        "global_alias": f"f_{name}",
        "field_type": field_type,
        "snapshot_metric": 0,
        "has_formula_config": 0,
    }


def _plan(query: str) -> dict:
    adapter = MetadataAdapter(
        {
            "datasets": [
                {
                    "table_id": 1,
                    "dataset_alias": "ds_ads",
                    "dataset_name": "ads_detail",
                    "dataset_category": "normal",
                    "description": "广告投放数据集",
                    "remarks": "广告投放指标明细",
                    "select_columns": [],
                }
            ],
            "fields": [
                _field("date_id", "日期", "dimension"),
                _field("platform_name", "平台", "dimension"),
                _field("ads_cpc_avg_cny", "平均CPC", "metric"),
                _field("ads_cpc_percent", "CPC转化率", "metric"),
                _field("ads_clicks_percent", "点击率", "metric"),
                _field("ads_acos", "ACOS", "metric"),
            ],
        }
    )
    return query_plan.build_model_query_plan(
        adapter,
        "广告投放数据集" + query,
        requested_fields=[],
        refresh_fn=None,
        enum_fn=lambda *_args, **_kwargs: [],
    )


def test_partial_metric_name_clarifies_with_candidates():
    """「CPC」转澄清，提示是多个字段名称的一部分，并给出近似字段。"""
    result = _plan("近7天各平台的CPC")

    view = result["model_view"]
    assert result["status"] == "clarify_required"
    assert "metric_not_in_dataset" in view["clarification_reason_codes"]
    assert any("只是多个字段名称的一部分" in item for item in view.get("pending_confirmations_zh") or [])
    candidates = view["field_suggestions_zh"][0]["candidates_zh"]
    assert "平均CPC" in candidates and "CPC转化率" in candidates


def test_tacos_is_not_silently_mapped_to_acos():
    """「TACOS」没有对应字段时转澄清，不能静默替换成 ACOS。"""
    result = _plan("近7天各平台的TACOS")

    assert result["status"] == "clarify_required"
    assert "ACOS" not in (result["model_view"].get("metrics") or [])


def test_ctr_alias_maps_to_click_rate_without_false_missing():
    """「CTR」落到数据集的「点击率」，并披露称呼对应关系，不误报缺失。"""
    result = _plan("近7天各平台的CTR")

    view = result["model_view"]
    assert result["status"] == "planned"
    assert view["metrics"] == ["点击率"]
    assert {"requested": "ctr", "field_zh": "点击率", "field_name": "ads_clicks_percent"} in (
        view.get("field_alias_mappings_zh") or []
    )
