"""浏览器 attach 服务。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from opscli.amazon_rufus.domain.exceptions import ChromeCdpUnavailableError, SeedRequestNotCapturedError
from opscli.amazon_rufus.domain.models import SeedRequestRecord


class BrowserAttachService:
    """通过 Playwright CDP 连接本地 Chrome 并捕获 seed request。"""

    def __init__(self) -> None:
        self.current_page = None

    def open_marketplace_for_login(
        self,
        *,
        marketplace_url: str,
        cdp_url: str,
        timeout_seconds: int = 30,
        chrome_path: str | None = None,
        launch_if_needed: bool = True,
    ) -> None:
        """打开国家站点登录窗口并保留浏览器。"""
        self._ensure_cdp_ready(
            cdp_url=cdp_url,
            timeout_seconds=min(max(timeout_seconds, 1), 10),
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            new_chrome=False,
        )

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

    def capture_storage_state(
        self,
        *,
        marketplace_url: str,
        cdp_url: str,
        timeout_seconds: int = 30,
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
    ) -> dict:
        """捕获当前 CDP Chrome 上下文的 Playwright storage_state。"""
        self._ensure_cdp_ready(
            cdp_url=cdp_url,
            timeout_seconds=min(max(timeout_seconds, 1), 10),
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            new_chrome=False,
        )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ChromeCdpUnavailableError("缺少 Playwright，请安装 `opscli[amazon]`") from exc

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except Exception as exc:
                raise ChromeCdpUnavailableError(f"无法连接 Chrome CDP: {cdp_url}") from exc

            # 复用当前调试 Chrome 的第一个上下文，保证保存的是用户刚登录的 profile。
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            pages = list(getattr(context, "pages", []) or [])
            page = pages[0] if pages else context.new_page()
            page.goto(marketplace_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.bring_to_front()
            self.current_page = page
            storage_state = context.storage_state()
            return storage_state if isinstance(storage_state, dict) else {}

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
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
        on_captured: Callable[[Any, SeedRequestRecord], bool | None] | None = None,
    ) -> SeedRequestRecord:
        """捕获首个 Rufus streaming 请求。"""
        launched_by_service = self._ensure_cdp_ready(
            cdp_url=cdp_url,
            timeout_seconds=min(max(timeout_seconds, 1), 10),
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            new_chrome=new_chrome,
        )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ChromeCdpUnavailableError("缺少 Playwright，请安装 `opscli[amazon]`") from exc

        deadline_ms = max(int(timeout_seconds), 1) * 1000
        captured: list[SeedRequestRecord] = []
        keep_open_after_capture = False
        browser = None
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
                    if "/rufus/cl/streaming" not in str(getattr(request, "url", "") or "") or captured:
                        return
                    body = str(getattr(request, "post_data", "") or "{}")
                    captured.append(
                        SeedRequestRecord(
                            request_url=str(getattr(request, "url", "") or ""),
                            request_headers=dict(getattr(request, "headers", {}) or {}),
                            request_body=body,
                            page_url=str(getattr(page, "url", "") or page_url),
                            tab_id=self._extract_tab_id(str(getattr(request, "url", "") or ""), body),
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
                    keep_open_after_capture = bool(on_captured(page, seed))
                return seed
            finally:
                if launched_by_service and browser is not None and not keep_chrome_open and not keep_open_after_capture:
                    self._close_new_chrome(browser)

    def _ensure_cdp_ready(
        self,
        *,
        cdp_url: str,
        timeout_seconds: int,
        chrome_path: str | None,
        launch_if_needed: bool,
        new_chrome: bool,
    ) -> bool:
        """在需要时启动调试 Chrome，并等待 CDP 可用。"""
        launched_by_service = False
        if new_chrome:
            self._start_new_chrome(cdp_url=cdp_url, chrome_path=chrome_path)
            launched_by_service = True
        elif launch_if_needed and not self._is_cdp_available(cdp_url):
            self._start_new_chrome(cdp_url=cdp_url, chrome_path=chrome_path)
            launched_by_service = True
        self._wait_for_cdp(cdp_url, timeout_seconds=timeout_seconds)
        return launched_by_service

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

    def _start_new_chrome(self, *, cdp_url: str, chrome_path: str | None) -> None:
        """新开一个固定 profile 的 Chrome 调试窗口。"""
        resolved_chrome = self._resolve_chrome_path(chrome_path)
        port = self._resolve_cdp_port(cdp_url)
        profile_dir = Path.home() / ".opscli" / "chrome-profiles" / f"amazon-rufus-{port}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                [
                    resolved_chrome,
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={profile_dir}",
                    "--auto-open-devtools-for-tabs",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ChromeCdpUnavailableError(
                "无法启动 Chrome 调试窗口，请确认本机已安装 Chrome，或使用 --chrome-path 指定可执行文件。"
            ) from exc

    def _resolve_chrome_path(self, chrome_path: str | None) -> str:
        """解析 Chrome 可执行文件路径。"""
        if chrome_path:
            candidate = Path(chrome_path).expanduser()
            if candidate.exists():
                return str(candidate)
            raise ChromeCdpUnavailableError(f"指定的 Chrome 路径不存在: {chrome_path}")

        for command in ("chrome.exe", "chrome"):
            found = shutil.which(command)
            if found:
                return found

        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        raise ChromeCdpUnavailableError(
            "未找到 Chrome 可执行文件，请先安装 Chrome，或使用 --chrome-path 指定可执行文件。"
        )

    def _is_cdp_available(self, cdp_url: str) -> bool:
        """探测 Chrome DevTools HTTP 端点是否可用。"""
        version_url = cdp_url.rstrip("/") + "/json/version"
        try:
            response = httpx.get(version_url, timeout=1)
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    def _wait_for_cdp(self, cdp_url: str, *, timeout_seconds: int) -> None:
        """等待 Chrome DevTools HTTP 端点可用。"""
        deadline = time.monotonic() + max(int(timeout_seconds), 1)
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
        raise ChromeCdpUnavailableError(f"Chrome CDP 端点不可用: {cdp_url}") from last_error

    def _resolve_cdp_port(self, cdp_url: str) -> int:
        """从 CDP URL 中提取端口。"""
        parsed = urlsplit(cdp_url)
        if parsed.port:
            return parsed.port
        return 9222

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
