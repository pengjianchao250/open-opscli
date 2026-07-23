import asyncio
from types import SimpleNamespace
import subprocess

import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.browser_route import ocr as ocr_module
from opscli.seller_sprite.browser_route import worker as worker_module
from opscli.seller_sprite.browser_route.worker import SellerSpriteBrowserRouteWorker
from opscli.seller_sprite.config import (
    DEFAULT_BROWSER_RUNTIME,
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
        return 1

    async def is_visible(self, **kwargs):
        return True

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

    def locator(self, selector):
        if "input" in selector:
            return FakeListingLocator(self, "asin")
        return FakeListingLocator(self, "submit")


class _AssociationResponseWaiter:
    """模拟 Playwright 的响应等待上下文。"""

    def __init__(self, endpoint):
        self.value = asyncio.get_running_loop().create_future()
        self.value.set_result(
            SimpleNamespace(
                url=f"https://www.sellersprite.com{endpoint}",
                status=200,
            )
        )

    async def __aenter__(self):
        """进入响应等待上下文并返回自身。"""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """退出响应等待上下文，不吞掉测试异常。"""
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

    async def press(self, key, **kwargs):
        """记录输入框按键。"""
        self.page.presses.append(key)

    async def click(self, **kwargs):
        """记录按钮点击。"""
        self.page.clicks.append(self.kind)

    async def get_attribute(self, name):
        """返回按回车次数生成的 ASIN 计数占位符。"""
        if self.kind == "asin" and name == "placeholder":
            return f"已录入{len(self.page.presses)}/20个ASIN"
        return None


class _AssociationPage:
    """模拟关联流量查询入口页。"""

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.fills = []
        self.presses = []
        self.clicks = []
        self.timeout_calls = []

    def expect_response(self, predicate, **kwargs):
        """返回主接口响应等待上下文。"""
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


class _AssociationPageWithoutVariantButton(_AssociationPage):
    """模拟弹窗未提供全部变体按钮的异常页面。"""

    def locator(self, selector):
        """让全部变体按钮保持不可见，其余控件沿用正常页面。"""
        if "用全部变体查询" in selector:
            return _AssociationLocator(self, "missing")
        return super().locator(selector)


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
            endpoint="/v3/api/ai-workflow/listing-analysis",
            method="POST_QUERY",
            payload={"asin": "B0TEST", "station": "GLOBAL"},
        )
    )

    assert response.status == 200
    call = page.context.request.post_calls[0]
    assert call["url"] == "https://www.sellersprite.com/v3/api/ai-workflow/listing-analysis?asin=B0TEST&station=GLOBAL"
    assert call["kwargs"]["data"] == "{}"
    assert call["kwargs"]["headers"]["Content-Type"] == "application/json;charset=UTF-8"


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


def test_listing_analysis_trigger_fills_asin_and_submits_with_enter_first():
    page = FakeListingPage()

    clicked = _run(
        worker_module._trigger_listing_analysis_query(
            page,
            {"asin": "B0TEST123", "station": "GLOBAL"},
        )
    )

    assert clicked is True
    assert page.fills == [{"kind": "asin", "value": "B0TEST123"}]
    assert page.presses == [{"kind": "asin", "key": "Enter"}]
    assert page.clicks == []


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


def test_browser_runtime_defaults_to_patchright():
    assert DEFAULT_BROWSER_RUNTIME == "patchright"
    assert SellerSpriteSettings().browser_runtime == "patchright"
    assert SellerSpriteSettings().browser_cooldown_seconds == 10.0
    assert SellerSpriteSettings().browser_captcha_ocr_enabled is True
    assert SellerSpriteSettings().browser_captcha_ocr_max_attempts == 2
    assert SellerSpriteSettings().browser_idle_ttl_seconds == 1800
    assert SellerSpriteSettings().browser_max_lifetime_seconds == 21600
    assert DEFAULT_TASK_TIMEOUT_SECONDS == 600
    assert SellerSpriteSettings().task_timeout_seconds == 600


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
