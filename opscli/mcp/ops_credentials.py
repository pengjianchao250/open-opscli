"""按 MCP 请求身份解析并确保 OPS 凭证绑定。"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from weakref import WeakKeyDictionary, WeakValueDictionary

from opscli.mcp.context import (
    get_current_api_key,
    get_current_auth_mode,
    get_current_user_email,
)
from opscli.mcp.tools.auth import auth_mcp_login
from opscli.mcp.tools.helpers import (
    _decode_jwt_payload,
    _get_auth_pair,
    _get_credential_dir,
    _get_isolated_credential_cache,
)


class OpsCredentialBindingError(RuntimeError):
    """当前 MCP 身份无法建立可信 OPS 凭证绑定。"""

    code = "OPS_CREDENTIAL_ENSURE_FAILED"

    def to_dict(self) -> dict[str, str]:
        """返回供 MCP 与 REST 复用的稳定错误合同。"""
        return {"code": self.code, "message": str(self)}


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
        refreshed: 本次调用是否新建 Session 或获取了新的 OPS JWT。
    """

    credential_scope: str
    user_email: str
    session_id: str | None
    jwt: str | None
    runtime_auth: tuple[str | None, str | None] | None = None
    refreshed: bool = False


def _get_authenticated_user_email() -> str | None:
    """优先使用中间件验证邮箱，stdio/fixed 模式回退隔离凭证邮箱。"""
    transport_email = str(get_current_user_email() or "").strip().lower()
    if transport_email:
        return transport_email
    credential_dir = _get_credential_dir()
    cached_email = _get_isolated_credential_cache(credential_dir).get_email()
    return str(cached_email or "").strip().lower() or None


def _jwt_expires_in(jwt: str) -> int:
    """从 JWT 解析剩余有效期，异常结构使用认证模块默认值。"""
    from opscli.auth.core.token_manager import MAX_JWT_TTL

    expires_in = 7200
    try:
        exp = _decode_jwt_payload(jwt).get("exp")
        if exp:
            expires_in = max(
                0,
                int(float(exp) - datetime.now(timezone.utc).timestamp()),
            )
    except Exception:
        pass
    return min(expires_in, MAX_JWT_TTL)


async def _fetch_and_store_ops_jwt(
    session_id: str,
    credential_dir: Path | None,
) -> str:
    """使用 Session 换取 OPS JWT，并写入对应的统一凭据存储。"""
    from opscli.auth import AuthClient
    from opscli.auth.storage.credential_store import CredentialStore
    from opscli.mcp.credential_cache import invalidate_credential_cache

    jwt = await asyncio.to_thread(
        AuthClient().get_token_by_session,
        session_id,
        "ops",
    )
    store = (
        CredentialStore(base_dir=credential_dir)
        if credential_dir is not None
        else CredentialStore()
    )
    store.save_token("ops", jwt, _jwt_expires_in(jwt))
    invalidate_credential_cache(base_dir=credential_dir)
    return jwt


def _invalidate_ops_credentials(credential_dir: Path | None) -> None:
    """清除服务端已拒绝的 Session/JWT，并同步失效内存缓存。"""
    from opscli.auth.storage.credential_store import CredentialStore
    from opscli.mcp.credential_cache import invalidate_credential_cache

    store = (
        CredentialStore(base_dir=credential_dir)
        if credential_dir is not None
        else CredentialStore()
    )
    store.clear()
    invalidate_credential_cache(base_dir=credential_dir)


