"""标签形态下显式列举多个筛选值的回归测试。

线上事故形态（codex 实测，退出码 2）：
    筛选渠道为傲彼瑞-美国、傲彼瑞-tiktok、傲彼瑞-加拿大三个当前账号授权渠道中的任意一个
标签抽取只取第一个值「傲彼瑞-美国」，于是
① 静默把三渠道缩成一个渠道；
② 其余两个值没被登记为已消费，「傲彼瑞-加拿大」里的「加拿大」被国家字段反查抓走，
最终下发 channel=傲彼瑞-美国 AND country=加拿大 —— 用户从未表达过的条件，
执行前校验因「国家」不是授权筛选字段而报错退出。

修复思路：标签抽取只负责判断"其后是否紧跟列举分隔符"，
其余值交给授权枚举反查做完整等值匹配。为什么不在标签抽取里把列表抽全：
末位值后面往往接自由描述，靠边界前瞻猜结尾必然过度捕获
（实测会抽成「傲彼瑞-加拿大三个当前账号授权渠道」）。
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

CHANNEL_TERMS = ("渠道", "channel", "channel_name")


@pytest.mark.parametrize(
    "query, expected_first, expected_enumerated",
    [
        # 事故原句：三值列举
        (
            "筛选渠道为傲彼瑞-美国、傲彼瑞-tiktok、傲彼瑞-加拿大三个当前账号授权渠道中的任意一个",
            "傲彼瑞-美国",
            True,
        ),
        ("渠道为傲彼瑞-美国,傲彼瑞-加拿大", "傲彼瑞-美国", True),
        ("渠道为傲彼瑞-美国，傲彼瑞-加拿大", "傲彼瑞-美国", True),
        ("渠道为傲彼瑞-美国/傲彼瑞-加拿大", "傲彼瑞-美国", True),
        ("渠道为傲彼瑞-美国或傲彼瑞-加拿大", "傲彼瑞-美国", True),
        # 单值：不得误判为列举
        ("渠道为傲彼瑞-美国的所有ASIN", "傲彼瑞-美国", False),
        ("渠道是傲彼瑞的所有ASIN", "傲彼瑞", False),
        # 「和」不是列举分隔符：后面接的不是同类枚举值
        ("渠道为傲彼瑞-美国和所有ASIN", "傲彼瑞-美国", False),
        # 标签不匹配时不得谎报
        ("渠道SKU是ON-OB-JL-007-68157", "", False),
    ],
)
def test_labeled_value_match(query: str, expected_first: str, expected_enumerated: bool):
    """标签抽取返回 (首个值, 是否为显式列举)。"""
    first, enumerated = query_plan._labeled_value_match(query, CHANNEL_TERMS)

    assert first == expected_first
    assert enumerated is expected_enumerated


def test_single_value_helper_unchanged():
    """保留的单值签名行为不变，既有调用方不受影响。"""
    assert query_plan._extract_labeled_value(
        "渠道为傲彼瑞-美国的所有ASIN", CHANNEL_TERMS
    ) == "傲彼瑞-美国"


def test_enumeration_is_not_resolved_by_boundary_guessing():
    """列举判定不依赖把末位值抽全——那必然过度捕获。

    这条锁住修复思路：末位值后面接自由描述时，标签抽取只保证首个值与列举标记正确，
    完整值集合由授权枚举反查负责。
    """
    first, enumerated = query_plan._labeled_value_match(
        "筛选渠道为傲彼瑞-美国、傲彼瑞-加拿大三个当前账号授权渠道中的任意一个",
        CHANNEL_TERMS,
    )

    assert (first, enumerated) == ("傲彼瑞-美国", True)
    # 反查才是值集合的来源：三个完整原值都在原文里，命中类型必须是 exact
    hits, kind = query_plan._reverse_lookup_component_matches(
        "筛选渠道为傲彼瑞-美国、傲彼瑞-加拿大三个当前账号授权渠道中的任意一个",
        ["傲彼瑞-美国", "傲彼瑞-加拿大", "傲彼瑞-tiktok"],
        query_plan._normalize_component_value,
    )
    assert kind == "exact"
    assert set(hits) == {"傲彼瑞-美国", "傲彼瑞-加拿大"}
