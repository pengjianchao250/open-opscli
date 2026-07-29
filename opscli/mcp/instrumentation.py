"""MCP Tool 限额与遥测注册切面。"""

from __future__ import annotations

import functools
import time


def quota_wrap(fn, *, limiter=None):
    """为 MCP Tool 增加调用前后限额处理。"""

    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        from opscli.mcp.quota import get_quota_limiter

        quota_limiter = limiter or get_quota_limiter()
        decision = await quota_limiter.before_call(fn.__name__)
        if not decision.allowed:
            return decision.error_response

        from opscli.mcp.quota import reset_quota_access_context, set_quota_access_context

        token = set_quota_access_context(getattr(decision, "access_context", None))
        ticket = getattr(decision, "ticket", None)
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            await quota_limiter.after_exception(ticket)
            raise
        finally:
            reset_quota_access_context(token)

        if isinstance(result, dict):
            return await quota_limiter.after_call(ticket, result)
        return result

    return _wrapper


def telemetry_wrap(fn):
    """为 MCP Tool 增加无阻塞调用遥测。"""

    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        started_at = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            _fire_mcp_event(
                fn.__name__,
                status="success",
                duration_ms=int((time.monotonic() - started_at) * 1000),
                params=kwargs,
            )
            return result
        except Exception as exc:
            _fire_mcp_event(
                fn.__name__,
                status="error",
                duration_ms=int((time.monotonic() - started_at) * 1000),
                error_type=type(exc).__name__,
                params=kwargs,
            )
            raise

    return _wrapper


def _get_current_mcp_user_email() -> str | None:
    """读取当前 MCP 用户邮箱，遥测失败时静默降级。"""
    try:
        from opscli.mcp.context import get_current_user_email

        email = get_current_user_email()
        if email:
            return email

        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.tools.helpers import _get_credential_dir

        cred_dir = _get_credential_dir()
        store = CredentialStore(base_dir=cred_dir) if cred_dir else CredentialStore()
        data = store.load()
        return data.get("email") if data else None
    except Exception:
        return None


def _get_current_mcp_client_name() -> str | None:
    """读取当前 MCP 客户端名称，遥测失败时静默降级。"""
    try:
        from opscli.mcp.context import get_current_client_name

        return get_current_client_name()
    except Exception:
        return None


def _fire_mcp_event(
    tool_name: str,
    *,
    status: str,
    duration_ms: int,
    error_type: str | None = None,
    params: dict | None = None,
) -> None:
    """异步上报 MCP Tool 调用事件，不影响主流程。"""
    try:
        from opscli.telemetry.collector import build_event
        from opscli.telemetry.reporter import TelemetryReporter

        event = build_event(
            event_type="mcp_tool",
            command=tool_name,
            module=tool_name.split("_")[0],
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            user_email=_get_current_mcp_user_email(),
            skill_name=_get_current_mcp_client_name(),
            raw_payload={"params": params} if params else None,
        )
        TelemetryReporter.fire(**event)
    except Exception:
        pass
