"""Auth 工具模块。

将 opscli auth 子模块的核心能力暴露为 MCP 工具（无状态设计）：
- auth_login_start      — 发起 Device Flow 登录第一步
- auth_login_poll       — 获取授权状态
- auth_get_token        — 获取指定系统 JWT
- auth_check_token      — 检测 JWT 有效性（纯本地）
- auth_is_authenticated — 检查 session_id 是否有效
- auth_token_refresh    — 刷新 JWT
- auth_system_list      — 列出所有已注册系统
- auth_system_add       — 添加用户自定义系统
- auth_system_remove    — 移除用户自定义系统
- auth_system_sync      — 从 ops 同步系统列表
- auth_build_request_auth — 构造请求认证参数
- auth_doctor           — 诊断 session 有效性与系统连通性

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from mcp.types import ToolAnnotations

# 按 API Key 隔离的待处理登录流缓存（device_code 存服务端，不暴露给客户端）
# 避免 device_code 出现在 ChatGPT 等客户端的上下文中，防止触发凭证确认弹框
_pending_flows: dict[str | None, dict] = {}

from .helpers import (
    _auth_client,
    _decode_jwt_payload,
    _err,
    _get_credential_dir,
    _ok,
    _registry,
    _sync_systems_after_login,
)


def _get_isolated_store():
    """获取当前请求对应的隔离 CredentialStore 实例。

    在 HTTP/SSE 多用户模式下，按 API Key 隔离存储。
    stdio 模式下使用默认路径。

    Returns:
        CredentialStore 实例
    """
    from opscli.auth.storage.credential_store import CredentialStore

    cred_dir = _get_credential_dir()
    if cred_dir:
        return CredentialStore(base_dir=cred_dir)
    return CredentialStore()


def _get_mcp_request_headers() -> dict | None:
    """获取当前 MCP 请求中的 API Key，用于向后端透传。

    Returns:
        包含 X-MCP-API-Key 的请求头字典，或 None（stdio 模式无上下文）
    """
    from opscli.mcp.context import get_current_api_key

    api_key = get_current_api_key()
    if api_key:
        return {"X-MCP-API-Key": api_key}
    return None


async def auth_login_start() -> dict:
    """发起 Device Flow 登录第一步，返回验证 URL 和用户码。

    调用后引导用户在浏览器中打开 verification_url 并输入 user_code，
    再调用 auth_login_poll（无需参数）获取授权结果。

    device_code 由服务端缓存，不会暴露给客户端，避免触发 ChatGPT 等平台的凭证确认弹框。
    """
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow
    from opscli.mcp.context import get_current_api_key

    try:
        # 无状态模式：store=None 不保存凭证，凭证由调用方管理
        # 向后端透传当前 API Key，便于 OPS 记录追踪
        flow = DeviceFlow(
            ops_url=OPS_URL,
            store=None,
            headers=_get_mcp_request_headers(),
        )
        data = await asyncio.to_thread(flow.request_device_code)

        # 将 device_code 存入服务端缓存，按 API Key 隔离
        # 不返回 device_code 给客户端，防止触发 ChatGPT 等平台的凭证确认弹框
        api_key = get_current_api_key()
        _pending_flows[api_key] = {
            "device_code": data["device_code"],
            "expires_at": time.time() + data.get("expires_in", 300),
        }

        # 只返回用户需要的信息，不暴露 device_code
        return _ok({
            "user_code": data.get("user_code"),
            "verification_url": data.get("verification_url"),
            "expires_in": data.get("expires_in", 300),
        })
    except Exception as exc:
        return _err(exc)


async def auth_login_poll(timeout: int = 5) -> dict:
    """单次请求检查 Device Flow 授权状态

    device_code 由服务端自动管理（auth_login_start 时已缓存），无需传入任何参数。
    授权成功后自动将 session_id 保存到 MCP 凭证存储，在 HTTP/SSE 多用户模式下按 API Key 隔离。

    ⚠️ 重要：本工具只做单次状态检查，AI Agent 需要自行控制轮询节奏和终止条件：

    轮询约束（AI Agent 必须遵守）：
    - 最大轮询次数：不超过 20 次（约 2-3 分钟）
    - 轮询间隔：3-5 秒
    - 超过最大次数仍未成功 → 停止轮询，告知用户"授权等待超时，请重新运行 auth_login_start 并尽快完成浏览器授权"

    Args:
        timeout: HTTP 请求超时秒数（默认 30s），不是轮询等待时长。后端接口通常 1-2 秒内返回

    返回结构中 data.status 字段指示当前状态及 AI Agent 必须执行的动作：

    ┌──────────────┬──────────────────────────────────────────────────┐
    │ status       │ AI Agent 动作                                    │
    ├──────────────┼──────────────────────────────────────────────────┤
    │ "authorized" │ ✅ 授权成功，凭证已保存，流程结束，告知用户已登录  │
    │ "pending"    │ 🔄 用户尚未完成授权，等待 3-5 秒后再次调用本工具   │
    │ "error"      │ ⚠️ 检查 data.retryable：true → 等待后重试；      │
    │              │    false → 停止轮询，将 data.error 展示给用户      │
    │ "expired"    │ ❌ 设备码已过期，停止轮询，引导用户重新调用         │
    │              │    auth_login_start                               │
    │ "denied"     │ ❌ 用户拒绝授权，停止轮询，告知用户已取消           │
    └──────────────┴──────────────────────────────────────────────────┘
    """
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow
    from opscli.mcp.context import get_current_api_key

    # 从服务端缓存取出 device_code，不依赖客户端传入
    api_key = get_current_api_key()
    pending = _pending_flows.get(api_key)
    if not pending:
        return _err(ValueError("没有待处理的登录流，请先调用 auth_login_start"))
    if time.time() > pending["expires_at"]:
        _pending_flows.pop(api_key, None)
        return _err(ValueError("登录流已过期，请重新调用 auth_login_start"))

    device_code = pending["device_code"]

    try:
        # 向后端透传当前 API Key，便于 OPS 记录追踪
        flow = DeviceFlow(
            ops_url=OPS_URL,
            store=None,
            headers=_get_mcp_request_headers(),
        )
        # poll_once 内部使用同步 httpx，请放到线程中执行，避免阻塞 MCP 事件循环。
        result = await asyncio.to_thread(flow.poll_once, device_code, timeout=timeout)

        # poll_once 返回 error 状态时直接透传（包含 retryable 标志）
        if isinstance(result, dict) and result.get("status") == "error":
            return _ok(result)

        status = result.get("status") if isinstance(result, dict) else None

        # 终态（成功/过期/拒绝）时清理服务端缓存
        if status in ("authorized", "expired", "denied"):
            _pending_flows.pop(api_key, None)

        # 授权成功时自动持久化保存 session_id（按 API Key 隔离）
        if status == "authorized":
            session_id = result.get("session_id")
            email = result.get("email", "")
            expires_at = result.get("expires_at", "")
            if session_id:
                store = _get_isolated_store()
                store.save_session(session_id, email, expires_at)
                # 刷新内存缓存，确保后续 Tool 调用立即可见
                from opscli.mcp.credential_cache import invalidate_credential_cache
                invalidate_credential_cache(base_dir=_get_credential_dir())
                result["saved_locally"] = True
        return _ok(result)
    except Exception as exc:
        return _err(exc)


async def auth_get_token(system: str = "ops", session_id: str | None = None) -> dict:
    """获取指定系统的有效 JWT。

    优先使用调用方传入的 session_id，其次尝试从本地加载。
    成功获取 JWT 后自动保存到 CredentialStore（按 API Key 隔离）。

    Args:
        system:     系统别名（默认 "ops"）
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
    """
    from opscli.mcp.tools.helpers import _get_session_id

    sid = _get_session_id(system, session_id)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        jwt = _auth_client().get_token_by_session(sid, system)
        # 解析 JWT payload 获取过期时间，默认 2 小时
        try:
            payload = _decode_jwt_payload(jwt)
            exp = payload.get("exp")
            if exp:
                expires_in = int(exp - datetime.now(timezone.utc).timestamp())
            else:
                expires_in = 7200
        except Exception:
            expires_in = 7200
        # 保存到隔离的 CredentialStore
        store = _get_isolated_store()
        store.save_token(system, jwt, expires_in)
        from opscli.mcp.credential_cache import invalidate_credential_cache
        invalidate_credential_cache(base_dir=_get_credential_dir())
        return _ok({"jwt": jwt, "source": "remote", "cached": True})
    except Exception as exc:
        return _err(exc)


async def auth_check_token(jwt: str | None = None, system: str = "ops") -> dict:
    """检测 JWT 有效性及剩余有效时间（秒）。纯本地解析，不向后端发请求。

    如果未提供 jwt，会自动检查本地 CredentialStore 缓存的 JWT（按 API Key 隔离）。

    Args:
        jwt:    可选，待检测的 JWT 字符串（为空则检查本地缓存）
        system: 系统别名（默认 "ops"，用于定位本地缓存的 JWT）
    """
    target_jwt = jwt
    if not target_jwt:
        store = _get_isolated_store()
        data = store.load() or {}
        td = data.get("tokens", {}).get(system)
        if td:
            target_jwt = td.get("jwt")
    if not target_jwt:
        return _ok({"valid": False, "expires_in": 0, "source": None})
    try:
        payload = _decode_jwt_payload(target_jwt)
        exp = payload.get("exp")
        if not exp:
            return _ok({"valid": True, "expires_in": -1, "source": "provided" if jwt else "local"})
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        valid = remaining > 0
        if not valid and not jwt:
            # 本地缓存已过期，自动清除
            store = _get_isolated_store()
            store.remove_token(system)
            from opscli.mcp.credential_cache import invalidate_credential_cache
            invalidate_credential_cache(base_dir=_get_credential_dir())
        return _ok({
            "valid": valid,
            "expires_in": max(0, remaining),
            "source": "provided" if jwt else "local",
        })
    except Exception as exc:
        return _err(exc)


async def auth_is_authenticated(session_id: str | None = None) -> dict:
    """检查 session_id 是否有效（尝试用其获取 JWT）。

    如果未提供 session_id，会自动尝试从本地加载已保存的 session。

    Args:
        session_id: 可选，待检查的 Session ID（为空则自动加载本地保存的）
    """
    from opscli.mcp.tools.helpers import _get_session_id

    sid = _get_session_id("ops", session_id)
    if not sid:
        return _ok({"authenticated": False, "source": None})
    try:
        _auth_client().get_token_by_session(sid, "ops")
        return _ok({"authenticated": True, "source": "provided" if session_id else "local"})
    except Exception:
        return _ok({"authenticated": False, "source": "provided" if session_id else "local"})


async def auth_token_refresh(system: str = "__all__", session_id: str | None = None) -> dict:
    """刷新指定系统 JWT 并保存到 CredentialStore（按 API Key 隔离）。

    优先使用调用方传入的 session_id，其次尝试从本地加载。

    Args:
        system:     系统别名，"__all__" 表示刷新所有系统
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
    """
    from opscli.mcp.tools.helpers import _get_session_id

    sid = _get_session_id("ops", session_id)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        client = _auth_client()

        def _save_jwt(alias: str, jwt: str) -> None:
            """解析过期时间并保存到隔离的 CredentialStore。"""
            try:
                payload = _decode_jwt_payload(jwt)
                exp = payload.get("exp")
                if exp:
                    expires_in = int(exp - datetime.now(timezone.utc).timestamp())
                else:
                    expires_in = 7200
            except Exception:
                expires_in = 7200
            store = _get_isolated_store()
            store.save_token(alias, jwt, expires_in)
            from opscli.mcp.credential_cache import invalidate_credential_cache
            invalidate_credential_cache(base_dir=_get_credential_dir())

        if system == "__all__":
            results = {}
            for sys in client._registry.list_all():
                alias = sys["alias"]
                try:
                    jwt = client.get_token_by_session(sid, alias)
                    _save_jwt(alias, jwt)
                    results[alias] = {"jwt": jwt, "ok": True, "cached": True}
                except Exception as e:
                    results[alias] = {"ok": False, "error": str(e)}
            return _ok(results)
        jwt = client.get_token_by_session(sid, system)
        _save_jwt(system, jwt)
        return _ok({"jwt": jwt, "cached": True})
    except Exception as exc:
        return _err(exc)


async def auth_system_list() -> dict:
    """列出所有已注册系统（builtin / local / ops_sync）。不需要认证。"""
    try:
        return _ok(_registry().list_all())
    except Exception as exc:
        return _err(exc)


async def auth_system_add(
    alias: str,
    url: str,
    key: str | None = None,
    token_endpoint: str = "/api/auth/cli-token",
) -> dict:
    """添加或更新用户自定义系统。不需要认证。

    Args:
        alias:          系统显示别名
        url:            系统 Base URL
        key:            系统唯一键（不传则由 alias 自动生成）
        token_endpoint: Token 获取端点（默认 /api/auth/cli-token）
    """
    try:
        registry = _registry()
        # key 未指定时由 alias 转换（空格→下划线，统一小写）
        system_key = key or alias.replace(" ", "_").lower()
        registry.add_local(alias, system_key, url, token_endpoint=token_endpoint)
        return _ok({"alias": alias, "system_key": system_key, "url": url})
    except Exception as exc:
        return _err(exc)


async def auth_system_remove(alias: str) -> dict:
    """移除用户自定义系统；内置系统不可删除。不需要认证。

    Args:
        alias: 要移除的系统别名（builtin 系统会被拒绝）
    """
    try:
        _registry().remove(alias)
        return _ok({"removed": alias})
    except Exception as exc:
        return _err(exc)


async def auth_system_sync(session_id: str | None = None) -> dict:
    """从 ops 后端同步系统列表。需要 session_id。

    如果未提供 session_id，会自动尝试从本地加载已保存的。

    Args:
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
    """
    from opscli.mcp.tools.helpers import _get_session_id

    sid = _get_session_id("ops", session_id)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        return _ok(await _sync_systems_after_login(sid))
    except Exception as exc:
        return _err(exc)


async def auth_build_request_auth(
    system: str = "ops",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """构造统一请求认证参数（JWT Bearer + Session Cookie）。

    如果未提供 session_id / jwt，会自动尝试从本地加载已保存的凭据。

    Args:
        system:     目标系统别名（默认 "ops"）
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:        可选，已有 JWT 可直接使用（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair(system, session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成授权登录，或传入有效的 session_id"))
    try:
        headers, cookies = _auth_client().build_request_auth_with_session(
            sid, jw, system
        )
        return _ok({"headers": headers, "cookies": cookies})
    except Exception as exc:
        return _err(exc)


async def auth_logout(system: str = "__all__") -> dict:
    """清除本地保存的 session 和 JWT（退出登录）。

    按 API Key 隔离清除凭证，不影响其他用户的凭证。
    仅删除本地凭证，不影响后端 session 状态。

    Args:
        system: 系统别名，"__all__" 表示清除所有系统
    """
    try:
        store = _get_isolated_store()
        if system == "__all__":
            store.clear()
        else:
            store.remove_token(system)
        from opscli.mcp.credential_cache import invalidate_credential_cache
        invalidate_credential_cache(base_dir=_get_credential_dir())
        return _ok({"cleared": system})
    except Exception as exc:
        return _err(exc)


async def auth_doctor(session_id: str | None = None) -> dict:
    """检查 session 有效性与各系统连通性，返回结构化诊断结果。

    如果未提供 session_id，会自动尝试从本地加载已保存的 session（按 API Key 隔离）。

    Args:
        session_id: 可选，提供后额外检测 session 是否已认证（为空则自动加载本地保存的）
    """
    try:
        client = _auth_client()
        from opscli.mcp.tools.helpers import _get_session_id

        sid = _get_session_id("ops", session_id)
        checks: list[dict] = []
        # 检测 session_id 认证状态（可选项）
        authenticated = False
        if sid:
            try:
                client.get_token_by_session(sid, "ops")
                authenticated = True
            except Exception:
                pass
        # 逐一检测所有系统的网络连通性
        for system in client._registry.list_all():
            ok = False
            error = None
            try:
                httpx.get(system["url"], timeout=5)
                ok = True
            except Exception as exc:
                error = str(exc)
            checks.append(
                {
                    "alias": system["alias"],
                    "url": system["url"],
                    "reachable": ok,
                    "error": error,
                }
            )
        # 从隔离的 CredentialStore 读取本地凭证概览
        store = _get_isolated_store()
        store_data = store.load() or {}
        local_sessions = {
            "email": store_data.get("email"),
            "session_id_present": bool(store_data.get("session_id")),
            "tokens": list(store_data.get("tokens", {}).keys()),
        }
        return _ok({
            "authenticated": authenticated,
            "session_id_present": bool(sid),
            "local_sessions": local_sessions,
            "systems": checks,
        })
    except Exception as exc:
        return _err(exc)


# ── 工具注解（供 ChatGPT/OpenAI 判断工具副作用）─────────────────────
_AUTH_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
)

