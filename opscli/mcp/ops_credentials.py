"""按 MCP 请求身份解析并确保 OPS 凭证绑定。"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from weakref import WeakKeyDictionary, WeakValueDictionary

from opscli.mcp.context import get_current_api_key, get_current_user_email
from opscli.mcp.tools.auth import auth_mcp_login
from opscli.mcp.tools.helpers import (
    _get_auth_pair,
    _get_credential_dir,
    _get_isolated_credential_cache,
)


class OpsCredentialBindingError(RuntimeError):
    """当前 MCP 身份无法建立可信 OPS 凭证绑定。"""


_login_locks_guard = threading.Lock()
_login_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    WeakValueDictionary[str, asyncio.Lock],
] = WeakKeyDictionary()


def _get_login_lock(credential_scope: str) -> asyncio.Lock:
    """按事件循环和凭证作用域复用弱引用锁，避免并发登录及长期残留。"""
    loop = asyncio.get_running_loop()
    with _login_locks_guard:
        locks_by_scope = _login_locks.get(loop)
        if locks_by_scope is None:
            locks_by_scope = WeakValueDictionary()
            _login_locks[loop] = locks_by_scope
        lock = locks_by_scope.get(credential_scope)
        if lock is None:
            lock = asyncio.Lock()
            locks_by_scope[credential_scope] = lock
        return lock


@dataclass(frozen=True)
class OpsCredentialBinding:
    """业务工具可使用的可信 OPS 凭证绑定。

    Attributes:
        credential_scope: 可持久化到任务队列的非敏感 CredentialStore 作用域。
        user_email: 当前已验证 MCP 身份对应的标准化邮箱。
        session_id: 该作用域中的 OPS Session，仅供当前调用或作用域解析使用。
        jwt: 该作用域中的 OPS JWT；未获取时为 None。
        runtime_auth: stdio 显式凭证的逐任务内存副本；远端模式始终为 None。
    """

    credential_scope: str
    user_email: str
    session_id: str
    jwt: str | None
    runtime_auth: tuple[str, str | None] | None = None


def _get_authenticated_user_email() -> str | None:
    """优先使用中间件验证邮箱，stdio/fixed 模式回退隔离凭证邮箱。"""
    transport_email = str(get_current_user_email() or "").strip().lower()
    if transport_email:
        return transport_email
    credential_dir = _get_credential_dir()
    cached_email = _get_isolated_credential_cache(credential_dir).get_email()
    return str(cached_email or "").strip().lower() or None


async def ensure_ops_credentials(
    *,
    provided_session: str | None = None,
    provided_jwt: str | None = None,
) -> OpsCredentialBinding:
    """按当前 MCP 身份确保并返回可信 OPS 凭证。

    远端模式只信任 ``X-MCP-API-Key`` 对应的隔离 CredentialStore，调用方显式
    传入的旧 ``session_id/jwt`` 会被忽略。隔离 Session 缺失或过期时，在同一
    事件循环和凭证作用域内以 single-flight 锁执行一次自动登录；二次检查用于
    复用先取得锁请求刚写入的 Session。stdio 模式继续使用本机默认凭证。

    Args:
        provided_session: 旧客户端或 stdio 调用方显式传入的 OPS Session。
        provided_jwt: 旧客户端或 stdio 调用方显式传入的 OPS JWT。

    Returns:
        与当前 MCP 身份一致的凭证作用域、邮箱和 OPS 凭证绑定。

    Raises:
        OpsCredentialBindingError: 无法登录、凭证不完整或凭证邮箱与请求身份不一致。
    """
    api_key = get_current_api_key()
    if api_key:
        credential_dir = _get_credential_dir()
        if credential_dir is None:
            raise OpsCredentialBindingError("无法确定当前 MCP 用户的隔离凭证作用域")
        cache = _get_isolated_credential_cache(credential_dir)
        if not cache.is_authenticated():
            async with _get_login_lock(str(credential_dir)):
                # 取得锁后必须二次检查，其他并发请求可能已经完成自动登录。
                if not cache.is_authenticated():
                    login_result = await auth_mcp_login()
                    if login_result.get("success") is not True:
                        error = login_result.get("error") or {}
                        message = str(error.get("message") or "自动建立 OPS 隔离登录态失败")
                        raise OpsCredentialBindingError(message)
                    if not cache.is_authenticated():
                        raise OpsCredentialBindingError("OPS 隔离登录态未保存成功")
        session_id = cache.get_session_id()
        user_email = str(_get_authenticated_user_email() or "").strip().lower()
        cached_email = str(cache.get_email() or "").strip().lower()
        if not session_id or not user_email:
            raise OpsCredentialBindingError("当前 MCP 用户的 OPS 隔离凭证不完整")
        if cached_email and cached_email != user_email:
            raise OpsCredentialBindingError("当前 MCP 用户与 OPS 隔离凭证用户不一致")
        return OpsCredentialBinding(
            credential_scope=str(credential_dir),
            user_email=user_email,
            session_id=session_id,
            jwt=cache.get_jwt("ops"),
        )

    session_id, jwt = _get_auth_pair("ops", provided_session, provided_jwt)
    user_email = str(_get_authenticated_user_email() or "").strip().lower()
    if not session_id:
        raise OpsCredentialBindingError("无 OPS 登录态，请先完成 opscli auth login")
    if not user_email:
        raise OpsCredentialBindingError("当前 MCP 用户邮箱缺失，无法安全执行 OPS 任务")
    runtime_auth = (session_id, jwt) if provided_session or provided_jwt else None
    return OpsCredentialBinding(
        credential_scope="default",
        user_email=user_email,
        session_id=session_id,
        jwt=jwt,
        runtime_auth=runtime_auth,
    )
