import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.browser_route import ocr as ocr_module
from opscli.seller_sprite.browser_route import worker as worker_module
from opscli.seller_sprite.browser_route.worker import SellerSpriteBrowserRouteWorker
from opscli.seller_sprite.config import (
    DEFAULT_BROWSER_RUNTIME,
    DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    DEFAULT_TASK_HEARTBEAT_SECONDS,
    DEFAULT_TASK_LEASE_SECONDS,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    SellerSpriteSettings,
    load_settings,
)
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError


def _run(coro):
    return asyncio.run(coro)


def test_close_browser_route_worker_closes_and_removes_account_session():
    class CloseProbe:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    async def scenario():
        worker_module._WORKERS.clear()
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        probe = CloseProbe()
        settings = SellerSpriteSettings()
        key = worker_module._worker_registry_key(
            settings=settings,
            account=account,
            owner_id="default",
        )
        worker_module._WORKERS[key] = probe

        closed = await worker_module.close_browser_route_worker(
            settings=settings,
            account=account,
        )

        assert closed is True
        assert probe.closed is True
        assert worker_module.get_existing_browser_route_worker(
            settings=SellerSpriteSettings(),
            account=account,
        ) is None

    _run(scenario())


def test_authentication_failure_close_quarantines_persistent_profile(tmp_path):
    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(browser_profile_dir=tmp_path / "profiles")
        account = SellerSpriteAccount(
            name="account-1",
            username="user@example.com",
            password="secret",
        )
        profile_dir = settings.browser_profile_dir / "account-1-a542c5d5f236"
        profile_dir.mkdir(parents=True)
        (profile_dir / "Cookies").write_text("diagnostic-state", encoding="utf-8")
        worker_module.get_browser_route_worker(settings=settings, account=account)

        closed = await worker_module.close_browser_route_worker(
            settings=settings,
            account=account,
            reason="authentication_failed",
        )

        quarantined = list((settings.browser_profile_dir / ".quarantine").iterdir())
        assert closed is True
        assert not profile_dir.exists()
        assert len(quarantined) == 1
        assert quarantined[0].name.startswith("account-1-a542c5d5f236-")
        assert (quarantined[0] / "Cookies").read_text(encoding="utf-8") == "diagnostic-state"

    _run(scenario())


def test_profile_quarantine_waits_until_last_account_owner_closes(tmp_path):
    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(browser_profile_dir=tmp_path / "profiles")
        account = SellerSpriteAccount(
            name="account-1",
            username="user@example.com",
            password="secret",
        )
        profile_dir = settings.browser_profile_dir / "account-1-a542c5d5f236"
        profile_dir.mkdir(parents=True)
        worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-a",
        )
        worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-b",
        )

        await worker_module.close_browser_route_worker(
            settings=settings,
            account=account,
            reason="authentication_failed",
            owner_id="scheduler-a",
        )
        assert profile_dir.exists()

        await worker_module.close_browser_route_worker(
            settings=settings,
            account=account,
            reason="authentication_failed",
            owner_id="scheduler-b",
        )
        assert not profile_dir.exists()

    _run(scenario())


def test_profile_quarantine_does_not_move_profile_locked_by_other_process(tmp_path):
    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(browser_profile_dir=tmp_path / "profiles")
        account = SellerSpriteAccount(
            name="account-1",
            username="user@example.com",
            password="secret",
        )
        profile_dir = settings.browser_profile_dir / "account-1-a542c5d5f236"
        profile_dir.mkdir(parents=True)
        (profile_dir / "SingletonLock").write_text("locked", encoding="utf-8")

        closed = await worker_module.close_browser_route_worker(
            settings=settings,
            account=account,
            reason="authentication_failed",
        )

        assert closed is False
        assert profile_dir.exists()
        assert not (settings.browser_profile_dir / ".quarantine").exists()

    _run(scenario())


def test_close_all_browser_route_workers_releases_healthy_sessions(tmp_path):
    """调度器关闭时应统一释放当前事件循环中的健康会话。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        accounts = [
            SellerSpriteAccount(name=f"account-{index}", username=f"user-{index}@example.com", password="secret")
            for index in (1, 2)
        ]
        closed = []
        transitions = []

        class CloseProbe:
            def __init__(self, account_name):
                self.account_name = account_name

            async def close(self):
                closed.append(self.account_name)

        for account in accounts:
            worker = worker_module.get_browser_route_worker(
                settings=settings,
                account=account,
                state_listener=lambda current_account, payload: transitions.append(
                    (current_account.name, payload["state"], payload["reason"])
                ),
            )
            worker.mark_session_ready(context=CloseProbe(account.name), page=object())

        close_count = await worker_module.close_all_browser_route_workers(
            settings=settings,
            reason="scheduler_close",
        )

        assert close_count == 2
        assert closed == ["account-1", "account-2"]
        assert all(
            worker_module.get_existing_browser_route_worker(settings=settings, account=account) is None
            for account in accounts
        )
        assert transitions == [
            ("account-1", "registered", "worker_registered"),
            ("account-1", "ready", "browser_context_opened"),
            ("account-2", "registered", "worker_registered"),
            ("account-2", "ready", "browser_context_opened"),
            ("account-1", "closing", "scheduler_close"),
            ("account-1", "closed", "scheduler_close"),
            ("account-2", "closing", "scheduler_close"),
            ("account-2", "closed", "scheduler_close"),
        ]

    _run(scenario())


def test_close_all_browser_route_workers_continues_cleanup_after_context_close_failure(tmp_path):
    """context 关闭失败时仍应停止 Playwright，并报告 close_failed。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        transitions = []
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=lambda current_account, payload: transitions.append(payload),
        )

        class FailingContext:
            async def close(self):
                raise RuntimeError("context close failed")

        class PlaywrightProbe:
            def __init__(self):
                self.stopped = False

            async def stop(self):
                self.stopped = True

        playwright = PlaywrightProbe()
        worker.mark_session_ready(context=FailingContext(), page=object())
        worker._playwright = playwright

        close_count = await worker_module.close_all_browser_route_workers(
            settings=settings,
            reason="scheduler_close",
        )

        assert close_count == 0
        assert playwright.stopped is True
        assert transitions[-1]["state"] == "close_failed"
        assert transitions[-1]["error_code"] == "RuntimeError"
        assert worker_module.get_existing_browser_route_worker(settings=settings, account=account) is None

    _run(scenario())


def test_reap_browser_route_workers_closes_session_after_thirty_idle_minutes(monkeypatch, tmp_path):
    """空闲未满 30 分钟保持复用，达到阈值后关闭并从 registry 移除。"""

    async def scenario():
        worker_module._WORKERS.clear()
        now = [100.0]
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        settings = SellerSpriteSettings(
            output_dir=tmp_path,
            browser_idle_ttl_seconds=1800,
            browser_max_lifetime_seconds=21600,
        )
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            clock=lambda: now[0],
        )

        class CloseProbe:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        context = CloseProbe()

        async def fake_run_one(request):
            worker.mark_session_ready(context=context, page=object())
            return worker_module.BrowserRouteResult(
                login={"logged_in": True},
                response={"code": "OK", "data": {"items": []}},
                high_frequency_response=None,
                warnings=[],
            )

        monkeypatch.setattr(worker, "_run_one", fake_run_one)
        await worker.submit(
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
            )
        )

        now[0] = 1899.0
        assert await worker_module.reap_browser_route_workers(settings=settings, now=now[0]) == []
        assert context.closed is False

        now[0] = 1900.0
        recycled = await worker_module.reap_browser_route_workers(settings=settings, now=now[0])

        assert recycled == [{"account_name": "account-1", "reason": "idle_timeout"}]
        assert context.closed is True
        assert worker_module.get_existing_browser_route_worker(settings=settings, account=account) is None

    _run(scenario())


def test_worker_automatically_reaps_idle_session_without_scheduler(monkeypatch, tmp_path):
    """debug/直调路径没有 scheduler 时，worker 也应按自身计时器回收。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(
            output_dir=tmp_path,
            browser_idle_ttl_seconds=1,
            browser_max_lifetime_seconds=60,
        )
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        states = []
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=lambda current_account, payload: states.append(payload["state"]),
        )

        class CloseProbe:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        context = CloseProbe()

        async def fake_run_one(request):
            worker.mark_session_ready(context=context, page=object())
            return worker_module.BrowserRouteResult(login={}, response={})

        monkeypatch.setattr(worker, "_run_one", fake_run_one)
        await worker.submit(
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
            )
        )
        await asyncio.sleep(1.1)

        assert context.closed is True
        assert worker_module.get_existing_browser_route_worker(
            settings=settings,
            account=account,
        ) is None
        assert states[-2:] == ["recycling", "closed"]

    _run(scenario())


def test_listing_report_failure_returns_session_to_idle_and_schedules_reap(monkeypatch, tmp_path):
    """Listing 报告异常也必须形成 idle 边界并恢复自动回收。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        states = []
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=lambda current_account, payload: states.append(payload["state"]),
        )

        class CloseProbe:
            async def close(self):
                return None

        async def fail_capture(**kwargs):
            worker.mark_session_ready(context=CloseProbe(), page=object())
            worker._transition_state("busy", reason="task_started")
            raise RuntimeError("capture failed")

        monkeypatch.setattr(worker, "_fetch_listing_analysis_report_once", fail_capture)
        with pytest.raises(RuntimeError, match="capture failed"):
            await worker.fetch_listing_analysis_report(task_id="task-1", root_dir=tmp_path)

        assert states[-1] == "idle"
        assert worker._automatic_reap_task is not None
        await worker.close()

    _run(scenario())


def test_reap_browser_route_workers_rotates_six_hour_session_only_after_busy_task(monkeypatch, tmp_path):
    """六小时轮换不得中断运行中任务，应在任务完成边界关闭。"""

    async def scenario():
        worker_module._WORKERS.clear()
        now = [100.0]
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        settings = SellerSpriteSettings(
            output_dir=tmp_path,
            browser_idle_ttl_seconds=1800,
            browser_max_lifetime_seconds=21600,
        )
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            clock=lambda: now[0],
        )

        class CloseProbe:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        context = CloseProbe()
        request = worker_module.BrowserRouteRequest(
            scenario="keyword-reverse",
            method="POST",
            endpoint="/v3/api/keyword/reverse",
            payload={"asin": "B0TEST"},
            referer=worker_module.DEFAULT_PAGE_URL,
            account=account,
            root_dir=tmp_path,
        )

        async def first_run(current_request):
            worker.mark_session_ready(context=context, page=object())
            return worker_module.BrowserRouteResult(
                login={"logged_in": True},
                response={"code": "OK", "data": {"items": []}},
                high_frequency_response=None,
                warnings=[],
            )

        monkeypatch.setattr(worker, "_run_one", first_run)
        await worker.submit(request)

        started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def blocking_run(current_request):
            started.set()
            await allow_finish.wait()
            return worker_module.BrowserRouteResult(
                login={"logged_in": True},
                response={"code": "OK", "data": {"items": []}},
                high_frequency_response=None,
                warnings=[],
            )

        monkeypatch.setattr(worker, "_run_one", blocking_run)
        now[0] = 21700.0
        running = asyncio.create_task(worker.submit(request))
        await started.wait()

        assert await worker_module.reap_browser_route_workers(settings=settings, now=now[0]) == []
        assert context.closed is False

        allow_finish.set()
        await running
        recycled = await worker_module.reap_browser_route_workers(settings=settings, now=now[0])

        assert recycled == [{"account_name": "account-1", "reason": "max_lifetime"}]
        assert context.closed is True

    _run(scenario())


def test_browser_route_worker_reports_real_session_state_changes_without_duplicates(monkeypatch, tmp_path):
    """会话只报告真实状态变化，复用任务应产生 busy/idle 状态链。"""

    async def scenario():
        worker_module._WORKERS.clear()
        now = [100.0]
        transitions = []
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        settings = SellerSpriteSettings(output_dir=tmp_path)
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=lambda current_account, payload: transitions.append(payload),
            clock=lambda: now[0],
        )

        class CloseProbe:
            async def close(self):
                return None

        context = CloseProbe()

        async def fake_run_one(request):
            worker.mark_session_ready(context=context, page=object())
            return worker_module.BrowserRouteResult(
                login={"logged_in": True},
                response={"code": "OK", "data": {"items": []}},
                high_frequency_response=None,
                warnings=[],
            )

        monkeypatch.setattr(worker, "_run_one", fake_run_one)
        request = worker_module.BrowserRouteRequest(
            scenario="keyword-reverse",
            method="POST",
            endpoint="/v3/api/keyword/reverse",
            payload={"asin": "B0TEST"},
            referer=worker_module.DEFAULT_PAGE_URL,
            account=account,
            root_dir=tmp_path,
        )
        await worker.submit(request)
        now[0] = 200.0
        await worker.submit(request)
        now[0] = 2000.0
        await worker_module.reap_browser_route_workers(settings=settings, now=now[0])

        assert [event["state"] for event in transitions] == [
            "registered",
            "ready",
            "idle",
            "busy",
            "idle",
            "recycling",
            "closed",
        ]
        assert transitions[-2]["reason"] == "idle_timeout"
        assert transitions[-1]["task_count"] == 2

    _run(scenario())


