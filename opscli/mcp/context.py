"""MCP Tool 上下文辅助函数。

本模块集中处理单用户兼容模式与多用户隔离模式的凭证目录选择，避免每个
Tool 重复解析环境变量、HTTP Header 或 FastMCP Context。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from opscli.mcp.user_store import MCPUserStore


_MULTI_USER_ENABLED = False
_REQUIRE_AUTH = False
_USER_STORE_BASE_DIR: Path | None = None


class MCPAuthError(PermissionError):
    """MCP API Key 鉴权失败。"""

    def __init__(self, message: str, *, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        """转换为统一错误结构。"""
        return {
            "code": "MCP_AUTH_ERROR",
            "message": str(self),
            "status_code": self.status_code,
        }


def configure_multi_user(
    *,
    enabled: bool,
    require_auth: bool = False,
    base_dir: Path | None = None,
) -> None:
    """配置 MCP Server 当前进程的多用户模式。"""
    global _MULTI_USER_ENABLED, _REQUIRE_AUTH, _USER_STORE_BASE_DIR
    _MULTI_USER_ENABLED = enabled
    _REQUIRE_AUTH = require_auth
    _USER_STORE_BASE_DIR = base_dir


def is_multi_user_enabled() -> bool:
    """返回当前进程是否启用多用户隔离。"""
    return _MULTI_USER_ENABLED


async def get_credential_dir(ctx: Any | None = None) -> Path | None:
    """根据当前 MCP 请求解析凭证目录。

    未启用多用户模式时返回 None，调用方会继续使用现有单用户凭证路径。
    启用后优先读取 FastMCP session state，其次解析 HTTP Authorization Header，
    最后回退到 stdio 场景常用的 `OPSCLI_MCP_API_KEY` 环境变量。
    """
    if not _MULTI_USER_ENABLED:
        return None

    token_dir = _credential_dir_from_access_token()
    if token_dir is not None:
        return token_dir

    if ctx is not None:
        state_value = await _get_state(ctx, "opscli_credential_dir")
        if state_value:
            return Path(state_value)

    api_key = _extract_api_key_from_http_headers() or os.getenv("OPSCLI_MCP_API_KEY")
    user = MCPUserStore(base_dir=_USER_STORE_BASE_DIR).verify_api_key(api_key)
    if user is None:
        status = 401 if not api_key else 403
        if _REQUIRE_AUTH or api_key:
            raise MCPAuthError("MCP API Key 缺失或无效", status_code=status)
        return None

    if ctx is not None:
        await _set_state(ctx, "opscli_credential_dir", str(user.credential_dir))
        await _set_state(ctx, "opscli_user_id", user.user_id)
    return user.credential_dir


def _extract_api_key_from_http_headers() -> str | None:
    """从当前 HTTP 请求头中提取 Bearer Token。"""
    try:
        from fastmcp.server.dependencies import get_http_headers

        headers = get_http_headers(include={"authorization"})
    except Exception:
        return None

    authorization = headers.get("authorization")
    if not authorization:
        return None
    return authorization


def _credential_dir_from_access_token() -> Path | None:
    """从 FastMCP HTTP 鉴权结果中读取凭证目录。"""
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        return None
    claims = getattr(token, "claims", None) if token is not None else None
    if isinstance(claims, dict) and claims.get("credential_dir"):
        return Path(str(claims["credential_dir"]))
    return None


async def _get_state(ctx: Any, key: str) -> Any:
    """兼容测试假对象与 FastMCP Context 的状态读取。"""
    getter = getattr(ctx, "get_state", None)
    if not callable(getter):
        return None
    return await getter(key)


async def _set_state(ctx: Any, key: str, value: str) -> None:
    """兼容测试假对象与 FastMCP Context 的状态写入。"""
    setter = getattr(ctx, "set_state", None)
    if callable(setter):
        await setter(key, value)
