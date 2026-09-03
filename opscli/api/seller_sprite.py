"""SellerSprite 产品化 REST 路由。

HTTP 适配器只定义稳定合同并调用通用 MCP 的 Collector 代理；任务执行、
额度、权限、账号池和任务所有权仍由 Collector MCP 统一负责。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


SellerSpriteExportFormat = Literal["xls", "xlsx", "json"]
SellerSpriteJobId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]
SellerSpritePathJobId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]

_logger = logging.getLogger("opscli.api.seller_sprite")


class SellerSpriteRunRequest(BaseModel):
    """普通卖家精灵异步任务提交合同。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    site: str = Field(default="US", min_length=2, max_length=8)
    period: str = Field(default="30d", min_length=1, max_length=32)
    page_size: int = Field(default=100, ge=1, le=100)
    export_format: SellerSpriteExportFormat = "xls"
    job_id: SellerSpriteJobId | None = None


class SellerSpriteJobsStatusRequest(BaseModel):
    """卖家精灵批量任务状态查询合同。"""

    model_config = ConfigDict(extra="forbid")

    job_ids: list[SellerSpriteJobId] = Field(min_length=1, max_length=50)
    wait_seconds: int = Field(default=0, ge=0, le=30)


class SellerSpriteListingAnalysisRequest(BaseModel):
    """Listing Analysis 异步任务提交合同。"""

    model_config = ConfigDict(extra="forbid")

    asin: str = Field(
        min_length=10,
        max_length=10,
        pattern=r"^[A-Za-z0-9]{10}$",
    )
    station: str = Field(default="GLOBAL", min_length=1, max_length=16)
    site: str = Field(default="US", min_length=2, max_length=8)
    export_format: SellerSpriteExportFormat = "json"
    job_id: SellerSpriteJobId | None = None


router = APIRouter(prefix="/api/v1/seller-sprite", tags=["seller-sprite"])


def _authentication_error() -> JSONResponse | None:
    """要求请求上下文中存在经过验证的 opscli 用户身份。"""
    from opscli.mcp.tools.helpers import _get_authenticated_user_email

    if _get_authenticated_user_email():
        return None
    return JSONResponse(
        status_code=401,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "authentication_required",
                "message": "请先完成 opscli 账号授权",
            },
        },
    )


async def _call_gateway_proxy(fn, **kwargs) -> dict[str, Any]:
    """调用 Collector 代理，并记录不重复扣额度的网关遥测。"""
    from opscli.mcp.instrumentation import telemetry_wrap

    proxy = telemetry_wrap(
        fn,
        module="seller_sprite",
        runtime_role="gateway_proxy",
    )
    try:
        return await proxy(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "SellerSprite REST Collector 代理异常: tool=%s error_type=%s",
            getattr(fn, "__name__", "unknown"),
            type(exc).__name__,
        )
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "COLLECTOR_MCP_CALL_FAILED",
                "message": "数据采集服务调用失败，请稍后重试",
            },
        }


def _result_response(
    result: dict[str, Any],
    *,
    success_status_code: int = 200,
) -> JSONResponse:
    """将 MCP 统一信封映射为稳定 HTTP 状态码。"""
    if result.get("success") is True:
        return JSONResponse(status_code=success_status_code, content=result)

    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(error.get("code") or "COLLECTOR_MCP_CALL_FAILED")
    return JSONResponse(status_code=_error_status_code(code), content=result)


def _error_status_code(code: str) -> int:
    """按稳定错误码分类 HTTP 状态，不解析易变化的错误文案。"""
    normalized = code.strip().upper()
    if normalized in {
        "AUTHENTICATION_REQUIRED",
        "COLLECTOR_MCP_IDENTITY_MISSING",
    }:
        return 401
    if normalized in {"PERMISSIONERROR", "TOOLERROR"} or any(
        marker in normalized for marker in ("FORBIDDEN", "PERMISSION_DENIED")
    ):
        return 403
    if normalized in {"FILENOTFOUNDERROR", "SELLER_SPRITE_TASK_NOT_FOUND"}:
        return 404
    if normalized in {
        "COLLECTOR_MCP_CONFIG_MISSING",
        "COLLECTOR_MCP_CONFIG_INVALID",
        "COLLECTOR_MCP_UNAVAILABLE",
        "COLLECTOR_MODULE_NOT_READY",
        "QUEUE_DATABASE_UNAVAILABLE",
    }:
        return 503
    if normalized in {"VALUEERROR", "VALIDATIONERROR"}:
        return 422
    return 502