def test_worker_owner_isolation_prevents_scheduler_from_closing_other_sessions(tmp_path):
    """同配置的两个调度器必须只关闭自己拥有的会话。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        owner_a = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-a",
        )
        owner_b = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-b",
        )

        closed = await worker_module.close_all_browser_route_workers(
            settings=settings,
            owner_id="scheduler-a",
        )

        assert closed == 1
        assert worker_module.get_existing_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-a",
        ) is None
        assert worker_module.get_existing_browser_route_worker(
            settings=settings,
            account=account,
            owner_id="scheduler-b",
        ) is owner_b
        assert owner_a is not owner_b

    _run(scenario())


def test_close_all_cleans_old_browser_namespace_after_settings_reload(tmp_path):
    """浏览器启动配置热更新后，owner 仍应清理旧命名空间会话。"""

    async def scenario():
        worker_module._WORKERS.clear()
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        old_settings = SellerSpriteSettings(browser_profile_dir=tmp_path / "old")
        new_settings = SellerSpriteSettings(browser_profile_dir=tmp_path / "new")
        old_worker = worker_module.get_browser_route_worker(
            settings=old_settings,
            account=account,
            owner_id="scheduler-a",
        )
        new_worker = worker_module.get_browser_route_worker(
            settings=new_settings,
            account=account,
            owner_id="scheduler-a",
        )

        assert old_worker is not new_worker
        assert await worker_module.close_all_browser_route_workers(
            settings=new_settings,
            owner_id="scheduler-a",
        ) == 2
        assert not any(key[1] == "scheduler-a" for key in worker_module._WORKERS)

    _run(scenario())


def test_reserved_worker_is_not_reaped_until_task_releases_reservation(monkeypatch, tmp_path):
    """已领取任务预留的会话在提交窗口内不得被周期回收。"""

    async def scenario():
        worker_module._WORKERS.clear()
        now = [100.0]
        settings = SellerSpriteSettings(output_dir=tmp_path, browser_idle_ttl_seconds=1800)
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            clock=lambda: now[0],
        )

        class CloseProbe:
            async def close(self):
                return None

        worker.mark_session_ready(context=CloseProbe(), page=object())
        worker._last_finished_at = now[0]
        reservation = worker_module.reserve_browser_route_worker(settings=settings, account=account)
        assert reservation is worker

        now[0] = 1900.0
        assert await worker_module.reap_browser_route_workers(settings=settings, now=now[0]) == []

        reservation.release_reservation()
        assert await worker_module.reap_browser_route_workers(settings=settings, now=now[0]) == [
            {"account_name": "account-1", "reason": "idle_timeout"}
        ]

    _run(scenario())


def test_closing_worker_waits_for_queue_and_old_reference_cannot_reopen(monkeypatch, tmp_path):
    """显式关闭应等待当前任务，并拒绝旧引用在移出 registry 后再次提交。"""

    async def scenario():
        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")
        transitions = []
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=lambda current_account, payload: transitions.append(payload["state"]),
        )
        started = asyncio.Event()
        finish = asyncio.Event()

        class CloseProbe:
            async def close(self):
                return None

        context = CloseProbe()

        async def blocking_run(request):
            worker.mark_session_ready(context=context, page=object())
            started.set()
            await finish.wait()
            return worker_module.BrowserRouteResult(login={}, response={})

        monkeypatch.setattr(worker, "_run_one", blocking_run)
        request = worker_module.BrowserRouteRequest(
            scenario="keyword-reverse",
            method="POST",
            endpoint="/v3/api/keyword/reverse",
            payload={},
            referer=worker_module.DEFAULT_PAGE_URL,
            account=account,
            root_dir=tmp_path,
        )
        running = asyncio.create_task(worker.submit(request))
        await started.wait()
        closing = asyncio.create_task(
            worker_module.close_browser_route_worker(settings=settings, account=account)
        )
        await asyncio.sleep(0)
        assert closing.done() is False

        finish.set()
        await running
        assert await closing is True
        with pytest.raises(worker_module.BrowserRouteWorkerClosedError):
            await worker.submit(request)
        replacement = worker_module.get_browser_route_worker(settings=settings, account=account)
        assert replacement is not worker
        assert transitions[-3:] == ["idle", "closing", "closed"]

    _run(scenario())


def test_record_timing_keeps_diagnostic_data_without_warning_log(caplog, tmp_path):
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-reverse",
        method="POST",
        endpoint="/v3/api/keyword/reverse",
        payload={"asin": "B0TEST"},
        referer=worker_module.DEFAULT_PAGE_URL,
        account=account,
        root_dir=tmp_path,
    )
    timings = []

    with caplog.at_level("WARNING", logger=worker_module.__name__):
        event = worker_module._record_timing(
            timings,
            request,
            "test",
            0.0,
            url=worker_module.DEFAULT_PAGE_URL,
        )

    assert event["stage"] == "test"
    assert timings == [event]
    assert "卖家精灵 browser-route 耗时" not in caplog.text


def test_route_fetch_keeps_success_when_page_closes_during_unroute(monkeypatch, tmp_path):
    """主请求成功后页面关闭时，unroute 清理不得覆盖成功结果。"""

    class TargetClosedError(Exception):
        """模拟 Playwright/Patchright 目标关闭异常。"""

    class ClosingPage:
        async def route(self, pattern, handler):
            return None

        def is_closed(self):
            return False

        async def unroute(self, pattern, handler):
            raise TargetClosedError(
                "Page.unroute: Target page, context or browser has been closed"
            )

    async def fake_trigger(*args, **kwargs):
        return SimpleNamespace(status=200), "page_response"

    async def fake_parse(*args, **kwargs):
        return {"code": "OK", "data": {"items": []}}

    monkeypatch.setattr(worker_module, "_trigger_request", fake_trigger)
    monkeypatch.setattr(worker_module, "_parse_response", fake_parse)
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
    )

    result = _run(
        worker._execute_route_fetch(
            page=ClosingPage(),
            method="POST",
            endpoint="/v3/api/keyword/reverse",
            payload={"asin": "B0TEST"},
            root_dir=tmp_path,
            section="main",
        )
    )

    assert result == {"code": "OK", "data": {"items": []}}


def test_route_fetch_keeps_primary_error_when_page_closes_during_unroute(
    monkeypatch, tmp_path
):
    """主请求失败且页面关闭时，unroute 清理不得覆盖主异常。"""

    class TargetClosedError(Exception):
        """模拟 Playwright/Patchright 目标关闭异常。"""

    class ClosingPage:
        async def route(self, pattern, handler):
            return None

        def is_closed(self):
            return False

        async def unroute(self, pattern, handler):
            raise TargetClosedError(
                "Page.unroute: Target page, context or browser has been closed"
            )

    async def fail_trigger(*args, **kwargs):
        raise SellerSpriteApiError(
            "卖家精灵主请求失败",
            api_code="ERR_BROWSER_FETCH_FAILED",
        )

    monkeypatch.setattr(worker_module, "_trigger_request", fail_trigger)
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker._execute_route_fetch(
                page=ClosingPage(),
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                root_dir=tmp_path,
                section="main",
            )
        )

    assert exc_info.value.api_code == "ERR_BROWSER_FETCH_FAILED"


class FakePage:
    def __init__(self, *, url="", logged_in=False):
        self.url = url
        self.goto_calls = []
        self.reload_calls = 0
        self.timeout_calls = []
        self.logged_in = logged_in

    async def goto(self, url, **kwargs):
        self.url = url
        self.goto_calls.append({"url": url, "kwargs": kwargs})

    async def wait_for_timeout(self, timeout):
        self.timeout_calls.append(timeout)

    async def reload(self, **kwargs):
        self.reload_calls += 1


class RedirectedLoginPage(FakePage):
    async def goto(self, url, **kwargs):
        await super().goto(url, **kwargs)
        if url.startswith(worker_module.LOGIN_URL):
            self.url = worker_module.DEFAULT_PAGE_URL
            self.logged_in = True

    def locator(self, selector):
        raise AssertionError(f"locator should not be called after logged-in redirect: {selector}")


class LoginPage(FakePage):
    def __init__(self, *, url=worker_module.LOGIN_URL, logged_in=False):
        super().__init__(url=url, logged_in=logged_in)
        self.wait_for_url_calls = []

    async def wait_for_url(self, predicate, **kwargs):
        self.wait_for_url_calls.append(kwargs)
        self.url = worker_module.DEFAULT_PAGE_URL
        self.logged_in = True
        assert predicate(self.url)

    def get_by_text(self, text):
        raise AssertionError(f"text check should not run after login redirect: {text}")


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class FakeCaptchaLocator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    def locator(self, selector):
        return self.page.locator(selector)

    async def count(self):
        return int(self.kind != "missing" and (self.kind != "dialog" or self.page.dialog_visible))

    async def is_visible(self, **kwargs):
        return self.kind != "missing" and (self.kind != "dialog" or self.page.dialog_visible)

    async def get_attribute(self, name):
        if self.kind == "image" and name == "src":
            return "data:image/gif;base64,aW1hZ2U="
        return None

    async def screenshot(self):
        return b"image"

    async def fill(self, value):
        self.page.filled_values.append(value)

    async def click(self, **kwargs):
        self.page.clicks.append(self.kind)
        if self.kind == "button":
            self.page.dialog_visible = False


class FakeCaptchaPage:
    def __init__(self, *, dialog_visible=True):
        self.dialog_visible = dialog_visible
        self.filled_values = []
        self.clicks = []
        self.timeout_calls = []

    def locator(self, selector):
        if "机器人检测" in selector or "role='dialog'" in selector:
            return FakeCaptchaLocator(self, "dialog")
        if selector.startswith("img"):
            return FakeCaptchaLocator(self, "image")
        if selector.startswith("input"):
            return FakeCaptchaLocator(self, "input")
        if selector.startswith("button"):
            return FakeCaptchaLocator(self, "button")
        return FakeCaptchaLocator(self, "missing")

    async def wait_for_timeout(self, timeout):
        self.timeout_calls.append(timeout)


class FakeContextRequest:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []

    async def post(self, url, **kwargs):
        self.post_calls.append({"url": url, "kwargs": kwargs})
        return SimpleNamespace(status=200)

    async def get(self, url, **kwargs):
        self.get_calls.append({"url": url, "kwargs": kwargs})
        return SimpleNamespace(status=200)


class FakeContextPage:
    def __init__(self):
        self.url = "https://www.sellersprite.com/v3/listing-analysis?asin=B0TEST&station=GLOBAL"
        self.context = SimpleNamespace(request=FakeContextRequest())


class FakeListingLocator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    async def count(self):
        return int(self.kind != "missing")

    async def is_visible(self, **kwargs):
        return self.kind != "missing"

    async def fill(self, value):
        self.page.fills.append({"kind": self.kind, "value": value})

    async def press(self, key, **kwargs):
        self.page.presses.append({"kind": self.kind, "key": key})

    async def click(self, **kwargs):
        self.page.clicks.append(self.kind)


class FakeListingPage:
    def __init__(self):
        self.fills = []
        self.presses = []
        self.clicks = []
        self.main_response_timeout = None

    def expect_response(self, predicate, **kwargs):
        response = SimpleNamespace(
            url="https://www.sellersprite.com/v3/api/ai-workflow/listing-analysis",
            status=200,
        )
        assert predicate(response)
        self.main_response_timeout = kwargs.get("timeout")
        return _AssociationResponseWaiter(
            "/v3/api/ai-workflow/listing-analysis",
            response=response,
        )

    def locator(self, selector):
        if "placeholder='请选择'" in selector:
            return FakeListingLocator(self, "station_select")
        if "美国站" in selector:
            return FakeListingLocator(self, "station_us")
        if "日本站" in selector:
            return FakeListingLocator(self, "station_japan")
        if selector.startswith("textarea") and "ASIN" in selector:
            return FakeListingLocator(self, "asin")
        if "全景分析" in selector:
            return FakeListingLocator(self, "all")
        if "立即生成解读报告" in selector:
            return FakeListingLocator(self, "submit")
        return FakeListingLocator(self, "missing")


class _AssociationResponseWaiter:
    """模拟 Playwright 的响应等待上下文。"""

    def __init__(self, endpoint, response=None, error=None):
        self.value = asyncio.get_running_loop().create_future()
        if error is not None:
            self.value.set_exception(error)
        else:
            self.value.set_result(
                response
                or SimpleNamespace(
                    url=f"https://www.sellersprite.com{endpoint}",
                    status=200,
                )
            )

    async def __aenter__(self):
        """进入响应等待上下文并返回自身。"""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """按真实 Playwright 语义等待事件，或在代码块异常时取消监听。"""
        if exc is not None:
            self.value.cancel()
            return False
        await self.value
        return False


class _AssociationLocator:
    """记录关联流量页面输入、回车和按钮点击。"""

    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    async def count(self):
        """返回当前测试 locator 是否存在。"""
        return int(self.kind != "missing")

    async def is_visible(self, **kwargs):
        """返回当前测试 locator 是否可见。"""
        return self.kind != "missing"

    async def fill(self, value):
        """记录输入框填充值。"""
        self.page.fills.append(value)

    async def evaluate(self, expression):
        """返回不含请求体和账号信息的按钮 DOM 事件诊断。"""
        if self.kind not in {"sell_well", "current"}:
            return {}
        return {
            "connected": True,
            "visible": True,
            "enabled": True,
            "focused": self.kind in getattr(self.page, "focuses", []),
            "dialogVisible": True,
            "clickCount": self.page.variant_dom_clicks,
            "keydownCount": self.page.variant_dom_keydowns,
            "keyupCount": self.page.variant_dom_keyups,
            "mousedownCount": self.page.variant_dom_mousedowns,
            "mouseupCount": self.page.variant_dom_mouseups,
            "pointerdownCount": self.page.variant_dom_pointerdowns,
            "pointerupCount": self.page.variant_dom_pointerups,
            "clickTrusted": self.page.variant_dom_click_trusted,
            "clickDetail": self.page.variant_dom_click_detail,
        }

    async def focus(self, **kwargs):
        """记录流量词对比变体按钮获得焦点。"""
        if hasattr(self.page, "focuses"):
            self.page.focuses.append(self.kind)
        if hasattr(self.page, "events"):
            self.page.events.append(f"focus_{self.kind}")

    async def scroll_into_view_if_needed(self, **kwargs):
        """模拟滚动到目标按钮。"""

    async def bounding_box(self, **kwargs):
        """返回稳定的按钮坐标，供单次真实鼠标事件激活。"""
        if self.kind not in {"sell_well", "current"}:
            return None
        self.page.variant_mouse_target = self.kind
        return {"x": 100, "y": 50, "width": 160, "height": 40}

    async def press(self, key, **kwargs):
        """记录按键，并模拟回车产生 DOM 键盘和 click 事件。"""
        self.page.presses.append(key)
        if hasattr(self.page, "events"):
            self.page.events.append(f"press_{self.kind}_{key}")
        if self.kind in {"sell_well", "current"} and hasattr(
            self.page, "main_query_calls"
        ):
            if self.page.variant_click_error is not None:
                raise self.page.variant_click_error
            self.page.variant_dom_keydowns += 1
            self.page.variant_dom_keyups += 1
            self.page.variant_dom_clicks += 1
            self.page.main_query_calls += 1

    async def click(self, **kwargs):
        """记录按钮点击及流量词对比主查询触发次数。"""
        self.page.clicks.append(self.kind)
        if hasattr(self.page, "events"):
            self.page.events.append(f"click_{self.kind}")
        if self.kind == "query" and getattr(
            self.page, "query_click_error", None
        ) is not None:
            raise self.page.query_click_error
        if self.kind in {"sell_well", "current"} and hasattr(
            self.page, "main_query_calls"
        ):
            if self.page.variant_click_error is not None:
                raise self.page.variant_click_error
            self.page.main_query_calls += 1

    async def get_attribute(self, name):
        """返回按回车次数生成的 ASIN 计数占位符。"""
        if self.kind == "asin" and name == "placeholder":
            return f"已录入{len(self.page.presses)}/20个ASIN"
        return None


class _AssociationSuccessResponse:
    """模拟关联流量准备接口成功响应。"""

    url = "https://www.sellersprite.com/v3/api/relation/traffic/prepare"
    status = 200

    async def text(self):
        """返回准备接口成功 JSON。"""
        return json.dumps({"code": "OK", "data": {}}, ensure_ascii=False)


class _AssociationPage:
    """模拟关联流量查询入口页。"""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.fills = []
        self.presses = []
        self.clicks = []
        self.timeout_calls = []

    def expect_response(self, predicate, **kwargs):
        """按监听路径返回准备接口或主接口响应。"""
        prepare_response = _AssociationSuccessResponse()
        if predicate(prepare_response):
            return _AssociationResponseWaiter(self.endpoint, response=prepare_response)
        return _AssociationResponseWaiter(self.endpoint)

    def locator(self, selector):
        """按页面选择器返回对应的测试 locator。"""
        if "input" in selector and "ASIN" in selector:
            return _AssociationLocator(self, "asin")
        if "清除" in selector:
            return _AssociationLocator(self, "clear")
        if "用全部变体查询" in selector:
            return _AssociationLocator(self, "all_variants")
        if "立即查询" in selector:
            return _AssociationLocator(self, "query")
        return _AssociationLocator(self, "missing")

    async def wait_for_timeout(self, timeout):
        """记录页面等待时间。"""
        self.timeout_calls.append(timeout)


class _AssociationPrepareErrorResponse:
    """模拟关联流量准备接口返回业务错误。"""

    url = "https://www.sellersprite.com/v3/api/relation/traffic/prepare"
    status = 200

    async def text(self):
        """返回卖家精灵准备接口业务错误 JSON。"""
        return json.dumps(
            {
                "message": "处理请求出现错误,请稍后重试。",
                "code": "ERR_GLOBAL_500",
            },
            ensure_ascii=False,
        )


class _AssociationPageWithoutVariantButton(_AssociationPage):
    """模拟弹窗未提供全部变体按钮的异常页面。"""

    def locator(self, selector):
        """让全部变体按钮保持不可见，其余控件沿用正常页面。"""
        if "用全部变体查询" in selector:
            return _AssociationLocator(self, "missing")
        return super().locator(selector)


class _AssociationPageWithPrepareError(_AssociationPage):
    """模拟准备接口报错且主接口不会发起的关联流量页面。"""

    def expect_response(self, predicate, **kwargs):
        """仅准备接口命中响应，主接口等待由准备错误提前中断。"""
        response = _AssociationPrepareErrorResponse()
        if predicate(response):
            return _AssociationResponseWaiter(self.endpoint, response=response)
        return _AssociationResponseWaiter(self.endpoint)


class _TrafficExtendPrepareResponse:
    """模拟拓展流量词准备接口成功响应。"""

    url = "https://www.sellersprite.com/v3/api/traffic/extend/prepare"
    status = 200

    async def text(self):
        return json.dumps(
            {
                "code": "OK",
                "success": True,
                "data": {
                    "variationResults": 2614,
                    "diamondResults": 2483,
                    "results": 2163,
                    "diamondList": ["B089K9L3VY"],
                },
            },
            ensure_ascii=False,
        )


class _TrafficExtendPage:
    """模拟拓展流量词查询入口页。"""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.fills = []
        self.presses = []
        self.clicks = []
        self.timeout_calls = []

    def expect_response(self, predicate, **kwargs):
        prepare_response = _TrafficExtendPrepareResponse()
        if predicate(prepare_response):
            return _AssociationResponseWaiter(self.endpoint, response=prepare_response)
        return _AssociationResponseWaiter(self.endpoint)

    def locator(self, selector):
        if ".el-select-dropdown__item" in selector and "2026-06" in selector:
            return _AssociationLocator(self, "period_2026-06")
        if ".date-select" in selector:
            return _AssociationLocator(self, "period_select")
        if ("input" in selector or "textarea" in selector) and "ASIN" in selector:
            return _AssociationLocator(self, "asin")
        if "用全部变体拓词" in selector:
            return _AssociationLocator(self, "all_variants")
        if "用畅销变体拓词" in selector:
            return _AssociationLocator(self, "sell_well")
        if "用当前变体拓词" in selector:
            return _AssociationLocator(self, "current")
        if "立即查询" in selector:
            return _AssociationLocator(self, "query")
        return _AssociationLocator(self, "missing")

    async def wait_for_timeout(self, timeout):
        self.timeout_calls.append(timeout)


class _KeywordConversionRateLocator:
    """模拟关键词转化率批量标签输入和筛选控件。"""

    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    async def count(self):
        if self.kind == "tags":
            return len(self.page.tags)
        return int(self.kind != "missing")

    async def is_visible(self, **kwargs):
        return self.kind != "missing"

    async def fill(self, value):
        self.page.current_keyword = value
        self.page.fills.append(value)

    async def press(self, key, **kwargs):
        self.page.presses.append(key)
        self.page.events.append(f"press:{self.page.current_keyword}")
        keyword = self.page.current_keyword.strip()
        if keyword and keyword not in self.page.tags:
            self.page.tags.append(keyword)
        self.page.current_keyword = ""
        if self.page.press_timeout_after_commit:
            raise TimeoutError("input placeholder changed after committed Enter")

    async def click(self, **kwargs):
        self.page.clicks.append(self.kind)
        self.page.events.append(f"click:{self.kind}")
        if self.kind == "clear":
            self.page.tags.clear()
            self.page.current_keyword = ""

    async def get_attribute(self, name):
        if self.kind == "keyword_input" and name == "placeholder":
            if self.page.placeholder_override != "default":
                return self.page.placeholder_override
            return f"已录入{len(self.page.tags)}/1000个关键词"
        return None


class _KeywordConversionRatePage:
    """模拟关键词转化率页面的站点、周期和批量标签交互。"""

    def __init__(
        self,
        endpoint,
        *,
        press_timeout_after_commit=False,
        placeholder_override="default",
    ):
        self.endpoint = endpoint
        self.press_timeout_after_commit = press_timeout_after_commit
        self.placeholder_override = placeholder_override
        self.tags = ["stale keyword"]
        self.current_keyword = ""
        self.fills = []
        self.presses = []
        self.clicks = []
        self.timeout_calls = []
        self.events = []

    def expect_response(self, predicate, **kwargs):
        self.events.append("expect_response")
        return _AssociationResponseWaiter(self.endpoint)

    def locator(self, selector):
        if ".kcr--tags-list" in selector:
            return _KeywordConversionRateLocator(self, "tags")
        if ".batch-input" in selector:
            return _KeywordConversionRateLocator(self, "keyword_input")
        if ":not(.interval-select)" in selector:
            return _KeywordConversionRateLocator(self, "market_select")
        if "interval-select" in selector:
            return _KeywordConversionRateLocator(self, "period_select")
        if "market-select" in selector:
            return _KeywordConversionRateLocator(self, "market_select")
        if "美国站" in selector:
            return _KeywordConversionRateLocator(self, "market_US")
        if "近90天" in selector:
            return _KeywordConversionRateLocator(self, "period_90D")
        if "按周" in selector:
            return _KeywordConversionRateLocator(self, "period_W")
        if "清除" in selector:
            return _KeywordConversionRateLocator(self, "clear")
        if "立即查询" in selector:
            return _KeywordConversionRateLocator(self, "query")
        return _KeywordConversionRateLocator(self, "missing")

    async def wait_for_timeout(self, timeout):
        self.timeout_calls.append(timeout)


class _KeywordComparisonPrepareResponse:
    """模拟流量词对比准备接口响应。"""

    url = "https://www.sellersprite.com/v3/api/keyword-comparison/prepare"

    def __init__(self, payload, *, status=200, raw_text=None):
        self.payload = payload
        self.status = status
        self.raw_text = raw_text

    async def text(self):
        if self.raw_text is not None:
            return self.raw_text
        return json.dumps(self.payload, ensure_ascii=False)


class _KeywordComparisonMouse:
    """模拟只发送一次可信鼠标激活事件。"""

    def __init__(self, page):
        self.page = page

    async def click(self, x, y, **kwargs):
        target = self.page.variant_mouse_target
        self.page.mouse_clicks.append({"target": target, "x": x, "y": y})
        self.page.events.append(f"mouse_click_{target}")
        if self.page.variant_click_error is not None:
            raise self.page.variant_click_error
        self.page.variant_dom_pointerdowns += 1
        self.page.variant_dom_mousedowns += 1
        self.page.variant_dom_pointerups += 1
        self.page.variant_dom_mouseups += 1
        self.page.variant_dom_clicks += 1
        self.page.variant_dom_click_trusted = True
        self.page.variant_dom_click_detail = 1
        self.page.main_query_calls += 1


class _KeywordComparisonPage:
    """模拟流量词对比页面及两种变体拓词弹窗。"""

    def __init__(
        self,
        endpoint,
        prepare_payload,
        *,
        prepare_status=200,
        prepare_text=None,
        query_click_error=None,
        variant_click_error=None,
        main_request_error=None,
        main_request_url=None,
        main_response_error=None,
    ):
        self.endpoint = endpoint
        self.prepare_payload = prepare_payload
        self.prepare_status = prepare_status
        self.prepare_text = prepare_text
        self.query_click_error = query_click_error
        self.variant_click_error = variant_click_error
        self.main_request_error = main_request_error
        self.main_request_url = main_request_url
        self.main_response_error = main_response_error
        self.fills = []
        self.clicks = []
        self.focuses = []
        self.presses = []
        self.events = []
        self.timeout_calls = []
        self.main_query_calls = 0
        self.variant_mouse_target = None
        self.mouse_clicks = []
        self.mouse = _KeywordComparisonMouse(self)
        self.variant_dom_clicks = 0
        self.variant_dom_keydowns = 0
        self.variant_dom_keyups = 0
        self.variant_dom_mousedowns = 0
        self.variant_dom_mouseups = 0
        self.variant_dom_pointerdowns = 0
        self.variant_dom_pointerups = 0
        self.variant_dom_click_trusted = None
        self.variant_dom_click_detail = None

    def expect_response(self, predicate, **kwargs):
        prepare_response = _KeywordComparisonPrepareResponse(
            self.prepare_payload,
            status=self.prepare_status,
            raw_text=self.prepare_text,
        )
        if predicate(prepare_response):
            self.events.append("listen_prepare")
            return _AssociationResponseWaiter(self.endpoint, response=prepare_response)
        self.events.append("listen_main")
        self.main_response_timeout = kwargs.get("timeout")
        return _AssociationResponseWaiter(
            self.endpoint,
            error=self.main_response_error,
        )

    def expect_request(self, predicate, **kwargs):
        self.events.append("listen_main_request")
        self.main_request_timeout = kwargs.get("timeout")
        request = SimpleNamespace(
            url=self.main_request_url
            or f"https://www.sellersprite.com{self.endpoint}",
            method="POST",
        )
        assert predicate(request)
        return _AssociationResponseWaiter(
            self.endpoint,
            response=request,
            error=self.main_request_error,
        )

    def locator(self, selector):
        if "自己的ASIN" in selector:
            return _AssociationLocator(self, "own_asin")
        if "竞品ASIN" in selector:
            return _AssociationLocator(self, "competitor_asins")
        if "用畅销变体拓词" in selector:
            return _AssociationLocator(self, "sell_well")
        if "用当前变体拓词" in selector:
            return _AssociationLocator(self, "current")
        if "立即查询" in selector:
            return _AssociationLocator(self, "query")
        return _AssociationLocator(self, "missing")

    async def wait_for_timeout(self, timeout):
        self.timeout_calls.append(timeout)


class _KeywordMinerLocator:
    """记录关键词挖掘页面输入和按钮点击。"""

    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    def locator(self, selector):
        if self.kind == "query" and selector.startswith("xpath=ancestor::"):
            return _KeywordMinerLocator(self.page, "container")
        if self.kind == "container" and selector.startswith("input:visible"):
            return _KeywordMinerLocator(
                self.page,
                "keyword" if self.page.input_mode == "scoped" else "missing",
            )
        return _KeywordMinerLocator(self.page, "missing")

    async def count(self):
        return int(self.kind != "missing")

    async def is_visible(self, **kwargs):
        return self.kind != "missing"

    async def fill(self, value):
        self.page.fills.append(value)

    async def click(self, **kwargs):
        self.page.clicks.append(self.kind)


class _KeywordMinerPage:
    """模拟关键词输入框文案和页面结构变化。"""

    def __init__(self, endpoint, *, input_mode):
        self.endpoint = endpoint
        self.input_mode = input_mode
        self.url = worker_module.DEFAULT_PAGE_URL
        self.context = SimpleNamespace(request=FakeContextRequest())
        self.fills = []
        self.clicks = []

    def expect_response(self, predicate, **kwargs):
        return _AssociationResponseWaiter(self.endpoint)

    def locator(self, selector):
        if "立即查询" in selector and not selector.startswith("input"):
            return _KeywordMinerLocator(self, "query")
        if self.input_mode == "placeholder_cn" and "placeholder" in selector and "关键词" in selector:
            return _KeywordMinerLocator(self, "keyword")
        if self.input_mode == "placeholder_example" and "placeholder" in selector and "flashlight" in selector:
            return _KeywordMinerLocator(self, "keyword")
        if self.input_mode == "aria" and "aria-label" in selector and "keyword" in selector.lower():
            return _KeywordMinerLocator(self, "keyword")
        if self.input_mode == "name" and "name" in selector and "keyword" in selector.lower():
            return _KeywordMinerLocator(self, "keyword")
        return _KeywordMinerLocator(self, "missing")


@pytest.mark.parametrize(
    "input_mode",
    ["placeholder_cn", "placeholder_example", "aria", "name", "scoped"],
)
def test_keyword_miner_route_fills_compatible_input_before_query(input_mode, tmp_path):
    endpoint = "/v3/api/keyword-miner"
    page = _KeywordMinerPage(endpoint, input_mode=input_mode)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-miner",
        method="POST",
        endpoint=endpoint,
        payload={"keyword": "bed"},
        referer=worker_module.DEFAULT_PAGE_URL,
        account=account,
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == ["bed"]
    assert page.clicks == ["query"]


def test_keyword_miner_missing_input_falls_back_without_empty_query_click(tmp_path):
    endpoint = "/v3/api/keyword-miner"
    page = _KeywordMinerPage(endpoint, input_mode="missing")
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-miner",
        method="POST",
        endpoint=endpoint,
        payload={"keyword": "bed"},
        referer=worker_module.DEFAULT_PAGE_URL,
        account=account,
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "context_request"
    assert page.fills == []
    assert page.clicks == []
    assert len(page.context.request.post_calls) == 1


def test_keyword_miner_high_frequency_uses_context_request_without_second_page_query(monkeypatch, tmp_path):
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=account,
    )
    page = SimpleNamespace(url=worker_module.DEFAULT_PAGE_URL)
    route_sections = []
    context_calls = []

    async def no_wait(*args, **kwargs):
        return None

    async def ensure_page(current_account):
        return page

    async def open_referer(current_page, request, **kwargs):
        return {"logged_in": True}

    async def execute_route_fetch(**kwargs):
        route_sections.append(kwargs["section"])
        return {"code": "OK", "data": {"items": [{"keyword": "bed"}]}}

    async def request_with_context(current_page, *, endpoint, method, payload):
        context_calls.append({"endpoint": endpoint, "method": method, "payload": payload})
        return SimpleNamespace(status=200)

    async def parse_response(response, **kwargs):
        return {"code": "OK", "data": {"items": [{"keyword": "bed frame"}]}}

    monkeypatch.setattr(worker, "_wait_for_cooldown", no_wait)
    monkeypatch.setattr(worker, "_wait_for_rate_limit", no_wait)
    monkeypatch.setattr(worker, "_ensure_page", ensure_page)
    monkeypatch.setattr(worker, "_open_referer_and_login", open_referer)
    monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", no_wait)
    monkeypatch.setattr(worker, "_execute_route_fetch", execute_route_fetch)
    monkeypatch.setattr(worker_module, "_prepare_page", no_wait)
    monkeypatch.setattr(worker_module, "_request_with_browser_context", request_with_context)
    monkeypatch.setattr(worker_module, "_parse_response", parse_response)

    result = _run(
        worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="keyword-miner",
                method="POST",
                endpoint="/v3/api/keyword-miner",
                payload={"keyword": "bed"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
                high_frequency_endpoint="/v3/api/keyword-miner/high/frequency-new",
                high_frequency_payload={"keyword": "bed"},
            )
        )
    )

    assert route_sections == ["main"]
    assert context_calls == [
        {
            "endpoint": "/v3/api/keyword-miner/high/frequency-new",
            "method": "POST",
            "payload": {"keyword": "bed"},
        }
    ]
    assert result.high_frequency_response["data"]["items"] == [{"keyword": "bed frame"}]
    timing_warning = next(item for item in result.warnings if item["stage"] == "browser_route_timing")
    stages = [item["stage"] for item in timing_warning["timings"]]
    assert "route_fetch.high_frequency.context_request" in stages
    assert "route_fetch.high_frequency.parse_response" in stages
    assert "route_fetch.high_frequency.route_setup" not in stages
    assert "route_fetch.high_frequency.page_response_fallback" not in stages


@pytest.mark.parametrize(
    "error",
    [
        SellerSpriteApiError(
            "登录态失效",
            status_code=401,
            api_code="ERR_GLOBAL_SESSION_EXPIRED",
        ),
        SellerSpriteApiError("未授权", status_code=401),
        SellerSpriteApiError("禁止访问", status_code=403),
        SellerSpriteApiError(
            "浏览器上下文请求超时",
            api_code="ERR_BROWSER_CONTEXT_REQUEST_FAILED",
        ),
        SellerSpriteApiError(
            "未返回 XLSX",
            api_code="ERR_SELLER_SPRITE_XLSX_INVALID",
        ),
    ],
    ids=["session_expired", "401", "403", "timeout", "invalid_xlsx"],
)
def test_non_replayable_request_does_not_repeat_after_failure(monkeypatch, tmp_path, error):
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=account,
    )
    page = SimpleNamespace(
        url="https://www.sellersprite.com/v3/branddb",
        is_closed=lambda: False,
    )
    execute_calls = []
    relogin_calls = []

    async def no_wait(*args, **kwargs):
        return None

    async def ensure_page(current_account):
        return page

    async def open_referer(current_page, request, **kwargs):
        return {"logged_in": True}

    async def execute_route_fetch(**kwargs):
        execute_calls.append(kwargs)
        raise error

    async def relogin(*args, **kwargs):
        relogin_calls.append(kwargs)

    monkeypatch.setattr(worker, "_wait_for_cooldown", no_wait)
    monkeypatch.setattr(worker, "_wait_for_rate_limit", no_wait)
    monkeypatch.setattr(worker, "_ensure_page", ensure_page)
    monkeypatch.setattr(worker, "_open_referer_and_login", open_referer)
    monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", no_wait)
    monkeypatch.setattr(worker, "_execute_route_fetch", execute_route_fetch)
    monkeypatch.setattr(worker, "_login_with_account", relogin)

    with pytest.raises(SellerSpriteApiError) as raised:
        _run(
            worker._run_one(
                worker_module.BrowserRouteRequest(
                    scenario="branddb",
                    method="POST_XLSX",
                    endpoint="/v3/api/branddb/export-syn",
                    payload={"text": "ANKER"},
                    referer=page.url,
                    account=account,
                    root_dir=tmp_path,
                    page_prepare=False,
                    replay_safe=False,
                )
            )
        )

    assert raised.value is error
    assert len(execute_calls) == 1
    assert relogin_calls == []


def test_non_keyword_miner_high_frequency_keeps_page_route_path(monkeypatch, tmp_path):
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=account,
    )
    page = SimpleNamespace(url=worker_module.DEFAULT_PAGE_URL)
    route_sections = []

    async def no_wait(*args, **kwargs):
        return None

    async def ensure_page(current_account):
        return page

    async def open_referer(current_page, request, **kwargs):
        return {"logged_in": True}

    async def execute_route_fetch(**kwargs):
        route_sections.append(kwargs["section"])
        return {"code": "OK", "data": {"items": []}}

    monkeypatch.setattr(worker, "_wait_for_cooldown", no_wait)
    monkeypatch.setattr(worker, "_wait_for_rate_limit", no_wait)
    monkeypatch.setattr(worker, "_ensure_page", ensure_page)
    monkeypatch.setattr(worker, "_open_referer_and_login", open_referer)
    monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", no_wait)
    monkeypatch.setattr(worker, "_execute_route_fetch", execute_route_fetch)
    monkeypatch.setattr(worker_module, "_prepare_page", no_wait)

    _run(
        worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="competitor-lookup",
                method="POST",
                endpoint="/v3/api/competing-lookup",
                payload={"keyword": "bed"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
                high_frequency_endpoint="/v3/api/example/high-frequency",
                high_frequency_payload={"keyword": "bed"},
            )
        )
    )

    assert route_sections == ["main", "high_frequency"]


def test_keyword_comparison_route_payload_only_keeps_page_asin_list():
    payload = {
        "asin": "B0949DWJCV",
        "asinList": ["B014INJCT4"],
        "station": "US",
        "page": 1,
        "size": 100,
        "desc": True,
    }

    effective = worker_module._keyword_comparison_route_payload(
        payload,
        json.dumps(
            {
                "asinList": ["B0949DWJCV", "B0744DM3Y3", "B0BRN58CXR"],
                "page": 9,
                "size": 5,
                "station": "JP",
                "diamondList": ["SHOULD_NOT_PASS"],
            }
        ),
    )

    assert effective == {
        **payload,
        "asinList": ["B0949DWJCV", "B0744DM3Y3", "B0BRN58CXR"],
        "page": 1,
        "size": 100,
    }
    assert "diamondList" not in effective


def test_keyword_comparison_route_payload_accepts_sell_well_replacement():
    """畅销变体替换原始 ASIN 后，页面生成的有效列表仍应放行。"""
    payload = {
        "asin": "B0949DWJCV",
        "asinList": ["B014INJCT4"],
        "station": "US",
        "page": 1,
        "size": 100,
    }

    effective = worker_module._keyword_comparison_route_payload(
        payload,
        json.dumps({"asinList": ["B0GS9B1X5X", "B0744DM3Y3"]}),
    )

    assert effective == {
        **payload,
        "asinList": ["B0GS9B1X5X", "B0744DM3Y3"],
        "page": 1,
        "size": 100,
    }


def test_keyword_comparison_route_sends_effective_asin_list(monkeypatch, tmp_path):
    """主请求只接受页面生成的畅销变体列表，并同步记录最终顺序。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    route_calls = []
    route_metadata = {}

    class RouteProbe:
        def __init__(self):
            self.request = SimpleNamespace(
                url=f"https://www.sellersprite.com{endpoint}",
                headers={"content-type": "application/json"},
                post_data=json.dumps(
                    {
                        "asinList": ["B0949DWJCV", "B0744DM3Y3"],
                        "page": 9,
                        "size": 5,
                        "station": "JP",
                    }
                ),
            )

        async def continue_(self, **kwargs):
            route_calls.append(kwargs)

    class PageProbe:
        def __init__(self):
            self.handler = None

        async def route(self, pattern, handler):
            self.handler = handler

        async def unroute(self, pattern, handler):
            assert handler is self.handler

        def is_closed(self):
            return False

    page = PageProbe()

    async def fake_trigger(*args, **kwargs):
        await page.handler(RouteProbe())
        return SimpleNamespace(status=200), "page_response"

    async def fake_parse(*args, **kwargs):
        return {"code": "OK", "data": {"items": []}}

    monkeypatch.setattr(worker_module, "_trigger_request", fake_trigger)
    monkeypatch.setattr(worker_module, "_parse_response", fake_parse)
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
    )
    payload = {
        "asin": "B0949DWJCV",
        "asinList": ["B014INJCT4"],
        "station": "US",
        "page": 1,
        "size": 100,
        "desc": True,
    }
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload=payload,
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=worker.account,
        root_dir=tmp_path,
    )

    result = _run(
        worker._execute_route_fetch(
            page=page,
            method="POST",
            endpoint=endpoint,
            payload=payload,
            root_dir=tmp_path,
            section="main",
            request=request,
            route_metadata=route_metadata,
        )
    )

    sent_body = json.loads(route_calls[0]["post_data"])
    assert result == {"code": "OK", "data": {"items": []}}
    assert sent_body == {
        **payload,
        "asinList": ["B0949DWJCV", "B0744DM3Y3"],
        "page": 1,
        "size": 100,
    }
    assert route_metadata == {"asinList": ["B0949DWJCV", "B0744DM3Y3"]}


