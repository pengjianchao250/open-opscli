"""面向产品化场景的 FastAPI 外壳。

本模块只负责 HTTP 合同、认证边界和协议组合；查询业务仍由 query
规划器和 QueryManager 负责，确保 MCP Tool 与 REST API 共用同一业务内核。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

_logger = logging.getLogger("opscli.api")


def _trace_keepa_api(message: str) -> None:
    """复用鉴权层的低依赖 Keepa 诊断输出。"""
    try:
        from opscli.mcp.auth_middleware import _trace_keepa

        _trace_keepa(message)
    except Exception:
        # 诊断日志不能影响 API 请求。
        pass


class QueryFlowOrderBy(BaseModel):
    """查询结果排序项。"""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=128)
    desc: bool = False


class QueryFlowRequest(BaseModel):
    """自然语言取数 API 的稳定请求合同。"""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=4000)
    requested_fields: list[str] = Field(default_factory=list, max_length=100)
    limit: int | None = Field(default=None, ge=1, le=10000)
    order_by: list[QueryFlowOrderBy] | None = Field(default=None, max_length=50)
    offset: int | None = Field(default=None, ge=0)


class KeepaRunRequest(BaseModel):
    """Keepa 场景 API 的稳定请求合同。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    site: str = Field(default="US", min_length=2, max_length=8)
    export_format: Literal["xls", "xlsx", "json"] = "xls"
    job_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    reserve_tokens: int | None = Field(default=None, ge=0)
    force: bool = False
    wait: bool = False


def _error_response(*, code: str, message: str, status_code: int) -> JSONResponse:
    """构造统一 API 错误响应，保持与 MCP 工具的 success/data/error 结构一致。"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


def _safe_exception_message(exc: Exception) -> str:
    """仅向调用方暴露可用于修正请求的业务错误，避免泄漏内部细节。"""
    safe_types = (ValueError,)
    if isinstance(exc, safe_types):
        return str(exc) or "请求参数无效"
    return "查询服务执行失败，请稍后重试"


def _run_query_flow(
    payload: QueryFlowRequest,
    *,
    user_email: str,
) -> dict[str, Any]:
    """在线程池中执行同步查询规划器，避免阻塞 FastAPI 事件循环。"""
    from opscli.mcp.tools.helpers import (
        _get_auth_pair,
        _get_credential_dir,
        _query_manager,
    )
    from opscli.query.services.planner import run_flow

    session_id, jwt = _get_auth_pair("ops", None, None)
    order_by = [item.model_dump() for item in payload.order_by] if payload.order_by else None
    return run_flow(
        payload.request,
        user_email=user_email,
        base_dir=_get_credential_dir(),
        requested_fields=payload.requested_fields,
        limit=payload.limit,
        order_by=order_by,
        offset=payload.offset,
        query_manager=_query_manager(jwt=jwt, session_id=session_id),
    )


async def _run_keepa_scenario(payload: KeepaRunRequest) -> dict[str, Any]:
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

    # REST 不直接调用 Manager：MCP 的 quota_wrap 负责日额度占用/失败退回，
    # telemetry_wrap 负责同一套低敏场景维度统计。
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
        result = await governed_run(**payload.model_dump(exclude_none=True))
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


def create_api_app(*, lifespan: Any = None) -> FastAPI:
    """创建产品化 REST API 应用。

    Args:
        lifespan: 可选的 MCP/宿主生命周期上下文，用于组合 ASGI 应用时复用资源管理。

    Returns:
        注册了健康检查和 query_flow 场景接口的 FastAPI 实例。
    """
    app = FastAPI(
        title="opscli Scenario API",
        version="v1",
        description="面向网站和业务系统的 Aukeys 运营场景 API。",
        lifespan=lifespan,
    )
    # 允许本地 HTML 原型跨端口调用 REST API；生产环境仍应通过部署层收紧来源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health/live", tags=["health"])
    async def health_live() -> dict[str, str]:
        """返回进程存活状态。"""
        return {"status": "live"}

    @app.post("/api/v1/query/flow", tags=["query"])
    async def query_flow(payload: QueryFlowRequest, _request: Request) -> JSONResponse:
        """执行一次自然语言取数规划，并在可执行时返回查询结果。"""
        from opscli.mcp.tools.helpers import _get_authenticated_user_email

        user_email = _get_authenticated_user_email()
        if not user_email:
            return _error_response(
                code="authentication_required",
                message="请先完成 opscli 账号授权",
                status_code=401,
            )

        try:
            result = await run_in_threadpool(
                _run_query_flow,
                payload,
                user_email=user_email,
            )
        except Exception as exc:
            return _error_response(
                code=type(exc).__name__,
                message=_safe_exception_message(exc),
                status_code=502,
            )

        return JSONResponse(
            {
                "success": True,
                "data": result,
                "error": None,
            }
        )

    @app.get("/api/v1/keepa/scenarios", tags=["keepa"])
    async def keepa_scenarios() -> JSONResponse:
        """列出可用于 Keepa 场景执行的公开场景定义。"""
        try:
            from opscli.keepa.services import KeepaApiManager

            scenarios = await run_in_threadpool(KeepaApiManager().scenarios)
        except Exception as exc:
            return _error_response(
                code=type(exc).__name__,
                message="Keepa 场景列表读取失败，请稍后重试",
                status_code=502,
            )
        return JSONResponse({"success": True, "data": scenarios, "error": None})

    @app.post("/api/v1/keepa/run", tags=["keepa"])
    async def keepa_run(payload: KeepaRunRequest) -> JSONResponse:
        """执行 Keepa 场景并返回完整格式化数据和额度信息。"""
        _trace_keepa_api(
            "route_enter path=/api/v1/keepa/run scenario=%s site=%s"
            % (payload.scenario, payload.site)
        )
        from opscli.mcp.tools.helpers import _get_authenticated_user_email

        user_email = _get_authenticated_user_email()
        _trace_keepa_api(
            "route_identity_resolved has_user_email=%s" % bool(user_email)
        )
        if not user_email:
            return _error_response(
                code="authentication_required",
                message="请先完成 opscli 账号授权",
                status_code=401,
            )

        try:
            result = await _run_keepa_scenario(payload)
        except Exception as exc:
            return _error_response(
                code=type(exc).__name__,
                message=_safe_exception_message(exc),
                status_code=502,
            )
        # keepa_run 已返回统一 success/data/error 合同，并由 quota_wrap 补充 quota。
        return JSONResponse(result)

    return app


def wrap_mcp_app(mcp_app: Any) -> FastAPI:
    """把 MCP ASGI 路由与产品化 REST 路由合并到同一 FastAPI 应用。

    MCP 子应用的生命周期被传给 FastAPI，避免 Streamable HTTP/SSE 的会话管理
    因挂载而丢失。调用方应在外层继续放置 ApiKeyAuthMiddleware。
    """
    router = getattr(mcp_app, "router", None)
    lifespan = getattr(router, "lifespan_context", None)
    app = create_api_app(lifespan=lifespan)
    app.router.routes.extend(list(getattr(mcp_app, "routes", ())))
    return app
