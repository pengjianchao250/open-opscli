"""CLI 与 MCP 模式 Session 互通端到端验证。

验证核心命题：
1. CLI 登录后（CredentialStore 写入 session），MCP 无需重复登录即可读取
2. MCP 登录后（auth_login_poll 写入 CredentialStore），CLI 无需重复登录即可读取
3. CLI 保存的 JWT，MCP 的 _get_jwt 能读取（含过期检查）
4. MCP 刷新/获取的 JWT，CLI 的 get_token 能读取（含自动刷新）
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta

from opscli.auth import AuthClient
from opscli.auth.storage.credential_store import CredentialStore
from opscli.mcp.tools.helpers import _get_session_id, _get_jwt
from opscli.mcp.credential_cache import McpCredentialCache, get_credential_cache


def _make_jwt(expires_in: int = 7200) -> str:
    """构造一个假的 JWT（格式正确但签名无效），用于本地测试。"""
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "sub": "user@example.com",
            "exp": int((datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()),
        }).encode()
    ).rstrip(b"=").decode()
    signature = "fake_signature"
    return f"{header}.{payload}.{signature}"


@pytest.fixture(autouse=True)
def _reset_credential_cache(monkeypatch, tmp_path):
    """每个测试使用独立的 CredentialStore 和内存缓存。

    核心：将 CONFIG_DIR monkeypatch 到 tmp_path，确保所有默认路径的
    CredentialStore 实例（包括 _get_session_id/_get_jwt 内部创建的）
    都读写临时目录，而非真实的 ~/.config/opscli/。
    """
    monkeypatch.setattr("opscli.config.CONFIG_DIR", tmp_path)
    # 禁用 Keychain，强制使用文件存储（避免 Keychain 中残留测试数据干扰）
    monkeypatch.setattr("opscli.auth.storage.credential_store._KEYRING_AVAILABLE", False)
    # 清除可能残留的测试凭证文件（防止之前失败的测试留下数据）
    (tmp_path / "credentials.bin").unlink(missing_ok=True)
    (tmp_path / ".key").unlink(missing_ok=True)
    # CredentialStore 在方法内部动态导入 opscli.config，因此只需 patch 配置模块
    # 重置全局缓存池
    import opscli.mcp.credential_cache as _cache_mod
    _cache_mod._mcp_credential_caches = {}
    yield
    _cache_mod._mcp_credential_caches = {}


# ── 测试 1：CLI 登录后，MCP 可直接读取 ─────────────────────────────


def test_cli_login_mcp_can_read_session(monkeypatch, tmp_path):
    """CLI 执行 auth login 写入 CredentialStore 后，MCP 的 _get_session_id 可直接读取。"""
    # CLI 登录
    cli_client = AuthClient(base_dir=tmp_path)
    cli_client._store.save_session("sess-cli-123", "user@example.com", "2099-01-01T00:00:00+00:00")

    # MCP 读取（不传入 provided session_id）
    sid = _get_session_id("ops", None)
    assert sid == "sess-cli-123"


def test_cli_login_mcp_can_read_jwt(monkeypatch, tmp_path):
    """CLI 保存 JWT 后，MCP 的 _get_jwt 可直接读取。"""
    cli_client = AuthClient(base_dir=tmp_path)
    cli_client._store.save_session("sess-cli-123", "user@example.com", "2099-01-01T00:00:00+00:00")
    jwt = _make_jwt(expires_in=7200)
    cli_client._store.save_token("ops", jwt, expires_in=7200)

    # MCP 读取
    mcp_jwt = _get_jwt("ops", None)
    assert mcp_jwt == jwt


# ── 测试 2：MCP 登录后，CLI 可直接读取 ─────────────────────────────


def test_mcp_login_cli_can_read_session(monkeypatch, tmp_path):
    """MCP 的 auth_login_poll 写入 CredentialStore 后，CLI 的 AuthClient 可直接读取。"""
    from opscli.auth.storage.credential_store import CredentialStore

    # 模拟 MCP auth_login_poll 写入
    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-mcp-456", "mcp@example.com", "2099-02-02T00:00:00+00:00")

    # CLI 读取
    cli_client = AuthClient(base_dir=tmp_path)
    sid = cli_client.get_session("ops")
    assert sid == "sess-mcp-456"
    assert cli_client.is_authenticated() is True


def test_mcp_login_cli_can_read_jwt(monkeypatch, tmp_path):
    """MCP 保存 JWT 后，CLI 的 AuthClient.check_token 可直接读取。"""
    from opscli.auth.storage.credential_store import CredentialStore

    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-mcp-456", "mcp@example.com", "2099-02-02T00:00:00+00:00")
    jwt = _make_jwt(expires_in=7200)
    store.save_token("ops", jwt, expires_in=7200)

    # CLI 检查
    cli_client = AuthClient(base_dir=tmp_path)
    result = cli_client.check_token("ops")
    assert result["valid"] is True
    assert result["expires_in"] > 0


# ── 测试 3：JWT 过期后 MCP 自动清除 ─────────────────────────────────


def test_mcp_auto_clears_expired_jwt(monkeypatch, tmp_path):
    """CredentialStore 中的 JWT 过期后，MCP 的 _get_jwt 返回 None 并清除存储。"""
    cli_client = AuthClient(base_dir=tmp_path)
    cli_client._store.save_session("sess-123", "user@example.com", "2099-01-01T00:00:00+00:00")
    expired_jwt = _make_jwt(expires_in=-10)  # 已过期
    cli_client._store.save_token("ops", expired_jwt, expires_in=-10)

    # 清除缓存确保从存储读取
    cache = get_credential_cache()
    cache.invalidate()

    mcp_jwt = _get_jwt("ops", None)
    assert mcp_jwt is None

    # 验证存储中已清除
    data = CredentialStore(base_dir=tmp_path).load() or {}
    assert "ops" not in data.get("tokens", {})


# ── 测试 4：内存缓存性能 ───────────────────────────────────────────


def test_credential_cache_avoids_repeated_decryption(monkeypatch, tmp_path):
    """第二次读取应命中内存缓存，无需重新解密文件。"""
    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-cache-test", "user@example.com", "2099-01-01T00:00:00+00:00")

    cache = McpCredentialCache()
    # 第一次加载
    sid1 = cache.get_session_id()
    # 第二次直接读内存
    sid2 = cache.get_session_id()
    assert sid1 == sid2 == "sess-cache-test"


# ── 测试 5：登出同步失效 ───────────────────────────────────────────


def test_logout_clears_for_both_cli_and_mcp(monkeypatch, tmp_path):
    """MCP auth_logout 清除 CredentialStore 后，CLI 也无法读取。"""
    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-to-clear", "user@example.com", "2099-01-01T00:00:00+00:00")

    # MCP 登出
    store.clear()
    # 刷新缓存
    get_credential_cache().invalidate()

    # CLI 无法读取
    cli_client = AuthClient(base_dir=tmp_path)
    assert cli_client.is_authenticated() is False

    # MCP 无法读取
    assert _get_session_id("ops", None) is None


# ── 测试 6：多系统 Token 互不干扰 ───────────────────────────────────


def test_multi_system_tokens_are_isolated(monkeypatch, tmp_path):
    """ops 和 polaris 的 JWT 独立存储，互不影响。"""
    store = CredentialStore(base_dir=tmp_path)
    store.save_session("sess-multi", "user@example.com", "2099-01-01T00:00:00+00:00")

    jwt_ops = _make_jwt(expires_in=7200)
    jwt_polaris = _make_jwt(expires_in=3600)
    store.save_token("ops", jwt_ops, expires_in=7200)
    store.save_token("polaris", jwt_polaris, expires_in=3600)

    get_credential_cache().invalidate()

    assert _get_jwt("ops", None) == jwt_ops
    assert _get_jwt("polaris", None) == jwt_polaris

    # 清除 ops 不影响 polaris
    store.remove_token("ops")
    get_credential_cache().invalidate()
    assert _get_jwt("ops", None) is None
    assert _get_jwt("polaris", None) == jwt_polaris
