"""Keepa 场景 REST 路由（从 api/app.py 迁移，逻辑保持不变）。

REST 不直接调用 Manager：复用 MCP 的 quota_wrap（日额度占用/失败退回）与
telemetry_wrap（同一套低敏场景维度统计），保证 REST 与 MCP 同源同治理。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from opscli.api.deps import require_authenticated_user
from opscli.api.errors import error_response, safe_exception_message
from opscli.api.schemas.keepa import KeepaRunRequest

_logger = logging.getLogger("opscli.api")

router = APIRouter(prefix="/api/v1", tags=["keepa"])


def _trace_keepa_api(message: str) -> None:
    """复用鉴权层的低依赖 Keepa 诊断输出。"""
    try:
        from opscli.mcp.auth_middleware import _trace_keepa

        _trace_keepa(message)
    except Exception:
        # 诊断日志不能影响 API 请求。
        pass


async def _run_keepa_scenario(payload: KeepaRunRequest) -> dict:
    """调用 Keepa MCP 同源实现，并保留其额度与遥测治理。"""
    _trace_keepa_api("import_start module=opscli.keepa.api.scenarios")
    from opscli.keepa.api.scenarios import telemetry_dimensions
    _trace_keepa_api("import_done module=opscli.keepa.api.scenarios")
    _trace_keepa_api("import_start module=opscli.mcp.instrumentation")
    from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
    _trace_keepa_api("import_done module=opscli.mcp.instrumentation")
    _trace_keepa_api("import_start module=opscli.mcp.tools.keepa")
    from opscli.mcp.tools.keepa import _KEEPA_API_MODE, keepa_run
    _trace_keepa_api("import_done module=opscli.mcp.tools.keepa")

    started_at = time.monotonic()
    _logger.info(
        "[KEEPA-TRACE] api_start scenario=%s site=%s export_format=%s wait=%s",
        payload.scenario,
        payload.site,
        payload.export_format,
        payload.wait,
    )
    _trace_keepa_api(
        "api_start scenario=%s site=%s export_format=%s wait=%s"
        % (payload.scenario, payload.site, payload.export_format, payload.wait)
    )
    governed_run = telemetry_wrap(
        quota_wrap(keepa_run),
        module="keepa",
        dimension_resolver=telemetry_dimensions,
    )
    _trace_keepa_api("governance_ready scenario=%s" % payload.scenario)
    api_mode_token = _KEEPA_API_MODE.set(True)
    try:
        from opscli.mcp.context import get_current_jwt, get_current_session_id

        result = await governed_run(
            **payload.model_dump(exclude_none=True),
            session_id=get_current_session_id(),
            jwt=get_current_jwt(),
        )
    except Exception as exc:
        _logger.warning(
            "[KEEPA-TRACE] api_error scenario=%s site=%s error_type=%s elapsed_ms=%s",
            payload.scenario,
            payload.site,
            type(exc).__name__,
            int((time.monotonic() - started_at) * 1000),
        )
        _trace_keepa_api(
            "api_error scenario=%s site=%s error_type=%s elapsed_ms=%s"
            % (
                payload.scenario,
                payload.site,
                type(exc).__name__,
                int((time.monotonic() - started_at) * 1000),
            )
        )
        raise
    finally:
        _KEEPA_API_MODE.reset(api_mode_token)
    _logger.info(
        "[KEEPA-TRACE] api_done scenario=%s site=%s success=%s elapsed_ms=%s",
        payload.scenario,
        payload.site,
        result.get("success") if isinstance(result, dict) else None,
        int((time.monotonic() - started_at) * 1000),
    )
    _trace_keepa_api(
        "api_done scenario=%s site=%s success=%s elapsed_ms=%s"
        % (
            payload.scenario,
            payload.site,
            result.get("success") if isinstance(result, dict) else None,
            int((time.monotonic() - started_at) * 1000),
        )
    )
    return result


@router.get("/keepa/scenarios")
async def keepa_scenarios() -> JSONResponse:
    """列出可用于 Keepa 场景执行的公开场景定义（公开端点，无需账号授权）。"""
    try:
        from opscli.keepa.services import KeepaApiManager

        result = await run_in_threadpool(KeepaApiManager().scenarios)
    except Exception as exc:
        return error_response(
            code=type(exc).__name__,
            message="Keepa 场景列表读取失败，请稍后重试",
            status_code=502,
        )
    return JSONResponse({"success": True, "data": result, "error": None})


@router.post("/keepa/run")
async def keepa_run(
    payload: KeepaRunRequest,
    _user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """执行 Keepa 场景并返回完整格式化数据和额度信息。"""
    _trace_keepa_api(
        "route_enter path=/api/v1/keepa/run scenario=%s site=%s"
        % (payload.scenario, payload.site)
    )
    _trace_keepa_api("route_identity_resolved has_user_email=%s" % bool(_user_email))
    try:
        result = await _run_keepa_scenario(payload)
    except Exception as exc:
        return error_response(
            code=type(exc).__name__,
            message=safe_exception_message(exc),
            status_code=502,
        )
    # keepa_run 已返回统一 success/data/error 合同，并由 quota_wrap 补充 quota。
    return JSONResponse(result)
