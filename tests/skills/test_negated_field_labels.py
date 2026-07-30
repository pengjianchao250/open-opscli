"""否定语境下字段标签不得被当成用户点名字段的回归测试。

线上事故形态：用户写「找到渠道是傲彼瑞-美国的所有ASIN；全部时间，不加日期筛选」，
字段标签匹配是对原文做子串包含，「不加日期筛选」里的「日期」命中了日期维度标签，
于是「日期」被加成分组维度。结果 38 行的 ASIN 明细膨胀到 9625 行，超过执行器
5000 行补齐上限而被服务端截断——用户越明确要求不加日期，规划器越确定按日期分组。

同时验证否定词表扩充（忽略/去掉/去除）没有破坏 time_scope 原有的时间口径识别。
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
import time_scope  # noqa: E402


def _guidance(*labels: str) -> dict:
    """构造字段指导结果：每个标签都是打分兜底选出的候选（非显式传参）。"""
    return {
        "field_guidance": {
            "dimensions": [
                {"verbose_name": label, "field_name": f"f_{index}"}
                for index, label in enumerate(labels)
            ],
            "metrics": [],
        }
    }


@pytest.mark.parametrize(
    "query",
    [
        "找到渠道是傲彼瑞-美国的所有ASIN，不加日期筛选",
        "找到渠道是傲彼瑞-美国的所有ASIN，不要按日期拆分",
        "找到渠道是傲彼瑞-美国的所有ASIN，无需日期",
        "找到渠道是傲彼瑞-美国的所有ASIN，忽略日期",
        "找到渠道是傲彼瑞-美国的所有ASIN，去掉日期维度",
        "全部时间，不加日期筛选，仅返回去重后的ASIN列表",
    ],
)
def test_negated_label_is_not_requested(query: str):
    """否定语境里的字段标签不算用户点名。"""
    picked = query_plan._requested_fields(_guidance("日期", "渠道", "ASIN"), "dimensions", query)
    labels = {item["verbose_name"] for item in picked}

    assert "日期" not in labels, f"「日期」被误当成点名维度：{query}"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("按日期看傲彼瑞-美国的销售额", True),
        ("查每个日期的ASIN数", True),
        ("查渠道维度的ASIN数", False),
    ],
)
def test_positive_mention_still_counts(query: str, expected: bool):
    """正面提及必须照常识别，屏蔽不能把正常诉求一起吃掉。"""
    picked = query_plan._requested_fields(_guidance("日期", "渠道"), "dimensions", query)
    labels = {item["verbose_name"] for item in picked}

    assert ("日期" in labels) is expected


def test_negation_span_stops_at_punctuation():
    """屏蔽范围只到最近的标点，否定句之后的正面诉求仍要生效。"""
    picked = query_plan._requested_fields(
        _guidance("日期", "渠道"), "dimensions", "不要按日期拆分，按渠道汇总"
    )
    labels = {item["verbose_name"] for item in picked}

    assert "渠道" in labels
    assert "日期" not in labels


def test_explicit_source_bypasses_masking():
    """显式传参（--field）不受原文屏蔽影响：那是用户直接指定的字段。"""
    guidance = {
        "field_guidance": {
            "dimensions": [
                {"verbose_name": "日期", "field_name": "date_id", "selection_source": "explicit"}
            ],
            "metrics": [],
        }
    }
    picked = query_plan._requested_fields(guidance, "dimensions", "所有ASIN，不加日期筛选")

    assert [item["verbose_name"] for item in picked] == ["日期"]


@pytest.mark.parametrize(
    "query, expect_unbounded",
    [
        # 全时段判断在否定屏蔽之前，这几条不能被新增的否定词打乱
        ("全部时间，不加日期筛选", True),
        ("不限日期，查所有ASIN", True),
        ("历史以来的销售额", True),
        ("查近7天的销售额", False),
        # 有意区分：「不要按日期拆分」表达的是不要分组维度，不是不要时间筛选，
        # 时间窗口未表态时仍走默认近30天，不能顺带放开成全时段
        ("不要按日期拆分，看总销售额", False),
        ("忽略日期，只看ASIN数", False),
    ],
)
def test_time_scope_not_broken_by_new_negation_terms(query: str, expect_unbounded: bool):
    """扩充否定词表（忽略/去掉/去除）不得破坏原有时间口径识别。"""
    parsed = time_scope.parse(query)

    assert bool(parsed.get("unbounded")) is expect_unbounded


def test_negated_time_scope_still_masked():
    """否定语境里的时间口径仍被屏蔽：「不要近30天，查上月」取上月。"""
    parsed = time_scope.parse("不要近30天，查上月的销售额")

    assert parsed.get("start") is not None
    assert "近30天" not in (parsed.get("scope_zh") or "")
