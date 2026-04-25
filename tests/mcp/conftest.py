import pytest

from opscli.mcp.context import configure_multi_user


@pytest.fixture(autouse=True)
def reset_mcp_context(monkeypatch):
    configure_multi_user(enabled=False, require_auth=False, base_dir=None)
    monkeypatch.delenv("OPSCLI_MCP_API_KEY", raising=False)
    yield
    configure_multi_user(enabled=False, require_auth=False, base_dir=None)
