import httpx
import pytest

from opscli.feedback.transport.client import FeedbackClient


class DummyAuthClient:
    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        assert alias == "ops"
        return (
            {"Authorization": "Bearer jwt-token"},
            {"polarisUserToken": "session-123"},
        )


def test_submit_sends_auth_headers_and_cookies(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    monkeypatch.setattr("opscli.feedback.transport.client.httpx.post", fake_post)
    client = FeedbackClient(auth_client=DummyAuthClient())

    result = client.submit({"type": "bug", "content": "test"})

    assert captured["url"].endswith("/v1/data-metrics/feedback")
    assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    assert captured["cookies"]["polarisUserToken"] == "session-123"
    assert result["message"] == "ok"


def test_submit_forwards_mcp_api_key_when_context_present(monkeypatch):
    """MCP 上下文存在时，请求头应透传 X-MCP-API-Key。"""
    from opscli.mcp.context import mcp_request_ctx

    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["headers"] = headers
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    monkeypatch.setattr("opscli.feedback.transport.client.httpx.post", fake_post)
    client = FeedbackClient(auth_client=DummyAuthClient())

    token = mcp_request_ctx.set({"api_key": "mcp_key_456"})
    try:
        client.submit({"type": "bug"})
        assert captured["headers"]["X-MCP-API-Key"] == "mcp_key_456"
        assert captured["headers"]["Authorization"] == "Bearer jwt-token"
    finally:
        mcp_request_ctx.reset(token)


def test_submit_no_mcp_header_when_context_absent(monkeypatch):
    """无 MCP 上下文时，不应附加 X-MCP-API-Key。"""
    captured = {}

    def fake_post(url, json=None, headers=None, cookies=None, timeout=None):
        captured["headers"] = headers
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    monkeypatch.setattr("opscli.feedback.transport.client.httpx.post", fake_post)
    client = FeedbackClient(auth_client=DummyAuthClient())

    client.submit({"type": "bug"})
    assert "X-MCP-API-Key" not in captured["headers"]
