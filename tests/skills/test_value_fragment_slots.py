"""复合字面值后段不得被读成槽位诉求的回归测试。

线上事故形态：用户写「字段“渠道”精确等于“傲彼瑞-tiktok”，查询所有ASIN」，
渠道值里的 tiktok 命中 slots.platform 词表（terms = tiktok / tik tok / tk），
而 platform_scope.members 只映射 amazon*，非 amazon 平台展开为空，
于是整条查询被判 block_platform_scope_unsupported 直接无法执行——
用户给出的是渠道值，根本没有提平台诉求。

判据取「命中紧跟在连字符/下划线之后」：这说明该词只是用户给出的复合值的后段。
真正的平台诉求（「查tiktok平台」「查亚马逊平台」）不带前置连字符，照常识别。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = (
    Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-dataset-query"
)
if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

import typed_schema_linking as schema  # noqa: E402

RULES = json.loads((SKILL_DIR / "data" / "intent_rules.json").read_text(encoding="utf-8"))


def _platform_slots(query: str) -> list[str]:
    return schema.extract_query_semantics(query, RULES)["slots"].get("platform", [])


@pytest.mark.parametrize(
    "query",
    [
        '字段“渠道”精确等于“傲彼瑞-tiktok”，查询所有ASIN',
        "查询渠道为傲彼瑞-tiktok的所有ASIN",
        '查询渠道为“傲彼瑞-美国”、“傲彼瑞-tiktok”、“傲彼瑞-加拿大”中任意一个的所有ASIN',
        "渠道 ohwill-shopify-美国 的销售额",
    ],
)
def test_value_fragment_is_not_a_platform_request(query: str):
    """连字符后的平台词只是渠道值的一段，不算平台诉求。"""
    assert _platform_slots(query) == [], f"复合值后段被误读成平台诉求：{query}"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("查tiktok平台的所有ASIN", "tiktok"),
        ("查亚马逊平台近7天的销售额", "amazon"),
        ("查沃尔玛的销售额", "walmart"),
        ("查temu的销售额", "temu"),
    ],
)
def test_real_platform_request_still_read(query: str, expected: str):
    """真正的平台诉求不带前置连字符，必须照常识别。"""
    assert expected in _platform_slots(query)


def test_hyphenated_platform_term_itself_still_matches():
    """平台词自身含分隔符时不受影响：amazon-vc 仍应识别为 amazon_vc。

    该词条的匹配区间从 amazon 起算、前面没有连字符，因此不会被当成值后段剔除。
    """
    assert "amazon_vc" in _platform_slots("查 amazon-vc 的销售额")


def test_profile_matching_is_unaffected():
    """数据集说明的画像匹配不启用该剔除，避免改动画像语义。

    profile_card 走 _pattern_spans 且不传 drop_value_fragments，
    说明文案里形如「-TikTok」的表述仍按原样参与画像。
    """
    card = {
        "dataset_alias": "ds_test",
        "dataset_name": "测试数据集",
        "description": "覆盖渠道-TikTok的销售数据",
        "remarks": "",
        "dimension_terms": [],
        "metric_terms": [],
        "select_column_terms": [],
    }
    profile = schema.profile_card(card, RULES)

    assert "tiktok" in profile["slots"]["platform"]
