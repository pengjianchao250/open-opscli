"""FastAPI runtime for the Keepa JSON Lens frontend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field


KeepaRunner = Callable[..., Awaitable[dict[str, Any]]]


class KeepaRunRequest(BaseModel):
    """Stable browser request contract for Keepa scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    site: str = Field(default="US", min_length=2, max_length=8)
    export_format: str = "json"
    job_id: str | None = None
    reserve_tokens: int | None = Field(default=None, ge=0)
    force: bool = False
    wait: bool = False


def _frontend_file(dist: Path, request_path: str) -> Path | None:
    candidate = (dist / request_path).resolve()
    if not candidate.is_relative_to(dist):
        return None
    return candidate if candidate.is_file() else None


def _bearer_token(request: Request) -> str | None:
    ops_token = request.headers.get("X-Ops-Token", "").strip()
    if ops_token:
        return ops_token
    authorization = request.headers.get("Authorization", "").strip()
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def _default_keepa_runner(**kwargs: Any) -> dict[str, Any]:
    # Keep these imports request-local so AppHub startup does not load unrelated API routes.
    from opscli.keepa.api.scenarios import telemetry_dimensions
    from opscli.mcp.context import mcp_request_ctx
    from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
    from opscli.mcp.tools.keepa import _KEEPA_API_MODE, keepa_run

    context_token = mcp_request_ctx.set(
        {
            "email": kwargs.pop("user_email", None),
            "session_id": kwargs.get("session_id"),
            "jwt": kwargs.get("jwt"),
        }
    )
    api_mode_token = _KEEPA_API_MODE.set(True)
    governed_run = telemetry_wrap(
        quota_wrap(keepa_run),
        module="keepa",
        dimension_resolver=telemetry_dimensions,
    )
    try:
        return await governed_run(**kwargs)
    finally:
        _KEEPA_API_MODE.reset(api_mode_token)
        mcp_request_ctx.reset(context_token)


def create_app(
    *,
    frontend_dist: str | Path | None = None,
    keepa_runner: KeepaRunner | None = None,
) -> FastAPI:
    app = FastAPI(title="test-keepa")
    dist = Path(
        frontend_dist or Path(__file__).resolve().parents[1] / "frontend" / "dist"
    ).resolve()
    run_keepa = keepa_runner or _default_keepa_runner

    @app.get("/__apphub_healthz", include_in_schema=False)
    async def apphub_healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/keepa/run")
    async def keepa_run_route(payload: KeepaRunRequest, request: Request) -> JSONResponse:
        jwt = _bearer_token(request)
        session_id = (
            request.cookies.get("polarisUserToken")
            or request.headers.get("X-Session-Id")
            or ""
        ).strip() or None
        if not jwt and not session_id:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "authentication_required",
                        "message": "AppHub login is missing or expired",
                    },
                },
            )

        result = await run_keepa(
            **payload.model_dump(exclude_none=True),
            session_id=session_id,
            jwt=jwt,
            user_email=request.headers.get("X-User-Email", "").strip() or None,
        )
        return JSONResponse(result)

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def api_not_found(path: str) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "data": None,
                "error": {"code": "not_found", "message": "API route not found"},
            },
        )

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
        response_model=None,
    )
    async def serve_frontend(path: str) -> FileResponse | JSONResponse:
        static_file = _frontend_file(dist, path)
        if static_file is not None:
            return FileResponse(static_file)
        if path.startswith("assets/") or Path(path).suffix:
            return JSONResponse(status_code=404, content={"detail": "Static asset not found"})
        index_file = _frontend_file(dist, "index.html")
        if index_file is None:
            return JSONResponse(status_code=404, content={"detail": "Frontend build is missing"})
        return FileResponse(index_file)

    return app


app = create_app()
