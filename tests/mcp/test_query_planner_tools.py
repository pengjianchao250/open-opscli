"""MCP query_plan / query_flow 工具测试。"""

import asyncio

from opscli.mcp.tools import helpers
from opscli.mcp.tools import query as query_tools


def _run(coro):
    return asyncio.run(coro)


def _patch_identity(monkeypatch, email="u@x.com"):
    """统一注入已验证身份、凭证对与隔离目录、QueryManager。"""
    monkeypatch.setattr(helpers, "_get_authenticated_user_email", lambda: email)
    monkeypatch.setattr(helpers, "_get_auth_pair", lambda system, session_id, jwt: ("sid-1", "jwt-1"))
    monkeypatch.setattr(helpers, "_get_credential_dir", lambda: None)
    monkeypatch.setattr(query_tools, "_query_manager", lambda jwt=None, session_id=None: object())


def _contract():
    return {
        "contract": "query_plan_model_contract_v2",
        "status": "planned",
        "model_view": {"dataset_name_zh": "即时综合数据集"},
        "execution_ref": {},
    }


def test_query_plan_returns_contract(monkeypatch):
    """query_plan：解析身份→调 run_plan→_ok 包裹合同。"""
    _patch_identity(monkeypatch)
    captured = {}

    def _fake_run_plan(request, *, user_email, base_dir, requested_fields, top_n, query_manager):
        captured.update(
            request=request, user_email=user_email, base_dir=base_dir,
            requested_fields=list(requested_fields), top_n=top_n,
        )
        return _contract()

    monkeypatch.setattr(query_tools, "run_plan", _fake_run_plan)

    result = _run(query_tools.query_plan("查销售额", requested_fields=["销售额"], top_n=3))
    assert result["success"] is True
    assert result["data"]["contract"] == "query_plan_model_contract_v2"
    assert captured["request"] == "查销售额"
    assert captured["user_email"] == "u@x.com"
    assert captured["requested_fields"] == ["销售额"]
    assert captured["top_n"] == 3


def test_query_plan_requires_authenticated_email(monkeypatch):
    """无法确认已验证身份 → 失败闭合，不调 run_plan。"""
    monkeypatch.setattr(helpers, "_get_authenticated_user_email", lambda: None)
    called = {"n": 0}
    monkeypatch.setattr(query_tools, "run_plan", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    result = _run(query_tools.query_plan("查销售额"))
    assert result["success"] is False
    assert called["n"] == 0


def test_query_flow_returns_result(monkeypatch):
    """query_flow：调 run_flow→_ok 包裹（含 result）。"""
    _patch_identity(monkeypatch)

    def _fake_run_flow(request, *, user_email, base_dir, requested_fields, query_manager):
        return {**_contract(), "result": {"data": {"result": {"data": [{"销售额": 1}]}}}}

    monkeypatch.setattr(query_tools, "run_flow", _fake_run_flow)

    result = _run(query_tools.query_flow("查销售额 近7天"))
    assert result["success"] is True
    assert result["data"]["result"]["data"]["result"]["data"] == [{"销售额": 1}]


def test_planner_tools_registered():
    """query_plan / query_flow 已入 _ALL_TOOLS。"""
    names = {fn.__name__ for fn in query_tools._ALL_TOOLS}
    assert "query_plan" in names
    assert "query_flow" in names


def test_requested_fields_accepts_json_string(monkeypatch):
    """requested_fields 以 JSON 字符串传入时兼容解析。"""
    _patch_identity(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        query_tools,
        "run_plan",
        lambda request, **k: captured.update(fields=list(k["requested_fields"])) or _contract(),
    )
    result = _run(query_tools.query_plan("查销售额", requested_fields='["销售额","库存量"]'))
    assert result["success"] is True
    assert captured["fields"] == ["销售额", "库存量"]
