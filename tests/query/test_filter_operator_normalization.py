"""filters 操作符符号形态必须在 payload 组装入口归一的回归测试。

事故形态：归一此前只作用于 `--where` 简写（走 _parse_where_condition），
而 `query simple` 的 filters 直接来自 --json / --payload / MCP 参数，
从不经过归一。手写 payload 里的 "=" 会被服务端硬拒：
「INVALID_PAYLOAD: 无效的过滤操作符: =; 支持: between, eq, gt, ...」。
线上 3987 条取数反馈中有 189 条卡在这里，全部来自绕过执行器直连的场景。

关键点：既有的 _validate_simple_filter_operators 已经支持嵌套 conditions
与 AND/OR 逻辑节点，只是此前仅在 validate_fields=True 时可达；
本次把它提到 build_simple 的无条件路径上，而不是另写一份更弱的实现。
"""

from __future__ import annotations

import pytest

from opscli.query.domain.exceptions import InvalidPayloadError
from opscli.query.services.manager import QueryManager


def _manager() -> QueryManager:
    # 只测 payload 组装，不需要 HTTP/凭证，绕过 __init__
    return QueryManager.__new__(QueryManager)


def _build(filters):
    return _manager().build_simple(
        table_id=2,
        metrics=[{"field": "price", "alias": "price", "aggregation": "SUM"}],
        filters=filters,
    )["payload"]["filters"]


@pytest.mark.parametrize(
    "symbol,expected",
    [(">=", "gte"), ("<=", "lte"), (">", "gt"), ("<", "lt"),
     ("=", "eq"), ("==", "eq"), ("!=", "ne"), ("<>", "ne"),
     ("neq", "ne"), ("notEquals", "ne")],
)
def test_symbol_operators_are_normalized(symbol: str, expected: str):
    """八种符号写法都要归一为服务端语义操作符。"""
    # 用数值作值：字符串单值 ne 还会继续改写为单元素 not_in，由下方专门的用例覆盖
    assert _build([{"field": "date_id", "operator": symbol, "value": 1}])[0]["operator"] == expected


@pytest.mark.parametrize("symbol", ["!=", "<>", "neq", "notEquals", "ne"])
def test_string_single_exclusion_is_sent_as_single_element_not_in(symbol: str):
    """字符串单值排除必须以单元素 not_in 下发。

    事故形态：「近7天各平台的销售额，剔除亚马逊VC」规划出 platform_name != Amazon VC，
    simple 接口却只返回 Amazon VC 一行。实测该接口的 ne 在平台、销售小组、大组、
    渠道、品牌、品类、SPU 上都会反转，单元素 not_in 在同批字段上全部正确。
    """
    filters = _build([{"field": "platform_name", "operator": symbol, "value": "Amazon VC"}])
    assert filters == [{"field": "platform_name", "operator": "not_in", "value": ["Amazon VC"]}]


def test_numeric_single_exclusion_keeps_ne():
    """数值单值排除保持 ne：服务端把数值字面量 not_in [0] 判成 0 行，而数值 ne 正确。"""
    filters = _build([{"field": "order_qty", "operator": "!=", "value": 0}])
    assert filters == [{"field": "order_qty", "operator": "ne", "value": 0}]


def test_nested_string_exclusion_is_rewritten_once():
    """嵌套条件里的字符串排除同样改写，重复归一不会把列表再包一层。

    build_simple 在 validate_fields=True 时会先后两次调用归一，必须幂等。
    """
    manager = _manager()
    filters = [{"operator": "AND", "conditions": [
        {"field": "team_name", "operator": "!=", "value": "一部-B组"},
    ]}]
    manager._validate_simple_filter_operators(filters)
    manager._validate_simple_filter_operators(filters)
    assert filters[0]["conditions"][0] == {
        "field": "team_name", "operator": "not_in", "value": ["一部-B组"],
    }


def test_semantic_operators_pass_through():
    """已是语义形态的操作符原样保留。"""
    filters = _build([
        {"field": "a", "operator": "in", "value": ["x"]},
        {"field": "b", "operator": "is_null"},
    ])
    assert [item["operator"] for item in filters] == ["in", "is_null"]


def test_nested_conditions_are_normalized():
    """嵌套在 AND/OR 逻辑节点里的操作符同样要归一。"""
    filters = _build([
        {"operator": "AND", "conditions": [
            {"field": "a", "operator": "!=", "value": 1},
            {"operator": "OR", "conditions": [{"field": "b", "operator": ">=", "value": 2}]},
        ]}
    ])
    inner = filters[0]["conditions"]
    assert inner[0]["operator"] == "ne"
    assert inner[1]["conditions"][0]["operator"] == "gte"
    assert filters[0]["operator"] == "AND", "逻辑操作符不得被当成比较符处理"


def test_unmappable_operator_fails_locally_with_full_hint():
    """无法归一的操作符要在客户端就报错，并附服务端支持的完整清单。

    在本地拦下比让服务端回一句「无效的过滤操作符」再让调用方去猜，
    能省掉一整轮网络往返。
    """
    with pytest.raises(InvalidPayloadError) as excinfo:
        _build([{"field": "a", "operator": "~="}])
    message = str(excinfo.value)
    assert "无效的过滤操作符" in message
    assert "eq" in message and "between" in message, f"缺少支持清单：{message}"


def test_no_filters_is_a_noop():
    """不带 filters 时不应报错，也不应凭空生成该键。"""
    payload = _manager().build_simple(
        table_id=2, metrics=[{"field": "price", "alias": "price"}]
    )["payload"]
    assert "filters" not in payload
