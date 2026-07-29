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
