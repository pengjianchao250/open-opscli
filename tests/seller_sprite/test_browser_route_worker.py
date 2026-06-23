import asyncio
from types import SimpleNamespace
import subprocess

import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.browser_route import worker as worker_module
from opscli.seller_sprite.browser_route.worker import SellerSpriteBrowserRouteWorker
from opscli.seller_sprite.config import DEFAULT_BROWSER_RUNTIME, SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError


def _run(coro):
    return asyncio.run(coro)


class FakePage:
    def __init__(self, *, url="", logged_in=False):
        self.url = url
        self.goto_calls = []
        self.reload_calls = 0
        self.logged_in = logged_in

    async def goto(self, url, **kwargs):
        self.url = url
        self.goto_calls.append({"url": url, "kwargs": kwargs})

    async def wait_for_timeout(self, timeout):
        return None

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


def test_open_referer_navigates_directly_without_homepage(monkeypatch, tmp_path):
    page = FakePage(url="https://www.sellersprite.com/v3/product-research", logged_in=True)
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    login_calls = []

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fake_login(self, current_page, current_account, *, callback):
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

    async def fail_login(self, current_page, current_account, *, callback):
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


def test_browser_runtime_defaults_to_patchright():
    assert DEFAULT_BROWSER_RUNTIME == "patchright"
    assert SellerSpriteSettings().browser_runtime == "patchright"
    assert SellerSpriteSettings().browser_cooldown_seconds == 10.0


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

    assert network_wait == 3.0
    assert rate_limit_wait == 15.0
    assert captcha_wait == 15.0
    assert calls == [(3.0, 5.0), (15.0, 20.0), (15.0, 20.0)]


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

    monkeypatch.setattr(worker_module, "_detect_logged_in", fake_detect_logged_in)
    monkeypatch.setattr(worker_module, "_click_account_login_tab", fake_click_account_login_tab)
    monkeypatch.setattr(worker_module, "_click_login_submit", fake_click_login_submit)

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

        async def fake_open(current_page, request):
            open_calls.append(request.referer)
            return {"logged_in": True, "current_url": request.referer}

        async def fake_login(current_page, current_account, *, callback):
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

        async def fake_open(current_page, request):
            return {"logged_in": True, "current_url": request.referer}

        async def fake_login(current_page, current_account, *, callback):
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