def test_keyword_comparison_route_aborts_and_reports_invalid_body(monkeypatch, tmp_path):
    """页面主请求体无效时即使中止异常，也应立即透传原始校验错误。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    route_calls = []

    class RouteProbe:
        def __init__(self):
            self.request = SimpleNamespace(
                url=f"https://www.sellersprite.com{endpoint}",
                headers={"content-type": "application/json"},
                post_data="not-json",
            )

        async def continue_(self, **kwargs):
            route_calls.append(("continue", kwargs))

        async def abort(self, error_code):
            route_calls.append(("abort", error_code))
            raise RuntimeError("route abort failed")

    class PageProbe:
        def __init__(self):
            self.handler = None

        async def route(self, pattern, handler):
            self.handler = handler

        async def unroute(self, pattern, handler):
            assert handler is self.handler

        def is_closed(self):
            return False

    page = PageProbe()

    async def fake_trigger(*args, **kwargs):
        await page.handler(RouteProbe())
        await asyncio.Future()

    monkeypatch.setattr(worker_module, "_trigger_request", fake_trigger)
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
    )
    payload = {
        "asin": "B0949DWJCV",
        "asinList": ["B014INJCT4"],
        "station": "US",
        "page": 1,
        "size": 100,
    }
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload=payload,
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=worker.account,
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker._execute_route_fetch(
                page=page,
                method="POST",
                endpoint=endpoint,
                payload=payload,
                root_dir=tmp_path,
                section="main",
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_REQUEST_BODY"
    assert route_calls == [("abort", "blockedbyclient")]


def test_keyword_comparison_retry_does_not_reuse_failed_asin_list(monkeypatch, tmp_path):
    """重试成功但未捕获最终列表时，不得沿用失败尝试的 ASIN 顺序。"""
    account = SellerSpriteAccount(
        name="default", username="user@example.com", password="secret"
    )
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=account,
    )
    page = SimpleNamespace(
        url="https://www.sellersprite.com/v3/keyword-comparison",
        is_closed=lambda: False,
    )
    calls = []

    async def no_wait(*args, **kwargs):
        return None

    async def ensure_page(current_account):
        return page

    async def open_referer(current_page, request, **kwargs):
        return {"logged_in": True}

    async def execute_route_fetch(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            kwargs["route_metadata"]["asinList"] = [
                "B0949DWJCV",
                "B0744DM3Y3",
            ]
            raise SellerSpriteApiError(
                "登录态失效",
                status_code=401,
                api_code="ERR_GLOBAL_SESSION_EXPIRED",
            )
        return {"code": "OK", "data": {"items": []}}

    monkeypatch.setattr(worker, "_wait_for_cooldown", no_wait)
    monkeypatch.setattr(worker, "_wait_for_rate_limit", no_wait)
    monkeypatch.setattr(worker, "_ensure_page", ensure_page)
    monkeypatch.setattr(worker, "_open_referer_and_login", open_referer)
    monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", no_wait)
    monkeypatch.setattr(worker, "_login_with_account", no_wait)
    monkeypatch.setattr(worker, "_execute_route_fetch", execute_route_fetch)
    monkeypatch.setattr(worker_module, "_prepare_page", no_wait)

    result = _run(
        worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="keyword-comparison",
                method="POST",
                endpoint="/v3/api/keyword-comparison/asin",
                payload={
                    "asin": "B0949DWJCV",
                    "asinList": ["B0744DM3Y3"],
                    "page": 1,
                    "size": 100,
                },
                referer=page.url,
                account=account,
                root_dir=tmp_path,
            )
        )
    )

    assert len(calls) == 2
    assert result.effective_asin_list is None


@pytest.mark.parametrize("post_data", [None, "not-json", "{}", '{"asinList": []}'])
def test_keyword_comparison_route_payload_rejects_invalid_page_body(post_data):
    with pytest.raises(SellerSpriteApiError, match="流量词对比"):
        worker_module._keyword_comparison_route_payload(
            {"asin": "B0949DWJCV", "page": 1, "size": 100},
            post_data,
        )


def test_keyword_comparison_route_selects_sell_well_variant(tmp_path):
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {
                "diamondList": ["B0949DWJCV", "B0744DM3Y3", "B0BRN58CXR"]
            },
        },
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B014INJCT4", "B0BRN58CXR"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == ["B0949DWJCV", "B014INJCT4 B0BRN58CXR"]
    assert page.clicks == ["query"]
    assert page.focuses == []
    assert page.presses == []
    assert len(page.mouse_clicks) == 1
    assert page.mouse_clicks[0]["target"] == "sell_well"
    assert page.timeout_calls[-1] == 300
    assert page.events == [
        "listen_prepare",
        "click_query",
        "listen_main",
        "listen_main_request",
        "mouse_click_sell_well",
    ]
    assert page.main_response_timeout == worker_module.DEFAULT_TIMEOUT_MS


def test_keyword_comparison_route_selects_current_variant(tmp_path):
    """用户明确要求当前变体时，只点击当前变体拓词按钮。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
        keyword_comparison_variant="current",
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.clicks == ["query"]
    assert page.focuses == []
    assert page.presses == []
    assert len(page.mouse_clicks) == 1
    assert page.mouse_clicks[0]["target"] == "current"
    assert page.main_query_calls == 1


