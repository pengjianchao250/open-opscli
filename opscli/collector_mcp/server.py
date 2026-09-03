"""统一数据采集 MCP Server 入口。"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from opscli.collector_mcp.health import CollectorHealthTools
from opscli.collector_mcp.prefetch import CollectorPrefetchRuntime
from opscli.collector_mcp.profile import load_profile
from opscli.collector_mcp.registry import resolve_bundles, validate_bundle_tools
from opscli.mcp.app_factory import create_mcp_app, run_mcp_app
from opscli.mcp.tool_catalog import ToolCatalog
from opscli.mcp.tools.auth import auth_is_authenticated, auth_mcp_login
from opscli.shared.collection_storage import (
    build_collection_storage_runtime,
    collection_storage_lifespan,
)

PUBLIC_TOOLS = frozenset(
    {
        "auth_mcp_login",
        "auth_is_authenticated",
        "collector_service_info",
        "collector_modules_health",
    }
)


def _register_minimal_auth(mcp) -> None:
    """仅注册 Collector 业务所需的最小认证入口。"""
    mcp.tool()(auth_mcp_login)
    mcp.tool()(auth_is_authenticated)


def _build_server():
    """构造 Collector MCP，并让 App 闭包独占存储 Runtime。"""
    profile = load_profile()
    bundles = resolve_bundles(profile)
    storage_runtime = build_collection_storage_runtime("collector")
    prefetch_runtime = CollectorPrefetchRuntime(
        storage_runtime,
        seller_sprite_enabled=any(
            bundle.bundle_id == "seller_sprite" for bundle in bundles
        ),
    )
    health_tools = CollectorHealthTools(profile, bundles, storage_runtime)

    @asynccontextmanager
    async def lifespan(_server):
        """按稳定顺序启动存储和 Bundle，并在关闭时逆序释放。"""
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(
                collection_storage_lifespan(storage_runtime)
            )
            for bundle in bundles:
                await stack.enter_async_context(bundle.lifespan(storage_runtime))
            await stack.enter_async_context(prefetch_runtime.lifespan())
            yield {}

    catalog = ToolCatalog()
    registrars = [_register_minimal_auth, health_tools.register]
    registrars.extend(bundle.register for bundle in bundles)
    server = create_mcp_app(
        name="opscli-collector",
        instructions=(
            "Aukeys 统一数据采集 MCP 服务。\n"
            "仅公开 Profile 显式启用的数据采集 Tool Bundle。\n"
            "使用 auth_mcp_login 完成 MCP 一步登录后调用业务工具。"
        ),
        registrars=registrars,
        catalog=catalog,
        lifespan=lifespan,
    )
    validate_bundle_tools(catalog.get_catalog(), bundles, public_tools=PUBLIC_TOOLS)
    return server, catalog


mcp, catalog = _build_server()


def run() -> None:
    """运行统一数据采集 MCP 服务。"""
    run_mcp_app(
        mcp,
        service_name="opscli-collector-mcp",
        catalog=catalog.get_catalog(),
        api_key_filename="collector_mcp_api_key",
    )


if __name__ == "__main__":
    run()
