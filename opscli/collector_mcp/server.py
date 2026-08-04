"""统一数据采集 MCP Server 入口。"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from opscli.collector_mcp import health
from opscli.collector_mcp.profile import load_profile
from opscli.collector_mcp.registry import resolve_bundles, validate_bundle_tools
from opscli.collector_mcp.storage.runtime import collection_storage_lifespan
from opscli.mcp.app_factory import create_mcp_app, run_mcp_app
from opscli.mcp.tool_catalog import ToolCatalog
from opscli.mcp.tools.auth import auth_is_authenticated, auth_mcp_login

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


profile = load_profile()
bundles = resolve_bundles(profile)
health.configure_health(profile, bundles)


@asynccontextmanager
async def _collector_lifespan(_server):
    """按稳定顺序启动 Bundle，并在关闭时逆序释放资源。"""
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(collection_storage_lifespan())
        for bundle in bundles:
            await stack.enter_async_context(bundle.lifespan())
        yield {}


catalog = ToolCatalog()
registrars = [_register_minimal_auth, health.register]
registrars.extend(bundle.register for bundle in bundles)
mcp = create_mcp_app(
    name="opscli-collector",
    instructions=(
        "Aukeys 统一数据采集 MCP 服务。\n"
        "仅公开 Profile 显式启用的数据采集 Tool Bundle。\n"
        "使用 auth_mcp_login 完成 MCP 一步登录后调用业务工具。"
    ),
    registrars=registrars,
    catalog=catalog,
    lifespan=_collector_lifespan,
)
validate_bundle_tools(catalog.get_catalog(), bundles, public_tools=PUBLIC_TOOLS)


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
