"""2026-09-07 第二轮多代理 E2E 验收暴露的规划器缺陷回归（全部先红后绿）。

覆盖六类静默错答/漏披露缺陷：
1. 无字段标签的未授权国家（「只看德国」）被静默丢弃，下发了不带筛选的全范围模板；
2. 趋势/按日查询不下发日期排序，服务端返回乱序序列；
3. 「前3」这类无行数单位的 TopN 既不解析也不披露；
4. 「各仓库」这类数据集里不存在的分组维度被静默丢弃；
5. 「订单量」被静默映射为「销量」而无披露；
6. 非亚马逊平台语义成员以小写内部键（temu）而非展示名回显。
"""

from __future__ import annotations

from opscli.query.services.planner import query_plan
from tests.query.planner.test_acceptance_defects import _adapter, _instant_dataset, _plan


def _template(contract):
    return contract["execution_ref"]["query_template"]


# ── 1. 未授权国家值（无标签形态）必须澄清 ──────────────────────────────────────


def test_unlabeled_unauthorized_country_is_clarified():
    """「只看德国」：德国不在授权枚举（加拿大/美国），必须澄清并给出可见国家，不得放行成全范围。"""
    for query in ("近7天销售额 只看德国", "近7天各国家销售额 只看德国"):
        contract = _plan(_adapter(_instant_dataset), query)
        assert contract["status"] == "clarify_required", query
        assert "component_filter_unauthorized" in contract["model_view"]["clarification_reason_codes"], query
        assert contract["model_view"]["component_candidates_zh"] == [
            {"field_zh": "国家", "values_zh": ["加拿大", "美国"], "total": 2}
        ], query
        assert "query_template" not in contract["execution_ref"], query
        assert "德国" in " ".join(contract["model_view"]["clarification_messages_zh"]), query


def test_authorized_country_without_label_still_resolves():
    """「只看美国」在授权枚举内：照常锁定为等值筛选（守住既有行为）。"""
    contract = _plan(_adapter(_instant_dataset), "近7天销售额 只看美国")
    assert contract["status"] == "planned"
    assert {"field": "country_name", "operator": "=", "value": "美国"} in _template(contract)["filters"]


# ── 2. 趋势/按日查询默认按日期升序 ───────────────────────────────────────────────


def test_daily_trend_orders_by_date_ascending():
    """趋势序列必须按日期升序下发 orderBy，否则「按日期序列表述」的披露无法执行。"""
    for query in ("近7天销售额趋势", "近7天各平台每日销售额", "近30天销售额 按日趋势"):
        contract = _plan(_adapter(_instant_dataset), query)
        assert contract["status"] == "planned", query
        assert _template(contract)["orderBy"] == [{"field": "date_id", "desc": False}], query


def test_explicit_order_wins_over_trend_default():
    """用户显式点名排序字段时不被趋势默认排序覆盖。"""
    contract = _plan(_adapter(_instant_dataset), "近7天每天的销售额 按销售额降序")
    assert contract["status"] == "planned"
    assert _template(contract)["orderBy"] == [{"field": "price", "desc": True}]


# ── 3. 无行数单位的 TopN ────────────────────────────────────────────────────────


def test_top_n_without_row_unit_is_resolved():
    """「各部门订单量前3」：单指标场景下应解析为按该指标降序取 3 行。"""
    contract = _plan(_adapter(_instant_dataset), "近7天各部门订单量前3")
    assert contract["status"] == "planned"
    template = _template(contract)
    assert template["limit"] == 3
    assert template["orderBy"] == [{"field": "order_qty", "desc": True}]


def test_leading_time_words_are_not_row_limits():
    """「前7天」「前3个月」是时间表述，不得误读成行数限制。"""
    for query in ("前7天各部门销量", "前3个月各部门销量"):
        contract = _plan(_adapter(_instant_dataset), query)
        template = contract["execution_ref"].get("query_template") or {}
        assert template.get("limit") is None, query


# ── 4. 分组维度不在数据集 ───────────────────────────────────────────────────────


def test_group_dimension_missing_in_dataset_is_clarified():
    """「各仓库销售额」：当前数据集没有仓库维度，必须澄清并给近似字段，不得静默丢掉分组诉求。"""
    contract = _plan(_adapter(_instant_dataset), "各仓库销售额 昨天")
    assert contract["status"] == "clarify_required"
    assert "dimension_not_in_dataset" in contract["model_view"]["clarification_reason_codes"]
    assert "仓库" in contract["model_view"]["unknown_requested_fields"]
    assert any(
        item.get("requested") == "仓库" for item in contract["model_view"]["field_suggestions_zh"]
    )
    assert "query_template" not in contract["execution_ref"]


def test_group_dimension_present_is_not_flagged():
    """「各平台」「各个部门」都能在数据集里找到，不得误报。"""
    for query in ("各平台销售额 昨天", "各个部门销售额 昨天", "近7天各部门每天的销售额", "各站点销售额 昨天"):
        contract = _plan(_adapter(_instant_dataset), query)
        assert "dimension_not_in_dataset" not in contract["model_view"].get(
            "clarification_reason_codes", []
        ), query


# ── 5. 指标别名映射必须披露 ─────────────────────────────────────────────────────


def test_metric_alias_mapping_is_disclosed():
    """「订单量」按数据集口径落到「销量」（order_qty）时，必须在合同里披露这次称呼替换。"""
    contract = _plan(_adapter(_instant_dataset), "本月各部门订单量")
    assert contract["status"] == "planned"
    assert contract["model_view"]["metrics"] == ["销量"]
    disclosures = " ".join(contract["answer_contract"]["required_disclosures_zh"])
    assert "订单量" in disclosures and "销量" in disclosures
    assert contract["model_view"]["field_alias_mappings_zh"] == [
        {"requested": "订单量", "field_zh": "销量", "field_name": "order_qty"}
    ]


def test_exact_metric_name_has_no_alias_disclosure():
    """原文直接写「销量」时没有称呼替换，不得多出无意义披露。"""
    contract = _plan(_adapter(_instant_dataset), "本月各部门销量")
    assert contract["status"] == "planned"
    assert "field_alias_mappings_zh" not in contract["model_view"]
    assert not any("订单量" in item for item in contract["answer_contract"]["required_disclosures_zh"])


# ── 6. 平台语义成员用展示名 ─────────────────────────────────────────────────────


def test_platform_semantic_members_use_display_labels():
    """model_view 是用户可见层，平台成员必须是展示名（Temu）而不是内部键（temu）。"""
    contract = _plan(_adapter(_instant_dataset), "近7天Temu销售额")
    assert contract["model_view"]["platform_semantic_members"] == ["Temu"]
    assert query_plan.PLATFORM_MEMBER_LABELS["tiktok"] == "TikTok"
