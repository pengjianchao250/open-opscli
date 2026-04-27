"""MCP 凭证内存缓存。

为高频 Tool 调用提供零开销的凭证读取，避免每次请求都执行 AES-256-GCM 解密
或访问系统 Keychain。

生命周期：
    1. MCP Server 启动时（或首次访问）从 CredentialStore 加载凭证到内存
    2. 后续 Tool 调用直接读内存，~0.1ms 延迟
    3. 凭证变更（登录、刷新、登出）时调用 invalidate() 重新加载

线程安全：内部使用 threading.Lock 保护缓存数据。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


class McpCredentialCache:
    """MCP 凭证内存缓存，线程安全，支持多用户隔离。

    通过传入 base_dir 参数可为不同用户创建独立的凭证缓存，
    配合 MCPUserStore 的 credential_dir 实现多用户场景下的凭证隔离。
    """

    def __init__(self, base_dir: Any | None = None):
        from opscli.auth.storage.credential_store import CredentialStore
        from pathlib import Path

        self._store = CredentialStore(base_dir=Path(base_dir) if base_dir else None)
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """从 CredentialStore 加载凭证到内存。"""
        raw = self._store.load() or {}
        with self._lock:
            self._data = dict(raw)

    def invalidate(self) -> None:
        """凭证变更后刷新缓存。"""
        self._load()

    def get_session_id(self) -> str | None:
        """获取全局 session_id。"""
        with self._lock:
            return self._data.get("session_id")

    def get_email(self) -> str | None:
        """获取登录邮箱。"""
        with self._lock:
            return self._data.get("email")

    def get_jwt(self, system: str = "ops") -> str | None:
        """获取指定系统的有效 JWT（含过期检查）。

        如果 JWT 已过期，会自动清除并返回 None。

        Args:
            system: 系统别名（默认 "ops"）

        Returns:
            有效的 JWT 字符串，或 None
        """
        with self._lock:
            tokens = self._data.get("tokens", {})
            td = tokens.get(system)
            if not td or not td.get("jwt"):
                return None
            try:
                exp = datetime.fromisoformat(td["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > datetime.now(timezone.utc):
                    return td["jwt"]
            except (KeyError, ValueError):
                pass
            # 已过期：从缓存中移除（下次 _load 会从存储同步真实状态）
            del tokens[system]
            return None

    def list_tokens(self) -> list[str]:
        """返回所有已缓存 token 的系统别名列表。"""
        with self._lock:
            return list(self._data.get("tokens", {}).keys())

    def is_authenticated(self) -> bool:
        """检查是否存在未过期的全局 session。"""
        with self._lock:
            if not self._data.get("session_id"):
                return False
            try:
                exp = datetime.fromisoformat(self._data["session_expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                return exp > datetime.now(timezone.utc)
            except (KeyError, ValueError):
                return False


# 模块级缓存池：按 base_dir 区分不同用户的凭证缓存
# key 为 base_dir 字符串（None 表示默认路径），value 为 McpCredentialCache 实例
_mcp_credential_caches: dict[str | None, McpCredentialCache] = {}
_mcp_cache_lock = threading.Lock()


def get_credential_cache(base_dir: Any | None = None) -> McpCredentialCache:
    """获取 MCP 凭证缓存实例（懒加载），支持多用户隔离。

    Args:
        base_dir: 凭证存储目录，默认使用 CONFIG_DIR（~/.config/opscli/）。
                  多用户场景下传入 MCPUserStore 分配的 credential_dir。

    Returns:
        McpCredentialCache 实例
    """
    global _mcp_credential_caches
    key = str(base_dir) if base_dir else None
    if key not in _mcp_credential_caches:
        with _mcp_cache_lock:
            if key not in _mcp_credential_caches:
                _mcp_credential_caches[key] = McpCredentialCache(base_dir=base_dir)
    return _mcp_credential_caches[key]


def invalidate_credential_cache(base_dir: Any | None = None) -> None:
    """强制刷新指定 base_dir 的凭证缓存。

    Args:
        base_dir: 要刷新的缓存对应的凭证目录，None 表示默认路径。
    """
    key = str(base_dir) if base_dir else None
    with _mcp_cache_lock:
        cache = _mcp_credential_caches.get(key)
        if cache:
            cache.invalidate()
