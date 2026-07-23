"""MCP HTTP/SSE 服务与卖家精灵调度器生命周期测试。"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.testclient import TestClient


class RecordingScheduler:
    def __init__(self) -> None:
        self.start_calls = 0
        self.close_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def test_seller_sprite_lifespan_starts_and_closes_scheduler_once(monkeypatch):
    from opscli.mcp.server import _with_seller_sprite_lifespan
    from opscli.seller_sprite import services

    events = []
    scheduler = RecordingScheduler()

    @asynccontextmanager
    async def original_lifespan(_app):
        events.append("app-start")
        try:
            yield
        finally:
            events.append("app-close")

    monkeypatch.setattr(services, "get_task_scheduler", lambda: scheduler)
    original_app = Starlette(lifespan=original_lifespan)
    original_app.state.marker = "preserved"
    app = _with_seller_sprite_lifespan(original_app)

    assert app is original_app
    assert app.state.marker == "preserved"
    with TestClient(app):
        assert scheduler.start_calls == 1
        assert events == ["app-start"]

    assert scheduler.close_calls == 1
    assert events == ["app-start", "app-close"]


def test_dual_endpoint_app_uses_single_scheduler_lifespan(monkeypatch):
    from opscli.mcp.server import _build_dual_endpoint_app
    from opscli.seller_sprite import services

    scheduler = RecordingScheduler()
    monkeypatch.setattr(services, "get_task_scheduler", lambda: scheduler)
    app = _build_dual_endpoint_app(api_key="test-api-key")

    with TestClient(app):
        assert scheduler.start_calls == 1

    assert scheduler.close_calls == 1


def test_seller_sprite_lifespan_closes_scheduler_when_start_fails(monkeypatch):
    from opscli.mcp.server import _with_seller_sprite_lifespan
    from opscli.seller_sprite import services

    class FailingScheduler(RecordingScheduler):
        async def start(self) -> None:
            self.start_calls += 1
            raise RuntimeError("scheduler start failed")

    scheduler = FailingScheduler()
    monkeypatch.setattr(services, "get_task_scheduler", lambda: scheduler)
    app = _with_seller_sprite_lifespan(Starlette())

    try:
        with TestClient(app):
            pass
    except RuntimeError as exc:
        assert str(exc) == "scheduler start failed"
    else:
        raise AssertionError("scheduler 启动失败应阻止 ASGI 应用启动")

    assert scheduler.start_calls == 1
    assert scheduler.close_calls == 1
