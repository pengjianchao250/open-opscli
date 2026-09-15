"""可信 AppHub 身份经过 Collector 认证与工具权限边界的回归测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp.exceptions import ToolError

from opscli.mcp import context, permissions
from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    """隔离请求上下文和 stdio 缓存，禁止读取测试机真实凭证。"""
    token = context.mcp_request_ctx.set(None)
    monkeypatch.setattr(context, "_get_scope_from_mcp_request_ctx", lambda: None)
    monkeypatch.setattr(permissions, "_stdio_cache", None)
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_session_id", lambda: None)
    yield
    context.mcp_request_ctx.reset(token)


@pytest.mark.parametrize("scope_only", [False, True])
def test_collector_trusted_identity_can_list_and_call_scenarios(monkeypatch, scope_only):
    """复现真实中间件组合，覆盖 contextvar 丢失后的 POST scope 降级。"""
    from opscli.mcp.tools.seller_sprite import seller_sprite_scenarios

    local_session = Mock(return_value=None)
    monkeypatch.setattr("opscli.mcp.tools.helpers._get_session_id", local_session)
    observed = {}

    async def app(scope, receive, send):
        assert scope["mcp_auth_mode"] == "internal"
        assert scope["mcp_permission_enabled"] is False
        if scope_only:
            context.mcp_request_ctx.set(None)
            monkeypatch.setattr(context, "_get_scope_from_mcp_request_ctx", lambda: scope)
        middleware = permissions.ToolPermissionMiddleware()
        tool = SimpleNamespace(name="seller_sprite_scenarios")

        async def list_next(_context):
            return [tool]

        async def call_next(_context):
            return await seller_sprite_scenarios()

        observed["tools"] = await middleware.on_list_tools(None, list_next)
        observed["result"] = await middleware.on_call_tool(
            SimpleNamespace(message=tool), call_next,
        )

    middleware = ApiKeyAuthMiddleware(
        app, api_key="regular-test-key", trust_upstream_apphub_identity=True,
    )
    scope = {
        "type": "http", "path": "/mcp", "method": "POST", "query_string": b"",
        "headers": [(b"x-apphub-user-email", b"user@example.com")],
    }
    asyncio.run(middleware(scope, None, None))
    assert [tool.name for tool in observed["tools"]] == ["seller_sprite_scenarios"]
    assert observed["result"]["success"] is True
    local_session.assert_not_called()


@pytest.mark.parametrize("auth_mode", ["internal", "apphub_session", "apphub_viewer", "apphub_local"])
@pytest.mark.parametrize("scope_only", [False, True])
def test_verified_identity_uses_request_policy(monkeypatch, auth_mode, scope_only):
    """可信身份仍遵守显式白名单；缺失策略时不继承服务器默认权限。"""
    stdio = Mock(side_effect=AssertionError("可信请求不得读取 stdio 权限"))
    monkeypatch.setattr(permissions, "_stdio_allowed_tools", stdio)
    data = {"auth_mode": auth_mode, "permission_enabled": False, "allowed_tools": None}
    if scope_only:
        monkeypatch.setattr(context, "_get_scope_from_mcp_request_ctx",
                            lambda: {f"mcp_{key}": value for key, value in data.items()})
    else:
        context.mcp_request_ctx.set(data)

    async def scenario():
        assert await permissions._resolve_allowed_tools() is None
        data.update(permission_enabled=True, allowed_tools=["seller_sprite_scenarios"])
        allowed = await permissions._resolve_allowed_tools()
        assert allowed == permissions.BASE_ALWAYS_ALLOWED_TOOLS | {"seller_sprite_scenarios"}

        async def call_next(_context):
            raise AssertionError("白名单外的工具不应执行")

        with pytest.raises(ToolError, match="无权限"):
            await permissions.ToolPermissionMiddleware().on_call_tool(
                SimpleNamespace(message=SimpleNamespace(name="seller_sprite_run")), call_next,
            )
        for enabled in (True, None):
            data.update(permission_enabled=enabled, allowed_tools=None)
            assert await permissions._resolve_allowed_tools() == permissions.BASE_ALWAYS_ALLOWED_TOOLS
        data.update(permission_enabled=True, allowed_tools=[])
        assert await permissions._resolve_allowed_tools() == permissions.BASE_ALWAYS_ALLOWED_TOOLS

    asyncio.run(scenario())
    stdio.assert_not_called()


def test_untrusted_identity_header_cannot_reach_tool_permissions():
    """未开启可信上游的入口仍拒绝伪造身份头。"""
    sent = []

    async def app(scope, receive, send):
        raise AssertionError("未受信任的身份不能进入工具层")

    async def send(message):
        sent.append(message)

    middleware = ApiKeyAuthMiddleware(app, api_key="regular-test-key")
    scope = {
        "type": "http", "path": "/mcp", "query_string": b"",
        "headers": [(b"x-apphub-user-email", b"user@example.com")],
    }
    asyncio.run(middleware(scope, None, send))
    assert sent[0]["status"] == 401


def test_unknown_auth_mode_cannot_disable_tool_permissions():
    """未知模式即使携带关闭标志，也不能被识别为可信 AppHub 请求。"""
    context.mcp_request_ctx.set({"auth_mode": "apphub_unverified", "permission_enabled": False})
    assert asyncio.run(permissions._resolve_allowed_tools()) == permissions.BASE_ALWAYS_ALLOWED_TOOLS


def test_partial_context_reads_missing_policy_from_scope(monkeypatch):
    """scope 补齐缺失开关，但不能覆盖 contextvar 中已有的空白名单。"""
    context.mcp_request_ctx.set({"auth_mode": "internal", "allowed_tools": []})
    scope = {"mcp_auth_mode": "internal", "mcp_permission_enabled": False,
             "mcp_allowed_tools": ["seller_sprite_run"]}
    monkeypatch.setattr(context, "_get_scope_from_mcp_request_ctx", lambda: scope)
    assert asyncio.run(permissions._resolve_allowed_tools()) is None
    scope["mcp_permission_enabled"] = True
    assert asyncio.run(permissions._resolve_allowed_tools()) == permissions.BASE_ALWAYS_ALLOWED_TOOLS
