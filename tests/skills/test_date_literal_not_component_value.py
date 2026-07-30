"""时间解析已消费的日期字面量不得再被组件形态抽取的回归测试。

线上事故形态（codex 实测）：
    沿用 2026-07-01 至 2026-07-30 的口径，按「渠道 + ASIN」汇总销量、销售额和毛利
渠道SKU 的编码形态是 `[A-Za-z0-9]{2,}(-[A-Za-z0-9]{2,}){2,}`，
ISO 日期「2026-07-01」正好命中三段连字符结构，于是被当成渠道SKU 筛选值，
因无法在授权枚举里完整等值命中而转澄清——
「渠道SKU“2026-07-01”没有唯一完整等值的授权成员」，
用户的日期口径反而落不了地（渠道三值本身已正确锁定）。

修复思路：日期已被时间解析消费，登记进 consumed 即可，
不新造"日期形态"判断——consumed 的语义本来就是"这段文本已被别的解释占用"。
"""

from __future__ import annotations

import re
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


def _contract(start: str | None, end: str | None, **extra) -> dict:
    scope = {"start": start, "end": end}
    scope.update(extra)
    return {"status": "planned", "execution_ref": {"time_scope": scope}}


def test_sell_sku_pattern_really_matches_iso_date():
    """先固定住前提：渠道SKU 形态确实会命中 ISO 日期。

    这条是缺陷根因的存在性证明——若哪天形态收紧了，这条会失败并提示重新评估。
    """
    spec = next(
        item for item in query_plan._ENUM_COMPONENT_SPECS if item["field_name"] == "sell_sku"
    )
    assert re.search(spec["value_pattern"], "沿用 2026-07-01 至 2026-07-30 的口径")


@pytest.mark.parametrize(
    "start, end",
    [
        ("2026-07-01", "2026-07-30"),
        ("2026-01-01", "2026-12-31"),
    ],
)
def test_time_literals_are_consumed(start: str, end: str):
    """时间窗口的起止日期必须登记为已消费。"""
    consumed = query_plan._time_literals_consumed(_contract(start, end))

    assert query_plan._normalize_component_value(start) in consumed
    assert query_plan._normalize_component_value(end) in consumed


def test_comparison_window_literals_are_consumed():
    """环比/同比的对比窗口日期同样要登记，否则对比口径的日期会被误读。"""
    consumed = query_plan._time_literals_consumed(
        _contract(
            "2026-07-01",
            "2026-07-30",
            comparison_start="2026-06-01",
            comparison_end="2026-06-30",
        )
    )

    assert query_plan._normalize_component_value("2026-06-01") in consumed
    assert query_plan._normalize_component_value("2026-06-30") in consumed


def test_unbounded_scope_consumes_nothing():
    """全时段查询没有日期字面量，不得凭空登记。"""
    assert query_plan._time_literals_consumed(_contract(None, None)) == set()


def test_missing_time_scope_is_tolerated():
    """合同缺 time_scope 时返回空集合，不得抛异常。"""
    assert query_plan._time_literals_consumed({"status": "planned"}) == set()


def test_consumed_date_blocks_patterned_extraction():
    """已消费的日期不再被形态抽取取走——这是缺陷的直接回归点。"""
    spec = next(
        item for item in query_plan._ENUM_COMPONENT_SPECS if item["field_name"] == "sell_sku"
    )
    query = "沿用 2026-07-01 至 2026-07-30 的口径，按渠道+ASIN汇总销量"

    without_guard = query_plan._spec_extract(spec, query, consumed=())
    with_guard = query_plan._spec_extract(
        spec, query, consumed=query_plan._time_literals_consumed(
            _contract("2026-07-01", "2026-07-30")
        )
    )

    assert without_guard == "2026-07-01", "前提变了：日期已不再被形态抽取命中"
    assert with_guard == ""


def test_real_sell_sku_still_extracted():
    """真实渠道SKU 不受影响：它不在时间窗口字面量里。"""
    spec = next(
        item for item in query_plan._ENUM_COMPONENT_SPECS if item["field_name"] == "sell_sku"
    )
    consumed = query_plan._time_literals_consumed(_contract("2026-07-24", "2026-07-30"))

    assert (
        query_plan._spec_extract(
            spec, "查渠道SKU是ON-OB-JL-007-68157的近7天销量", consumed=consumed
        )
        == "ON-OB-JL-007-68157"
    )
