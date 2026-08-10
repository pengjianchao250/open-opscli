"""Google Trends MCP Server 注册测试。"""

import asyncio
from types import SimpleNamespace

from fastmcp import Client

from opscli.mcp import server as server_module
from opscli.mcp.server import mcp


def _run(coro):
    """运行异步测试协程。"""
    return asyncio.run(coro)


def test_server_registers_google_trends_tools(monkeypatch):
    """Google Trends 工具应出现在正式 MCP Server 的工具列表中。"""

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)

    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    names = [tool.name for tool in tools]

    assert "google_trends_spec_must_read" in names
    assert "google_trends_scenarios" in names
    assert "google_trends_run" in names
    assert "google_trends_job_status" in names
    assert "google_trends_export" in names


def test_server_lifespan_registers_google_trends_collection_source(
    monkeypatch, tmp_path
):
    """通用 MCP 生命周期应组合 Google Trends 数据沉淀 Runtime。"""
    calls = []

    class FakeStorageRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        async def start(self):
            calls.append("storage:start")

        async def close(self):
            calls.append("storage:close")

        def register_source(self, parser, reconciler):
            calls.append(f"source:register:{parser.source_system}")

        def unregister_source(self, source_system):
            calls.append(f"source:unregister:{source_system}")

        def submit(self, submission):
            return True

    storage_runtime = FakeStorageRuntime()
    monkeypatch.setattr(
        server_module,
        "build_collection_storage_runtime",
        lambda runtime_id: storage_runtime,
    )
    monkeypatch.setattr(
        "opscli.google_trends.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )

    async def allow_all():
        return None

    monkeypatch.setattr("opscli.mcp.permissions._resolve_allowed_tools", allow_all)
    test_server, _registrars = server_module._build_server()

    async def scenario():
        async with Client(test_server) as client:
            return await client.list_tools()

    tools = _run(scenario())

    assert any(tool.name == "google_trends_run" for tool in tools)
    assert "source:register:google_trends" in calls
    assert "source:unregister:google_trends" in calls
    assert calls[0] == "storage:start"
    assert calls[-1] == "storage:close"


def test_optional_asin_review_registration_skips_only_when_module_missing(monkeypatch):
    """仅当顶层 asin_review 模块缺失时，才允许降级跳过。"""
    calls = []

    def fake_import_module(name: str):
        assert name == "opscli.mcp.tools.asin_review"
        raise ModuleNotFoundError("missing optional module", name=name)

    class FakeLogger:
        """记录降级日志。"""

        def info(self, message: str) -> None:
            calls.append(("info", message))

    monkeypatch.setattr(server_module.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(server_module, "_logger", FakeLogger())

    server_module._register_optional_asin_review_tool(SimpleNamespace())

    assert calls == [("info", "asin_review 工具未加载：缺少可选模块 opscli.mcp.tools.asin_review")]


def test_optional_asin_review_registration_reraises_internal_module_not_found(monkeypatch):
    """asin_review 模块内部缺依赖时，不应被静默吞掉。"""

    def fake_import_module(name: str):
        assert name == "opscli.mcp.tools.asin_review"
        raise ModuleNotFoundError("inner dependency missing", name="opscli.mcp.tools.shared_bits")

    monkeypatch.setattr(server_module.importlib, "import_module", fake_import_module)

    try:
        server_module._register_optional_asin_review_tool(SimpleNamespace())
    except ModuleNotFoundError as exc:
        assert exc.name == "opscli.mcp.tools.shared_bits"
    else:
        raise AssertionError("expected internal ModuleNotFoundError to be re-raised")
