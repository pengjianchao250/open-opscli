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
     ("=", "eq"), ("==", "eq"), ("!=", "neq"), ("<>", "neq")],
)
def test_symbol_operators_are_normalized(symbol: str, expected: str):
    """八种符号写法都要归一为服务端语义操作符。"""
    assert _build([{"field": "date_id", "operator": symbol, "value": "x"}])[0]["operator"] == expected


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
    assert inner[0]["operator"] == "neq"
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
