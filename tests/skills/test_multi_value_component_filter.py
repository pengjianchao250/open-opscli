"""显式多值组件筛选的回归测试。

线上事故形态：用户写「查询渠道为“傲彼瑞-美国”、“傲彼瑞-tiktok”、“傲彼瑞-加拿大”
三个准确渠道名称中任意一个的所有ASIN」，三个值都是当前账号可见的完整授权原值，
却被判为"没有唯一完整等值的授权成员"并转澄清，回显还退化成共同前缀「傲彼瑞」，
反过来要求用户"请指定准确渠道名称"——用户给的本来就是准确全名。
codex 只能退化成逐个查询再本地取并集。

根因：_reverse_lookup_component_values 内部已分开算 exact_hits（原文写了完整原值）
与 base_hits（原文只出现主段），但返回时拍平成一个列表，调用方只能统一要求
len(matched) == 1，无法区分「三个准确值」与「一个模糊主段」。

修复后的语义分界：
- 整值命中多个 → 全部锁定，按 IN 下发（用户点名的准确值集合）
- 主段命中多个 → 保持 fail-closed 转澄清（「傲彼瑞」确实歧义）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import query_plan  # noqa: E402

ENUM = [
    "傲彼瑞-美国",
    "傲彼瑞-加拿大",
    "傲彼瑞-tiktok",
    "傲彼瑞-日本",
    "其他品牌-美国",
]


def _matches(query: str):
    return query_plan._reverse_lookup_component_matches(
        query, list(ENUM), query_plan._normalize_component_value
    )


def test_multiple_exact_values_are_marked_exact():
    """逐个写出完整原值时，命中类型必须是 exact 且返回全部值。"""
    hits, kind = _matches(
        "查询渠道为“傲彼瑞-美国”、“傲彼瑞-tiktok”、“傲彼瑞-加拿大”中任意一个的所有ASIN"
    )

    assert kind == "exact"
    assert set(hits) == {"傲彼瑞-美国", "傲彼瑞-tiktok", "傲彼瑞-加拿大"}


def test_base_segment_only_is_marked_base():
    """只写主段时命中类型是 base，交由调用方按 fail-closed 转澄清。"""
    hits, kind = _matches("查询渠道为傲彼瑞的所有ASIN")

    assert kind == "base"
    assert set(hits) == {"傲彼瑞-美国", "傲彼瑞-加拿大", "傲彼瑞-tiktok", "傲彼瑞-日本"}


def test_single_exact_value():
    """单个整值命中保持原有语义。"""
    hits, kind = _matches("查询渠道为“傲彼瑞-加拿大”的所有ASIN")

    assert kind == "exact"
    assert hits == ["傲彼瑞-加拿大"]


def test_no_hit_returns_empty_kind():
    """零命中时不得谎报命中类型。"""
    hits, kind = _matches("查询所有ASIN")

    assert hits == []
    assert kind == ""


def test_legacy_values_helper_still_returns_flat_list():
    """保留的旧签名仍只返回候选列表，既有调用方与测试不受影响。"""
    hits = query_plan._reverse_lookup_component_values(
        "查询渠道为“傲彼瑞-美国”的所有ASIN", list(ENUM), query_plan._normalize_component_value
    )

    assert hits == ["傲彼瑞-美国"]


def _write(resolved):
    """跑一遍写入，返回 (filters, 披露文案)。"""
    contract = {"model_view": {}}
    execution = {"query_template": {}}
    query_plan._write_component_filter(
        contract,
        execution,
        field_name="channel_name",
        label_zh="渠道",
        requested="傲彼瑞-美国、傲彼瑞-加拿大" if isinstance(resolved, list) else resolved,
        resolved=resolved,
    )
    return (
        execution["query_template"]["filters"],
        contract["model_view"]["component_filter_disclosures_zh"],
    )


def test_single_value_keeps_equals_operator():
    """单值不得改变既有 payload 形状，仍用 `=`。"""
    filters, disclosures = _write("傲彼瑞-美国")

    assert filters == [{"field": "channel_name", "operator": "=", "value": "傲彼瑞-美国"}]
    assert "任一命中" not in disclosures[0]


def test_multi_value_writes_in_operator():
    """多值按服务端支持的 IN 语义下发，且披露必须列出全部值。"""
    filters, disclosures = _write(["傲彼瑞-美国", "傲彼瑞-加拿大"])

    assert filters == [
        {
            "field": "channel_name",
            "operator": "in",
            "value": ["傲彼瑞-美国", "傲彼瑞-加拿大"],
        }
    ]
    assert "傲彼瑞-美国" in disclosures[0]
    assert "傲彼瑞-加拿大" in disclosures[0]
    assert "任一命中" in disclosures[0]


@pytest.mark.parametrize("resolved", ["傲彼瑞-美国", ["傲彼瑞-美国", "傲彼瑞-加拿大"]])
def test_resolved_component_filters_records_values(resolved):
    """执行侧登记必须与下发值一致，供审计与披露核对。"""
    contract = {"model_view": {}}
    execution = {"query_template": {}}
    query_plan._write_component_filter(
        contract,
        execution,
        field_name="channel_name",
        label_zh="渠道",
        requested="x",
        resolved=resolved,
    )
    recorded = execution["resolved_component_filters"][0]["resolved_value"]

    assert recorded == resolved
