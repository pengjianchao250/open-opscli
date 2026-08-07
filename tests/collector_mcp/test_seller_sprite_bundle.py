"""SellerSprite Collector Bundle 生命周期测试。"""

import asyncio
import sqlite3

import pytest

from opscli.seller_sprite import mcp_bundle


class _DisabledStorageRuntime:
    settings = type("Settings", (), {"enabled": False})()


def test_seller_sprite_bundle_starts_and_closes_scheduler(monkeypatch):
    calls = []

    class FakeScheduler:
        async def start(self):
            calls.append("start")

        async def close(self):
            calls.append("close")

    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: FakeScheduler(),
    )

    async def scenario():
        async with mcp_bundle.lifespan(_DisabledStorageRuntime()):
            health = await mcp_bundle.health_check()
            assert health["status"] == "ready"
            assert health["checks"] == {"queue": "ok", "scheduler": "running"}

    asyncio.run(scenario())

    assert calls == ["start", "close"]
    assert asyncio.run(mcp_bundle.health_check())["status"] == "not_ready"


def test_seller_sprite_bundle_marks_failed_when_scheduler_start_fails(monkeypatch):
    class FakeScheduler:
        closed = False

        async def start(self):
            raise sqlite3.OperationalError(
                "unable to open database file: /var/lib/opscli/private.sqlite3"
            )

        async def close(self):
            self.closed = True

    scheduler = FakeScheduler()
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: scheduler,
    )

    async def scenario():
        async with mcp_bundle.lifespan(_DisabledStorageRuntime()):
            health = await mcp_bundle.health_check()
            assert health == {
                "bundle_id": "seller_sprite",
                "status": "failed",
                "checks": {"queue": "error", "scheduler": "not_started"},
                "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                "error_class": "OperationalError",
            }
            assert "/var/lib" not in repr(health)

    asyncio.run(scenario())
    assert scheduler.closed is True


def test_seller_sprite_bundle_rejects_business_access_when_not_ready(monkeypatch):
    monkeypatch.setitem(mcp_bundle._MODULE_STATE, "status", "failed")

    with pytest.raises(mcp_bundle.SellerSpriteModuleNotReadyError) as exc_info:
        mcp_bundle.require_ready()

    assert exc_info.value.to_dict() == {
        "code": "COLLECTOR_MODULE_NOT_READY",
        "message": "卖家精灵采集模块尚未就绪，请先检查 Collector 模块健康状态",
        "module": "seller_sprite",
    }


def test_seller_sprite_bundle_registers_collector_storage_adapter(monkeypatch):
    calls = []

    class FakeScheduler:
        collection_submitter = None
        store = object()

        async def start(self):
            calls.append("scheduler:start")

        async def close(self):
            calls.append("scheduler:close")

    class FakeRuntime:
        settings = type("Settings", (), {"enabled": True, "data_environment": "debug"})()

        def register_source(self, parser, reconciler):
            calls.append(f"parser:register:{parser.source_system}")
            calls.append(f"reconciler:register:{reconciler.source_system}")

        def unregister_source(self, source_system):
            calls.append(f"reconciler:unregister:{source_system}")
            calls.append(f"parser:unregister:{source_system}")

        def submit(self, submission):
            return True

    scheduler = FakeScheduler()
    runtime = FakeRuntime()
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: scheduler,
    )
    async def scenario():
        async with mcp_bundle.lifespan(runtime):
            assert scheduler.collection_submitter is not None

    asyncio.run(scenario())

    assert calls == [
        "parser:register:seller_sprite",
        "reconciler:register:seller_sprite",
        "scheduler:start",
        "scheduler:close",
        "reconciler:unregister:seller_sprite",
        "parser:unregister:seller_sprite",
    ]
    assert scheduler.collection_submitter is None