def test_keyword_comparison_query_click_error_is_not_response_missed(tmp_path):
    """立即查询按钮点击失败时，不得误报主响应丢失。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
        query_click_error=TimeoutError("query button is not actionable"),
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_QUERY_CLICK"
    assert page.events == ["listen_prepare", "click_query"]
    assert page.main_query_calls == 0


def test_keyword_comparison_variant_click_error_is_not_response_missed(tmp_path):
    """变体按钮点击失败应保留准确错误，不能误报主响应丢失。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
        variant_click_error=TimeoutError("button is not actionable"),
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_VARIANT_CLICK"
    assert page.events[-3:] == [
        "listen_main",
        "listen_main_request",
        "mouse_click_sell_well",
    ]
    assert page.focuses == []
    assert page.presses == []
    assert len(page.mouse_clicks) == 1
    assert page.main_query_calls == 0


def test_keyword_comparison_response_error_after_click_is_response_missed(tmp_path):
    """只有变体按钮点击成功后主响应失败，才报告响应丢失。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
        main_response_error=TimeoutError("main response timeout"),
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_RESPONSE_MISSED"
    assert page.events[-3:] == [
        "listen_main",
        "listen_main_request",
        "mouse_click_sell_well",
    ]
    assert page.focuses == []
    assert page.presses == []
    assert len(page.mouse_clicks) == 1
    assert page.main_query_calls == 1


def test_keyword_comparison_activation_without_post_is_request_missed(
    tmp_path, caplog
):
    """无 POST 时应输出脱敏 DOM 事件诊断，同时禁止补点。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
        main_request_error=TimeoutError("no keyword comparison request"),
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )
    caplog.set_level("WARNING", logger=worker_module.__name__)

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_REQUEST_MISSED"
    assert page.main_request_timeout == 15000
    assert page.clicks == ["query"]
    assert page.focuses == []
    assert page.presses == []
    assert len(page.mouse_clicks) == 1
    assert page.main_query_calls == 1
    assert "[SELLER_SPRITE_KC_DIAG]" in caplog.text
    assert '"clickCount": 1' in caplog.text
    assert '"keydownCount": 0' in caplog.text
    assert '"mousedownCount": 1' in caplog.text
    assert '"mouseupCount": 1' in caplog.text
    assert '"pointerdownCount": 1' in caplog.text
    assert '"pointerupCount": 1' in caplog.text
    assert '"clickTrusted": true' in caplog.text
    assert '"clickDetail": 1' in caplog.text
    assert '"dialogVisible": true' in caplog.text
    assert "Cookie" not in caplog.text
    assert "Authorization" not in caplog.text


