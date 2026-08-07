"""Keepa Collector Bundle 生命周期测试。"""

import asyncio
from types import SimpleNamespace

from opscli.keepa import mcp_bundle


def test_keepa_bundle_registers_collection_storage_adapter(monkeypatch, tmp_path):
    calls = []

    class FakeRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_parser(self, parser):
            calls.append(f"parser:register:{parser.source_system}")

        def unregister_parser(self, source_system):
            calls.append(f"parser:unregister:{source_system}")

        def register_reconciler(self, reconciler):
            calls.append(f"reconciler:register:{reconciler.source_system}")

        def unregister_reconciler(self, source_system):
            calls.append(f"reconciler:unregister:{source_system}")

        def submit(self, submission):
            calls.append(f"submit:{submission.source_system}:{submission.source_job_id}")
            return True

    runtime = FakeRuntime()
    monkeypatch.setattr(
        "opscli.collector_mcp.storage.runtime.get_collection_storage_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        "opscli.keepa.config.load_settings",
        lambda: SimpleNamespace(output_dir=tmp_path),
    )
    bundle_runtime = mcp_bundle.KeepaBundleRuntime()

    async def scenario():
        async with bundle_runtime.lifespan():
            assert bundle_runtime.collection_submitter is not None
            health = await bundle_runtime.health_check()
            assert health == {
                "bundle_id": "keepa",
                "status": "ready",
                "checks": {"api": "ready", "storage_registration": "ok"},
            }

    asyncio.run(scenario())

    assert bundle_runtime.collection_submitter is None
    assert calls == [
        "parser:register:keepa",
        "reconciler:register:keepa",
        "reconciler:unregister:keepa",
        "parser:unregister:keepa",
    ]


def test_keepa_bundle_is_ready_without_optional_storage(monkeypatch):
    class FakeRuntime:
        settings = type("Settings", (), {"enabled": False, "data_environment": None})()

    monkeypatch.setattr(
        "opscli.collector_mcp.storage.runtime.get_collection_storage_runtime",
        lambda: FakeRuntime(),
    )
    bundle_runtime = mcp_bundle.KeepaBundleRuntime()

    async def scenario():
        async with bundle_runtime.lifespan():
            health = await bundle_runtime.health_check()
            assert health["status"] == "ready"
            assert health["checks"]["storage_registration"] == "disabled"

    asyncio.run(scenario())


def test_keepa_bundle_blocks_collection_when_storage_registration_fails(monkeypatch):
    class FakeRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()
        outbox = object()

        def register_parser(self, parser):
            raise RuntimeError("storage registration failed")

    monkeypatch.setattr(
        "opscli.collector_mcp.storage.runtime.get_collection_storage_runtime",
        lambda: FakeRuntime(),
    )
    bundle_runtime = mcp_bundle.KeepaBundleRuntime()

    async def scenario():
        async with bundle_runtime.lifespan():
            result = await bundle_runtime.keepa_run(scenario="product")
            assert result["success"] is False
            assert result["error"]["code"] == "COLLECTOR_MODULE_NOT_READY"

    asyncio.run(scenario())
