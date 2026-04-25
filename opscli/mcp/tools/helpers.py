"""MCP 工具共享辅助函数。

提供统一响应结构（_ok / _err）和各业务对象工厂函数，
避免在 auth / query / skills 各工具模块中重复实现。
"""

from __future__ import annotations

import base64
import json
from typing import Any


def _ok(data: Any) -> dict:
    """统一成功响应结构。

    Args:
        data: 任意业务数据

    Returns:
        {"success": True, "data": data, "error": None}
    """
    return {"success": True, "data": data, "error": None}


def _err(exc: Exception) -> dict:
    """统一失败响应结构，保留异常类型信息。

    优先调用异常上的 to_dict()（自定义业务异常），
    否则回退到 {code: ClassName, message: str}。

    Args:
        exc: 捕获到的异常

    Returns:
        {"success": False, "data": None, "error": {...}}
    """
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        error = to_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    return {"success": False, "data": None, "error": error}


def _auth_client() -> Any:
    """创建 AuthClient 实例（无状态，不读取本地凭证目录）。

    每次调用创建新实例，保证无状态设计。

    Returns:
        AuthClient 实例
    """
    from opscli.auth import AuthClient

    return AuthClient()


def _get_session_id(system: str = "ops", provided: str | None = None) -> str | None:
    """获取 session_id：优先使用调用方传入的，否则尝试从本地加载。

    Args:
        system:   目标系统别名（默认 "ops"）
        provided: 调用方显式传入的 session_id（优先级最高）

    Returns:
        可用的 session_id，或 None（均未找到）
    """
    if provided:
        return provided
    from opscli.mcp.session_store import get_session

    return get_session(system)


def _get_jwt(system: str = "ops", provided: str | None = None) -> str | None:
    """获取 JWT：优先使用调用方传入的，否则尝试从本地加载（含过期检查）。

    本地缓存的 JWT 如果已过期，会自动清除并返回 None，触发重新换取。

    Args:
        system:   目标系统别名（默认 "ops"）
        provided: 调用方显式传入的 JWT（优先级最高）

    Returns:
        有效的 JWT 字符串，或 None（不存在或已过期）
    """
    if provided:
        return provided
    from opscli.mcp.session_store import get_jwt, is_jwt_valid_locally

    jwt = get_jwt(system)
    if jwt and is_jwt_valid_locally(jwt):
        return jwt
    # 已过期则清除本地缓存
    if jwt:
        from opscli.mcp.session_store import clear_jwt

        clear_jwt(system)
    return None


def _get_auth_pair(
    system: str = "ops",
    provided_session: str | None = None,
    provided_jwt: str | None = None,
) -> tuple[str | None, str | None]:
    """获取认证凭据对 (session_id, jwt)。

    优先使用调用方传入的，其次从本地加载。
    JWT 会检查本地缓存是否过期，过期则自动清除。

    Args:
        system:           目标系统别名（默认 "ops"）
        provided_session: 调用方显式传入的 session_id
        provided_jwt:     调用方显式传入的 JWT

    Returns:
        (session_id, jwt) 元组，任一可能为 None
    """
    session_id = provided_session or _get_session_id(system)
    jwt = provided_jwt or _get_jwt(system)
    return session_id, jwt


def _query_manager(jwt: str | None = None, session_id: str | None = None) -> Any:
    """创建 QueryManager 实例，支持外部传入认证凭证。

    Args:
        jwt:        可选，已有 JWT Token
        session_id: 可选，OAuth 授权后的 Session ID

    Returns:
        QueryManager 实例
    """
    from opscli.query.services.manager import QueryManager

    return QueryManager(auth_client=_auth_client(), jwt=jwt, session_id=session_id)


def _registry() -> Any:
    """创建系统注册表实例，包含内置系统。

    Returns:
        SystemRegistry 实例（含 ops / polaris 内置系统）
    """
    from opscli.auth import BUILTIN_SYSTEMS
    from opscli.auth.core.system_registry import SystemRegistry

    return SystemRegistry(builtin_systems=BUILTIN_SYSTEMS)


def _decode_jwt_payload(jwt: str) -> dict:
    """解析 JWT payload（不验证签名），用于本地检查有效期。

    Args:
        jwt: 原始 JWT 字符串（header.payload.signature）

    Returns:
        解码后的 payload 字典

    Raises:
        ValueError: JWT 格式不合法（段数不为 3）
    """
    parts = jwt.split(".")
    if len(parts) != 3:
        raise ValueError("非法 JWT 格式")
    # JWT payload 使用 base64url 编码，需补齐 padding 后解码
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload))


async def _sync_systems_after_login(session_id: str) -> dict:
    """使用外部传入的 session_id 从 ops 后端同步系统列表。

    Args:
        session_id: OAuth 授权成功后的 Session ID

    Returns:
        {"synced": int, "systems": [...]}

    Raises:
        httpx.HTTPStatusError: 后端返回非 2xx 状态码
    """
    import httpx

    from opscli.auth import OPS_URL

    response = httpx.get(
        f"{OPS_URL}/api/v1/cli/systems",
        headers={"X-Session-Id": session_id},
        timeout=10,
    )
    response.raise_for_status()
    systems = response.json().get("systems", [])
    # 同步到本地系统注册表（按 alias 合并更新）
    _registry().sync_from_ops(systems)
    return {"synced": len(systems), "systems": systems}