def test_keyword_comparison_click_reports_changed_post_endpoint(tmp_path):
    """变体按钮触发了其他对比接口时，应报告脱敏路径而非误报响应丢失。"""
    endpoint = "/v3/api/keyword-comparison/asin"
    actual_path = "/v3/api/keyword-comparison/query"
    page = _KeywordComparisonPage(
        endpoint,
        {
            "code": "OK",
            "success": True,
            "data": {"diamondList": ["B0949DWJCV", "B0744DM3Y3"]},
        },
        main_request_url=f"https://www.sellersprite.com{actual_path}?ignored=1",
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_KEYWORD_COMPARISON_ENDPOINT_CHANGED"
    assert exc_info.value.response_excerpt == f"method=POST path={actual_path}"
    assert "ignored" not in exc_info.value.response_excerpt


@pytest.mark.parametrize(
    ("prepare_payload", "page_kwargs", "api_code", "status_code"),
    [
        (
            {"code": "ERR_GLOBAL_500", "message": "处理请求出现错误,请稍后重试。"},
            {},
            "ERR_GLOBAL_500",
            200,
        ),
        (
            {"code": "OK", "success": False, "message": "ASIN 无效", "data": None},
            {},
            "ERR_KEYWORD_COMPARISON_PREPARE",
            200,
        ),
        (
            {"code": "OK", "data": {"diamondList": ["B0949DWJCV"]}},
            {},
            "ERR_KEYWORD_COMPARISON_PREPARE",
            200,
        ),
        (
            {"success": True, "data": {"diamondList": ["B0949DWJCV"]}},
            {},
            "ERR_KEYWORD_COMPARISON_PREPARE",
            200,
        ),
        (
            {"code": "OK", "success": True, "data": {}},
            {},
            "ERR_KEYWORD_COMPARISON_PREPARE_DATA",
            200,
        ),
        (
            {"code": "OK", "success": True, "data": {"diamondList": ["B0949DWJCV"]}},
            {"prepare_status": 500},
            None,
            500,
        ),
        (
            {},
            {"prepare_text": "not-json"},
            None,
            200,
        ),
    ],
)
def test_keyword_comparison_prepare_error_stops_before_dialog(
    tmp_path, prepare_payload, page_kwargs, api_code, status_code
):
    endpoint = "/v3/api/keyword-comparison/asin"
    page = _KeywordComparisonPage(endpoint, prepare_payload, **page_kwargs)
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-comparison",
        method="POST",
        endpoint=endpoint,
        payload={
            "asin": "B0949DWJCV",
            "asinList": ["B0744DM3Y3"],
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-comparison",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == api_code
    assert exc_info.value.status_code == status_code
    assert page.clicks == ["query"]
    assert page.timeout_calls == []
    assert page.main_query_calls == 0


def test_association_traffic_route_fills_asins_and_selects_all_variants(tmp_path):
    endpoint = "/v3/api/relation/traffic"
    page = _AssociationPage(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="association-traffic",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": [
                "B098T9ZFB5",
                "B09JW5FNVX",
                "B0B71DH45N",
                "B07MHHM31K",
                "B08RYQR1CJ",
            ],
            "queryVariations": True,
        },
        referer="https://www.sellersprite.com/v3/relation-keyword",
        account=account,
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == request.payload["asinList"]
    assert page.presses == ["Enter"] * 5
    assert page.clicks == ["clear", "query", "all_variants"]


def test_traffic_extend_route_fills_asins_and_defaults_to_all_variants(tmp_path):
    endpoint = "/v3/api/traffic/extend/asin"
    page = _TrafficExtendPage(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="traffic-extend",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": ["B089K9L3VY", "B07F8S18D5"],
            "originAsinList": ["B089K9L3VY", "B07F8S18D5"],
            "queryVariations": True,
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/traffic/extend/asin",
        account=account,
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == ["B089K9L3VY B07F8S18D5"]
    assert page.clicks == ["query", "all_variants"]


def test_traffic_extend_route_payload_keeps_page_variant_scope_and_first_page():
    effective = worker_module._traffic_extend_route_payload(
        {
            "originAsinList": ["B089K9L3VY"],
            "asinList": ["B089K9L3VY"],
            "queryVariations": True,
            "page": 3,
            "size": 20,
            "market": 1,
        },
        json.dumps(
            {
                "asinList": ["B07F8S18D5"],
                "originAsinList": ["B089K9L3VY"],
                "queryVariations": False,
                "page": 9,
                "size": 50,
            }
        ),
    )

    assert effective["asinList"] == ["B07F8S18D5"]
    assert effective["originAsinList"] == ["B089K9L3VY"]
    assert effective["queryVariations"] is False
    assert effective["page"] == 1
    assert effective["size"] == 100


def test_traffic_extend_route_selects_historical_period_before_prepare(tmp_path):
    endpoint = "/v3/api/traffic/extend/asin"
    page = _TrafficExtendPage(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="traffic-extend",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": ["B089K9L3VY"],
            "originAsinList": ["B089K9L3VY"],
            "month": "202606",
            "page": 1,
            "size": 100,
        },
        referer="https://www.sellersprite.com/v3/traffic/extend?marketId=1",
        account=account,
        root_dir=tmp_path,
    )

    _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert page.clicks == [
        "period_select",
        "period_2026-06",
        "query",
        "all_variants",
    ]


def test_keyword_conversion_rate_route_submits_each_phrase_once_before_query(
    tmp_path,
):
    endpoint = "/v3/api/keyword-conv"
    page = _KeywordConversionRatePage(endpoint)
    account = SellerSpriteAccount(
        name="default",
        username="user@example.com",
        password="secret",
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-conversion-rate",
        method="POST",
        endpoint=endpoint,
        payload={
            "market": "US",
            "timeType": "90D",
            "keyword": "wireless charger stand,phone holder",
            "pageNum": 1,
            "pageSize": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-conversion-rate",
        account=account,
        root_dir=tmp_path,
        replay_safe=False,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == ["wireless charger stand", "phone holder"]
    assert page.presses == ["Enter", "Enter"]
    assert page.tags == ["wireless charger stand", "phone holder"]
    assert page.clicks == [
        "market_select",
        "market_US",
        "period_select",
        "period_90D",
        "clear",
        "query",
    ]
    assert page.events.index("press:phone holder") < page.events.index(
        "expect_response"
    )
    assert page.events.index("expect_response") < page.events.index(
        "click:query"
    )


def test_real_time_bidding_detail_merge_combines_sp_and_sb_by_keyword():
    sp_response = {
        "code": "OK",
        "data": {
            "keywordList": {
                "page": 1,
                "size": 100,
                "total": 1,
                "items": [
                    {
                        "keyword": "phone stand",
                        "autoSponsor": {"EXACT": {"value": 0.53}},
                        "manualSponsor": {"EXACT": {"value": 0.47}},
                    }
                ],
            },
            "task": {"queryTime": "2025-06-30 00:00:00"},
        },
    }
    sb_response = {
        "code": "OK",
        "data": {
            "keywordList": {
                "page": 1,
                "size": 100,
                "total": 1,
                "items": [
                    {
                        "keyword": "phone stand",
                        "sponsorBrand": {"EXACT": {"value": 0.71}},
                        "sponsorBrandVideo": {"EXACT": {"value": 0.83}},
                    }
                ],
            },
            "task": {"queryTime": "2025-06-30 00:00:00"},
        },
    }

    merged = worker_module._merge_real_time_bidding_detail_responses(
        sp_response,
        sb_response,
    )

    row = merged["data"]["keywordList"]["items"][0]
    assert row["autoSponsor"]["EXACT"]["value"] == 0.53
    assert row["sponsorBrand"]["EXACT"]["value"] == 0.71
    assert row["queryTime"] == "2025-06-30 00:00:00"


def test_real_time_bidding_workflow_uses_latest_completed_history_and_both_ad_types(
    tmp_path,
):
    worker = object.__new__(SellerSpriteBrowserRouteWorker)
    context_calls = []
    submitted = False

    async def fake_context_fetch(**kwargs):
        nonlocal submitted
        context_calls.append((kwargs["endpoint"], kwargs["payload"]))
        if kwargs["endpoint"].endswith("/newTask"):
            submitted = True
            return {"code": "OK", "data": {"taskId": 13}}
        if kwargs["endpoint"].endswith("/taskList"):
            if submitted:
                return {
                    "code": "OK",
                    "data": {"items": [{
                        "id": 13,
                        "parentTaskId": 11,
                        "asin": "B07Z82895W",
                        "taskStatus": 3,
                    }]},
                }
            if kwargs["payload"]["page"] == 1:
                return {
                    "code": "OK",
                    "data": {
                        "page": 1,
                        "size": 20,
                        "total": 23,
                        "items": [
                            {
                                "id": 100 + index,
                                "parentTaskId": 100 + index,
                                "asin": "B000000000",
                                "taskStatus": 2,
                            }
                            for index in range(20)
                        ],
                    },
                }
            return {
                "code": "OK",
                "data": {
                    "page": 2,
                    "size": 20,
                    "total": 23,
                    "items": [
                        {
                            "id": 12,
                            "parentTaskId": 12,
                            "asin": "B000000000",
                            "taskStatus": 2,
                        },
                        {
                            "id": 11,
                            "parentTaskId": 11,
                            "asin": "B07Z82895W",
                            "taskStatus": 3,
                        },
                        {
                            "id": 10,
                            "parentTaskId": 10,
                            "asin": "B07Z82895W",
                            "taskStatus": 3,
                        },
                    ]
                },
            }
        ad_type = kwargs["payload"]["adType"]
        field = (
            {"autoSponsor": {"EXACT": {"value": 0.53}}}
            if ad_type == "sp"
            else {"sponsorBrand": {"EXACT": {"value": 0.71}}}
        )
        return {
            "code": "OK",
            "data": {
                "keywordList": {
                    "items": [{"keyword": "phone stand", **field}]
                },
                "task": {"queryTime": "2026-07-31 16:27:36"},
            },
        }

    worker._execute_context_fetch = fake_context_fetch
    request = worker_module.BrowserRouteRequest(
        scenario="real-time-bidding",
        method="POST",
        endpoint="/v3/api/keywordbidding/taskList",
        payload={
            "asin": "B07Z82895W",
            "isExampleAsin": False,
            "marketId": 1,
            "page": 1,
            "size": 20,
            "order": {"desc": True, "field": "updatedTime"},
        },
        referer="https://www.sellersprite.com/v3/real-time-bidding",
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
        root_dir=tmp_path,
        replay_safe=True,
        task_interval_seconds=0,
    )

    result = _run(
        worker._execute_real_time_bidding_workflow(
            page=SimpleNamespace(),
            request=request,
            timings=[],
        )
    )

    detail_calls = [
        payload
        for endpoint, payload in context_calls
        if endpoint.endswith("/getTaskDetail")
    ]
    assert [endpoint for endpoint, _ in context_calls] == [
        "/v3/api/keywordbidding/taskList",
        "/v3/api/keywordbidding/taskList",
        "/v3/api/keywordbidding/newTask",
        "/v3/api/keywordbidding/taskList",
        "/v3/api/keywordbidding/getTaskDetail",
        "/v3/api/keywordbidding/getTaskDetail",
    ]
    history_pages = [
        payload["page"]
        for endpoint, payload in context_calls
        if endpoint.endswith("/taskList")
    ]
    assert history_pages == [1, 2, 1]
    assert [payload["adType"] for payload in detail_calls] == ["sp", "sb"]
    assert all(payload["page"] == 1 and payload["size"] == 100 for payload in detail_calls)
    assert all(payload["taskId"] == 13 for payload in detail_calls)
    rerun_payload = next(
        payload for endpoint, payload in context_calls if endpoint.endswith("/newTask")
    )
    assert rerun_payload["queryAgain"] is True
    assert rerun_payload["failTaskId"] == 11
    assert rerun_payload["parentTaskId"] == 11
    row = result["data"]["keywordList"]["items"][0]
    assert row["autoSponsor"]["EXACT"]["value"] == 0.53
    assert row["sponsorBrand"]["EXACT"]["value"] == 0.71


@pytest.mark.parametrize("initial_status", [0, 2])
def test_real_time_bidding_workflow_waits_without_resubmitting_non_terminal_task(
    tmp_path,
    initial_status,
):
    worker = object.__new__(SellerSpriteBrowserRouteWorker)
    task_list_calls = 0

    async def fake_context_fetch(**kwargs):
        nonlocal task_list_calls
        if kwargs["endpoint"].endswith("/getTaskDetail"):
            return {
                "code": "OK",
                "data": {"keywordList": {"items": []}, "task": {}},
            }
        task_list_calls += 1
        return {
            "code": "OK",
            "data": {
                "items": [
                    {
                        "id": 12,
                        "asin": "B07Z82895W",
                        "taskStatus": initial_status if task_list_calls == 1 else 3,
                    }
                ]
            },
        }

    worker._execute_context_fetch = fake_context_fetch
    request = worker_module.BrowserRouteRequest(
        scenario="real-time-bidding",
        method="POST",
        endpoint="/v3/api/keywordbidding/taskList",
        payload={
            "asin": "B07Z82895W",
            "isExampleAsin": False,
            "marketId": 1,
            "page": 1,
            "size": 20,
            "order": {"desc": True, "field": "updatedTime"},
        },
        referer="https://www.sellersprite.com/v3/real-time-bidding",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
        task_interval_seconds=0,
    )

    result = _run(
        worker._execute_real_time_bidding_workflow(
            page=SimpleNamespace(),
            request=request,
            timings=[],
        )
    )

    assert result["data"]["keywordList"]["items"] == []
    assert task_list_calls == 2


def test_real_time_bidding_workflow_reads_official_example_without_creating_task(
    tmp_path,
):
    worker = object.__new__(SellerSpriteBrowserRouteWorker)
    calls = []

    async def fake_context_fetch(**kwargs):
        calls.append((kwargs["endpoint"], kwargs["payload"]))
        if kwargs["endpoint"].endswith("/taskList"):
            items = (
                [{
                    "id": 2,
                    "parentTaskId": 2,
                    "asin": "B0B56CHMSC",
                    "taskStatus": 3,
                    "exampleAsinFlag": True,
                }]
                if kwargs["payload"]["isExampleAsin"]
                else []
            )
            return {"code": "OK", "data": {"items": items}}
        return {
            "code": "OK",
            "data": {"keywordList": {"items": []}, "task": {}},
        }

    async def fail_route_fetch(**kwargs):
        raise AssertionError("官网示例 ASIN 不应新建任务")

    worker._execute_context_fetch = fake_context_fetch
    worker._execute_route_fetch = fail_route_fetch
    request = worker_module.BrowserRouteRequest(
        scenario="real-time-bidding",
        method="POST",
        endpoint="/v3/api/keywordbidding/taskList",
        payload={
            "asin": "B0B56CHMSC",
            "isExampleAsin": False,
            "marketId": 1,
            "page": 1,
            "size": 20,
            "order": {"desc": True, "field": "updatedTime"},
        },
        referer="https://www.sellersprite.com/v3/real-time-bidding",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
        replay_safe=False,
        task_interval_seconds=0,
    )

    result = _run(
        worker._execute_real_time_bidding_workflow(
            page=SimpleNamespace(), request=request, timings=[]
        )
    )

    detail_payloads = [
        payload for endpoint, payload in calls if endpoint.endswith("/getTaskDetail")
    ]
    assert result["data"]["keywordList"]["items"] == []
    assert [payload["isExampleAsin"] for payload in detail_payloads] == [True, True]
    assert [payload["taskId"] for payload in detail_payloads] == [2, 2]


def test_real_time_bidding_workflow_creates_new_task_when_history_is_empty(tmp_path):
    worker = object.__new__(SellerSpriteBrowserRouteWorker)
    submitted = False
    route_calls = []

    async def fake_context_fetch(**kwargs):
        if kwargs["endpoint"].endswith("/taskList"):
            items = ([{
                "id": 20,
                "parentTaskId": 20,
                "asin": "B07Z82895W",
                "taskStatus": 3,
            }] if submitted and not kwargs["payload"]["isExampleAsin"] else [])
            return {"code": "OK", "data": {"items": items}}
        return {"code": "OK", "data": {"keywordList": {"items": []}, "task": {}}}

    async def fake_route_fetch(**kwargs):
        nonlocal submitted
        submitted = True
        route_calls.append(kwargs)
        return {"code": "OK", "data": {"taskId": 20}}

    worker._execute_context_fetch = fake_context_fetch
    worker._execute_route_fetch = fake_route_fetch
    request = worker_module.BrowserRouteRequest(
        scenario="real-time-bidding",
        method="POST",
        endpoint="/v3/api/keywordbidding/taskList",
        payload={
            "asin": "B07Z82895W", "isExampleAsin": False, "marketId": 1,
            "page": 1, "size": 20,
            "order": {"desc": True, "field": "updatedTime"},
        },
        referer="https://www.sellersprite.com/v3/real-time-bidding",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
        replay_safe=False,
        task_interval_seconds=0,
    )

    result = _run(worker._execute_real_time_bidding_workflow(
        page=SimpleNamespace(), request=request, timings=[]
    ))

    assert result["data"]["keywordList"]["items"] == []
    assert len(route_calls) == 1
    assert route_calls[0]["section"] == "real_time_bidding_new_task"
    assert route_calls[0]["payload"] == {
        "asin": "B07Z82895W", "taskType": "AC", "marketId": 1, "keywordList": []
    }


def test_real_time_bidding_new_task_waits_for_dialog_and_confirms_once():
    class Locator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind
            self.first = self

        async def count(self):
            return 1

        async def is_visible(self, **kwargs):
            if self.kind == "dialog":
                self.page.dialog_checks += 1
                return self.page.dialog_checks >= 3
            return True

        async def fill(self, value):
            self.page.events.append(f"fill_{self.kind}:{value}")

        async def click(self, **kwargs):
            self.page.events.append(f"click_{self.kind}")
            if self.kind == "confirm":
                self.page.confirm_clicks += 1

        def locator(self, selector):
            if "input" in selector:
                return Locator(self.page, "modal_asin")
            if "推荐关键词" in selector:
                return Locator(self.page, "recommended")
            return Locator(self.page, "confirm")

    class Page:
        def __init__(self):
            self.events = []
            self.dialog_checks = 0
            self.confirm_clicks = 0

        def locator(self, selector):
            if "dropdown" in selector:
                kind = "market_option"
            elif "el-select" in selector:
                kind = "market"
            elif "新建查询任务" in selector:
                kind = "create"
            elif "dialog" in selector:
                kind = "dialog"
            else:
                kind = "main_asin"
            return Locator(self, kind)

        async def wait_for_timeout(self, timeout):
            self.events.append("wait_dialog")

        def expect_response(self, predicate, timeout):
            self.events.append("listen_new_task")
            return _AssociationResponseWaiter("/v3/api/keywordbidding/newTask")

    page = Page()
    response = _run(worker_module._trigger_real_time_bidding_new_task(
        page,
        {"asin": "B07Z82895W", "marketId": 1},
        endpoint="/v3/api/keywordbidding/newTask",
    ))

    assert response.status == 200
    assert page.dialog_checks == 3
    assert page.confirm_clicks == 1
    assert page.events.index("listen_new_task") < page.events.index("click_confirm")
    assert "click_recommended" in page.events


def test_real_time_bidding_poll_ignores_stale_failed_task_without_created_id(
    tmp_path,
):
    worker = object.__new__(SellerSpriteBrowserRouteWorker)
    tasks = iter([
        {"id": 11, "asin": "B07Z82895W", "taskStatus": 4},
        {"id": 12, "asin": "B07Z82895W", "taskStatus": 3},
    ])

    async def fake_find(**kwargs):
        return next(tasks)

    worker._find_real_time_bidding_task = fake_find
    request = worker_module.BrowserRouteRequest(
        scenario="real-time-bidding",
        method="POST",
        endpoint="/v3/api/keywordbidding/taskList",
        payload={"asin": "B07Z82895W", "marketId": 1},
        referer="https://www.sellersprite.com/v3/real-time-bidding",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
        task_interval_seconds=0,
    )

    task = _run(worker._poll_real_time_bidding_task(
        page=SimpleNamespace(),
        request=request,
        timings=[],
        expected_task_id=None,
        previous_task_id=11,
    ))

    assert task["id"] == 12


def test_real_time_bidding_detail_merge_rejects_mismatched_keyword_pages():
    sp_response = {
        "code": "OK",
        "data": {
            "keywordList": {"items": [{"keyword": "phone stand"}]},
            "task": {},
        },
    }
    sb_response = {
        "code": "OK",
        "data": {
            "keywordList": {"items": [{"keyword": "tablet stand"}]},
            "task": {},
        },
    }

    with pytest.raises(SellerSpriteApiError) as exc_info:
        worker_module._merge_real_time_bidding_detail_responses(
            sp_response,
            sb_response,
        )

    assert exc_info.value.api_code == "ERR_REAL_TIME_BIDDING_DETAIL_MISMATCH"


def test_keyword_conversion_rate_does_not_repeat_enter_after_committed_timeout(
    tmp_path,
):
    endpoint = "/v3/api/keyword-conv"
    page = _KeywordConversionRatePage(
        endpoint,
        press_timeout_after_commit=True,
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-conversion-rate",
        method="POST",
        endpoint=endpoint,
        payload={
            "market": "US",
            "timeType": "W",
            "keyword": "wireless charger stand,phone holder",
            "pageNum": 1,
            "pageSize": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-conversion-rate",
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
        root_dir=tmp_path,
        replay_safe=False,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.presses == ["Enter", "Enter"]
    assert page.tags == ["wireless charger stand", "phone holder"]
    assert page.clicks.count("query") == 1


def test_keyword_conversion_rate_requires_exact_tag_count_placeholder(
    tmp_path,
):
    endpoint = "/v3/api/keyword-conv"
    page = _KeywordConversionRatePage(
        endpoint,
        placeholder_override=None,
    )
    request = worker_module.BrowserRouteRequest(
        scenario="keyword-conversion-rate",
        method="POST",
        endpoint=endpoint,
        payload={
            "market": "US",
            "timeType": "W",
            "keyword": "wireless charger stand",
            "pageNum": 1,
            "pageSize": 100,
        },
        referer="https://www.sellersprite.com/v3/keyword-conversion-rate",
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
        root_dir=tmp_path,
        replay_safe=False,
    )

    with pytest.raises(
        SellerSpriteApiError,
        match="关键词计数与输入不一致",
    ):
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert "query" not in page.clicks
    assert "expect_response" not in page.events


def test_association_traffic_route_propagates_prepare_business_error(tmp_path):
    endpoint = "/v3/api/relation/traffic"
    page = _AssociationPageWithPrepareError(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="association-traffic",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": ["B0GS9B1X5X"],
            "queryVariations": True,
        },
        referer="https://www.sellersprite.com/v3/relation-keyword",
        account=account,
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_GLOBAL_500"
    assert exc_info.value.api_message == "处理请求出现错误,请稍后重试。"
    assert "ERR_GLOBAL_500" in (exc_info.value.response_excerpt or "")
    assert page.clicks == ["clear", "query"]


def test_association_traffic_route_does_not_silently_fallback_when_variant_dialog_is_missing(tmp_path):
    endpoint = "/v3/api/relation/traffic"
    page = _AssociationPageWithoutVariantButton(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="association-traffic",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": ["B098T9ZFB5"],
            "queryVariations": True,
        },
        referer="https://www.sellersprite.com/v3/relation-keyword",
        account=account,
        root_dir=tmp_path,
    )

    with pytest.raises(SellerSpriteApiError) as exc_info:
        _run(
            worker_module._trigger_request(
                page,
                endpoint=endpoint,
                method="POST",
                payload=request.payload,
                request=request,
            )
        )

    assert exc_info.value.api_code == "ERR_ASSOCIATION_TRAFFIC_VARIANT_DIALOG"
    assert page.clicks == ["clear", "query"]


def test_association_traffic_page_prepare_false_still_uses_visible_ui(tmp_path):
    endpoint = "/v3/api/relation/traffic"
    page = _AssociationPage(endpoint)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    request = worker_module.BrowserRouteRequest(
        scenario="association-traffic",
        method="POST",
        endpoint=endpoint,
        payload={
            "asinList": ["B098T9ZFB5"],
            "queryVariations": True,
            "pageNum": 1,
        },
        referer="https://www.sellersprite.com/v3/relation-keyword",
        account=account,
        root_dir=tmp_path,
        page_prepare=False,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="POST",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.fills == ["B098T9ZFB5"]
    assert page.presses == ["Enter"]
    assert page.clicks == ["clear", "query", "all_variants"]


def test_post_query_context_request_uses_query_and_empty_json_body():
    page = FakeContextPage()

    response = _run(
        worker_module._request_with_browser_context(
            page,
            endpoint="/v3/api/test-post-query",
            method="POST_QUERY",
            payload={"asin": "B0TEST", "station": "GLOBAL"},
        )
    )

    assert response.status == 200
    call = page.context.request.post_calls[0]
    assert call["url"] == "https://www.sellersprite.com/v3/api/test-post-query?asin=B0TEST&station=GLOBAL"
    assert call["kwargs"]["data"] == "{}"
    assert call["kwargs"]["headers"]["Content-Type"] == "application/json;charset=UTF-8"


def test_branddb_context_request_posts_xlsx_json_once():
    page = FakeContextPage()
    payload = {"text": "ANKER", "office": [], "ids": []}

    response = _run(
        worker_module._request_with_browser_context(
            page,
            endpoint="/v3/api/branddb/export-syn",
            method="POST_XLSX",
            payload=payload,
        )
    )

    assert response.status == 200
    assert len(page.context.request.post_calls) == 1
    call = page.context.request.post_calls[0]
    assert call["url"] == "https://www.sellersprite.com/v3/api/branddb/export-syn"
    assert json.loads(call["kwargs"]["data"]) == payload
    assert call["kwargs"]["timeout"] == 120000
    assert call["kwargs"]["fail_on_status_code"] is False
    assert "spreadsheetml.sheet" in call["kwargs"]["headers"]["Accept"]
    assert call["kwargs"]["headers"]["Content-Type"] == "application/json;charset=UTF-8"


def test_branddb_route_fetch_bypasses_page_trigger(monkeypatch, tmp_path):
    content = b"PK\x03\x04" + b"official-branddb-workbook" * 20
    context_calls = []
    trigger_calls = []

    class XlsxResponse:
        status = 200
        url = "https://www.sellersprite.com/v3/api/branddb/export-syn"
        headers = {
            "content-type": "application/msexcel;charset=utf-8",
            "content-disposition": "attachment; filename=Branddb-ANKER.xlsx",
        }

        async def body(self):
            return content

    async def fake_context_request(page, **kwargs):
        context_calls.append(kwargs)
        return XlsxResponse()

    async def fail_page_trigger(*args, **kwargs):
        trigger_calls.append(kwargs)
        raise AssertionError("POST_XLSX 不应进入页面监听路径")

    monkeypatch.setattr(worker_module, "_request_with_browser_context", fake_context_request)
    monkeypatch.setattr(worker_module, "_trigger_request", fail_page_trigger)
    worker = SellerSpriteBrowserRouteWorker(
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account=SellerSpriteAccount(
            name="default",
            username="user@example.com",
            password="secret",
        ),
    )

    result = _run(
        worker._execute_route_fetch(
            page=FakeContextPage(),
            method="POST_XLSX",
            endpoint="/v3/api/branddb/export-syn",
            payload={"text": "ANKER"},
            root_dir=tmp_path,
            section="main",
        )
    )

    assert len(context_calls) == 1
    assert context_calls[0]["method"] == "POST_XLSX"
    assert trigger_calls == []
    assert Path(result["data"]["official_xlsx_path"]).read_bytes() == content


def test_keyword_research_context_request_uses_get_page_html_headers():
    page = FakeContextPage()

    response = _run(
        worker_module._request_with_browser_context(
            page,
            endpoint="/v2/keyword-research",
            method="GET_PAGE",
            payload={"station": "US", "month": "202606", "page": "1", "size": "50"},
        )
    )

    assert response.status == 200
    call = page.context.request.get_calls[0]
    assert call["url"] == (
        "https://www.sellersprite.com/v2/keyword-research"
        "?station=US&month=202606&page=1&size=50"
    )
    assert call["kwargs"]["headers"]["Accept"].startswith("text/html")
    assert "Content-Type" not in call["kwargs"]["headers"]


def test_aba_reverse_context_request_uses_xlsx_get_headers():
    page = FakeContextPage()

    response = _run(
        worker_module._request_with_browser_context(
            page,
            endpoint="/v2/aba/reverse/export",
            method="GET_XLSX",
            payload={"station": "US", "table": "ara_20260718", "asin": "B00000JBNX"},
        )
    )

    assert response.status == 200
    call = page.context.request.get_calls[0]
    assert call["url"].startswith(
        "https://www.sellersprite.com/v2/aba/reverse/export?station=US"
    )
    assert "spreadsheetml.sheet" in call["kwargs"]["headers"]["Accept"]
    assert "Content-Type" not in call["kwargs"]["headers"]


def test_browser_response_saves_official_xlsx_bytes(tmp_path):
    content = b"PK\x03\x04" + b"official-workbook" * 20

    class XlsxResponse:
        status = 200
        url = "https://www.sellersprite.com/v2/aba/reverse/export"
        headers = {
            "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content-disposition": (
                "attachment; filename*=UTF-8''ABA-Reverse-B00000JBNX-US-20260723.xlsx"
            ),
        }

        async def body(self):
            return content

    result = _run(
        worker_module._parse_response(
            XlsxResponse(),
            method="GET_XLSX",
            root_dir=tmp_path,
            section="main",
        )
    )

    path = Path(result["data"]["official_xlsx_path"])
    assert path.name == "ABA-Reverse-B00000JBNX-US-20260723.xlsx"
    assert path.read_bytes() == content
    assert result["data"]["official_filename"] == (
        "ABA-Reverse-B00000JBNX-US-20260723.xlsx"
    )
    assert result["data"]["content_length"] == len(content)


def test_browser_response_accepts_branddb_xlsx_and_preserves_bytes(tmp_path):
    content = b"PK\x03\x04" + b"official-branddb-workbook" * 20

    class XlsxResponse:
        status = 200
        url = "https://www.sellersprite.com/v3/api/branddb/export-syn"
        headers = {
            "content-type": "application/msexcel;charset=utf-8",
            "content-disposition": "attachment; filename=Branddb-ANKER%282000%29-20260730.xlsx",
        }

        async def body(self):
            return content

    result = _run(
        worker_module._parse_response(
            XlsxResponse(),
            method="POST_XLSX",
            root_dir=tmp_path,
            section="main",
        )
    )

    path = Path(result["data"]["official_xlsx_path"])
    assert path.name == "Branddb-ANKER(2000)-20260730.xlsx"
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("application/json", b'PK{"code":"ERR"}' + b"x" * 300),
        ("text/application/msexcel", b"PK\x03\x04" + b"x" * 300),
        ("application/msexcel", b"PK\x03\x04short"),
        ("application/msexcel", b"not-a-zip-workbook" * 20),
    ],
)
def test_branddb_xlsx_rejects_invalid_content_type_or_length(tmp_path, content_type, content):
    class XlsxResponse:
        status = 200
        url = "https://www.sellersprite.com/v3/api/branddb/export-syn"
        headers = {"content-type": content_type}

        async def body(self):
            return content

    with pytest.raises(SellerSpriteApiError, match="未返回 XLSX"):
        _run(
            worker_module._parse_response(
                XlsxResponse(),
                method="POST_XLSX",
                root_dir=tmp_path,
                section="main",
            )
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("../../evil.xlsx", "evil.xlsx"),
        ("..\\..\\evil.xlsx", "evil.xlsx"),
        ("unsafe\x00\x1fname.xlsx", "unsafename.xlsx"),
        ("CON.xlsx", "official-CON.xlsx"),
        ("lpt9", "official-lpt9.xlsx"),
    ],
)
def test_xlsx_response_filename_is_safe_on_windows(value, expected):
    assert worker_module._safe_response_filename(value) == expected


def test_listing_analysis_trigger_selects_panorama_and_clicks_latest_submit_button():
    page = FakeListingPage()

    clicked = _run(
        worker_module._trigger_listing_analysis_query(
            page,
            {"asin": "B0TEST123", "station": "GLOBAL"},
        )
    )

    assert clicked is True
    assert page.fills == [{"kind": "asin", "value": "B0TEST123"}]
    assert page.presses == []
    assert page.clicks == ["station_select", "station_us", "all", "submit"]


def test_listing_analysis_trigger_selects_requested_station_before_submit():
    page = FakeListingPage()

    clicked = _run(
        worker_module._trigger_listing_analysis_query(
            page,
            {"asin": "B0TEST123", "station": "JAPAN"},
        )
    )

    assert clicked is True
    assert page.clicks == ["station_select", "station_japan", "all", "submit"]


def test_listing_analysis_trigger_waits_for_panorama_creation_response(tmp_path):
    endpoint = "/v3/api/ai-workflow/listing-analysis"
    page = FakeListingPage()
    request = worker_module.BrowserRouteRequest(
        scenario="listing-analysis",
        method="PAGE_CAPTURE",
        endpoint=endpoint,
        payload={"asin": "B0TEST123", "station": "GLOBAL"},
        referer="https://www.sellersprite.com/v3/ai-history?module=LA",
        account=SellerSpriteAccount(
            name="default", username="user@example.com", password="secret"
        ),
        root_dir=tmp_path,
    )

    response, transport = _run(
        worker_module._trigger_request(
            page,
            endpoint=endpoint,
            method="PAGE_CAPTURE",
            payload=request.payload,
            request=request,
        )
    )

    assert response.status == 200
    assert transport == "page_response"
    assert page.main_response_timeout == worker_module.DEFAULT_TIMEOUT_MS


def test_listing_analysis_report_url_uses_latest_history_task_route():
    assert worker_module._listing_analysis_report_url("task id/1") == (
        "https://www.sellersprite.com/v3/ai-history?module=LA&taskId=task%20id/1"
    )


def test_open_referer_navigates_directly_without_homepage(monkeypatch, tmp_path):
    page = FakePage(url="https://www.sellersprite.com/v3/product-research", logged_in=True)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    login_calls = []

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fake_login(self, current_page, current_account, *, callback, **kwargs):
        login_calls.append({"account": current_account.username, "callback": callback})
        current_page.logged_in = True

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(SellerSpriteBrowserRouteWorker, "_login_with_account", fake_login)

    result = _run(
        worker._open_referer_and_login(
            page,
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
            ),
        )
    )

    assert [call["url"] for call in page.goto_calls] == [
        worker_module.DEFAULT_PAGE_URL,
    ]
    assert login_calls == []
    assert result["mode"] == "browser-route"
    assert result["browser_headless"] is False
    assert result["auto_xvfb"] is False


def test_open_referer_reloads_same_target_without_homepage(monkeypatch, tmp_path):
    page = FakePage(url=worker_module.DEFAULT_PAGE_URL, logged_in=True)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fail_login(self, current_page, current_account, *, callback, **kwargs):
        raise AssertionError("logged-in same-target page must not login again")

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(SellerSpriteBrowserRouteWorker, "_login_with_account", fail_login)

    result = _run(
        worker._open_referer_and_login(
            page,
            worker_module.BrowserRouteRequest(
                scenario="keyword-miner",
                method="POST",
                endpoint="/v3/api/keyword/miner",
                payload={"keyword": "flashlight"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
            ),
        )
    )

    assert page.reload_calls == 1
    assert page.goto_calls == []
    assert result["current_url"] == worker_module.DEFAULT_PAGE_URL


def test_login_url_uses_cn_account_login_page():
    assert worker_module.LOGIN_URL == "https://www.sellersprite.com/cn/w/user/login"


def test_open_referer_skips_reload_after_login_redirect(monkeypatch, tmp_path):
    page = FakePage(url=worker_module.LOGIN_URL, logged_in=False)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    login_calls = []

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fake_login(self, current_page, current_account, *, callback, **kwargs):
        login_calls.append(callback)
        current_page.url = callback
        current_page.logged_in = True

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(SellerSpriteBrowserRouteWorker, "_login_with_account", fake_login)

    result = _run(
        worker._open_referer_and_login(
            page,
            worker_module.BrowserRouteRequest(
                scenario="keyword-miner",
                method="POST",
                endpoint="/v3/api/keyword/miner",
                payload={"keyword": "flashlight"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
            ),
        )
    )

    assert login_calls == [worker_module.DEFAULT_PAGE_URL]
    assert page.reload_calls == 0
    assert page.goto_calls == []
    assert result["current_url"] == worker_module.DEFAULT_PAGE_URL


def test_login_returns_when_login_url_redirects_to_logged_in_page(monkeypatch, tmp_path):
    page = RedirectedLoginPage()
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fail_click_account_login_tab(current_page):
        raise AssertionError("account login tab should not be clicked after logged-in redirect")

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(worker_module, "_click_account_login_tab", fail_click_account_login_tab)

    _run(worker._login_with_account(page, account, callback=worker_module.DEFAULT_PAGE_URL))

    assert page.goto_calls[0]["url"].startswith(worker_module.LOGIN_URL)
    assert page.url == worker_module.DEFAULT_PAGE_URL


def test_login_waits_for_redirect_instead_of_fixed_three_seconds(monkeypatch, tmp_path):
    page = LoginPage()
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    events = []

    class FakeInput:
        first = None

        def __init__(self, name):
            self.name = name
            self.first = self

        async def wait_for(self, **kwargs):
            events.append((self.name, "wait_for", kwargs))

        async def fill(self, value):
            events.append((self.name, "fill", value))

    password_input = FakeInput("password")
    username_input = FakeInput("username")

    def fake_locator(selector):
        if selector == "input[type='password']:visible":
            return password_input
        return username_input

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fake_click_account_login_tab(current_page):
        events.append(("page", "click_account_login_tab", None))

    async def fake_click_login_submit(current_page):
        events.append(("page", "click_login_submit", None))

    page.locator = fake_locator
    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(worker_module, "_click_account_login_tab", fake_click_account_login_tab)
    monkeypatch.setattr(worker_module, "_click_login_submit", fake_click_login_submit)

    _run(worker._login_with_account(page, account, callback=worker_module.DEFAULT_PAGE_URL))

    assert page.wait_for_url_calls == [{"timeout": worker_module.LOGIN_SUCCESS_TIMEOUT_MS}]
    assert page.timeout_calls == [1000, worker_module.LOGIN_SETTLE_TIMEOUT_MS]
    assert page.url == worker_module.DEFAULT_PAGE_URL


def test_linux_without_display_starts_auto_xvfb(monkeypatch):
    fake_process = FakeProcess()
    popen_calls = []
    monkeypatch.setattr(worker_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: "/usr/bin/Xvfb")
    monkeypatch.setattr(worker_module, "_wait_for_xvfb", lambda process, display: True)
    monkeypatch.setattr(
        worker_module.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append({"args": args, "kwargs": kwargs}) or fake_process,
    )

    try:
        attached = worker_module._ensure_headed_browser_environment(SellerSpriteSettings(browser_headless=False))
        assert attached is True
        assert worker_module.os.environ["DISPLAY"] == ":99"
        assert popen_calls[0]["args"] == [
            "/usr/bin/Xvfb",
            ":99",
            "-screen",
            "0",
            "1920x1080x24",
            "-ac",
            "-nolisten",
            "tcp",
        ]
        assert popen_calls[0]["kwargs"]["stdout"] == subprocess.DEVNULL
        assert popen_calls[0]["kwargs"]["stderr"] == subprocess.DEVNULL
    finally:
        worker_module._stop_auto_xvfb()


def test_linux_without_display_requires_xvfb_when_missing(monkeypatch):
    monkeypatch.setattr(worker_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: None)
    worker_module._stop_auto_xvfb()

    with pytest.raises(SellerSpriteConfigError, match="未找到 Xvfb"):
        worker_module._ensure_headed_browser_environment(SellerSpriteSettings(browser_headless=False))


def test_headless_mode_does_not_start_xvfb(monkeypatch):
    monkeypatch.setattr(worker_module.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        worker_module,
        "_ensure_auto_xvfb",
        lambda: pytest.fail("headless mode should not start Xvfb"),
    )

    assert worker_module._ensure_headed_browser_environment(SellerSpriteSettings(browser_headless=True)) is False


def test_load_settings_reads_patchright_browser_runtime(monkeypatch):
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_BROWSER_RUNTIME", "patchright")

    settings = load_settings()

    assert settings.browser_runtime == "patchright"


def test_load_settings_reads_captcha_ocr_options(monkeypatch):
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_BROWSER_CAPTCHA_OCR_ENABLED", "false")
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_BROWSER_CAPTCHA_OCR_MAX_ATTEMPTS", "3")

    settings = load_settings()

    assert settings.browser_captcha_ocr_enabled is False
    assert settings.browser_captcha_ocr_max_attempts == 3


def test_load_settings_reads_browser_session_lifecycle_options(monkeypatch):
    """浏览器空闲回收和最大生命周期应支持环境变量覆盖。"""
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_BROWSER_IDLE_TTL_SECONDS", "1200")
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_BROWSER_MAX_LIFETIME_SECONDS", "14400")

    settings = load_settings()

    assert settings.browser_idle_ttl_seconds == 1200
    assert settings.browser_max_lifetime_seconds == 14400


def test_load_settings_reads_task_timeout(monkeypatch):
    """单任务执行超时应支持环境变量覆盖。"""
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_TASK_TIMEOUT_SECONDS", "300")

    settings = load_settings()

    assert settings.task_timeout_seconds == 300


def test_load_settings_reads_task_lease_lifecycle(monkeypatch):
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_TASK_LEASE_SECONDS", "90")
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_TASK_HEARTBEAT_SECONDS", "15")
    monkeypatch.setenv("OPSCLI_SELLER_SPRITE_SHUTDOWN_TIMEOUT_SECONDS", "8")

    settings = load_settings()

    assert settings.task_lease_seconds == 90
    assert settings.task_heartbeat_seconds == 15
    assert settings.shutdown_timeout_seconds == 8


def test_browser_runtime_defaults_to_patchright():
    assert DEFAULT_BROWSER_RUNTIME == "patchright"
    assert SellerSpriteSettings().browser_runtime == "patchright"
    assert SellerSpriteSettings().browser_cooldown_seconds == 10.0
    assert SellerSpriteSettings().browser_captcha_ocr_enabled is True
    assert SellerSpriteSettings().browser_captcha_ocr_max_attempts == 2
    assert SellerSpriteSettings().browser_idle_ttl_seconds == 1800
    assert SellerSpriteSettings().browser_max_lifetime_seconds == 21600
    assert DEFAULT_TASK_TIMEOUT_SECONDS == 600
    assert DEFAULT_TASK_LEASE_SECONDS == 60
    assert DEFAULT_TASK_HEARTBEAT_SECONDS == 20
    assert DEFAULT_SHUTDOWN_TIMEOUT_SECONDS == 15
    assert SellerSpriteSettings().task_timeout_seconds == 600
    assert SellerSpriteSettings().task_lease_seconds == 60
    assert SellerSpriteSettings().task_heartbeat_seconds == 20
    assert SellerSpriteSettings().shutdown_timeout_seconds == 15


def test_load_async_playwright_uses_patchright_runtime(monkeypatch):
    calls = []
    fake_module = SimpleNamespace(async_playwright=lambda: "patchright-runtime")

    def fake_import_module(name):
        calls.append(name)
        return fake_module

    monkeypatch.setattr(worker_module.importlib, "import_module", fake_import_module)

    assert worker_module._load_async_playwright("patchright")() == "patchright-runtime"
    assert calls == ["patchright.async_api"]


def test_patchright_launch_options_use_no_viewport_without_fixed_viewport():
    settings = SellerSpriteSettings(browser_runtime="patchright", browser_headless=False)

    options = worker_module._build_launch_options(settings)

    assert options["no_viewport"] is True
    assert "viewport" not in options


def test_worker_reports_busy_when_drain_lock_is_held(tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
        worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)

        assert worker.is_busy is False
        async with worker._drain_lock:
            assert worker.is_busy is True

    _run(scenario())


def test_task_interval_randomizes_between_one_and_configured_max(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker_module.random,
        "uniform",
        lambda low, high: calls.append((low, high)) or 3.0,
    )

    assert worker_module._random_task_interval_seconds(5.0) == 3.0
    assert calls == [(1.0, 5.0)]


def test_failure_cooldown_classifies_network_and_risk_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker_module.random,
        "uniform",
        lambda low, high: calls.append((low, high)) or low,
    )

    network_wait = worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("network", api_code="ERR_BROWSER_FETCH_FAILED")
    )
    rate_limit_wait = worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("limited", status_code=429)
    )
    captcha_wait = worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("需要完成验证码")
    )
    robot_wait = worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("机器人检测")
    )

    assert network_wait == 3.0
    assert rate_limit_wait == 15.0
    assert captcha_wait == 15.0
    assert robot_wait == 15.0
    assert calls == [(3.0, 5.0), (15.0, 20.0), (15.0, 20.0), (15.0, 20.0)]