_AUTH_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=False,
    destructiveHint=False,
)

_AUTH_DESTRUCTIVE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=False,
    destructiveHint=True,
)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    (auth_login_start, _AUTH_WRITE_ANNOTATIONS),
    # poll 是"读取授权状态"操作，标记为只读避免 ChatGPT 等客户端弹确认框
    (auth_login_poll, _AUTH_READ_ANNOTATIONS),
    (auth_get_token, _AUTH_WRITE_ANNOTATIONS),
    (auth_check_token, _AUTH_READ_ANNOTATIONS),
    (auth_is_authenticated, _AUTH_READ_ANNOTATIONS),
    (auth_token_refresh, _AUTH_WRITE_ANNOTATIONS),
    (auth_system_list, _AUTH_READ_ANNOTATIONS),
    (auth_system_add, _AUTH_WRITE_ANNOTATIONS),
    (auth_system_remove, _AUTH_DESTRUCTIVE_ANNOTATIONS),
    (auth_system_sync, _AUTH_WRITE_ANNOTATIONS),
    (auth_build_request_auth, _AUTH_READ_ANNOTATIONS),
    (auth_logout, _AUTH_DESTRUCTIVE_ANNOTATIONS),
    (auth_doctor, _AUTH_READ_ANNOTATIONS),
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 auth_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn, annotations in _ALL_TOOLS:
        mcp.tool(annotations=annotations)(fn)
