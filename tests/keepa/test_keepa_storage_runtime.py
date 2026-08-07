"""通用 MCP Keepa 数据沉淀生命周期测试。"""

import asyncio
from types import SimpleNamespace

from opscli.keepa import mcp_runtime


def test_keepa_runtime_registers_collection_storage_adapter(monkeypatch, tmp_path):
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

    storage_runtime = FakeRuntime()
    monkeypatch.setattr(
        "opscli.keepa.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )
    runtime = mcp_runtime.KeepaMcpRuntime()

    async def scenario():
        async with runtime.lifespan(storage_runtime):
            assert runtime.collection_submitter is not None
            runtime.require_ready()

    asyncio.run(scenario())

    assert runtime.collection_submitter is None
    assert calls == [
        "parser:register:keepa",
        "reconciler:register:keepa",
        "reconciler:unregister:keepa",
        "parser:unregister:keepa",
    ]


def test_keepa_runtime_is_ready_without_optional_storage():
    class FakeRuntime:
        settings = type("Settings", (), {"enabled": False, "data_environment": None})()

    runtime = mcp_runtime.KeepaMcpRuntime()

    async def scenario():
        async with runtime.lifespan(FakeRuntime()):
            runtime.require_ready()
            assert runtime.collection_submitter is None

    asyncio.run(scenario())


def test_keepa_runtime_blocks_collection_when_storage_registration_fails():
    class FakeRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_source(self, parser, reconciler):
            raise RuntimeError("storage registration failed")

        def unregister_source(self, source_system):
            raise AssertionError("注册失败后不应解除未注册来源")

    runtime = mcp_runtime.KeepaMcpRuntime()

    async def scenario():
        async with runtime.lifespan(FakeRuntime()):
            result = await runtime.keepa_run(scenario="product")
            assert result["success"] is False
            assert result["error"]["code"] == "KEEPA_MODULE_NOT_READY"

    asyncio.run(scenario())
