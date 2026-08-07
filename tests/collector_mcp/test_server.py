"""统一数据采集 MCP Server 工具边界测试。"""

import asyncio

from fastmcp import Client

from opscli.collector_mcp.health import collector_modules_health, collector_service_info
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
    assert len(names) == 20
    assert {name for name in names if name.startswith("keepa_")} == {
        "keepa_export",
        "keepa_job_status",
        "keepa_quota_status",
        "keepa_run",
        "keepa_scenarios",
        "keepa_spec_must_read",
    }
    assert all(
        name in PUBLIC_TOOLS
        or name.startswith("seller_sprite_")
        or name.startswith("keepa_")
        for name in names
    )
    assert "query_simple" not in names
    assert "auth_system_sync" not in names


def test_collector_health_is_redacted_and_reports_not_ready_before_lifespan():
    info = _run(collector_service_info())
    health = _run(collector_modules_health())

    assert info["data"]["display_name"] == "数据采集服务"
    assert info["data"]["bundles"] == ["seller_sprite", "keepa"]
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
