import pytest

from opscli.mcp.context import mcp_request_ctx


@pytest.fixture(autouse=True)
def reset_mcp_context(monkeypatch):
    """每个测试前重置 MCP 请求上下文。"""
    # 清除可能残留的 contextvar
    token = mcp_request_ctx.set(None)
    monkeypatch.delenv("OPSCLI_MCP_API_KEY", raising=False)
    yield
    mcp_request_ctx.reset(token)
