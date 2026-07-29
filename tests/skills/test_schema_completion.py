"""确定性补全规则单测：字符二元组相似度与公式引用词表提取。

为什么需要：主规划器的字段打分末端只有 token 集合交集，
「点击份额」这类与真实字段中文名部分重叠的业务词会直接落空，
实测返回零候选。本模块补的是纯算法、无网络、无第三方依赖的一层。
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

import schema_completion as skill_completion  # noqa: E402


def test_identical_text_scores_one():
    assert skill_completion.bigram_similarity("点击份额", "点击份额") == 1.0


def test_unrelated_text_scores_zero():
    assert skill_completion.bigram_similarity("点击份额", "库存金额") == 0.0


def test_partial_overlap_scores_between():
    score = skill_completion.bigram_similarity("点击份额", "购买份额")
    assert 0.0 < score < 1.0


def test_short_text_is_not_matched():
    """单字与空串不参与模糊匹配，否则任意查询都会命中一堆字段。"""
    assert skill_completion.bigram_similarity("点", "点击份额") == 0.0
    assert skill_completion.bigram_similarity("", "点击份额") == 0.0


import dataset_guidance as skill_guidance  # noqa: E402


def _field(field_name: str, verbose_name: str) -> dict:
    return {
        "field_name": field_name,
        "verbose_name": verbose_name,
        "field_type": "metric",
        "dataset_alias": "ds_test",
    }


def test_fuzzy_match_rescues_zero_score_field():
    """业务词与字段中文名部分重叠时不能再得 0 分。

    实测形态：「搜索词的点击份额和购买份额」在当前实现下零候选，
    因为打分末端只有 token 交集。
    """
    field = _field("buy_share", "购买份额")
    score = skill_guidance._field_score(
        field, "看一下搜索词的点击份额", {"点击", "份额", "搜索"}
    )
    assert score > 0


def test_fuzzy_score_never_outranks_exact_match():
    """模糊分必须低于任何精确命中，否则会把准确字段挤下去。"""
    exact = skill_guidance._field_score(
        _field("buy_share", "购买份额"), "查购买份额", {"购买", "份额"}
    )
    fuzzy = skill_guidance._field_score(
        _field("buy_share", "购买份额"), "查点击份额", {"点击", "份额"}
    )
    assert fuzzy < exact


def test_unrelated_field_stays_zero():
    """完全无关的字段不能因为模糊匹配被拉进候选。"""
    score = skill_guidance._field_score(
        _field("stock_qty", "总库存"), "查点击份额", {"点击", "份额"}
    )
    assert score == 0
