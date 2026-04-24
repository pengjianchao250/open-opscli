import asyncio
from pathlib import Path

from opscli.auth import AuthClient
from opscli.mcp.context import configure_multi_user, get_credential_dir
from opscli.mcp.user_store import MCPUserStore


def _run(coro):
    return asyncio.run(coro)


def test_two_api_keys_use_different_credential_directories(tmp_path: Path, monkeypatch):
    store = MCPUserStore(base_dir=tmp_path)
    user_a = store.add_user(description="A")
    user_b = store.add_user(description="B")
    configure_multi_user(enabled=True, require_auth=True, base_dir=tmp_path)

    monkeypatch.setenv("OPSCLI_MCP_API_KEY", user_a["api_key"])
    dir_a = _run(get_credential_dir())
    AuthClient(base_dir=dir_a)._store.save_session("session-a", "a@example.com", "2099-01-01T00:00:00+00:00")

    monkeypatch.setenv("OPSCLI_MCP_API_KEY", user_b["api_key"])
    dir_b = _run(get_credential_dir())
    AuthClient(base_dir=dir_b)._store.save_session("session-b", "b@example.com", "2099-01-01T00:00:00+00:00")

    assert dir_a != dir_b
    assert AuthClient(base_dir=dir_a)._store.load()["session_id"] == "session-a"
    assert AuthClient(base_dir=dir_b)._store.load()["session_id"] == "session-b"