def test_failure_cooldown_skips_session_config_and_unknown_errors(monkeypatch):
    monkeypatch.setattr(
        worker_module.random,
        "uniform",
        lambda low, high: pytest.fail("non-recoverable errors must not randomize cooldown"),
    )

    assert worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("expired", api_code="ERR_GLOBAL_SESSION_EXPIRED")
    ) == 0.0
    assert worker_module._failure_cooldown_seconds(
        SellerSpriteApiError("参数不对", status_code=400, api_message="参数错误")
    ) == 0.0
    assert worker_module._failure_cooldown_seconds(SellerSpriteConfigError("bad account")) == 0.0
    assert worker_module._failure_cooldown_seconds(RuntimeError("code bug")) == 0.0


def test_login_waits_at_most_five_seconds_for_password_input(monkeypatch, tmp_path):
    events = []

    class FakeInput:
        def __init__(self, name):
            self.name = name
            self.first = self

        async def wait_for(self, **kwargs):
            events.append((self.name, "wait_for", kwargs))

        async def fill(self, value):
            events.append((self.name, "fill", value))

    class FakeLoginPage(FakePage):
        def __init__(self):
            super().__init__(url="")
            self.password_input = FakeInput("password")
            self.username_input = FakeInput("username")

        def locator(self, selector):
            if selector == "input[type='password']:visible":
                return self.password_input
            return self.username_input

    async def fake_detect_logged_in(current_page):
        return False

    async def fake_click_account_login_tab(current_page):
        events.append(("page", "click_account_login_tab", None))

    async def fake_click_login_submit(current_page):
        events.append(("page", "click_login_submit", None))

    async def fake_wait_for_login_success(current_page, *, callback):
        events.append(("page", "wait_for_login_success", callback))

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(worker_module, "_click_account_login_tab", fake_click_account_login_tab)
    monkeypatch.setattr(worker_module, "_click_login_submit", fake_click_login_submit)
    monkeypatch.setattr(worker_module, "_wait_for_login_success", fake_wait_for_login_success)

    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    page = FakeLoginPage()

    _run(worker._login_with_account(page, account, callback=worker_module.DEFAULT_PAGE_URL))

    assert ("password", "wait_for", {"state": "visible", "timeout": 5000}) in events


