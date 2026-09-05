"""组件枚举故障的影响范围回归测试。

背景：`dept_name` 是 `_ENUM_COMPONENT_SPECS` 首项且 `reverse_lookup=True`，用户没提部门
也必发一次枚举；再加上 `_resolve_component_filters` 里"首个失败即 break"，部门组件一坏，
连「查昨天总销售额」这种压根不涉及部门的请求也会被一起 blocked。

本文件钉住两件相反的事：
  - 有文本级检测器、且原文没提到该字段 → 不阻断，但必须披露"本次未施加该筛选"；
  - 没有文本级检测器（渠道/国家/品牌等靠枚举反查识别裸值）→ 必须继续 fail-closed 阻断，
    否则「查傲彼瑞的销售额」会被静默放行成查全部渠道。
"""

from __future__ import annotations

import pytest

from opscli.query.services.planner import query_plan


def _contract(field_name: str, label_zh: str, table_id: int) -> dict:
    """构造带指定筛选组件的 planned 合同骨架（含 answer_contract 以便登记披露）。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "answer_contract": {"required_disclosures_zh": []},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": field_name,
                    "label_zh": label_zh,
                    "component_dataset_alias": f"ds_{field_name}",
                    "component_table_id": table_id,
                }
            ],
            "query_template": {"tableId": 1, "dimensions": [], "metrics": [], "filters": []},
        },
    }


def _resolve(contract: dict, query: str, exc: Exception) -> dict:
    """让枚举回调抛出指定异常，返回处理后的合同。"""

    def enum_fn(_table_id, _field_name, *, limit):
        raise exc

    return query_plan._resolve_component_filters(contract, query, enum_fn, auto_enum=True)


BOOM = RuntimeError("字段不存在")


def test_dept_has_text_level_detector():
    """部门是当前唯一配了自定义 extract 的枚举组件——该能力是本特性的前提。"""
    specs = {spec["field_name"]: spec for spec in query_plan._ENUM_COMPONENT_SPECS}

    assert query_plan._has_text_level_detector(specs["dept_name"]) is True
    for field in ("channel_name", "country_name", "brand_name", "team_name"):
        assert query_plan._has_text_level_detector(specs[field]) is False, field


def test_unrelated_query_survives_dept_enum_failure():
    """原文没提部门时，部门组件故障不得阻断整条查询。"""
    contract = _resolve(_contract("dept_name", "部门", 40), "查昨天的总销售额", BOOM)

    assert contract["status"] == "planned"
    assert "query_template" in contract["execution_ref"]


def test_skipped_component_is_disclosed_not_silent():
    """跳过必须留下必披露事项：放宽可以，但不能悄悄放宽。"""
    contract = _resolve(_contract("dept_name", "部门", 40), "查昨天的总销售额", BOOM)

    disclosures = contract["answer_contract"]["required_disclosures_zh"]
    assert len(disclosures) == 1
    assert "部门筛选组件本次不可用" in disclosures[0]
    assert "未施加部门筛选" in disclosures[0]
    assert "字段不存在" in disclosures[0]


def test_dept_mentioned_still_blocks():
    """原文点名了部门就必须继续阻断——枚举挂了就无法确认该部门是否在授权范围内。"""
    contract = _resolve(_contract("dept_name", "部门", 40), "查九部昨天的销售额", BOOM)

    assert contract["status"] == "blocked"
    assert "query_template" not in contract["execution_ref"]


@pytest.mark.parametrize(
    "field_name, label_zh, query",
    [
        ("channel_name", "渠道", "查昨天的总销售额"),
        ("country_name", "国家", "查昨天的总销售额"),
        ("brand_name", "品牌", "查昨天的总销售额"),
    ],
)
def test_fields_without_text_detector_still_fail_closed(field_name, label_zh, query):
    """没有文本级检测器的字段一律继续阻断。

    这些字段的裸值（如渠道「傲彼瑞」）只能靠枚举反查识别，枚举一挂就无从判断原文
    有没有提到它；此时放行等于把「查傲彼瑞的销售额」静默变成查全部渠道。
    """
    contract = _resolve(_contract(field_name, label_zh, 7), query, BOOM)

    assert contract["status"] == "blocked"
    assert "query_template" not in contract["execution_ref"]


def test_auth_failure_on_unrelated_field_also_skips():
    """认证类故障同样适用：原文没提部门就不该被部门连累。

    与 P0-2 的归因分流互补——归因解决"说错原因"，本条解决"不该被连累"。
    """
    from opscli.auth.exceptions import TokenFetchError

    contract = _resolve(
        _contract("dept_name", "部门", 40),
        "查昨天的总销售额",
        TokenFetchError("获取 ops JWT 失败: 401"),
    )

    assert contract["status"] == "planned"
    assert contract["answer_contract"]["required_disclosures_zh"]


def _multi_component_contract() -> dict:
    """部门 + 渠道两个组件的合同（真实数据集的形态：组件不止一个）。"""
    contract = _contract("dept_name", "部门", 40)
    contract["execution_ref"]["filter_components"].append(
        {
            "field_name": "channel_name",
            "label_zh": "渠道",
            "component_dataset_alias": "ds_channel",
            "component_table_id": 7,
        }
    )
    return contract


def test_only_broken_component_is_skipped_others_still_resolve():
    """只有坏掉的那个组件被跳过，其余组件照常参与解析。

    这是本特性真正的价值场景：部门组件元数据异常（单组件缺陷），而渠道等其余组件正常，
    此时不涉及部门的查询应当照常出数，而不是被首个失败的组件整条 break 掉。
    """
    contract = _multi_component_contract()

    def enum_fn(table_id, field_name, *, limit):
        if field_name == "dept_name":
            raise BOOM
        return ["傲彼瑞-美国", "莱福特-美国"]

    result = query_plan._resolve_component_filters(
        contract, "查昨天的总销售额", enum_fn, auto_enum=True
    )

    assert result["status"] == "planned"
    assert "query_template" in result["execution_ref"]
    assert "部门筛选组件本次不可用" in result["answer_contract"]["required_disclosures_zh"][0]


def test_broken_dept_does_not_mask_a_real_channel_clarification():
    """部门被跳过后，渠道该澄清还得澄清——跳过不等于放行整条链路。"""
    contract = _multi_component_contract()

    def enum_fn(table_id, field_name, *, limit):
        if field_name == "dept_name":
            raise BOOM
        return ["傲彼瑞-美国", "傲彼瑞-加拿大"]

    result = query_plan._resolve_component_filters(
        contract, "查渠道是傲彼瑞的销售额", enum_fn, auto_enum=True
    )

    assert result["status"] == "clarify_required"