def _is_auth_rejection(exc: Exception) -> bool:
    """沿异常链识别明确的 401/403，避免网络故障触发无意义重登。"""
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        status_code = getattr(current, "status_code", None)
        response = getattr(current, "response", None)
        if status_code in {401, 403} or getattr(response, "status_code", None) in {
            401,
            403,
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


async def _auto_login(cache) -> None:
    """执行一次 MCP 静默登录，并确认 Session 已写入当前隔离缓存。"""
    login_result = await auth_mcp_login()
    if login_result.get("success") is not True:
        error = login_result.get("error") or {}
        message = str(error.get("message") or "自动建立 OPS 隔离登录态失败")
        raise OpsCredentialBindingError(message)
    if not cache.is_authenticated():
        raise OpsCredentialBindingError("OPS 隔离登录态未保存成功")


def _read_remote_identity(cache) -> tuple[str, str]:
    """读取并校验当前请求身份与隔离凭据中的用户绑定。"""
    session_id = cache.get_session_id()
    user_email = str(_get_authenticated_user_email() or "").strip().lower()
    cached_email = str(cache.get_email() or "").strip().lower()
    if not session_id or not user_email:
        raise OpsCredentialBindingError("当前 MCP 用户的 OPS 隔离凭证不完整")
    if cached_email and cached_email != user_email:
        raise OpsCredentialBindingError("当前 MCP 用户与 OPS 隔离凭证用户不一致")
    return session_id, user_email


async def ensure_ops_credentials(
    *,
    provided_session: str | None = None,
    provided_jwt: str | None = None,
    require_jwt: bool = False,
    force_relogin: bool = False,
) -> OpsCredentialBinding:
    """按当前 MCP 身份确保并返回可信 OPS 凭证。

    远端模式只信任 ``X-MCP-API-Key`` 对应的隔离 CredentialStore，调用方显式
    传入的旧 ``session_id/jwt`` 会被忽略。隔离 Session 缺失或过期时，在同一
    事件循环和凭证作用域内以 single-flight 锁执行一次自动登录；二次检查用于
    复用先取得锁请求刚写入的 Session。require_jwt=True 时还会在业务请求前
    换取并缓存 OPS JWT；若现有 Session 被 OPS 以 401/403 拒绝，则清除当前
    隔离凭据并静默重登一次。stdio 模式继续使用本机默认凭证。

    Args:
        provided_session: 旧客户端或 stdio 调用方显式传入的 OPS Session。
        provided_jwt: 旧客户端或 stdio 调用方显式传入的 OPS JWT。
        require_jwt: 是否必须在返回前建立可用的 OPS JWT。
        force_relogin: 远端模式下强制重新登录一次，忽略 ``is_authenticated()``。
            用于「本地看着没过期、服务端却已判无效」的场景——``is_authenticated()``
            只比对本地 ``session_expires_at``，而服务端还会校验 ``is_valid``
            与真实有效期，被登出或吊销的 Session 在本地依然显示未过期，
            于是自动登录永远不触发、调用方恒拿到 401。仅在调用方确实撞到
            认证类失败后才允许传 True，避免每次调用都重登。

    Returns:
        与当前 MCP 身份一致的凭证作用域、邮箱和 OPS 凭证绑定。

    Raises:
        OpsCredentialBindingError: 无法登录、凭证不完整或凭证邮箱与请求身份不一致。
    """
    auth_mode = str(get_current_auth_mode() or "")
    if auth_mode in {"apphub_viewer", "apphub_session", "internal"} and (
        provided_session or provided_jwt
    ):
        user_email = str(get_current_user_email() or "").strip().lower()
        if not user_email:
            raise OpsCredentialBindingError("当前 AppHub 用户邮箱缺失，无法安全执行 OPS 任务")
        jwt = provided_jwt
        refreshed = False
        if require_jwt and not jwt:
            if not provided_session:
                raise OpsCredentialBindingError("当前 AppHub 请求缺少可用的 OPS JWT")
            try:
                from opscli.auth import AuthClient

                jwt = await asyncio.to_thread(
                    AuthClient().get_token_by_session,
                    provided_session,
                    "ops",
                )
                refreshed = True
            except Exception as exc:
                raise OpsCredentialBindingError(f"获取 OPS JWT 失败：{exc}") from exc
        return OpsCredentialBinding(
            credential_scope=f"{auth_mode}:{user_email}",
            user_email=user_email,
            session_id=provided_session,
            jwt=jwt,
            runtime_auth=(provided_session, jwt),
            refreshed=refreshed,
        )

    api_key = get_current_api_key()
    if api_key:
        credential_dir = _get_credential_dir()
        if credential_dir is None:
            raise OpsCredentialBindingError("无法确定当前 MCP 用户的隔离凭证作用域")
        cache = _get_isolated_credential_cache(credential_dir)
        stale_session_id = cache.get_session_id() if force_relogin else None
        if (
            not force_relogin
            and cache.is_authenticated()
            and (not require_jwt or cache.get_jwt("ops"))
        ):
            session_id, user_email = _read_remote_identity(cache)
            return OpsCredentialBinding(
                credential_scope=str(credential_dir),
                user_email=user_email,
                session_id=session_id,
                jwt=cache.get_jwt("ops"),
            )

        async with _get_login_lock(str(credential_dir)):
            # 登录和 JWT 换取共用一把作用域锁，保证陈旧 Session 并发自愈只发生一次。
            refreshed = False
            logged_in = False
            current_session_id = cache.get_session_id() if force_relogin else None
            already_renewed = bool(
                force_relogin
                and current_session_id
                and current_session_id != stale_session_id
            )
            if force_relogin and not already_renewed:
                await _auto_login(cache)
                refreshed = True
                logged_in = True
            elif not force_relogin and not cache.is_authenticated():
                await _auto_login(cache)
                refreshed = True
                logged_in = True

            session_id, user_email = _read_remote_identity(cache)
            jwt = cache.get_jwt("ops")
            if require_jwt and not jwt:
                try:
                    jwt = await _fetch_and_store_ops_jwt(session_id, credential_dir)
                    refreshed = True
                except Exception as exc:
                    auth_rejected = _is_auth_rejection(exc)
                    if logged_in or not auth_rejected:
                        if logged_in and auth_rejected:
                            _invalidate_ops_credentials(credential_dir)
                        raise OpsCredentialBindingError(
                            f"获取 OPS JWT 失败：{exc}"
                        ) from exc

                    # 本地 Session 尚未过期但服务端已撤销时，仅在业务请求前重登一次。
                    _invalidate_ops_credentials(credential_dir)
                    await _auto_login(cache)
                    refreshed = True
                    logged_in = True
                    session_id, user_email = _read_remote_identity(cache)
                    try:
                        jwt = await _fetch_and_store_ops_jwt(
                            session_id,
                            credential_dir,
                        )
                    except Exception as retry_exc:
                        raise OpsCredentialBindingError(
                            f"重新登录后获取 OPS JWT 失败：{retry_exc}"
                        ) from retry_exc

            return OpsCredentialBinding(
                credential_scope=str(credential_dir),
                user_email=user_email,
                session_id=session_id,
                jwt=jwt,
                refreshed=refreshed,
            )

    session_id, jwt = _get_auth_pair("ops", provided_session, provided_jwt)
    user_email = str(_get_authenticated_user_email() or "").strip().lower()
    if not session_id:
        raise OpsCredentialBindingError("无 OPS 登录态，请先完成 opscli auth login")
    if not user_email:
        raise OpsCredentialBindingError("当前 MCP 用户邮箱缺失，无法安全执行 OPS 任务")
    refreshed = False
    if require_jwt and not jwt:
        try:
            jwt = await _fetch_and_store_ops_jwt(session_id, None)
            refreshed = True
        except Exception as exc:
            raise OpsCredentialBindingError(f"获取 OPS JWT 失败：{exc}") from exc
    runtime_auth = (session_id, jwt) if provided_session or provided_jwt else None
    return OpsCredentialBinding(
        credential_scope="default",
        user_email=user_email,
        session_id=session_id,
        jwt=jwt,
        runtime_auth=runtime_auth,
        refreshed=refreshed,
    )
