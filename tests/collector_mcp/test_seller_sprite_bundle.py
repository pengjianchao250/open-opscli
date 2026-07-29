"""SellerSprite Collector Bundle 生命周期测试。"""

import asyncio

from opscli.seller_sprite import mcp_bundle


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
        async with mcp_bundle.lifespan():
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
            raise RuntimeError("scheduler unavailable")

        async def close(self):
            self.closed = True

    scheduler = FakeScheduler()
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: scheduler,
    )

    async def scenario():
        async with mcp_bundle.lifespan():
            raise AssertionError("启动失败时不应进入服务阶段")

    try:
        asyncio.run(scenario())
    except RuntimeError as exc:
        assert str(exc) == "scheduler unavailable"
    else:
        raise AssertionError("预期调度器启动异常")

    health = asyncio.run(mcp_bundle.health_check())
    assert health["status"] == "failed"
    assert scheduler.closed is True
