"""浏览器 attach 服务。"""

from __future__ import annotations

import json
import os
import re
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

    def watch_login_and_capture_seed_request(
        self,
        *,
        asin: str,
        country: str,
        marketplace_url: str,
        page_url: str,
        cdp_url: str,
        timeout_seconds: int,
        chrome_path: str | None = None,
        launch_if_needed: bool = True,
        close_browser: bool = False,
    ) -> dict:
        """监听登录页，登录后捕获首个 Rufus streaming 请求。"""
        launched_by_service = self._ensure_cdp_ready(
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

        deadline_at = time.monotonic() + max(int(timeout_seconds), 1)
        captured: list[SeedRequestRecord] = []
        login_detected = False
        product_page_opened = False
        active_page = None
        registered_page_ids: set[int] = set()
        page_sources: dict[int, str] = {}
        pending_page_sources: list[str] = []
        debug_pages_enabled = self._debug_pages_enabled()
        browser = None

        with sync_playwright() as playwright:
            try:
                try:
                    browser = playwright.chromium.connect_over_cdp(cdp_url)
                except Exception as exc:
                    raise ChromeCdpUnavailableError(f"无法连接 Chrome CDP: {cdp_url}") from exc

                context = browser.contexts[0] if browser.contexts else browser.new_context()
                self._install_watch_login_request_filters(context)

                def debug_page_event(event: str, page: Any, *, source: str | None = None) -> None:
                    """按需输出页面生命周期诊断，避免默认路径产生噪声。"""
                    if not debug_pages_enabled:
                        return
                    self._print_debug_page_event(
                        event=event,
                        page=page,
                        source=source or page_sources.get(id(page), "external"),
                    )

                def new_service_page(source: str) -> Any:
                    """创建 opscli 页签并提前记录来源，兼容 Playwright 同步触发 page 事件。"""
                    pending_page_sources.append(source)
                    try:
                        page = context.new_page()
                    finally:
                        if pending_page_sources and pending_page_sources[-1] == source:
                            pending_page_sources.pop()
                    page_sources[id(page)] = source
                    register_page(page)
                    return page

                def register_page(page: Any) -> None:
                    page_id = id(page)
                    if page_id not in page_sources:
                        page_sources[page_id] = pending_page_sources.pop(0) if pending_page_sources else "external"
                    if page_id in registered_page_ids:
                        return
                    registered_page_ids.add(page_id)

                    def on_request(request: Any) -> None:
                        if captured:
                            return
                        if "/rufus/cl/streaming" not in str(getattr(request, "url", "") or ""):
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

                    page_source = page_sources[page_id]

                    def on_frame_navigated(*_args: Any, watched_page: Any = page, watched_source: str = page_source) -> None:
                        """外部广告页导航后立即关闭，避免空白页反复闪烁。"""
                        self._close_blocked_external_page(watched_page, watched_source)

                    page.on("request", on_request)
                    page.on("framenavigated", on_frame_navigated)
                    page.on("close", lambda *_args: debug_page_event("closed", page))
                    self._close_blocked_external_page(page, page_source)
                    debug_page_event("created", page, source=page_source)

                for page in list(getattr(context, "pages", []) or []):
                    page_sources.setdefault(id(page), "existing")
                    register_page(page)

                context_on = getattr(context, "on", None)
                if callable(context_on):
                    context_on("page", register_page)

                login_page = new_service_page("ops-login")
                active_page = login_page
                login_page.goto(marketplace_url, wait_until="domcontentloaded", timeout=self._remaining_ms(deadline_at))
                debug_page_event("navigated", login_page)
                login_page.bring_to_front()
                self.current_page = login_page

                while time.monotonic() < deadline_at:
                    if captured:
                        storage_state = context.storage_state()
                        return {
                            "storage_state": storage_state if isinstance(storage_state, dict) else {},
                            "seed_request": captured[0],
                            "login_detected": login_detected,
                        }

                    for page in list(getattr(context, "pages", []) or []):
                        register_page(page)

                    login_detected = login_detected or self._is_marketplace_logged_in(
                        context=context,
                        pages=list(getattr(context, "pages", []) or []),
                        marketplace_url=marketplace_url,
                    )
                    if login_detected and not product_page_opened:
                        product_page = new_service_page("ops-product")
                        active_page = product_page
                        product_page.goto(page_url, wait_until="domcontentloaded", timeout=self._remaining_ms(deadline_at))
                        debug_page_event("navigated", product_page)
                        product_page.bring_to_front()
                        self.current_page = product_page
                        product_page_opened = True

                    self._wait_page_or_sleep(active_page, min(self._remaining_ms(deadline_at), 1000))
            finally:
                if close_browser and launched_by_service and browser is not None:
                    self._close_new_chrome(browser)

        normalized_country = country.strip().upper()
        raise SeedRequestNotCapturedError(
            "未捕获 /rufus/cl/streaming。"
            f"已监听目标国家站点登录页并等待 {max(int(timeout_seconds), 1)} 秒；"
            f"请确认 {normalized_country} 站点已登录且目标商品页支持 Rufus: {page_url}"
        )

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

    def clear_owned_profile(self, *, cdp_url: str = "http://127.0.0.1:9222") -> bool:
        """删除 opscli 自己创建的 Rufus 调试 Chrome profile。"""
        port = self._resolve_cdp_port(cdp_url)
        root = (Path.home() / ".opscli" / "chrome-profiles").resolve()
        profile_dir = (root / f"amazon-rufus-{port}").resolve()
        try:
            profile_dir.relative_to(root)
        except ValueError as exc:
            raise ChromeCdpUnavailableError("拒绝删除非 opscli Rufus Chrome profile") from exc
        if profile_dir.name != f"amazon-rufus-{port}":
            raise ChromeCdpUnavailableError("拒绝删除非 Rufus 调试 Chrome profile")
        if not profile_dir.exists():
            return False
        if not profile_dir.is_dir():
            raise ChromeCdpUnavailableError("opscli Rufus Chrome profile 不是目录，拒绝删除。")
        try:
            shutil.rmtree(profile_dir)
        except OSError as exc:
            raise ChromeCdpUnavailableError("无法删除 opscli Rufus Chrome profile，请先关闭对应调试 Chrome 后重试。") from exc
        return True

    def _start_new_chrome(self, *, cdp_url: str, chrome_path: str | None) -> None:
        """新开一个固定 profile 的 Chromium 调试窗口。"""
        resolved_chrome = self._resolve_chrome_path(chrome_path)
        port = self._resolve_cdp_port(cdp_url)
        profile_dir = Path.home() / ".opscli" / "chrome-profiles" / f"amazon-rufus-{port}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._disable_auto_open_devtools(profile_dir)
        try:
            subprocess.Popen(
                [
                    resolved_chrome,
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ChromeCdpUnavailableError(
                "无法启动 Chrome/Edge 调试窗口，请确认本机已安装 Chrome 或 Edge，或使用 --chrome-path 指定可执行文件。"
            ) from exc

    def _disable_auto_open_devtools(self, profile_dir: Path) -> None:
        """关闭 opscli 自建 Rufus profile 中残留的 DevTools 自动打开偏好。"""
        preference_files = [profile_dir / "Default" / "Preferences"]
        preference_files.extend(profile_dir.glob("Profile */Preferences"))
        for preference_file in preference_files:
            self._disable_auto_open_devtools_in_file(preference_file)

    def _disable_auto_open_devtools_in_file(self, preference_file: Path) -> None:
        """宽容更新单个 Chrome 偏好文件，避免损坏文件阻断 Rufus 采集。"""
        if not preference_file.exists() or not preference_file.is_file():
            return
        try:
            preferences = json.loads(preference_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(preferences, dict):
            return
        if not self._disable_auto_open_devtools_values(preferences):
            return
        try:
            preference_file.write_text(
                json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except OSError:
            return

    def _disable_auto_open_devtools_values(self, value: Any) -> bool:
        """递归关闭 DevTools 自动打开键，保留其他浏览器偏好。"""
        changed = False
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if normalized_key in {"autoopendevtools", "autoopendevtoolsforpopups", "autoopendevtoolsfortabs"}:
                    value[key] = "false" if isinstance(child, str) else False
                    changed = True
                    continue
                changed = self._disable_auto_open_devtools_values(child) or changed
        elif isinstance(value, list):
            for child in value:
                changed = self._disable_auto_open_devtools_values(child) or changed
        return changed

    def _resolve_chrome_path(self, chrome_path: str | None) -> str:
        """解析 Chrome/Edge 可执行文件路径。"""
        if chrome_path:
            candidate = Path(chrome_path).expanduser()
            if candidate.exists():
                return str(candidate)
            raise ChromeCdpUnavailableError(f"指定的 Chrome 路径不存在: {chrome_path}")

        for command in ("chrome.exe", "chrome", "msedge.exe", "msedge"):
            found = shutil.which(command)
            if found:
                return found

        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        raise ChromeCdpUnavailableError(
            "未找到 Chrome/Edge 可执行文件，请先安装 Chrome 或 Edge，或使用 --chrome-path 指定可执行文件。"
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

    def _remaining_ms(self, deadline_at: float) -> int:
        """计算距离截止时间剩余的毫秒数。"""
        return max(int((deadline_at - time.monotonic()) * 1000), 1)

    def _wait_page_or_sleep(self, page: Any, timeout_ms: int) -> None:
        """优先用 Playwright page 等待，测试替身缺失时退回 sleep。"""
        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if callable(wait_for_timeout):
            try:
                wait_for_timeout(max(int(timeout_ms), 1))
            except Exception as exc:
                if self._is_page_closed_error(exc):
                    raise SeedRequestNotCapturedError(
                        "监听 Rufus 登录页时页面、上下文或浏览器已关闭；"
                        "请确认没有浏览器扩展或外部自动化反复打开并关闭页签后重试。"
                    ) from exc
                raise
            return
        time.sleep(max(int(timeout_ms), 1) / 1000)

    def _install_watch_login_request_filters(self, context: Any) -> None:
        """安装 watch-login 专用请求过滤，屏蔽会反复拉起空白页的广告域名。"""
        route = getattr(context, "route", None)
        if not callable(route):
            return
        try:
            route("https://s.amazon-adsystem.com/**", self._abort_watch_login_route)
        except Exception:
            # 过滤失败不应阻断登录采集，外部页签关闭逻辑仍会兜底处理。
            return

    def _abort_watch_login_route(self, route: Any) -> None:
        """中止 watch-login 阶段不需要的广告请求。"""
        abort = getattr(route, "abort", None)
        if callable(abort):
            abort()

    def _close_blocked_external_page(self, page: Any, source: str) -> None:
        """关闭 Amazon 广告系统触发的外部页签，不影响 opscli 自建页签。"""
        if source != "external":
            return
        if not self._is_blocked_watch_login_url(str(getattr(page, "url", "") or "")):
            return
        close = getattr(page, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception:
            # 外部广告页可能已经自关闭，忽略竞态即可继续监听 Rufus 请求。
            return

    def _is_blocked_watch_login_url(self, url: str) -> bool:
        """识别 watch-login 阶段可屏蔽的 Amazon 广告系统 URL。"""
        host = (urlsplit(str(url or "")).hostname or "").lower()
        return host == "s.amazon-adsystem.com"

    def _debug_pages_enabled(self) -> bool:
        """判断是否开启 Rufus 页面生命周期诊断。"""
        value = os.environ.get("OPS_RUFUS_DEBUG_PAGES", "")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _print_debug_page_event(self, *, event: str, page: Any, source: str) -> None:
        """输出脱敏后的 page 生命周期事件。"""
        url = self._sanitize_debug_url(str(getattr(page, "url", "") or ""))
        print(f"[rufus-debug-pages] event={event} page_id={id(page)} source={source} url={url}")

    def _sanitize_debug_url(self, url: str) -> str:
        """仅保留 URL 的 scheme、host 和 path，避免泄露 query 参数。"""
        raw_url = str(url or "").strip()
        if not raw_url:
            return "-"
        parsed = urlsplit(raw_url)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or "/"
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        return raw_url.split("?", 1)[0].split("#", 1)[0] or "-"

    def _is_page_closed_error(self, exc: Exception) -> bool:
        """识别 Playwright 页面关闭类异常。"""
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message or (
            "page.wait_for_timeout" in message and "closed" in message
        )

    def _is_marketplace_logged_in(self, *, context: Any, pages: list[Any], marketplace_url: str) -> bool:
        """通过登录态 Cookie key 或 Amazon 顶部工具区文本判断登录完成。"""
        if self._has_marketplace_login_cookie(context, marketplace_url):
            return True
        for page in pages:
            text = self._read_account_nav_text(page)
            if not text:
                continue
            normalized = text.strip().lower()
            if self._looks_like_signed_out_text(normalized):
                continue
            return True
        return False

    def _has_marketplace_login_cookie(self, context: Any, marketplace_url: str) -> bool:
        """检查当前 CDP context 是否已有目标站点登录态 Cookie key。"""
        host = (urlsplit(marketplace_url).hostname or "").lower()
        storage_state = context.storage_state()
        if not isinstance(storage_state, dict):
            return False
        login_cookie_names = {"sso-state-main", "at-main"}
        for item in storage_state.get("cookies", []):
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip().lower().lstrip(".")
            name = str(item.get("name") or "").strip().lower()
            if name in login_cookie_names and domain and (host == domain or host.endswith("." + domain)):
                return True
        return False

    def _read_account_nav_text(self, page: Any) -> str:
        """读取 Amazon 顶部工具区文本，失败时返回空字符串。"""
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return ""
        try:
            value = evaluate(
                """
                () => {
                  const node = document.querySelector('#nav-tools');
                  return node ? node.textContent : '';
                }
                """
            )
        except Exception:
            return ""
        return str(value or "")

    def _looks_like_signed_out_text(self, text: str) -> bool:
        """识别常见未登录文案。"""
        signed_out_markers = (
            "sign in",
            "signin",
            "log in",
            "login",
            "identifícate",
            "identificate",
            "identificarse",
            "iniciar sesión",
            "登录",
            "登入",
            "サインイン",
            "ログイン",
            "anmelden",
            "einloggen",
            "connexion",
            "se connecter",
        )
        return any(marker in text for marker in signed_out_markers)