def test_run_one_relogs_and_retries_main_request_once(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account=account,
        )
        page = object()
        execute_calls = []
        login_calls = []
        open_calls = []

        async def fake_ensure_page(current_account):
            return page

        async def fake_open(current_page, request, **kwargs):
            open_calls.append(request.referer)
            return {"logged_in": True, "current_url": request.referer}

        async def fake_login(current_page, current_account, *, callback, **kwargs):
            login_calls.append(callback)

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs["section"])
            if len(execute_calls) == 1:
                raise SellerSpriteApiError("expired", api_code="ERR_GLOBAL_SESSION_EXPIRED")
            return {"code": "OK", "data": {"items": []}}

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_login_with_account", fake_login)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        result = await worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
                page_prepare=False,
            )
        )

        assert result.response["code"] == "OK"
        assert execute_calls == ["main", "main"]
        assert login_calls == [worker_module.DEFAULT_PAGE_URL]
        assert open_calls == [worker_module.DEFAULT_PAGE_URL, worker_module.DEFAULT_PAGE_URL]

    _run(scenario())


def test_run_one_relogs_and_retries_guest_limited_association_response(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account=account,
        )
        page = SimpleNamespace(url="https://www.sellersprite.com/v3/relation-keyword")
        execute_calls = []
        login_calls = []

        async def fake_ensure_page(current_account):
            return page

        async def fake_open(current_page, request, **kwargs):
            return {"logged_in": True, "current_url": request.referer}

        async def fake_detect_logged_in(current_page):
            return True

        async def fake_login(current_page, current_account, *, callback, **kwargs):
            login_calls.append(callback)

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs["payload"]["pageNum"])
            size = 20 if len(execute_calls) == 1 else 100
            return {
                "code": "OK",
                "success": True,
                "data": {
                    "pagerDto": {
                        "page": kwargs["payload"]["pageNum"],
                        "size": size,
                        "total": 375,
                        "items": [{"asin": f"B0RESULT{index:03d}"} for index in range(size)],
                    }
                },
            }

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_login_with_account", fake_login)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        result = await worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="association-traffic",
                method="POST",
                endpoint="/v3/api/relation/traffic",
                payload={
                    "asinList": ["B098T9ZFB5"],
                    "pageNum": 2,
                    "pageSize": 100,
                    "queryVariations": True,
                },
                referer="https://www.sellersprite.com/v3/relation-keyword",
                account=account,
                root_dir=tmp_path,
                page_prepare=False,
            )
        )

        assert result.response["data"]["pagerDto"]["size"] == 100
        assert execute_calls == [2, 2]
        assert login_calls == ["https://www.sellersprite.com/v3/relation-keyword"]

    _run(scenario())


