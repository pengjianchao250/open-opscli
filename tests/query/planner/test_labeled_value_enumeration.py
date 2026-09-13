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

历史说明：本文件原属 tests/skills，随 Skill 本地规划器移除迁入内核，只改导入。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan

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


def test_copula_less_compound_list_is_enumerated():
    first, enumerated = query_plan._labeled_value_match(
        "渠道傲创-美国、傲创-加拿大的销量", CHANNEL_TERMS
    )

    assert first == "傲创-美国"
    assert enumerated is True


def test_explicit_prefix_label_wins_over_label_suffix_inside_a_value():
    first, enumerated = query_plan._labeled_value_match(
        "部门是范泰克、火星事业部的销量", ("部门", "事业部")
    )

    assert first == "范泰克"
    assert enumerated is True


def test_single_postfixed_exclusion_value_is_owned_by_its_label():
    assert query_plan._labeled_value_match(
        "只看HOMFA但HOMFA品牌除外看销量", ("品牌", "brand")
    ) == ("HOMFA", False)


def test_unlabeled_dimension_list_is_not_a_filter():
    first, enumerated = query_plan._labeled_value_match(
        "按渠道和ASIN看销量", CHANNEL_TERMS
    )

    assert first == ""
    assert enumerated is False


@pytest.mark.parametrize(
    ("query", "terms", "expected"),
    [
        (
            "2026年8月傲创-美国和傲创-加拿大渠道的销量",
            ("渠道", "channel"),
            ["傲创-美国", "傲创-加拿大"],
        ),
        ("美国、加拿大国家的销量", ("国家", "country"), ["美国", "加拿大"]),
        (
            "一部-C组与美国-A组销售小组的销量",
            ("销售小组", "小组"),
            ["一部-C组", "美国-A组"],
        ),
        (
            "傲创-美国,傲创-加拿大渠道除外看销量",
            ("渠道", "channel"),
            ["傲创-美国", "傲创-加拿大"],
        ),
    ],
)
def test_postfixed_component_list_values(query, terms, expected):
    assert query_plan._postfixed_labeled_list_values(query, terms) == expected
    assert query_plan._labeled_value_match(query, terms) == (expected[0], True)


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
