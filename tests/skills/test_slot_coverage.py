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
        },
        # ad_type 的取值在真实规则里没有中文词条（terms 只有 sp / sponsored products），
        # 标签必须退回枚举名并大写，这里照抄真实形态以覆盖该分支
        "ad_type": {
            "sp": {"terms": ["sp", "sponsored products"], "description_patterns": ["SP"]},
            "sd": {"terms": ["sd", "sponsored display"], "description_patterns": ["SD"]},
        },
    }
}


def _profile(supported: set, mode: str) -> dict:
    return {"slots": {"grain": supported}, "slot_modes": {"grain": mode}}


def _ad_type_profile(supported: set, mode: str) -> dict:
    return {"slots": {"ad_type": supported}, "slot_modes": {"ad_type": mode}}


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
    """多出的粒度必须能被取出，且只带中文标签供合同强制披露。

    披露句是面向用户的中文，槽位名（grain）与取值（keyword）都是内部标识，
    不能出现在里面——曾实测输出「所选数据集的ad_type粒度…额外覆盖：sb、sd」。
    """
    profile = _profile({"keyword", "search_term"}, "fixed")
    extra = module._extra_slot_terms(profile, {"grain": {"search_term"}}, RULES)
    assert extra == {
        "grain": {
            "slot_label_zh": "统计粒度",
            "requested_zh": ["搜索词"],
            "surplus_zh": ["关键词"],
        }
    }


@BOTH_VERSIONS
def test_extra_slot_terms_labels_ad_type_without_chinese_terms(module):
    """ad_type 取值在规则里没有中文词条，标签退回大写枚举名而不是原样小写。"""
    profile = _ad_type_profile({"sp", "sd"}, "fixed")
    extra = module._extra_slot_terms(profile, {"ad_type": {"sp"}}, RULES)
    assert extra == {
        "ad_type": {
            "slot_label_zh": "广告类型",
            "requested_zh": ["SP"],
            "surplus_zh": ["SD"],
        }
    }


@BOTH_VERSIONS
def test_extra_slot_terms_skips_filterable_slot(module):
    """可筛选槽位不产出 surplus——这是下游披露文案分语义的前提不变量。

    query_plan._slot_surplus_disclosure_zh 对 platform / ad_type 断言
    「筛不掉、结果是合计」，成立的唯一依据就是这里只收 fixed。
    """
    profile = _ad_type_profile({"sp", "sd"}, "filterable")
    assert module._extra_slot_terms(profile, {"ad_type": {"sp"}}, RULES) == {}


@BOTH_VERSIONS
def test_extra_slot_terms_empty_when_exact_match(module):
    """粒度正好相等时没有可披露内容，不应产生空噪声。"""
    profile = _profile({"search_term"}, "fixed")
    assert module._extra_slot_terms(profile, {"grain": {"search_term"}}, RULES) == {}


@BOTH_VERSIONS
def test_slot_labels_cover_every_allowed_slot(module):
    """槽位中文标签必须覆盖封闭槽位全集，漏一个就会往中文句子里漏英文标识。"""
    assert set(module.schema.SLOT_LABELS_ZH) == set(module.schema.ALLOWED_SLOTS)


@BOTH_VERSIONS
def test_attach_slot_coverage_fills_every_candidate(module):
    """显式命中路径的候选必须被补上覆盖信息，否则强制披露整条链路会静默消失。"""
    profile = _profile({"keyword", "search_term"}, "fixed")
    profile["card"] = {"dataset_alias": "ds_kw_st"}
    candidates = [{"dataset_alias": "ds_kw_st"}, {"dataset_alias": "ds_unknown"}]

    module._attach_slot_coverage(candidates, [profile], {"grain": {"search_term"}}, RULES)

    assert candidates[0]["grain_coverage"]["grain"]["surplus_zh"] == ["关键词"]
    # 画像里找不到的候选保持原样，不臆造覆盖信息
    assert "grain_coverage" not in candidates[1]