def _export_format(status: dict[str, Any]) -> str:
    """从任务状态的导出元数据读取规范化格式。"""
    export = status.get("export")
    if not isinstance(export, dict):
        return ""
    value = str(export.get("format") or "").strip().lower()
    if value:
        return "xlsx" if value == "xls" else value
    filename = str(export.get("filename") or "").strip().lower()
    if filename.endswith(".json"):
        return "json"
    if filename.endswith((".xls", ".xlsx")):
        return "xlsx"
    return ""


def _strip_json_export(status: dict[str, Any]) -> dict[str, Any]:
    """JSON API 状态保留业务数据，但不暴露冗余下载链接。"""
    normalized = dict(status)
    if _export_format(normalized) == "json":
        normalized.pop("export", None)
    return normalized


def _strip_json_exports(result: dict[str, Any]) -> dict[str, Any]:
    """在 REST 状态响应中移除 JSON 任务的文件导出信息。"""
    if result.get("success") is not True:
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result

    normalized_data = dict(data)
    jobs = normalized_data.get("jobs")
    if isinstance(jobs, list):
        normalized_data["jobs"] = [
            _strip_json_export(item) if isinstance(item, dict) else item
            for item in jobs
        ]
    else:
        normalized_data = _strip_json_export(normalized_data)
    return {**result, "data": normalized_data}


def _task_is_pending(status: dict[str, Any]) -> bool:
    state = str(status.get("state") or "").strip().lower()
    if state in {"queued", "running"}:
        return True
    return status.get("ready") is False and state not in {
        "succeeded",
        "failed",
        "cancelled",
    }


def _json_result_response(
    result: dict[str, Any],
    *,
    requested_format: str | None = None,
) -> JSONResponse:
    """把成功的 JSON 任务转换为 API 专用内联结果合同。"""
    if result.get("success") is not True:
        return _result_response(result)
    status = result.get("data")
    if not isinstance(status, dict):
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "data": None,
                "error": {
                    "code": "SELLER_SPRITE_RESULT_INVALID",
                    "message": "数据采集服务返回了无效的任务结果",
                },
            },
        )
    if _task_is_pending(status):
        return _result_response(
            {**result, "data": _strip_json_export(status)},
            success_status_code=202,
        )
    state = str(status.get("state") or "").strip().lower()
    if state in {"failed", "cancelled"} or status.get("failed") is True:
        return _result_response({**result, "data": _strip_json_export(status)})

    effective_format = (requested_format or _export_format(status)).strip().lower()
    if effective_format == "xls":
        effective_format = "xlsx"
    if effective_format != "json":
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "data": {
                    "job_id": status.get("job_id"),
                    "state": status.get("state"),
                    "format": effective_format or None,
                },
                "error": {
                    "code": "SELLER_SPRITE_RESULT_FORMAT_NOT_JSON",
                    "message": "任务结果不是 JSON 格式，请使用 export 接口读取文件下载信息",
                },
            },
        )

    inline = {
        "job_id": status.get("job_id"),
        "scenario": status.get("scenario"),
        "site": status.get("site"),
        "period": status.get("period"),
        "state": status.get("state"),
        "stage": status.get("stage"),
        "ready": status.get("ready"),
        "row_count": status.get("row_count"),
        "result": status.get("data"),
    }
    return JSONResponse(
        status_code=200,
        content={"success": True, "data": inline, "error": None},
    )


