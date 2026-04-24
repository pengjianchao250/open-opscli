import asyncio

from opscli.mcp.context import MCPAuthError, configure_multi_user, get_credential_dir
from opscli.mcp.user_store import MCPUserStore


def _run(coro):
    return asyncio.run(coro)


def test_single_user_mode_returns_none(tmp_path):
    configure_multi_user(enabled=False, base_dir=tmp_path)

    assert _run(get_credential_dir()) is None


def test_multi_user_mode_uses_env_api_key(tmp_path, monkeypatch):
    store = MCPUserStore(base_dir=tmp_path)
    created = store.add_user(description="测试用户")
    monkeypatch.setenv("OPSCLI_MCP_API_KEY", created["api_key"])
    configure_multi_user(enabled=True, require_auth=True, base_dir=tmp_path)

    credential_dir = _run(get_credential_dir())

    assert credential_dir == store.credential_dir(created["user_id"])


def test_multi_user_mode_rejects_invalid_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSCLI_MCP_API_KEY", "opscli-mcp-invalid")
    configure_multi_user(enabled=True, require_auth=True, base_dir=tmp_path)

    try:
        _run(get_credential_dir())
    except MCPAuthError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected MCPAuthError")
