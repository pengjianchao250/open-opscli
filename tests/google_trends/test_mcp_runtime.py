"""通用 MCP Google Trends 数据沉淀生命周期测试。"""

import asyncio
import inspect
from types import SimpleNamespace

from opscli.google_trends import mcp_runtime
from opscli.mcp.tools import google_trends as google_trends_tools


def test_google_trends_runtime_registers_collection_storage_adapter(
    monkeypatch, tmp_path
):
    """启用沉淀时应在生命周期内注册并清理 Google Trends 来源。"""
    calls = []

    class FakeRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_source(self, parser, reconciler):
            calls.append(f"parser:register:{parser.source_system}")
            calls.append(f"reconciler:register:{reconciler.source_system}")

        def unregister_source(self, source_system):
            calls.append(f"reconciler:unregister:{source_system}")
            calls.append(f"parser:unregister:{source_system}")

        def submit(self, submission):
            calls.append(f"submit:{submission.source_system}:{submission.source_job_id}")
            return True

    monkeypatch.setattr(
        "opscli.google_trends.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )
    runtime = mcp_runtime.GoogleTrendsMcpRuntime()

    async def scenario():
        async with runtime.lifespan(FakeRuntime()):
            assert runtime.collection_submitter is not None
            runtime.require_ready()

    asyncio.run(scenario())

    assert runtime.collection_submitter is None
    assert calls == [
        "parser:register:google_trends",
        "reconciler:register:google_trends",
        "reconciler:unregister:google_trends",
        "parser:unregister:google_trends",
    ]


def test_google_trends_runtime_is_ready_without_optional_storage():
    """未启用共享存储时应保持 Google Trends MCP 可用。"""

    class FakeRuntime:
        settings = type("Settings", (), {"enabled": False, "data_environment": None})()

    runtime = mcp_runtime.GoogleTrendsMcpRuntime()

    async def scenario():
        async with runtime.lifespan(FakeRuntime()):
            runtime.require_ready()
            assert runtime.collection_submitter is None

    asyncio.run(scenario())


def test_google_trends_runtime_injects_collection_submitter(monkeypatch, tmp_path):
    """运行时绑定的 MCP 工具应把当前提交器注入 API Manager 调用链。"""
    captured = {}

    class FakeStorageRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_source(self, parser, reconciler):
            return None

        def unregister_source(self, source_system):
            return None

        def submit(self, submission):
            return True

    async def fake_run_impl(**kwargs):
        captured.update(kwargs)
        return {"success": True, "data": {"job_id": "job-1"}, "error": None}

    monkeypatch.setattr(
        "opscli.google_trends.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )
    monkeypatch.setattr(
        google_trends_tools,
        "_google_trends_run_impl",
        fake_run_impl,
        raising=False,
    )
    runtime = mcp_runtime.GoogleTrendsMcpRuntime()

    async def scenario():
        async with runtime.lifespan(FakeStorageRuntime()):
            return await runtime.google_trends_run(
                scenario="trends",
                params={"q": "flashlight"},
            )

    result = asyncio.run(scenario())

    assert result["success"] is True
    assert callable(captured["collection_submitter"])
    assert captured["scenario"] == "trends"
    assert captured["params"] == {"q": "flashlight"}


def test_google_trends_runtime_lifespan_is_reentrant(monkeypatch, tmp_path):
    """SSE/HTTP 共用 Server 时嵌套 lifespan 不应重复注册来源。"""
    calls = []
    registered = set()

    class FakeStorageRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_source(self, parser, reconciler):
            if parser.source_system in registered:
                raise ValueError("duplicate source")
            registered.add(parser.source_system)
            calls.append(f"register:{parser.source_system}")

        def unregister_source(self, source_system):
            registered.remove(source_system)
            calls.append(f"unregister:{source_system}")

        def submit(self, submission):
            return True

    monkeypatch.setattr(
        "opscli.google_trends.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )
    runtime = mcp_runtime.GoogleTrendsMcpRuntime()
    storage_runtime = FakeStorageRuntime()

    async def scenario():
        async with runtime.lifespan(storage_runtime):
            outer_submitter = runtime.collection_submitter
            async with runtime.lifespan(storage_runtime):
                runtime.require_ready()
                assert runtime.collection_submitter is outer_submitter
            runtime.require_ready()
            assert runtime.collection_submitter is outer_submitter

    asyncio.run(scenario())

    assert calls == ["register:google_trends", "unregister:google_trends"]
    assert runtime.collection_submitter is None


def test_google_trends_runtime_hides_non_reconcilable_job_controls():
    """生产 MCP 不应允许任务写到对账范围外或复用数据库幂等键。"""
    parameters = inspect.signature(
        mcp_runtime.GoogleTrendsMcpRuntime.google_trends_run
    ).parameters

    assert "output_dir" not in parameters
    assert "job_id" not in parameters
