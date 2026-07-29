"""固定槽位覆盖判定的回归测试。

线上事故形态：用户说「搜索词的点击份额」返回零候选，而「搜索词和关键词的点击份额」
返回 3 个正确数据集——用户描述越具体候选越少。根因是固定槽位要求
数据集支持的取值与请求完全相等，覆盖更多粒度的数据集反而被拒。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli" / "skills" / "templates" / "ops-dataset-query" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import agent_query_planner as aqp  # noqa: E402

from opscli.query.services.planner import agent_query_planner as kernel_aqp  # noqa: E402

BOTH_VERSIONS = pytest.mark.parametrize(
    "module",
    [aqp, kernel_aqp],
    ids=["skill", "kernel"],
)

RULES = {
    "slots": {
        "grain": {
            "keyword": {"terms": ["关键词"], "description_patterns": ["关键词"]},
            "search_term": {"terms": ["搜索词"], "description_patterns": ["搜索词"]},
        }
    }
}


def _profile(supported: set, mode: str) -> dict:
    return {"slots": {"grain": supported}, "slot_modes": {"grain": mode}}


@BOTH_VERSIONS
def test_dataset_covering_more_grains_is_accepted(module):
    """数据集支持 keyword+search_term，用户只要 search_term——应通过。

    这是零候选的直接成因：覆盖面更广的数据集本该可用，却因「不完全相等」被拒。
    """
    profile = _profile({"keyword", "search_term"}, "fixed")
    assert module._slot_is_covered(profile, "grain", {"search_term"}, RULES) is True


@BOTH_VERSIONS
def test_dataset_missing_requested_grain_is_rejected(module):
    """数据集不支持用户要求的粒度时仍须拒绝——放开的是「多」，不是「少」。"""
    profile = _profile({"keyword"}, "fixed")
    assert module._slot_is_covered(profile, "grain", {"search_term"}, RULES) is False


@BOTH_VERSIONS
def test_unsupported_slot_mode_still_rejected(module):
    """槽位标记为 unsupported 时不因放开而通过。"""
    profile = _profile({"search_term"}, "unsupported")
    assert module._slot_is_covered(profile, "grain", {"search_term"}, RULES) is False


@BOTH_VERSIONS
def test_extra_slot_terms_reports_uncovered_surplus(module):
    """多出的粒度必须能被取出，供合同强制披露。"""
    profile = _profile({"keyword", "search_term"}, "fixed")
    extra = module._extra_slot_terms(profile, {"grain": {"search_term"}}, RULES)
    assert extra == {"grain": ["keyword"]}


@BOTH_VERSIONS
def test_extra_slot_terms_empty_when_exact_match(module):
    """粒度正好相等时没有可披露内容，不应产生空噪声。"""
    profile = _profile({"search_term"}, "fixed")
    assert module._extra_slot_terms(profile, {"grain": {"search_term"}}, RULES) == {}