def test_run_one_association_page_prepare_disabled_still_opens_referer(
    monkeypatch, tmp_path
):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account=account,
        )
        page = SimpleNamespace(url="https://www.sellersprite.com/v3/relation-keyword")
        events = []

        async def fake_ensure_page(current_account):
            events.append("ensure_page")
            return page

        async def fake_open(current_page, request, **kwargs):
            events.append("open_referer")
            return {"logged_in": True}

        async def fake_captcha(current_page, request, warnings, timings, *, stage):
            events.append(f"captcha:{stage}")

        async def fake_execute(**kwargs):
            events.append("execute")
            return {
                "code": "OK",
                "success": True,
                "data": {
                    "pagerDto": {
                        "page": 2,
                        "size": 100,
                        "total": 175,
                        "items": [{"asin": "B0RESULT001"}],
                    }
                },
            }

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", fake_captcha)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        result = await worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="association-traffic",
                method="POST",
                endpoint="/v3/api/relation/traffic",
                payload={
                    "asinList": ["B098T9ZFB5"],
                    "pageNum": 2,
                    "pageSize": 100,
                    "queryVariations": True,
                },
                referer="https://www.sellersprite.com/v3/relation-keyword?pageNum=2&pageSize=100",
                account=account,
                root_dir=tmp_path,
                page_prepare=False,
            )
        )

        assert result.response["data"]["pagerDto"]["page"] == 2
        assert events == ["ensure_page", "open_referer", "captcha:after_open_referer", "execute"]

    _run(scenario())


def test_run_one_stops_after_second_session_expiry(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account=account,
        )
        execute_calls = []
        login_calls = []

        async def fake_ensure_page(current_account):
            return object()

        async def fake_open(current_page, request, **kwargs):
            return {"logged_in": True, "current_url": request.referer}

        async def fake_login(current_page, current_account, *, callback, **kwargs):
            login_calls.append(callback)

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs["section"])
            raise SellerSpriteApiError("expired", api_code="ERR_GLOBAL_SESSION_EXPIRED")

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_login_with_account", fake_login)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        with pytest.raises(SellerSpriteApiError, match="expired"):
            await worker._run_one(
                worker_module.BrowserRouteRequest(
                    scenario="keyword-reverse",
                    method="POST",
                    endpoint="/v3/api/keyword/reverse",
                    payload={"asin": "B0TEST"},
                    referer=worker_module.DEFAULT_PAGE_URL,
                    account=account,
                    root_dir=tmp_path,
                    page_prepare=False,
                )
            )

        assert execute_calls == ["main", "main"]
        assert login_calls == [worker_module.DEFAULT_PAGE_URL]

    _run(scenario())


def test_listing_analysis_report_relogs_and_retries_expired_session(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account=account,
        )
        page = object()
        capture_calls = []
        login_calls = []
        open_calls = []

        async def fake_ensure_page(current_account):
            return page

        async def fake_open(current_page, request, **kwargs):
            open_calls.append(request.referer)
            return {"logged_in": True, "current_url": request.referer}

        async def fake_login(current_page, current_account, *, callback, **kwargs):
            login_calls.append(callback)

        async def fake_capture(current_page, *, task_id, report_url, root_dir):
            capture_calls.append(task_id)
            if len(capture_calls) == 1:
                raise SellerSpriteApiError("expired", api_code="ERR_GLOBAL_SESSION_EXPIRED")
            return {
                "code": "OK",
                "success": True,
                "data": {"taskId": task_id, "taskStatus": "COMPLETED"},
            }

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_login_with_account", fake_login)
        monkeypatch.setattr(worker_module, "_open_listing_analysis_report_and_capture", fake_capture)

        result = await worker.fetch_listing_analysis_report(
            task_id="task-ready-after-relogin",
            root_dir=tmp_path,
            page_prepare=False,
            task_interval_seconds=0,
            cooldown_seconds=0,
        )

        assert result.response["data"]["taskStatus"] == "COMPLETED"
        assert capture_calls == ["task-ready-after-relogin", "task-ready-after-relogin"]
        assert login_calls == ["https://www.sellersprite.com/v3/ai-history?module=LA"]
        assert open_calls == [
            "https://www.sellersprite.com/v3/ai-history?module=LA",
            "https://www.sellersprite.com/v3/ai-history?module=LA",
        ]

    _run(scenario())


@pytest.mark.parametrize(
    "api_code",
    [
        "ERR_KEYWORD_COMPARISON_REQUEST_MISSED",
        "ERR_KEYWORD_COMPARISON_ENDPOINT_CHANGED",
        "ERR_KEYWORD_COMPARISON_RESPONSE_MISSED",
    ],
)
def test_run_one_does_not_retry_ambiguous_keyword_comparison_click(
    monkeypatch, tmp_path, api_code
):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path, browser_captcha_ocr_enabled=True),
            account=account,
        )
        execute_calls = []
        captcha_calls = []
        ambiguous_error = SellerSpriteApiError(
            "流量词对比点击后状态不明确",
            api_code=api_code,
        )

        async def fake_ensure_page(current_account):
            return object()

        async def fake_open(current_page, request, **kwargs):
            return {"logged_in": True, "current_url": request.referer}

        async def fake_captcha(current_page, request, warnings, timings, *, stage):
            captcha_calls.append(stage)
            if stage == "after_main_error":
                return {"provider": "fake-ocr", "attempts": 1}
            return None

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs["section"])
            raise ambiguous_error

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", fake_captcha)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        with pytest.raises(SellerSpriteApiError) as exc_info:
            await worker._run_one(
                worker_module.BrowserRouteRequest(
                    scenario="keyword-comparison",
                    method="POST",
                    endpoint="/v3/api/keyword-comparison/asin",
                    payload={
                        "asin": "B0949DWJCV",
                        "asinList": ["B0744DM3Y3"],
                        "page": 1,
                        "size": 100,
                    },
                    referer="https://www.sellersprite.com/v3/keyword-comparison",
                    account=account,
                    root_dir=tmp_path,
                    page_prepare=False,
                )
            )

        assert exc_info.value is ambiguous_error
        assert execute_calls == ["main"]
        assert captcha_calls == ["after_open_referer"]

    _run(scenario())


def test_run_one_retries_main_request_after_robot_captcha(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path, browser_captcha_ocr_enabled=True),
            account=account,
        )
        execute_calls = []
        captcha_calls = []

        async def fake_ensure_page(current_account):
            return object()

        async def fake_open(current_page, request, **kwargs):
            return {"logged_in": True, "current_url": request.referer}

        async def fake_captcha(current_page, request, warnings, timings, *, stage):
            captcha_calls.append(stage)
            if stage == "after_main_error":
                return {"provider": "fake-ocr", "attempts": 1}
            return None

        async def fake_execute(**kwargs):
            execute_calls.append(kwargs["section"])
            if len(execute_calls) == 1:
                raise SellerSpriteApiError("机器人检测")
            return {"code": "OK", "data": {"items": []}}

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", fake_captcha)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        result = await worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
                page_prepare=False,
            )
        )

        assert result.response["code"] == "OK"
        assert execute_calls == ["main", "main"]
        assert captcha_calls == ["after_open_referer", "after_main_error"]

    _run(scenario())


def test_robot_captcha_solver_noops_when_disabled(monkeypatch):
    page = FakeCaptchaPage(dialog_visible=True)

    def fail_provider():
        raise AssertionError("OCR provider must not load when captcha OCR is disabled")

    monkeypatch.setattr(worker_module, "create_captcha_ocr_provider", fail_provider)

    result = _run(
        worker_module._solve_robot_image_captcha(
            page,
            settings=SellerSpriteSettings(browser_captcha_ocr_enabled=False),
            stage="test",
        )
    )

    assert result is None
    assert page.filled_values == []
    assert page.clicks == []


def test_robot_captcha_solver_noops_when_dialog_absent(monkeypatch):
    page = FakeCaptchaPage(dialog_visible=False)

    def fail_provider():
        raise AssertionError("OCR provider must not load when robot dialog is absent")

    monkeypatch.setattr(worker_module, "create_captcha_ocr_provider", fail_provider)

    result = _run(
        worker_module._solve_robot_image_captcha(
            page,
            settings=SellerSpriteSettings(browser_captcha_ocr_enabled=True),
            stage="test",
        )
    )

    assert result is None
    assert page.filled_values == []
    assert page.clicks == []


def test_robot_captcha_solver_reports_missing_ddddocr(monkeypatch):
    page = FakeCaptchaPage(dialog_visible=True)

    def fake_provider():
        raise SellerSpriteConfigError("未安装 ddddocr")

    monkeypatch.setattr(worker_module, "create_captcha_ocr_provider", fake_provider)

    with pytest.raises(SellerSpriteConfigError, match="未安装 ddddocr"):
        _run(
            worker_module._solve_robot_image_captcha(
                page,
                settings=SellerSpriteSettings(browser_captcha_ocr_enabled=True),
                stage="test",
            )
        )


def test_ddddocr_provider_loads_dependency_lazily(monkeypatch):
    created = []

    class FakeDdddOcr:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def classification(self, image_bytes):
            assert image_bytes == b"image"
            return "ABCD"

    monkeypatch.setattr(
        ocr_module.importlib,
        "import_module",
        lambda name: SimpleNamespace(DdddOcr=FakeDdddOcr),
    )

    provider = ocr_module.DdddOcrCaptchaProvider()

    assert provider.name == "ddddocr"
    assert provider.recognize(b"image") == "ABCD"
    assert created == [{"show_ad": False}]


def test_robot_captcha_solver_uses_ocr_provider_to_fill_and_confirm(monkeypatch):
    page = FakeCaptchaPage(dialog_visible=True)
    recognized = []

    class FakeProvider:
        name = "fake-ocr"

        def recognize(self, image_bytes):
            recognized.append(image_bytes)
            return "ABCD"

    monkeypatch.setattr(worker_module, "create_captcha_ocr_provider", lambda: FakeProvider())

    result = _run(
        worker_module._solve_robot_image_captcha(
            page,
            settings=SellerSpriteSettings(browser_captcha_ocr_enabled=True),
            stage="test",
        )
    )

    assert recognized == [b"image"]
    assert result == {"provider": "fake-ocr", "attempts": 1}
    assert page.filled_values == ["ABCD"]
    assert page.clicks == ["button"]


def test_run_one_handles_robot_captcha_before_page_prepare(monkeypatch, tmp_path):
    async def scenario():
        account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
        worker = SellerSpriteBrowserRouteWorker(
            settings=SellerSpriteSettings(output_dir=tmp_path, browser_captcha_ocr_enabled=True),
            account=account,
        )
        page = object()
        events = []

        async def fake_ensure_page(current_account):
            events.append("ensure_page")
            return page

        async def fake_open(current_page, request, **kwargs):
            events.append("open_referer_and_login")
            return {"logged_in": True, "current_url": request.referer}

        async def fake_captcha(current_page, request, warnings, timings, *, stage):
            events.append(f"captcha:{stage}")

        async def fake_prepare(current_page):
            events.append("page_prepare")

        async def fake_execute(**kwargs):
            events.append(f"execute:{kwargs['section']}")
            return {"code": "OK", "data": {"items": []}}

        monkeypatch.setattr(worker, "_ensure_page", fake_ensure_page)
        monkeypatch.setattr(worker, "_open_referer_and_login", fake_open)
        monkeypatch.setattr(worker, "_handle_robot_captcha_if_enabled", fake_captcha)
        monkeypatch.setattr(worker_module, "_prepare_page", fake_prepare)
        monkeypatch.setattr(worker, "_execute_route_fetch", fake_execute)

        result = await worker._run_one(
            worker_module.BrowserRouteRequest(
                scenario="keyword-reverse",
                method="POST",
                endpoint="/v3/api/keyword/reverse",
                payload={"asin": "B0TEST"},
                referer=worker_module.DEFAULT_PAGE_URL,
                account=account,
                root_dir=tmp_path,
                page_prepare=True,
            )
        )

        assert result.response["code"] == "OK"
        assert events == [
            "ensure_page",
            "open_referer_and_login",
            "captcha:after_open_referer",
            "page_prepare",
            "execute:main",
        ]

    _run(scenario())
