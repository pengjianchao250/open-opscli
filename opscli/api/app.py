"""面向产品化场景的 FastAPI 外壳（应用工厂）。

本模块只负责应用组装：中间件、异常处理器、路由注册与 MCP ASGI 组合；
HTTP 合同见 schemas/，路由见 routers/，共享依赖见 deps.py，错误信封见
errors.py。查询业务仍由 query 规划器和 QueryManager 负责，确保 MCP Tool
与 REST API 共用同一业务内核。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from opscli.api.errors import register_exception_handlers
from opscli.api.routers import health, keepa, query


def create_api_app(*, lifespan: Any = None) -> FastAPI:
    """创建产品化 REST API 应用。

    Args:
        lifespan: 可选的 MCP/宿主生命周期上下文，用于组合 ASGI 应用时复用资源管理。

    Returns:
        注册了健康检查、query 全量取数和 keepa 场景路由的 FastAPI 实例。
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
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(keepa.router)
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
