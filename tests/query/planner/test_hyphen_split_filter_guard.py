"""复合筛选值被拆成相邻片段时的 fail-closed 守卫。

事故形态：「一部-B组」是当前账号真实存在的销售小组值，而「一部」是部门、
「B组」是大组。销售小组组件枚举正常时，跨字段区间抑制会把两个片段撤下、
只保留完整值；一旦该组件枚举抖动（调用成功但返回空），就没有更长的值来抑制，
模板会静默变成 dept_name=一部 AND large_team_name=B组——范围与用户原意
相差几十倍，合同却仍是 planned 且带着笃定的匹配说明。

用户不会用连字符把两个独立筛选连在一起，因此两个组件值在原文里被一个连字符
直接连成一段时必须转澄清，而不是放行一份语义已经变了的模板。
"""

from __future__ import annotations

from opscli.query.services.planner import query_plan


HEALTHY_ENUMS = {
    "dept_name": ["一部", "九部", "范泰克"],
    "large_team_name": ["A组", "B组"],
    "team_name": ["一部-A组", "一部-B组", "二部-A组"],
}


def _contract() -> dict:
    """最小可用合同：只声明三个互相有子串关系的筛选组件。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_reason_codes": [], "clarification_messages_zh": []},
        "execution_ref": {
            "query_template": {"filters": []},
            "filter_components": [
                {"field_name": "dept_name", "label_zh": "部门", "component_table_id": 1},
                {"field_name": "large_team_name", "label_zh": "大组", "component_table_id": 2},
                {"field_name": "team_name", "label_zh": "销售小组", "component_table_id": 3},
            ],
        },
    }


def _resolve(query: str, enums: dict[str, list[str]]) -> dict:
    def enum_fn(_table_id, field_name, *, limit):  # noqa: ARG001
        return list(enums.get(field_name, []))

    return query_plan._resolve_component_filters(
        _contract(), query, enum_fn, auto_enum=True
    )


def _filters(result: dict) -> list[dict]:
    template = (result.get("execution_ref") or {}).get("query_template") or {}
    return list(template.get("filters") or [])


def test_composite_value_wins_when_enum_healthy():
    """枚举正常时只下发完整销售小组值，不保留被拆开的部门与大组片段。"""
    result = _resolve("近7天一部-B组各平台的销售额", HEALTHY_ENUMS)

    assert result["status"] == "planned"
    assert {"field": "team_name", "operator": "=", "value": "一部-B组"} in _filters(result)
    assert not [item for item in _filters(result) if item["field"] == "dept_name"]
    assert not [item for item in _filters(result) if item["field"] == "large_team_name"]


def test_hyphen_split_blocks_template_when_composite_enum_unavailable():
    """销售小组枚举返回空时必须澄清，不得放行拆开后的两条筛选。"""
    degraded = dict(HEALTHY_ENUMS, team_name=[])

    result = _resolve("近7天一部-B组各平台的销售额", degraded)

    assert result["status"] == "clarify_required"
    codes = result["model_view"]["clarification_reason_codes"]
    assert "component_filter_value_unmatched" in codes
    message = "".join(result["model_view"]["clarification_messages_zh"])
    assert "一部-B组" in message
    assert (result["execution_ref"].get("query_template")) is None


def test_separate_values_joined_by_conjunction_still_apply():
    """用「和」并列的两个独立筛选不受影响，仍各自下发。"""
    result = _resolve("近7天各销售小组销售额，排除一部和B组", HEALTHY_ENUMS)

    assert result["status"] == "planned"
    operators = {
        (item["field"], item["operator"], item["value"]) for item in _filters(result)
    }
    assert ("dept_name", "!=", "一部") in operators
    assert ("large_team_name", "!=", "B组") in operators
