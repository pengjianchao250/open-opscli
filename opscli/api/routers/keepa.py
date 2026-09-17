"""Keepa 场景 REST 路由（从 api/app.py 迁移，逻辑保持不变）。

REST 不直接调用 Manager：复用 MCP 的 quota_wrap（日额度占用/失败退回）与
telemetry_wrap（同一套低敏场景维度统计），保证 REST 与 MCP 同源同治理。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from opscli.api.deps import require_authenticated_user
from opscli.api.errors import error_response, safe_exception_message
from opscli.api.schemas.keepa import KeepaRunRequest


router = APIRouter(prefix="/api/v1", tags=["keepa"])


def _keepa_result_response(result: dict) -> JSONResponse:
    """按 Keepa 稳定错误码选择 HTTP 状态，并保留 MCP 错误信封。"""
    if result.get("success") is True:
        return JSONResponse(result)
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(error.get("code") or "")
    status_by_code = {
        "KEEPA_AUTH_ERROR": 401,
        "KEEPA_FORBIDDEN": 403,
        "KEEPA_QUOTA_INSUFFICIENT": 429,
        "KEEPA_RATE_LIMITED": 429,
    }
    status_code = status_by_code.get(code, 200)
    headers: dict[str, str] = {}
    retry_after = error.get("retry_after_seconds")
    if status_code == 429 and retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(result, status_code=status_code, headers=headers)


async def _run_keepa_scenario(payload: KeepaRunRequest) -> dict:
    """调用 Keepa MCP 同源实现，并保留其额度与遥测治理。"""
    from opscli.keepa.api.scenarios import telemetry_dimensions
    from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
    from opscli.mcp.tools.keepa import _KEEPA_API_MODE, keepa_run

    governed_run = telemetry_wrap(
        quota_wrap(keepa_run),
        module="keepa",
        dimension_resolver=telemetry_dimensions,
    )
    api_mode_token = _KEEPA_API_MODE.set(True)
    try:
        from opscli.mcp.context import get_current_jwt, get_current_session_id

        result = await governed_run(
            **payload.model_dump(exclude_none=True),
            session_id=get_current_session_id(),
            jwt=get_current_jwt(),
        )
    finally:
        _KEEPA_API_MODE.reset(api_mode_token)
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
    try:
        result = await _run_keepa_scenario(payload)
    except Exception as exc:
        return error_response(
            code=type(exc).__name__,
            message=safe_exception_message(exc),
            status_code=502,
        )
    # keepa_run 已返回统一 success/data/error 合同，并由 quota_wrap 补充 quota。
    return _keepa_result_response(result)
