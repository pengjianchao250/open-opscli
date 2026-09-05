"""规划器工具「登录态失效 → 强制重登 → 重试一次」的自愈回归测试。

背景：ensure_ops_credentials 平时只在 `is_authenticated()` 为假时自动登录，而它只比对
本地 `session_expires_at`；被服务端登出/吊销的 Session 在本地依然显示未过期，自动登录
因此永远不触发，调用方恒拿 401（生产会话 5384 即此形态）。本文件钉住三件事：
何时该重登、重登后必须用新凭证重跑一次、自愈失败不得盖掉原本的阻断原因。
"""

from __future__ import annotations

import asyncio

import pytest

from opscli.mcp.tools import query as query_tools


def _blocked_contract() -> dict:
    """登录态失效被阻断的合同。"""
    return {
        "status": "blocked",
        "model_view": {
            "component_filter_state": "auth_required",
            "next_action": "reauthenticate",
        },
    }


def _planned_contract() -> dict:
    """重登后成功规划的合同。"""
    return {"status": "planned", "model_view": {"component_filter_state": "resolved"}}


# ── 触发条件 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "contract, expected",
    [
        ({"model_view": {"component_filter_state": "auth_required"}}, True),
        ({"model_view": {"component_filter_state": "enum_failed"}}, False),
        ({"model_view": {"component_filter_state": "clarify_required"}}, False),
        ({"model_view": {}}, False),
        ({}, False),
        ({"model_view": "不是 dict"}, False),
        ("不是 dict", False),
        (None, False),
    ],
)
def test_needs_reauth_only_for_auth_required(contract, expected):
    """只有 auth_required 才触发重登：其余阻断重登也救不了，白多打一次登录。"""
    assert query_tools._contract_needs_reauth(contract) is expected


# ── 自愈重试 ────────────────────────────────────────────────────────────────


def test_query_flow_retries_with_refreshed_credentials(monkeypatch):
    """撞到 auth_required 时强制重登一次，并用新凭证重跑一次规划。"""
    calls: list[dict] = []

    def fake_run_flow(request, **kwargs):
        calls.append(kwargs["query_manager"])
        return _blocked_contract() if len(calls) == 1 else _planned_contract()

    def fake_query_manager(jwt=None, session_id=None):
        return {"jwt": jwt, "session_id": session_id}

    async def fake_reauth():
        return "sess-new", "jwt-new"

    monkeypatch.setattr(query_tools, "run_flow", fake_run_flow)
    monkeypatch.setattr(query_tools, "_query_manager", fake_query_manager)
    monkeypatch.setattr(query_tools, "_reauth_credentials_for_retry", fake_reauth)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email", lambda: "u@example.com"
    )
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_credential_dir", lambda: None)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_auth_pair", lambda *a, **k: ("sess-old", "jwt-old")
    )

    result = asyncio.run(query_tools.query_flow("查昨天销售额"))

    assert result["success"] is True
    assert result["data"]["status"] == "planned"
    # 重跑必须换成新凭证，否则等于原样再撞一次 401
    assert calls == [
        {"jwt": "jwt-old", "session_id": "sess-old"},
        {"jwt": "jwt-new", "session_id": "sess-new"},
    ]


def test_query_flow_retries_at_most_once(monkeypatch):
    """重登后仍失败时不再重试：防 401 风暴，并如实保留阻断合同。"""
    calls: list[str] = []

    def fake_run_flow(request, **kwargs):
        calls.append("run")
        return _blocked_contract()

    async def fake_reauth():
        return "sess-new", "jwt-new"

    monkeypatch.setattr(query_tools, "run_flow", fake_run_flow)
    monkeypatch.setattr(query_tools, "_query_manager", lambda **k: k)
    monkeypatch.setattr(query_tools, "_reauth_credentials_for_retry", fake_reauth)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email", lambda: "u@example.com"
    )
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_credential_dir", lambda: None)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_auth_pair", lambda *a, **k: ("sess-old", "jwt-old")
    )

    result = asyncio.run(query_tools.query_flow("查昨天销售额"))

    assert len(calls) == 2
    assert result["data"]["model_view"]["component_filter_state"] == "auth_required"


def test_query_flow_keeps_original_contract_when_relogin_fails(monkeypatch):
    """重登拿不到凭证时保留原合同：自愈是增强项，不能盖掉要告诉用户的阻断原因。"""

    def fake_run_flow(request, **kwargs):
        return _blocked_contract()

    async def fake_reauth():
        return None, None

    monkeypatch.setattr(query_tools, "run_flow", fake_run_flow)
    monkeypatch.setattr(query_tools, "_query_manager", lambda **k: k)
    monkeypatch.setattr(query_tools, "_reauth_credentials_for_retry", fake_reauth)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email", lambda: "u@example.com"
    )
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_credential_dir", lambda: None)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_auth_pair", lambda *a, **k: ("sess-old", "jwt-old")
    )

    result = asyncio.run(query_tools.query_flow("查昨天销售额"))

    assert result["success"] is True
    assert result["data"]["model_view"]["next_action"] == "reauthenticate"


def test_query_plan_also_self_heals(monkeypatch):
    """query_plan 与 query_flow 同源，同样要能自愈。"""
    contracts = [_blocked_contract(), _planned_contract()]

    def fake_run_plan(request, **kwargs):
        return contracts.pop(0)

    async def fake_reauth():
        return "sess-new", "jwt-new"

    monkeypatch.setattr(query_tools, "run_plan", fake_run_plan)
    monkeypatch.setattr(query_tools, "_query_manager", lambda **k: k)
    monkeypatch.setattr(query_tools, "_reauth_credentials_for_retry", fake_reauth)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_authenticated_user_email", lambda: "u@example.com"
    )
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_credential_dir", lambda: None)
    monkeypatch.setattr(
        "opscli.mcp.tools.helpers._get_auth_pair", lambda *a, **k: ("sess-old", "jwt-old")
    )

    result = asyncio.run(query_tools.query_plan("查昨天销售额"))

    assert result["data"]["status"] == "planned"


def test_reauth_helper_swallows_failures(monkeypatch):
    """重登辅助函数吞掉任何异常返回 (None, None)，绝不把异常抛回工具主链路。"""

    async def boom(**kwargs):
        raise RuntimeError("login down")

    monkeypatch.setattr("opscli.mcp.ops_credentials.ensure_ops_credentials", boom)

    assert asyncio.run(query_tools._reauth_credentials_for_retry()) == (None, None)
