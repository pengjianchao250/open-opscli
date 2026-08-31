"""统一数据采集 MCP Server 工具边界测试。"""

import asyncio

from fastmcp import Client

from opscli.collector_mcp.health import CollectorHealthTools
from opscli.collector_mcp.profile import load_profile
from opscli.collector_mcp.registry import resolve_bundles
from opscli.collector_mcp.server import PUBLIC_TOOLS, catalog, mcp
from opscli.mcp.tool_catalog import get_catalog


def _run(coro):
    return asyncio.run(coro)


def test_collector_only_exposes_public_and_collection_bundle_tools(monkeypatch):
    async def allow_all():
        return None

    class FakeStore:
        def reset_running_tasks(self):
            return 0

    class FakeScheduler:
        store = FakeStore()

        async def start(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: FakeScheduler(),
    )

    async def scenario():
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    names = _run(scenario())

    assert PUBLIC_TOOLS <= names
    assert len(names) == 14
    assert not any(name.startswith("keepa_") for name in names)
    assert all(
        name in PUBLIC_TOOLS
        or name.startswith("seller_sprite_")
        for name in names
    )
    assert "query_simple" not in names
    assert "auth_system_sync" not in names


def test_collector_health_is_redacted_and_reports_not_ready_before_lifespan():
    class FakeStorageRuntime:
        def health(self):
            return {
                "status": "disabled",
                "checks": {
                    "outbox": "disabled",
                    "mysql": "disabled",
                    "worker": "disabled",
                },
            }

    profile = load_profile({})
    health_tools = CollectorHealthTools(
        profile,
        resolve_bundles(profile),
        FakeStorageRuntime(),
    )
    info = _run(health_tools.collector_service_info())
    health = _run(health_tools.collector_modules_health())

    assert info["data"]["display_name"] == "数据采集服务"
    assert info["data"]["bundles"] == ["seller_sprite"]
    assert info["data"]["single_worker_required"] is True
    assert health["data"]["status"] == "not_ready"
    serialized = str({"info": info, "health": health}).lower()
    assert "config_dir" not in serialized
    assert "credential" not in serialized
    assert "api_key" not in serialized


def test_collector_catalog_is_isolated_from_general_catalog():
    import opscli.mcp.server  # noqa: F401  填充通用 MCP 默认清单

    collector_names = {item["name"] for item in catalog.get_catalog()}
    general_names = {item["name"] for item in get_catalog()}

    assert "collector_service_info" in collector_names
    assert "collector_service_info" not in general_names
    assert "query_simple" in general_names
    assert "query_simple" not in collector_names
