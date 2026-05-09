"""MCP 工具共享辅助函数。

提供统一响应结构（_ok / _err）和各业务对象工厂函数，
避免在 auth / query / skills 各工具模块中重复实现。

2025-05-09 改造：支持按 API Key 隔离凭证存储，解决多用户共享 MCP Server
时的 session 串用问题。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


def _ok(data: Any) -> dict:
    """统一成功响应结构。

    Args:
        data: 任意业务数据

    Returns:
        {"success": True, "data": data, "error": None}
    """
    return {"success": True, "data": data, "error": None}


def _err(
    exc: Exception,
    *,
    tool: str | None = None,
    call_params: dict | None = None,
    auto_feedback: bool = True,
) -> dict:
    """统一失败响应结构，保留异常类型信息。

    优先调用异常上的 to_dict()（自定义业务异常），
    否则回退到 {code: ClassName, message: str}。

    当 auto_feedback=True 时，返回结构中包含 `feedback` 草案字段，
    供 AI Agent 在工具调用失败后自动调用 feedback_submit。

    Args:
        exc: 捕获到的异常
        tool: 可选，当前失败的工具名称或命令，例如 "MCP → query_simple(...)"
        call_params: 可选，实际传入的关键参数，用于构造 execution_summary
        auto_feedback: 是否自动生成 feedback 草案，默认 True

    Returns:
        {"success": False, "data": None, "error": {...}, "feedback": {...}}
    """
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        error = to_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}

    result: dict[str, Any] = {"success": False, "data": None, "error": error}

    if auto_feedback:
        result["feedback"] = _draft_feedback(tool=tool, call_params=call_params, error=error)

    return result


def _draft_feedback(
    tool: str | None = None,
    call_params: dict | None = None,
    error: dict | None = None,
) -> dict:
    """从失败上下文自动构造 feedback 草案。

    返回的 payload 可直接传给 feedback_submit，AI Agent 只需补充 title 和 content。

    Args:
        tool: 失败的工具或命令
        call_params: 调用参数
        error: _err 生成的 error dict

    Returns:
        包含 feedback_type、severity、execution_summary 的草案 dict
    """
    error_message = ""
    if error:
        code = error.get("code", "")
        message = error.get("message", "")
        if code and message:
            error_message = f"{code}: {message}"
        else:
            error_message = message or str(code)

    failed_call: dict[str, Any] = {
        "tool": tool or "MCP Tool",
        "call_params": call_params or {},
        "error_message": error_message or "未知错误",
        "reason": "待补充：请基于错误响应、metadata 或接口规则分析原因；不确定时标注为推测。",
        "fix_suggestion": "待补充：请记录已采用的修复方式，或给出下一步建议。",
    }

    return {
        "feedback_type": "bug",
        "severity": "medium",
        "source": "mcp",
        "execution_summary": {
            "summary": "MCP Tool 调用失败，自动构造反馈草案。",
            "failed_calls": [failed_call],
            "successful_calls": [],
            "final_resolution": "待补充：请检查调用参数或重试。",
        },
        "_hint": (
            "此草案由 MCP Server 自动生成。AI Agent 应调用 feedback_submit "
            "提交反馈，并补充 title 和 content 后提交。"
        ),
    }


def _get_credential_dir() -> Path | None:
    """获取当前请求对应的凭证隔离目录。

    在 HTTP/SSE 多用户模式下，根据当前请求的 API Key 生成独立目录。
    stdio 模式下返回 None，使用默认路径（与 CLI 互通）。

    Returns:
        隔离目录的 Path 对象，或 None（stdio 模式）
    """
    from opscli.mcp.context import get_current_api_key
    from opscli.mcp.key_based_storage import get_credential_dir_for_key
    from opscli.config import CONFIG_DIR

    api_key = get_current_api_key()
    if not api_key:
        return None  # stdio 模式或无上下文，使用默认路径

    base_root = Path(CONFIG_DIR) / "credentials_by_key"
    return get_credential_dir_for_key(api_key, base_root)


def _get_isolated_credential_cache(cred_dir: Path | None):
    """获取隔离的凭证缓存实例。

    Args:
        cred_dir: 隔离目录路径，None 时使用默认路径

    Returns:
        McpCredentialCache 实例
    """
    from opscli.mcp.credential_cache import get_credential_cache

    return get_credential_cache(base_dir=cred_dir)


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

    在 HTTP/SSE 多用户模式下，按当前请求的 API Key 隔离读取凭证，
    避免不同用户共享同一个 session。

    stdio 模式下与 CLI 共用同一套加密存储，实现登录态互通。

    Args:
        system:   目标系统别名（默认 "ops"），当前仅保留接口兼容
        provided: 调用方显式传入的 session_id（优先级最高）

    Returns:
        可用的 session_id，或 None（均未找到）
    """
    if provided:
        return provided

    cred_dir = _get_credential_dir()
    cache = _get_isolated_credential_cache(cred_dir)
    return cache.get_session_id()


def _get_jwt(system: str = "ops", provided: str | None = None) -> str | None:
    """获取 JWT：优先使用调用方传入的，否则尝试从本地加载（含过期检查）。

    在 HTTP/SSE 多用户模式下，按当前请求的 API Key 隔离读取凭证。

    Args:
        system:   目标系统别名（默认 "ops"）
        provided: 调用方显式传入的 JWT（优先级最高）

    Returns:
        有效的 JWT 字符串，或 None（不存在或已过期）
    """
    if provided:
        return provided

    cred_dir = _get_credential_dir()
    cache = _get_isolated_credential_cache(cred_dir)

    jwt = cache.get_jwt(system)
    if jwt:
        return jwt

    # 缓存未命中（可能 CLI 新登录或缓存过期）：直接从存储读取并刷新缓存
    cache.invalidate()
    jwt = cache.get_jwt(system)
    if jwt:
        return jwt

    # 存储中已过期：清除
    from opscli.auth.storage.credential_store import CredentialStore
    from opscli.mcp.credential_cache import invalidate_credential_cache

    if cred_dir:
        CredentialStore(base_dir=cred_dir).remove_token(system)
        invalidate_credential_cache(base_dir=cred_dir)
    else:
        CredentialStore().remove_token(system)
        invalidate_credential_cache()

    return None


def _get_auth_pair(
    system: str = "ops",
    provided_session: str | None = None,
    provided_jwt: str | None = None,
) -> tuple[str | None, str | None]:
    """获取认证凭据对 (session_id, jwt)。

    优先使用调用方传入的，其次从本地加载。
    JWT 会检查本地缓存是否过期，过期则自动清除。

    在 HTTP/SSE 多用户模式下，按当前 API Key 隔离读取凭证。

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
    from opscli.mcp.context import get_mcp_request_headers

    headers = {"X-Session-Id": session_id}
    headers.update(get_mcp_request_headers())

    response = httpx.get(
        f"{OPS_URL}/api/v1/cli/systems",
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    systems = response.json().get("systems", [])
    # 同步到本地系统注册表（按 alias 合并更新）
    _registry().sync_from_ops(systems)
    return {"synced": len(systems), "systems": systems}
