"""Collector 代理错误诊断与凭证脱敏回归测试。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tools.collector_proxy import call_collector
from opscli.mcp_client import RemoteMcpToolError


def _invoke(monkeypatch, caplog, outcome, *, mode="apphub_session", tool="seller_sprite_run"):
    """使用真实代理和请求上下文，仅替换远端网络客户端。"""
    class RemoteClient:
        def __init__(self, url, *, headers):
            self.url = url

        async def call_tool(self, tool_name, arguments):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setenv("OPSCLI_COLLECTOR_MCP_URL",
                       "https://url-user:url-password@collector.example/mcp?ticket=url-ticket#url-fragment")
    caplog.set_level("WARNING", logger="opscli.mcp.tools.collector_proxy")
    token = mcp_request_ctx.set({
        "auth_mode": mode, "email": "diagnostic@example.com", "api_key": "request-api-secret",
        "session_id": "request-session-secret", "jwt": "request-jwt-secret",
    })
    try:
        return asyncio.run(call_collector(tool, {}, client_factory=RemoteClient))
    finally:
        mcp_request_ctx.reset(token)


def _diagnostic(caplog):
    """检查单条失败记录并解析结构化诊断字段。"""
    records = [r for r in caplog.records if r.name == "opscli.mcp.tools.collector_proxy"]
    assert len(records) == 1
    return json.loads(records[0].getMessage().split("diagnostic=", 1)[1])


def test_remote_tool_error_retains_safe_detail_without_changing_response(monkeypatch, caplog):
    error = RemoteMcpToolError("remote tool failed", result=SimpleNamespace(), raw_text=json.dumps({
        "error": {"code": "APPHUB_IDENTITY_MISSING", "message": "Collector missing trusted identity",
                  "debug": {"cookie": "must-not-log-debug"}},
    }))
    result = _invoke(monkeypatch, caplog, error)
    assert result["error"]["code"] == "COLLECTOR_MCP_CALL_FAILED"
    assert "Collector missing trusted identity" not in result["error"]["message"]
    diagnostic = _diagnostic(caplog)
    assert diagnostic["remote_code"] == "APPHUB_IDENTITY_MISSING"
    assert diagnostic["remote_message"] == "Collector missing trusted identity"
    assert diagnostic["collector_target"] == "https://collector.example/mcp"
    assert diagnostic["auth_mode"] == "apphub_session"
    assert diagnostic["identity_forwarded"] is True
    assert diagnostic["session_forwarded"] is True
    assert diagnostic["jwt_forwarded"] is True
    assert diagnostic["elapsed_ms"] >= 0
    for secret in ("must-not-log-debug", "url-user", "url-password", "url-ticket", "url-fragment"):
        assert secret not in caplog.text


@pytest.mark.parametrize("mode,tool,forwarded,identity", [
    ("apphub_session", "seller_sprite_scenarios", False, True),
    ("apphub_viewer", "seller_sprite_run", True, True),
    ("remote", "seller_sprite_run", False, False),
])
def test_diagnostics_report_actual_forwarding(monkeypatch, caplog, mode, tool, forwarded, identity):
    outcome = {"success": False, "error": {"code": "COLLECTOR_MODULE_NOT_READY", "message": "bundle not ready"}}
    assert _invoke(monkeypatch, caplog, outcome, mode=mode, tool=tool) is outcome
    diagnostic = _diagnostic(caplog)
    assert diagnostic["session_forwarded"] is forwarded
    assert diagnostic["jwt_forwarded"] is forwarded
    assert diagnostic["identity_forwarded"] is identity
    assert diagnostic["remote_message"] == "bundle not ready"


def test_error_summary_redacts_credentials_and_cannot_inject_log_lines(monkeypatch, caplog):
    secrets = ("foreign-bearer", "cookie-one", "cookie-two", "foreign-jwt", "foreign password",
               "foreign-session", "foreign-key", "foreign-access", "foreign-polaris",
               "request-api-secret", "request-session-secret", "request-jwt-secret",
               "diagnostic@example.com", "other-user", "other-password", "other-secret",
               "eyJhbGciOiJIUzI1NiJ9", "signature")
    message = (
        'validation failed\nAuthorization: Bearer foreign-bearer\n'
        'Cookie: first=cookie-one; second=cookie-two\n'
        'jwt="foreign-jwt" password="foreign password" session_id=foreign-session '
        'api_key=foreign-key apphubAccessToken=foreign-access polarisUserToken=foreign-polaris '
        'request-api-secret request-session-secret request-jwt-secret diagnostic@example.com '
        'https://other-user:other-password@other.example/mcp?secret=other-secret '
        'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature ' + ' detail' * 400
    )
    _invoke(monkeypatch, caplog, RemoteMcpToolError(message, result=SimpleNamespace(), raw_text=message))
    summary = _diagnostic(caplog)["remote_message"]
    assert "validation failed" in summary
    assert len(summary) <= 1024
    assert "\n" not in summary
    for secret in secrets:
        assert secret not in caplog.text


@pytest.mark.parametrize("kind", ["http", "remote", "timeout"])
def test_nested_errors_include_downstream_details(monkeypatch, caplog, kind):
    request = httpx.Request("POST", "https://collector.example/mcp")
    if kind == "http":
        cause = httpx.HTTPStatusError("Collector rejected request", request=request,
                                     response=httpx.Response(401, request=request))
    elif kind == "remote":
        cause = RemoteMcpToolError("Tool not found", result=SimpleNamespace(), raw_text="Tool not found")
    else:
        cause = httpx.ConnectTimeout("Collector timed out", request=request)
    result = _invoke(monkeypatch, caplog, ExceptionGroup("transport failed", [cause]))
    diagnostic = _diagnostic(caplog)
    if kind == "http":
        assert diagnostic["downstream_status"] == 401
    elif kind == "remote":
        assert diagnostic["remote_message"] == "Tool not found"
    else:
        assert result["error"]["code"] == "COLLECTOR_MCP_UNAVAILABLE"
        assert diagnostic["remote_message"] == "Collector timed out"


def test_missing_configuration_is_logged(monkeypatch, caplog):
    monkeypatch.delenv("OPSCLI_COLLECTOR_MCP_URL", raising=False)
    caplog.set_level("WARNING", logger="opscli.mcp.tools.collector_proxy")
    result = asyncio.run(call_collector("seller_sprite_scenarios", {}))
    assert result["error"]["code"] == "COLLECTOR_MCP_CONFIG_MISSING"
    assert _diagnostic(caplog)["stage"] == "configuration"


def test_success_does_not_emit_failure_log(monkeypatch, caplog):
    outcome = {"success": True, "data": {"scenarios": []}}
    assert _invoke(monkeypatch, caplog, outcome) is outcome
    assert not caplog.records


def test_structured_error_wins_over_other_transport_errors(monkeypatch, caplog):
    """远端结构化错误不能被同一异常组的清理失败覆盖。"""
    remote = RemoteMcpToolError(
        "Remote error", result=SimpleNamespace(structuredContent={
            "error": {"code": "TOOL_NOT_FOUND", "message": "Unknown tool seller_sprite_run"},
            "credentials": {"jwt": "never-log-response-dump"},
        }),
    )
    error = ExceptionGroup("cleanup failed", [remote, httpx.ReadError("stream closed")])
    _invoke(monkeypatch, caplog, error)
    diagnostic = _diagnostic(caplog)
    assert diagnostic["remote_message"] == "Unknown tool seller_sprite_run"
    assert diagnostic["remote_code"] == "TOOL_NOT_FOUND"
    assert "never-log-response-dump" not in caplog.text


def test_error_code_is_also_redacted(monkeypatch, caplog):
    """远端错误码来自不可信响应，不能成为绕过摘要脱敏的出口。"""
    outcome = {"success": False, "error": {
        "code": "request-api-secret", "message": {"jwt": "never-log-nested-message"},
    }}
    assert _invoke(monkeypatch, caplog, outcome) is outcome
    assert _diagnostic(caplog)["remote_code"] == "[REDACTED]"
    assert "request-api-secret" not in caplog.text
    assert "never-log-nested-message" not in caplog.text
