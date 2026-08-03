"""Collector Monitor Starlette 应用工厂与只读 HTTP API。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Mapping

from opscli.collector_monitor.service import (
    CollectorMonitorProbeBusyError,
    CollectorMonitorProbeCooldownError,
)
from opscli.collector_monitor.ui import DASHBOARD_HTML

_MAX_API_LIMIT = 500
_ALLOWED_HEALTH = {
    "healthy",
    "slow",
    "stalled",
    "orphaned",
    "queue_starved",
    "worker_unavailable",
}
_ALLOWED_TASK_STATUS = {"queued", "running", "succeeded", "failed"}
_ALLOWED_TASK_KIND = {"generic", "listing_analysis"}
_ALLOWED_INCIDENT_STATUS = {"active", "resolved"}
_ALLOWED_INCIDENT_RULE = {"stalled", "orphaned", "queue_starved", "worker_unavailable"}
_SENSITIVE_KEYS = {
    "account",
    "account_id",
    "account_key",
    "api_key",
    "assigned_account",
    "assigned_account_key",
    "credential",
    "credential_scope",
    "authorization",
    "cookie",
    "password",
    "secret",
    "params",
    "params_json",
    "request",
    "request_json",
    "path",
    "root_dir",
    "result_path",
    "error_json",
    "raw_error",
    "session_id",
    "jwt",
    "token",
    "webhook",
}


def create_app(service: Any, *, manage_polling: bool = True) -> Any:
    """创建只读 Starlette 应用，并可选择管理后台轮询生命周期。"""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Route

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        stop_event = asyncio.Event()
        task = None
        if manage_polling:
            async def bootstrap_polling() -> None:
                """后台完成首次扫描，再进入固定间隔轮询。"""
                await service.poll_once()
                await service.run(stop_event, poll_immediately=False)

            # 不等待 SQLite 首扫完成，确保存活端点可在启动后立即响应。
            task = asyncio.create_task(bootstrap_polling())
        try:
            yield
        finally:
            if task is not None:
                stop_event.set()
                await task

    async def home(_request: Request) -> Any:
        """返回嵌入式只读仪表盘。"""
        return HTMLResponse(DASHBOARD_HTML)

    async def live(_request: Request) -> Any:
        """返回进程存活状态。"""
        return JSONResponse({"status": "live"})

    async def ready(_request: Request) -> Any:
        """根据缓存中的本地数据源状态返回就绪结果。"""
        snapshot = service.cached_snapshot
        if service.is_ready:
            return JSONResponse(
                {"status": "ready", "generated_at": snapshot.get("generated_at")}
            )
        return JSONResponse(
            {
                "status": "not_ready",
                "source_error": _redact(snapshot.get("source", {}).get("error")),
            },
            status_code=503,
        )

    async def status(_request: Request) -> Any:
        """返回完整脱敏缓存快照。"""
        return JSONResponse(_redact(service.cached_snapshot))

    async def tasks(request: Request) -> Any:
        """返回有界缓存任务列表并支持白名单过滤。"""
        try:
            limit = _query_limit(request.query_params.get("limit"), default=100)
            filters = _allowed_filters(
                request.query_params,
                {"health": _ALLOWED_HEALTH, "status": _ALLOWED_TASK_STATUS, "task_kind": _ALLOWED_TASK_KIND},
            )
        except ValueError as exc:
            return JSONResponse(
                {"error": {"code": "invalid_query", "message": str(exc)}},
                status_code=400,
            )
        values = service.cached_snapshot.get("tasks", [])
        for field, expected in filters.items():
            source_field = "lifecycle" if field == "status" else field
            values = [item for item in values if item.get(source_field) == expected]
        return JSONResponse({"tasks": _redact(values[:limit])})

    async def task_detail(request: Request) -> Any:
        """返回缓存任务详情和进度时间线。"""
        job_id = request.path_params["job_id"]
        try:
            detail = service.task_detail(job_id)
        except KeyError:
            return JSONResponse(
                {"error": {"code": "task_not_found", "message": "任务不存在"}},
                status_code=404,
            )
        return JSONResponse(_redact(detail))

    async def incidents(request: Request) -> Any:
        """返回有界缓存事故列表并支持白名单过滤。"""
        try:
            limit = _query_limit(request.query_params.get("limit"), default=100)
            filters = _allowed_filters(
                request.query_params,
                {"status": _ALLOWED_INCIDENT_STATUS, "rule": _ALLOWED_INCIDENT_RULE},
            )
        except ValueError as exc:
            return JSONResponse(
                {"error": {"code": "invalid_query", "message": str(exc)}},
                status_code=400,
            )
        values = service.cached_snapshot.get("incidents", [])
        for field, expected in filters.items():
            values = [item for item in values if item.get(field) == expected]
        return JSONResponse({"incidents": _redact(values[:limit])})

    async def manual_probe(target: str) -> Any:
        """执行固定目标的手动探测并映射并发与冷却状态。"""
        try:
            result = await service.manual_probe(target)
        except CollectorMonitorProbeBusyError:
            return JSONResponse(
                {"error": {"code": "probe_in_progress", "message": "该目标正在探测中"}},
                status_code=409,
            )
        except CollectorMonitorProbeCooldownError as exc:
            return JSONResponse(
                {
                    "error": {
                        "code": "probe_cooldown",
                        "message": "该目标仍在探测冷却期",
                        "retry_after": exc.retry_after,
                    }
                },
                status_code=429,
            )
        return JSONResponse(_redact(result))

    async def validate_probe_request(request: Request) -> Any | None:
        """拒绝跨源或非 JSON 的浏览器探测请求。"""
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin is not None and origin.rstrip("/") != expected_origin:
            return JSONResponse(
                {"error": {"code": "cross_origin_probe_denied", "message": "拒绝跨源探测请求"}},
                status_code=403,
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return JSONResponse(
                {"error": {"code": "invalid_content_type", "message": "探测请求必须使用 application/json"}},
                status_code=415,
            )
        return None

    async def probe_collector(request: Request) -> Any:
        """手动探测配置中的固定 Collector MCP。"""
        invalid = await validate_probe_request(request)
        if invalid is not None:
            return invalid
        return await manual_probe("collector")

    async def probe_queue_source(request: Request) -> Any:
        """手动只读探测配置中的固定 SellerSprite 队列源。"""
        invalid = await validate_probe_request(request)
        if invalid is not None:
            return invalid
        return await manual_probe("queue-source")

    async def no_store(request: Any, call_next: Any) -> Any:
        """禁止浏览器和代理缓存监控数据。"""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            Route("/health/live", live, methods=["GET"]),
            Route("/health/ready", ready, methods=["GET"]),
            Route("/api/v1/status", status, methods=["GET"]),
            Route("/api/v1/tasks", tasks, methods=["GET"]),
            Route("/api/v1/tasks/{job_id}", task_detail, methods=["GET"]),
            Route("/api/v1/incidents", incidents, methods=["GET"]),
            Route("/api/v1/probes/collector", probe_collector, methods=["POST"]),
            Route("/api/v1/probes/queue-source", probe_queue_source, methods=["POST"]),
        ],
        middleware=[Middleware(BaseHTTPMiddleware, dispatch=no_store)],
        lifespan=lifespan,
    )


def _query_limit(value: str | None, *, default: int) -> int:
    """解析严格有界的 API 行数。"""
    try:
        parsed = default if value is None else int(value)
    except ValueError as exc:
        raise ValueError("limit 必须是整数") from exc
    if parsed < 1 or parsed > _MAX_API_LIMIT:
        raise ValueError(f"limit 必须在 1 到 {_MAX_API_LIMIT} 之间")
    return parsed


def _allowed_filters(params: Any, allowed: Mapping[str, set[str]]) -> dict[str, str]:
    """拒绝未知参数和白名单之外的过滤值。"""
    unknown = set(params) - set(allowed) - {"limit"}
    if unknown:
        raise ValueError(f"不支持的查询参数：{sorted(unknown)[0]}")
    result: dict[str, str] = {}
    for name, values in allowed.items():
        value = params.get(name)
        if value is not None:
            if value not in values:
                raise ValueError(f"不支持的 {name} 过滤值")
            result[name] = value
    return result


def _redact(value: Any) -> Any:
    """递归剔除敏感键，作为 API 输出的纵深防御。"""
    if isinstance(value, Mapping):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_KEYS
            and not str(key).lower().endswith("_path")
            and not str(key).lower().endswith("_json")
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value
