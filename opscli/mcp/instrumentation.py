"""MCP Tool 限额与遥测注册切面。"""

from __future__ import annotations

import functools
import inspect
import time
from typing import Any


# 场景统计维度使用独立版本，后续增加字段时可保持历史查询兼容。
_USAGE_DIMENSIONS_VERSION = 1
# 业务模块使用不同参数名表达场景，这里只读取稳定白名单，避免遥测完整业务参数。
_SCENARIO_KEYS = ("scenario", "feature", "function", "target")
_OPTIONAL_DIMENSION_KEYS = ("site", "domain", "geo", "period", "provider", "target")
_MAX_DIMENSION_LENGTH = 128


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


def telemetry_wrap(
    fn,
    *,
    module: str | None = None,
    runtime_role: str = "executor",
):
    """为 MCP Tool 增加低敏、可按场景聚合的无阻塞调用遥测。

    Args:
        fn: MCP Tool 实现。
        module: 注册清单确认的模块名，避免按下划线错误截断多段模块名。
        runtime_role: ``executor`` 表示实际执行入口，``gateway_proxy`` 表示代理入口。
    """

    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        started_at = time.monotonic()
        tool_name = fn.__name__
        resolved_module = module or _fallback_module(fn, tool_name)
        call_arguments = _bind_call_arguments(fn, args, kwargs)
        try:
            result = await fn(*args, **kwargs)
            status, error_type = _result_outcome(result)
            _fire_mcp_event(
                tool_name,
                module=resolved_module,
                status=status,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                error_type=error_type,
                dimensions=_build_usage_dimensions(
                    tool_name=tool_name,
                    module=resolved_module,
                    runtime_role=runtime_role,
                    arguments=call_arguments,
                    result=result,
                ),
            )
            return result
        except Exception as exc:
            _fire_mcp_event(
                tool_name,
                module=resolved_module,
                status="error",
                duration_ms=int((time.monotonic() - started_at) * 1000),
                error_type=type(exc).__name__,
                dimensions=_build_usage_dimensions(
                    tool_name=tool_name,
                    module=resolved_module,
                    runtime_role=runtime_role,
                    arguments=call_arguments,
                ),
            )
            raise

    return _wrapper


def _bind_call_arguments(fn, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """按 Tool 声明绑定位置参数，保证所有调用方式使用同一场景提取口径。"""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        # 动态 Tool 可能没有可检查签名；此时只使用命名参数仍可覆盖常规 MCP 调用。
        return dict(kwargs)
    return {
        name: value
        for name, value in bound.arguments.items()
        if name not in {"self", "cls"}
    }


def _build_usage_dimensions(
    *,
    tool_name: str,
    module: str,
    runtime_role: str,
    arguments: dict[str, Any],
    result: Any = None,
) -> dict[str, Any]:
    """构造固定、低敏的统计维度，不保留 ASIN、关键词、路径或认证信息。"""
    result_data = _result_data(result)
    dimensions: dict[str, Any] = {
        "schema_version": _USAGE_DIMENSIONS_VERSION,
        "service": _safe_dimension(module) or "unknown",
        "operation": _safe_dimension(tool_name) or "unknown",
        "runtime_role": _safe_dimension(runtime_role) or "executor",
    }

    # 成功结果通常带规范化场景，优先于调用方可能使用的别名。
    scenario = _first_dimension(result_data, _SCENARIO_KEYS)
    if scenario is None:
        scenario = _first_dimension(arguments, _SCENARIO_KEYS)
    if scenario is None and tool_name.startswith("seller_sprite_listing_analysis_"):
        scenario = "listing-analysis"
    if scenario is not None:
        dimensions["scenario"] = scenario

    for key in _OPTIONAL_DIMENSION_KEYS:
        value = _safe_dimension(result_data.get(key))
        if value is None:
            value = _safe_dimension(arguments.get(key))
        if value is not None:
            dimensions[key] = value
    return dimensions


def _result_data(result: Any) -> dict[str, Any]:
    """读取统一 MCP 成功响应中的公开结果字段，失败或非标准响应返回空字典。"""
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _first_dimension(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """按稳定优先级读取第一个可用维度。"""
    for key in keys:
        value = _safe_dimension(source.get(key))
        if value is not None:
            return value
    return None


def _safe_dimension(value: Any) -> str | None:
    """只接受短标量维度，拒绝容器对象进入遥测。"""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_MAX_DIMENSION_LENGTH]


def _result_outcome(result: Any) -> tuple[str, str | None]:
    """把统一响应中的业务失败映射为遥测错误，而不仅统计 Python 异常。"""
    if not isinstance(result, dict) or result.get("success") is not False:
        return "success", None
    error = result.get("error")
    if isinstance(error, dict):
        code = _safe_dimension(error.get("code"))
        if code:
            return "error", code
    return "error", "BusinessError"


def _fallback_module(fn, tool_name: str) -> str:
    """未由注册层传入模块时，优先使用 Python 模块名作为兼容回退。"""
    module_name = str(getattr(fn, "__module__", "") or "").rsplit(".", 1)[-1]
    return module_name or tool_name.split("_", 1)[0]


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
    module: str,
    status: str,
    duration_ms: int,
    error_type: str | None = None,
    dimensions: dict[str, Any] | None = None,
) -> None:
    """异步上报 MCP Tool 调用事件，不影响主流程。"""
    try:
        from opscli.telemetry.collector import build_event
        from opscli.telemetry.reporter import TelemetryReporter

        event = build_event(
            event_type="mcp_tool",
            command=tool_name,
            module=module,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            user_email=_get_current_mcp_user_email(),
            skill_name=_get_current_mcp_client_name(),
            dimensions=dimensions,
            raw_payload=None,
        )
        TelemetryReporter.fire(**event)
    except Exception:
        pass