@router.get("/scenarios")
async def seller_sprite_scenarios_api() -> JSONResponse:
    """列出 Collector 当前支持的卖家精灵场景。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(seller_sprite_proxy.seller_sprite_scenarios)
    return _result_response(result)


@router.get("/quota")
async def seller_sprite_quota_api() -> JSONResponse:
    """读取当前用户的卖家精灵每日额度。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(seller_sprite_proxy.seller_sprite_quota_status)
    return _result_response(result)


@router.post("/jobs/status")
async def seller_sprite_jobs_status_api(
    payload: SellerSpriteJobsStatusRequest,
) -> JSONResponse:
    """批量读取普通卖家精灵任务状态。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_jobs_status,
        **payload.model_dump(),
    )
    return _result_response(_strip_json_exports(result))


@router.post("/jobs")
async def seller_sprite_submit_api(payload: SellerSpriteRunRequest) -> JSONResponse:
    """提交普通卖家精灵异步任务并返回队列快照。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_run,
        **payload.model_dump(exclude_none=True),
    )
    return _result_response(result, success_status_code=202)


@router.get("/jobs/{job_id}")
async def seller_sprite_job_status_api(
    job_id: SellerSpritePathJobId,
    wait_seconds: int = Query(default=0, ge=0, le=30),
) -> JSONResponse:
    """读取单个普通卖家精灵任务状态。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_job_status,
        job_id=job_id,
        wait_seconds=wait_seconds,
    )
    return _result_response(_strip_json_exports(result))


@router.get("/jobs/{job_id}/result")
async def seller_sprite_job_result_api(
    job_id: SellerSpritePathJobId,
    wait_seconds: int = Query(default=0, ge=0, le=30),
) -> JSONResponse:
    """读取普通任务的 API 专用内联 JSON 结果。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_job_status,
        job_id=job_id,
        wait_seconds=wait_seconds,
    )
    return _json_result_response(result)


@router.get("/jobs/{job_id}/export")
async def seller_sprite_export_api(
    job_id: SellerSpritePathJobId,
) -> JSONResponse:
    """JSON 任务直接返回数据，文件任务返回下载信息。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    status_result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_job_status,
        job_id=job_id,
        wait_seconds=0,
    )
    status = status_result.get("data")
    if status_result.get("success") is not True:
        return _result_response(status_result)
    if isinstance(status, dict) and (
        _task_is_pending(status) or _export_format(status) == "json"
    ):
        return _json_result_response(status_result)

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_export,
        job_id=job_id,
    )
    return _result_response(result)


@router.post("/listing-analysis/jobs")
async def seller_sprite_listing_analysis_submit_api(
    payload: SellerSpriteListingAnalysisRequest,
) -> JSONResponse:
    """提交 Listing Analysis 异步任务。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_listing_analysis_submit,
        **payload.model_dump(exclude_none=True),
    )
    return _result_response(result, success_status_code=202)


@router.get("/listing-analysis/jobs/{job_id}")
async def seller_sprite_listing_analysis_status_api(
    job_id: SellerSpritePathJobId,
) -> JSONResponse:
    """读取 Listing Analysis 任务状态。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_listing_analysis_status,
        job_id=job_id,
    )
    return _result_response(_strip_json_exports(result))


@router.get("/listing-analysis/jobs/{job_id}/result")
async def seller_sprite_listing_analysis_result_api(
    job_id: SellerSpritePathJobId,
    export_format: SellerSpriteExportFormat = Query(default="json"),
) -> JSONResponse:
    """读取 Listing Analysis 最终结果。"""
    auth_error = _authentication_error()
    if auth_error is not None:
        return auth_error
    from opscli.mcp.tools import seller_sprite_proxy

    result = await _call_gateway_proxy(
        seller_sprite_proxy.seller_sprite_listing_analysis_result,
        job_id=job_id,
        export_format=export_format,
    )
    if export_format == "json":
        return _json_result_response(result, requested_format=export_format)
    return _result_response(result)


__all__ = [
    "SellerSpriteJobsStatusRequest",
    "SellerSpriteListingAnalysisRequest",
    "SellerSpriteRunRequest",
    "router",
]
