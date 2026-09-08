"""全时段（不加日期筛选）与否定语境的回归测试。

覆盖三条行为：
1. 用户明确要求全时段（历史以来/所有时间/不限时间）→ 空窗口，不注入日期筛选；
2. 否定语境里的时间口径不得被当成显式请求（「拒绝默认近30天」曾被识别成要近30天）；
3. 只查维度不查指标时，原文未给时间口径也不加日期筛选（去重维度全集不该被卡 30 天）。

第 3 条依赖组件筛选值解析（_resolve_component_filters）兜底：跳过时间确认门后，
带筛选值的请求由「锁定 / 澄清 / 阻断」三态保证不会执行未带筛选的模板。

历史说明：本文件原先同时对拍 Skill 版与内核版；Skill 本地规划器移除后只保留
内核半边，端到端两条用例的数据源由 Skill 的本地 CSV 目录改为 MetadataAdapter。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan, time_scope
from opscli.query.services.planner.metadata_adapter import MetadataAdapter


@pytest.mark.parametrize(
    "query",
    [
        "查询历史以来全部数据",
        "查所有时间的数据",
        "不限时间，全部ASIN",
        "不添加任何日期或时间筛选",
        "全时段的渠道明细",
    ],
)
def test_all_time_phrases_return_unbounded_window(query: str):
    """明确要求全时段时返回空窗口，且不算默认口径（不该再追问时间）。"""
    scope = time_scope.parse(query)
    assert scope["unbounded"] is True
    assert scope["start"] is None and scope["end"] is None
    assert scope["is_default"] is False


def test_negated_time_phrase_is_not_treated_as_explicit():
    """「拒绝默认近30天」不能被当成用户显式要求近30天。

    这是线上实际踩过的坑：用户越强调不要近30天，越会因为句中出现「近30天」
    被识别为显式口径，连确认都不弹就按 30 天执行。
    """
    scope = time_scope.parse("用户已明确拒绝默认近30天")
    assert scope["is_default"] is True, "否定语境应回落默认口径并触发确认"
    assert scope["unbounded"] is False


def test_negation_masking_stops_at_punctuation():
    """否定屏蔽只作用到最近的标点，后半句的真实时间表述仍要生效。"""
    scope = time_scope.parse("不要近30天，查上月")
    assert scope["label_zh"].startswith("上月")
    assert scope["is_default"] is False
    assert scope["unbounded"] is False


def test_generic_all_wording_is_not_all_time():
    """「全部ASIN」是维度泛指，不能被误判成不限时间。"""
    scope = time_scope.parse("查傲彼瑞的全部ASIN")
    assert scope["unbounded"] is False
    assert scope["is_default"] is True


@pytest.mark.parametrize(
    "query, expected_prefix",
    [
        ("近7天的销量", "近7天"),
        ("本月的销量", "本月"),
        ("2026-07-01 至 2026-07-15 的数据", "明确日期范围"),
    ],
)
def test_explicit_windows_are_unaffected(query: str, expected_prefix: str):
    """显式时间口径不受本次改动影响。"""
    scope = time_scope.parse(query)
    assert scope["unbounded"] is False
    assert scope["start"] is not None
    assert scope["label_zh"].startswith(expected_prefix)


@pytest.mark.parametrize("query", ["历史以来的数据，环比", "所有时间的数据，同比"])
def test_unbounded_window_has_no_comparison(query: str):
    """空窗口没有对比基准，不能凭空造出环比/同比周期。"""
    assert time_scope.parse(query)["comparison"] is None


def _dimension_only_payload() -> dict:
    """一套 ready 元数据：日期、ASIN 两个维度 + 一个销量指标 + 平台组件列。"""
    return {
        "datasets": [
            {
                "table_id": 1,
                "dataset_alias": "ds_ads",
                "dataset_name": "广告数据集",
                "dataset_category": "normal",
                "inner_where_enabled": 0,
                "description": "SP广告数据集",
                "remarks": "",
                "select_columns": [
                    {
                        "column_name": "platform_name",
                        "verbose_name": "平台",
                        "component_dataset_alias": "ds_ads",
                    }
                ],
            }
        ],
        "fields": [
            {
                "table_id": 1,
                "dataset_alias": "ds_ads",
                "dataset_name": "广告数据集",
                "field_name": "date_id",
                "verbose_name": "日期",
                "global_alias": "f_date_id",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 1,
                "dataset_alias": "ds_ads",
                "dataset_name": "广告数据集",
                "field_name": "asin",
                "verbose_name": "ASIN",
                "global_alias": "f_asin",
                "field_type": "dimension",
                "has_formula_config": 0,
            },
            {
                "table_id": 1,
                "dataset_alias": "ds_ads",
                "dataset_name": "广告数据集",
                "field_name": "sales",
                "verbose_name": "销量",
                "global_alias": "f_sales",
                "field_type": "metric",
                "has_formula_config": 0,
            },
        ],
    }


def _date_filters(result: dict) -> list:
    """取出执行模板里的日期筛选条件。"""
    template = (result.get("execution_ref") or {}).get("query_template") or {}
    return [
        item
        for item in template.get("filters") or []
        if "date" in str(item.get("field"))
    ]


def test_dimension_only_query_without_time_is_unbounded():
    """只查维度不查指标时不加日期筛选，也不再就时间口径追问。

    这类请求要的是去重维度全集（如某渠道下全部 ASIN），
    卡近 30 天只会漏掉更早出现过的值。
    """
    result = query_plan.build_model_query_plan(
        MetadataAdapter(_dimension_only_payload()),
        "广告数据集 ASIN",
        enum_fn=lambda *a, **k: [],
    )

    assert result["status"] == "planned"
    assert result["execution_ref"]["time_scope"]["unbounded"] is True
    assert _date_filters(result) == []
    assert "不加日期筛选" in result["model_view"]["time_scope_zh"]


def test_metric_query_without_time_still_confirms_default_window():
    """带指标且未给时间口径时，仍保留默认近30天 + 用户确认门。"""
    result = query_plan.build_model_query_plan(
        MetadataAdapter(_dimension_only_payload()),
        "广告数据集 ASIN 销量",
        enum_fn=lambda *a, **k: [],
    )

    assert result["status"] == "clarify_required"
    assert "time_scope_confirmation" in result["model_view"]["clarification_reason_codes"]
