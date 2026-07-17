"""MCP 有效认证邮箱解析测试。"""

from pathlib import Path

from opscli.mcp.tools import helpers


class FakeCredentialCache:
    """仅提供测试所需邮箱读取的凭证缓存。"""

    def __init__(self, email: str | None):
        self.email = email

    def get_email(self) -> str | None:
        """返回测试配置的邮箱。"""
        return self.email


def test_authenticated_email_prefers_verified_context(monkeypatch):
    """远程校验上下文邮箱优先于任何本地缓存。"""
    monkeypatch.setattr("opscli.mcp.context.get_current_user_email", lambda: " Verified@Example.com ")
    monkeypatch.setattr("opscli.mcp.context.get_current_auth_mode", lambda: "remote")
    monkeypatch.setattr("opscli.mcp.context.get_current_api_key", lambda: "remote-key")
    monkeypatch.setattr(
        helpers,
        "_get_isolated_credential_cache",
        lambda cred_dir: (_ for _ in ()).throw(AssertionError("已验证邮箱不应读取缓存")),
    )

    assert helpers._get_authenticated_user_email() == "verified@example.com"


def test_authenticated_email_stdio_falls_back_to_default_cache(monkeypatch):
    """stdio 无 API key/模式时从默认 CredentialStore 缓存回退。"""
    calls = []
    monkeypatch.setattr("opscli.mcp.context.get_current_user_email", lambda: None)
    monkeypatch.setattr("opscli.mcp.context.get_current_auth_mode", lambda: None)
    monkeypatch.setattr("opscli.mcp.context.get_current_api_key", lambda: None)
    monkeypatch.setattr(
        helpers,
        "_get_isolated_credential_cache",
        lambda cred_dir: calls.append(cred_dir) or FakeCredentialCache(" Stdio@Example.com "),
    )

    assert helpers._get_authenticated_user_email() == "stdio@example.com"
    assert calls == [None]


def test_authenticated_email_fixed_uses_isolated_cache(monkeypatch):
    """fixed 模式只从当前 API-key 与 Agent 隔离目录读取邮箱。"""
    isolated_dir = Path("isolated-credentials")
    calls = []
    monkeypatch.setattr(
        "opscli.mcp.context.get_current_user_email",
        lambda: "unverified-transport@example.com",
    )
    monkeypatch.setattr("opscli.mcp.context.get_current_auth_mode", lambda: "fixed")
    monkeypatch.setattr("opscli.mcp.context.get_current_api_key", lambda: "fixed-key")
    monkeypatch.setattr(helpers, "_get_credential_dir", lambda: isolated_dir)
    monkeypatch.setattr(
        helpers,
        "_get_isolated_credential_cache",
        lambda cred_dir: calls.append(cred_dir) or FakeCredentialCache(" Fixed@Example.com "),
    )

    assert helpers._get_authenticated_user_email() == "fixed@example.com"
    assert calls == [isolated_dir]


def test_authenticated_email_remote_without_verified_email_fails_closed(monkeypatch):
    """remote 缺 verified email 时不得回退默认或隔离凭证。"""
    monkeypatch.setattr("opscli.mcp.context.get_current_user_email", lambda: None)
    monkeypatch.setattr("opscli.mcp.context.get_current_auth_mode", lambda: "remote")
    monkeypatch.setattr("opscli.mcp.context.get_current_api_key", lambda: "remote-key")
    monkeypatch.setattr(
        helpers,
        "_get_isolated_credential_cache",
        lambda cred_dir: (_ for _ in ()).throw(AssertionError("remote 缺邮箱不得读取缓存")),
    )

    assert helpers._get_authenticated_user_email() is None


def test_authenticated_email_unknown_mode_with_api_key_fails_closed(monkeypatch):
    """存在 API key 但模式未知时不得信任 transport 邮箱或猜测缓存。"""
    monkeypatch.setattr(
        "opscli.mcp.context.get_current_user_email",
        lambda: "unverified-transport@example.com",
    )
    monkeypatch.setattr("opscli.mcp.context.get_current_auth_mode", lambda: None)
    monkeypatch.setattr("opscli.mcp.context.get_current_api_key", lambda: "unknown-key")
    monkeypatch.setattr(
        helpers,
        "_get_isolated_credential_cache",
        lambda cred_dir: (_ for _ in ()).throw(AssertionError("未知认证模式不得读取缓存")),
    )

    assert helpers._get_authenticated_user_email() is None
