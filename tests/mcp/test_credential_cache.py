"""McpCredentialCache 多用户隔离测试。"""

import pytest
from opscli.auth.storage.credential_store import CredentialStore
from opscli.mcp.credential_cache import McpCredentialCache, get_credential_cache, invalidate_credential_cache


def test_credential_cache_with_different_base_dirs(tmp_path):
    """不同 base_dir 的 McpCredentialCache 应该互相隔离。"""
    dir_a = tmp_path / "user_a"
    dir_b = tmp_path / "user_b"

    cache_a = McpCredentialCache(base_dir=dir_a)
    cache_b = McpCredentialCache(base_dir=dir_b)

    # 用户 A 登录
    CredentialStore(base_dir=dir_a).save_session("sess-a", "a@example.com", "2099-01-01T00:00:00+00:00")
    cache_a.invalidate()

    # 用户 B 登录（不同 session）
    CredentialStore(base_dir=dir_b).save_session("sess-b", "b@example.com", "2099-01-01T00:00:00+00:00")
    cache_b.invalidate()

    # 缓存隔离验证
    assert cache_a.get_session_id() == "sess-a"
    assert cache_b.get_session_id() == "sess-b"
    assert cache_a.get_session_id() != cache_b.get_session_id()


def test_get_credential_cache_isolated_by_base_dir(tmp_path):
    """get_credential_cache() 按 base_dir 返回不同实例。"""
    dir_a = tmp_path / "user_a"
    dir_b = tmp_path / "user_b"

    cache_a = get_credential_cache(base_dir=dir_a)
    cache_b = get_credential_cache(base_dir=dir_b)

    # 同一 base_dir 返回同一实例
    assert get_credential_cache(base_dir=dir_a) is cache_a
    assert get_credential_cache(base_dir=dir_b) is cache_b

    # 不同 base_dir 返回不同实例
    assert cache_a is not cache_b


def test_invalidate_credential_cache_by_base_dir(tmp_path):
    """invalidate_credential_cache() 只刷新指定 base_dir 的缓存。"""
    dir_a = tmp_path / "user_a"
    dir_b = tmp_path / "user_b"

    CredentialStore(base_dir=dir_a).save_session("sess-a", "a@example.com", "2099-01-01T00:00:00+00:00")
    CredentialStore(base_dir=dir_b).save_session("sess-b", "b@example.com", "2099-01-01T00:00:00+00:00")

    cache_a = get_credential_cache(base_dir=dir_a)
    cache_b = get_credential_cache(base_dir=dir_b)

    # 修改用户 A 的存储
    CredentialStore(base_dir=dir_a).save_session("sess-a-new", "a@example.com", "2099-01-01T00:00:00+00:00")

    # 只刷新 A 的缓存
    invalidate_credential_cache(base_dir=dir_a)

    assert cache_a.get_session_id() == "sess-a-new"
    # B 的缓存不受影响
    assert cache_b.get_session_id() == "sess-b"


def test_credential_cache_default_base_dir(tmp_path, monkeypatch):
    """默认 base_dir（None）使用 CONFIG_DIR。"""
    # monkeypatch CONFIG_DIR 到临时目录，避免污染真实凭证
    # credential_store.py 内部在方法调用时动态导入 opscli.config，
    # 因此只需 monkeypatch 配置模块即可生效
    monkeypatch.setattr("opscli.config.CONFIG_DIR", tmp_path)

    cache = get_credential_cache()  # base_dir=None
    CredentialStore().save_session("default-sess", "user@example.com", "2099-01-01T00:00:00+00:00")
    cache.invalidate()

    assert cache.get_session_id() == "default-sess"
