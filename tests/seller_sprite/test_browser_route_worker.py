import asyncio
import subprocess

import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.browser_route import worker as worker_module
from opscli.seller_sprite.browser_route.worker import SellerSpriteBrowserRouteWorker
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


def _run(coro):
    return asyncio.run(coro)


class FakePage:
    def __init__(self):
        self.url = ""
        self.goto_calls = []
        self.logged_in = False

    async def goto(self, url, **kwargs):
        self.url = url
        self.goto_calls.append({"url": url, "kwargs": kwargs})

    async def wait_for_timeout(self, timeout):
        return None


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


def test_open_referer_checks_homepage_login_prompt_first(monkeypatch, tmp_path):
    page = FakePage()
    account = SellerSpriteAccount(name="default", username="user@example.com", password="secret")
    settings = SellerSpriteSettings(output_dir=tmp_path, browser_profile_dir=tmp_path / "profiles")
    worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
    login_calls = []

    async def fake_homepage_requires_login(current_page):
        return current_page.url == worker_module.HOME_URL

    async def fake_detect_logged_in(current_page):
        return current_page.logged_in

    async def fake_login(self, current_page, current_account, *, callback):
        login_calls.append({"account": current_account.username, "callback": callback})
        current_page.logged_in = True

    monkeypatch.setattr(worker_module, "_homepage_requires_login", fake_homepage_requires_login)
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
        worker_module.HOME_URL,
        worker_module.DEFAULT_PAGE_URL,
    ]
    assert login_calls == [{"account": "user@example.com", "callback": worker_module.DEFAULT_PAGE_URL}]
    assert result["mode"] == "browser-route"
    assert result["browser_headless"] is False
    assert result["auto_xvfb"] is False


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
