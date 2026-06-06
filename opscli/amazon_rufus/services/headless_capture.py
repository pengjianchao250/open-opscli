"""Rufus headless 浏览器捕获服务。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.exceptions import HeadlessRufusCaptureError, InvalidRufusCookieError
from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace


# 页面重开只处理 Amazon 商品页偶发未触发，不覆盖浏览器启动失败。
MAX_HEADLESS_PAGE_REOPEN_RETRIES = 3


def _parse_cookie_header(cookie: str) -> list[dict[str, str]]:
    """把 Cookie header 拆成 Playwright 可接受的 cookie 列表。"""
    pairs: list[dict[str, str]] = []
    for part in str(cookie or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        pairs.append({"name": name, "value": value})
    return pairs


@dataclass(slots=True)
class HeadlessRufusCaptureService:
    """使用 Playwright headless browser 捕获 Rufus seed request。"""

    def capture_seed_request(
        self,
        *,
        asin: str,
        country: str,
        cookie: str | None = None,
        storage_state: dict | None = None,
        timeout_seconds: int,
        page_url: str | None = None,
        streaming_url: str | None = None,
    ) -> SeedRequestRecord:
        """打开商品页并捕获首个 Rufus 请求。"""
        normalized_cookie = str(cookie or "").strip()
        if storage_state is None and not normalized_cookie:
            raise InvalidRufusCookieError("cookie 不能为空")

        marketplace = resolve_marketplace(country)
        page_url = page_url or build_product_url(asin, marketplace.country)
        parsed_page = urlsplit(page_url)
        page_host = parsed_page.hostname or ""
        if not page_host:
            raise HeadlessRufusCaptureError(f"商品页 host 无效: {page_url}")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise HeadlessRufusCaptureError("缺少 Playwright，请安装 `opscli[amazon]`") from exc

        deadline_at = time.monotonic() + max(int(timeout_seconds), 0)
        with sync_playwright() as playwright:
            browser = self._launch_headless_browser_with_repair(playwright)

            # 远程授权流程优先使用 Playwright storage_state，确保 cookies 与 localStorage 同时进入浏览器。
            context = browser.new_context(storage_state=storage_state) if storage_state else browser.new_context()
            try:
                try:
                    cookies = _parse_cookie_header(normalized_cookie) if storage_state is None else []
                    if cookies:
                        context.add_cookies(
                            [
                                {
                                    "name": item["name"],
                                    "value": item["value"],
                                    "domain": page_host.lstrip("."),
                                    "path": "/",
                                    "secure": parsed_page.scheme.lower() == "https",
                                }
                                for item in cookies
                            ]
                        )

                    return self._capture_seed_request_with_page_retry(
                        context=context,
                        asin=asin,
                        country=marketplace.country,
                        page_url=page_url,
                        deadline_at=deadline_at,
                    )
                except HeadlessRufusCaptureError:
                    raise
                except Exception as exc:
                    raise HeadlessRufusCaptureError(f"headless 捕获失败: {type(exc).__name__}") from exc
            finally:
                context.close()
                browser.close()

    def _capture_seed_request_with_page_retry(
        self,
        *,
        context: Any,
        asin: str,
        country: str,
        page_url: str,
        deadline_at: float,
    ) -> SeedRequestRecord:
        """在同一浏览器上下文内重开商品页，处理 Rufus 请求偶发未触发。"""
        last_error: HeadlessRufusCaptureError | None = None
        for attempt_index in range(MAX_HEADLESS_PAGE_REOPEN_RETRIES + 1):
            timeout_ms = self._remaining_timeout_ms(deadline_at)
            if timeout_ms <= 0:
                last_error = HeadlessRufusCaptureError("headless 捕获超时")
                break

            try:
                return self._capture_seed_request_once(
                    context=context,
                    asin=asin,
                    country=country,
                    page_url=page_url,
                    timeout_ms=timeout_ms,
                )
            except HeadlessRufusCaptureError as exc:
                last_error = exc
                if attempt_index >= MAX_HEADLESS_PAGE_REOPEN_RETRIES:
                    break

        raise self._build_page_retry_error(last_error)

    def _capture_seed_request_once(
        self,
        *,
        context: Any,
        asin: str,
        country: str,
        page_url: str,
        timeout_ms: int,
    ) -> SeedRequestRecord:
        """打开一次 Amazon 商品页并捕获首个 Rufus streaming 请求。"""
        page = None
        try:
            page = context.new_page()
            captured: list[SeedRequestRecord] = []

            def on_request(request: Any) -> None:
                if "/rufus/cl/streaming" not in str(getattr(request, "url", "") or ""):
                    return
                if captured:
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
                        country=country,
                        captured_at=int(time.time() * 1000),
                    )
                )

            page.on("request", on_request)
            page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(timeout_ms, 1000))
            if not captured:
                raise HeadlessRufusCaptureError(
                    "未捕获 /rufus/cl/streaming。请确认 cookie 是否有效，或目标商品页是否支持 Rufus。"
                )
            return captured[0]
        except HeadlessRufusCaptureError:
            raise
        except Exception as exc:
            raise HeadlessRufusCaptureError(f"headless 捕获失败: {type(exc).__name__}") from exc
        finally:
            close = getattr(page, "close", None)
            if callable(close):
                close()

    def _remaining_timeout_ms(self, deadline_at: float) -> int:
        """按总捕获截止时间计算本次页面打开还能使用的毫秒数。"""
        return int(max((deadline_at - time.monotonic()) * 1000, 0))

    def _build_page_retry_error(self, exc: HeadlessRufusCaptureError | None) -> HeadlessRufusCaptureError:
        """生成页面重开重试耗尽后的脱敏错误。"""
        if exc is None:
            return HeadlessRufusCaptureError(
                "未捕获 /rufus/cl/streaming；已重新打开 Amazon 商品页并重试 3 次。"
                "请确认 cookie 或浏览器状态有效，或目标商品页支持 Rufus。"
            )

        message = str(exc)
        if "未捕获 /rufus/cl/streaming" in message:
            return HeadlessRufusCaptureError(
                "未捕获 /rufus/cl/streaming；已重新打开 Amazon 商品页并重试 3 次。"
                "请确认 cookie 或浏览器状态有效，或目标商品页支持 Rufus。"
            )
        return HeadlessRufusCaptureError(f"{message}；已重新打开 Amazon 商品页并重试 3 次。")

    def _launch_headless_browser_with_repair(self, playwright: Any) -> Any:
        """启动 headless Chromium，缺少 Playwright 浏览器时自动安装并重试一次。"""
        try:
            return self._launch_headless_browser(playwright)
        except Exception as exc:
            if not self._is_missing_playwright_browser(exc):
                raise HeadlessRufusCaptureError("无法启动 headless Chromium") from exc

            try:
                self._install_playwright_chromium()
            except Exception as install_exc:
                reason = self._summarize_exception(install_exc)
                raise HeadlessRufusCaptureError(
                    "无法启动 headless Chromium；已尝试自动安装 Playwright Chromium，但安装失败。"
                    "请在 opscli 运行环境执行 python -m playwright install chromium 后重试。"
                    f"原因：{reason}"
                ) from install_exc

            try:
                return self._launch_headless_browser(playwright)
            except Exception as retry_exc:
                reason = self._summarize_exception(retry_exc)
                raise HeadlessRufusCaptureError(
                    "无法启动 headless Chromium；已尝试自动安装 Playwright Chromium 并重试一次，但仍未成功。"
                    "请在 opscli 运行环境执行 python -m playwright install chromium 后重试。"
                    f"原因：{reason}"
                ) from retry_exc

    def _launch_headless_browser(self, playwright: Any) -> Any:
        """按 Rufus headless 捕获参数启动 Chromium。"""
        return playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )

    def _is_missing_playwright_browser(self, exc: Exception) -> bool:
        """判断 Playwright 是否明确提示浏览器二进制缺失。"""
        text = str(exc).lower()
        return "executable doesn't exist" in text or "playwright install" in text

    def _install_playwright_chromium(self) -> None:
        """安装当前 Python 环境匹配的 Playwright Chromium。"""
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )

    def _summarize_exception(self, exc: Exception) -> str:
        """提取安全的短错误摘要，避免 MCP 响应过长。"""
        if isinstance(exc, subprocess.CalledProcessError):
            value = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            value = str(exc).strip()
        return (value or type(exc).__name__).replace("\r", " ").replace("\n", " ")[:300]

    def _extract_tab_id(self, request_url: str, request_body: str) -> str:
        """从请求 URL 或 body 中提取 tabId。"""
        if "tabId=" in request_url:
            return request_url.split("tabId=", 1)[1].split("&", 1)[0]
        try:
            payload = json.loads(request_body)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, dict):
            return ""
        value = payload.get("tabId") or payload.get("tab_id")
        return str(value or "")
