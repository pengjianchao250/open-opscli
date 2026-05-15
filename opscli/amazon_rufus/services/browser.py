"""浏览器 attach 服务。"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Callable

from opscli.amazon_rufus.domain.exceptions import ChromeCdpUnavailableError, SeedRequestNotCapturedError
from opscli.amazon_rufus.domain.models import SeedRequestRecord


class BrowserAttachService:
    """通过 Playwright CDP 连接本地 Chrome 并捕获 seed request。"""

    DEFAULT_NEW_CHROME_ARGUMENTS = (
        "--remote-debugging-port=9222 "
        '--user-data-dir="E:\\chrome-profiles\\opscli-rufus" '
        "--auto-open-devtools-for-tabs "
        "--no-first-run "
        "--no-default-browser-check"
    )

    def __init__(self) -> None:
        self.current_page = None  # 保存页面句柄供后续 Rufus replay 复用

    def open_marketplace_for_login(
        self,
        *,
        marketplace_url: str,
        cdp_url: str,
        timeout_seconds: int = 30,
    ) -> None:
        """打开国家站点登录窗口并保留浏览器。"""
        self._start_new_chrome()
        self._wait_for_cdp(cdp_url, timeout_seconds=5)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ChromeCdpUnavailableError("缺少 Playwright，请安装 `opscli[amazon]`") from exc

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise ChromeCdpUnavailableError(f"无法连接 Chrome CDP: {cdp_url}") from exc
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.bring_to_front()
            self.current_page = page

    def capture_seed_request(
        self,
        *,
        asin: str,
        country: str,
        page_url: str,
        cdp_url: str,
        timeout_seconds: int,
        new_chrome: bool = False,
        keep_chrome_open: bool = False,
        on_captured: Callable[[Any, SeedRequestRecord], bool | None] | None = None,
    ) -> SeedRequestRecord:
        """捕获首个 Rufus streaming 请求。"""
        if new_chrome:
            self._start_new_chrome()
            self._wait_for_cdp(cdp_url, timeout_seconds=5)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ChromeCdpUnavailableError("缺少 Playwright，请安装 `opscli[amazon]`") from exc

        deadline_ms = timeout_seconds * 1000
        captured: list[SeedRequestRecord] = []
        keep_open_after_capture = False
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise ChromeCdpUnavailableError(f"无法连接 Chrome CDP: {cdp_url}") from exc
            try:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                page.bring_to_front()
                self.current_page = page

                def on_request(request: Any) -> None:
                    if "/rufus/cl/streaming" not in request.url or captured:
                        return
                    body = request.post_data or "{}"
                    captured.append(
                        SeedRequestRecord(
                            request_url=request.url,
                            request_headers=dict(request.headers),
                            request_body=body,
                            page_url=page.url or page_url,
                            tab_id=self._extract_tab_id(request.url, body),
                            asin=asin.strip().upper(),
                            country=country.strip().upper(),
                            captured_at=int(time.time() * 1000),
                        )
                    )

                page.on("request", on_request)
                page.goto(page_url, wait_until="domcontentloaded", timeout=deadline_ms)
                page.wait_for_timeout(min(deadline_ms, 1000))
                if not captured:
                    normalized_country = country.strip().upper()
                    raise SeedRequestNotCapturedError(
                        "未捕获 /rufus/cl/streaming。"
                        f"请先执行 opscli amazon-rufus init {normalized_country}，"
                        "并在新窗口登录 Amazon 后重试；"
                        f"同时确认目标站点支持 Rufus: {page_url}"
                    )
                seed = captured[0]
                if on_captured:
                    # 回放阶段发现用户可能未登录时，需要保留本次新开的 Chrome 供用户登录。
                    keep_open_after_capture = bool(on_captured(page, seed))
                return seed
            finally:
                # 仅关闭由本命令新开的调试 Chrome，避免影响用户已有浏览器。
                if new_chrome and not keep_chrome_open and not keep_open_after_capture:
                    self._close_new_chrome(browser)

    def _close_new_chrome(self, browser: Any) -> None:
        """通过 CDP 关闭本次新开的 Chrome。"""
        try:
            session = browser.new_browser_cdp_session()
            session.send("Browser.close")
            return
        except Exception:
            close = getattr(browser, "close", None)
            if callable(close):
                close()

    def _start_new_chrome(self) -> None:
        """新开一个固定 profile 的 Chrome 调试窗口。"""
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Start-Process chrome.exe -ArgumentList '"
            f"{self.DEFAULT_NEW_CHROME_ARGUMENTS}'",
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ChromeCdpUnavailableError(
                "无法启动 Chrome 调试窗口，请手动执行："
                "Start-Process chrome.exe -ArgumentList "
                "'--remote-debugging-port=9222 --user-data-dir=\"E:\\chrome-profiles\\opscli-rufus\" "
                "--auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'"
            ) from exc

    def _wait_for_cdp(self, cdp_url: str, *, timeout_seconds: int) -> None:
        """等待 Chrome DevTools HTTP 端点可用。"""
        import httpx

        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        version_url = cdp_url.rstrip("/") + "/json/version"
        while time.monotonic() < deadline:
            try:
                response = httpx.get(version_url, timeout=1)
                if response.status_code < 500:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.25)
        raise ChromeCdpUnavailableError(f"Chrome 调试窗口已启动，但 CDP 端点不可用: {cdp_url}") from last_error

    def _extract_tab_id(self, request_url: str, request_body: str) -> str:
        """从 URL 或 body 中提取 tabId。"""
        if "tabId=" in request_url:
            return request_url.split("tabId=", 1)[1].split("&", 1)[0]
        try:
            payload = json.loads(request_body)
        except json.JSONDecodeError:
            return ""
        value = payload.get("tabId") or payload.get("tab_id")
        return str(value or "")

