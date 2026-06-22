"""基于 Playwright browser-route 的卖家精灵接口执行器。"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import importlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.api.market_research import parse_market_research_html
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError


BASE_URL = "https://www.sellersprite.com"
HOME_URL = "https://www.sellersprite.com/"
LOGIN_URL = "https://www.sellersprite.com/cn/w/user/login"
DEFAULT_PAGE_URL = "https://www.sellersprite.com/v3/keyword-miner/"
DEFAULT_TIMEOUT_MS = 120000
XVFB_DISPLAY_CANDIDATES = range(99, 110)
TASK_INTERVAL_RANGE_SECONDS = (1.0, 5.0)
NETWORK_COOLDOWN_RANGE_SECONDS = (3.0, 5.0)
RISK_COOLDOWN_RANGE_SECONDS = (15.0, 20.0)

_AUTO_XVFB_PROCESS: subprocess.Popen | None = None
_AUTO_XVFB_DISPLAY: str | None = None
_AUTO_XVFB_REF_COUNT = 0


@dataclass(frozen=True)
class BrowserRouteRequest:
    """单个 browser-route 任务。"""

    scenario: str
    method: str
    endpoint: str
    payload: dict[str, Any]
    referer: str
    account: SellerSpriteAccount
    root_dir: Path
    high_frequency_endpoint: str | None = None
    high_frequency_payload: dict[str, Any] | None = None
    page_prepare: bool = True
    task_interval_seconds: float = 5.0
    cooldown_seconds: float = 20.0


@dataclass
class BrowserRouteResult:
    """browser-route 执行结果。"""

    login: dict[str, Any]
    response: dict[str, Any]
    high_frequency_response: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _QueuedTask:
    request: BrowserRouteRequest
    future: asyncio.Future


class SellerSpriteBrowserRouteWorker:
    """同账号串行消费 browser-route 任务，复用浏览器上下文。"""

    def __init__(self, *, settings: SellerSpriteSettings, account: SellerSpriteAccount) -> None:
        self.settings = settings
        self.account = account
        self._queue: asyncio.Queue[_QueuedTask] = asyncio.Queue()
        self._drain_lock = asyncio.Lock()
        self._last_finished_at = 0.0
        self._cooldown_until = 0.0
        self._playwright = None
        self._context = None
        self._page = None
        self._auto_xvfb_attached = False

    async def submit(self, request: BrowserRouteRequest) -> BrowserRouteResult:
        """入队并顺序执行任务。"""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(_QueuedTask(request=request, future=future))
        await self._drain_queue()
        return await future

    @property
    def is_busy(self) -> bool:
        """判断当前 worker 是否正在执行或已有排队任务。"""
        return self._drain_lock.locked() or not self._queue.empty()

    async def close(self) -> None:
        """关闭浏览器上下文。"""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        if self._auto_xvfb_attached:
            _release_auto_xvfb()
            self._auto_xvfb_attached = False

    async def _drain_queue(self) -> None:
        async with self._drain_lock:
            while not self._queue.empty():
                task = await self._queue.get()
                try:
                    result = await self._run_one(task.request)
                except Exception as exc:
                    cooldown_seconds = min(
                        _failure_cooldown_seconds(exc),
                        max(task.request.cooldown_seconds, 0.0),
                    )
                    if cooldown_seconds > 0:
                        self._cooldown_until = max(
                            self._cooldown_until,
                            time.monotonic() + cooldown_seconds,
                        )
                    if not task.future.done():
                        task.future.set_exception(exc)
                else:
                    if not task.future.done():
                        task.future.set_result(result)
                finally:
                    self._last_finished_at = time.monotonic()
                    self._queue.task_done()

    async def _run_one(self, request: BrowserRouteRequest) -> BrowserRouteResult:
        warnings: list[dict[str, Any]] = []
        referer = request.referer or DEFAULT_PAGE_URL
        await self._wait_for_cooldown(request, warnings)
        await self._wait_for_rate_limit(request, warnings)
        page = await self._ensure_page(request.account)
        login = await self._open_referer_and_login(page, request)
        if request.page_prepare:
            await _prepare_page(page)
        for attempt in range(2):
            try:
                response = await self._execute_route_fetch(
                    page=page,
                    method=request.method,
                    endpoint=request.endpoint,
                    payload=request.payload,
                    root_dir=request.root_dir,
                    section="main",
                )
                break
            except SellerSpriteApiError as exc:
                if attempt > 0 or not exc.is_session_expired():
                    raise
                await self._login_with_account(page, request.account, callback=referer)
                login = await self._open_referer_and_login(page, request)
                if request.page_prepare:
                    await _prepare_page(page)
        high_frequency_response = None
        if request.high_frequency_endpoint and request.high_frequency_payload:
            try:
                high_frequency_response = await self._execute_route_fetch(
                    page=page,
                    method="POST",
                    endpoint=request.high_frequency_endpoint,
                    payload=request.high_frequency_payload,
                    root_dir=request.root_dir,
                    section="high_frequency",
                )
            except SellerSpriteApiError as exc:
                warnings.append(
                    {
                        "stage": "high_frequency",
                        "message": "browser-route 高频词接口请求失败，主表继续导出",
                        "error": exc.to_dict(),
                    }
                )
        return BrowserRouteResult(
            login=login,
            response=response,
            high_frequency_response=high_frequency_response,
            warnings=warnings,
        )

    async def _wait_for_cooldown(self, request: BrowserRouteRequest, warnings: list[dict[str, Any]]) -> None:
        wait_seconds = self._cooldown_until - time.monotonic()
        if wait_seconds <= 0:
            return
        warnings.append(
            {
                "stage": "browser_queue",
                "message": "上一任务失败后进入账号冷却，已等待后继续",
                "wait_seconds": round(wait_seconds, 2),
                "account": request.account.to_public_dict(),
            }
        )
        await asyncio.sleep(wait_seconds)

    async def _wait_for_rate_limit(self, request: BrowserRouteRequest, warnings: list[dict[str, Any]]) -> None:
        if not self._last_finished_at:
            return
        interval = _random_task_interval_seconds(request.task_interval_seconds)
        if interval <= 0:
            return
        wait_seconds = interval - (time.monotonic() - self._last_finished_at)
        if wait_seconds <= 0:
            return
        warnings.append(
            {
                "stage": "browser_queue",
                "message": "同账号任务串行限速，已等待后继续",
                "wait_seconds": round(wait_seconds, 2),
                "account": request.account.to_public_dict(),
            }
        )
        await asyncio.sleep(wait_seconds)

    async def _ensure_page(self, account: SellerSpriteAccount):
        if self._page and not self._page.is_closed():
            return self._page
        if _ensure_headed_browser_environment(self.settings) and not self._auto_xvfb_attached:
            _retain_auto_xvfb()
            self._auto_xvfb_attached = True
        async_playwright = _load_async_playwright(self.settings.browser_runtime)
        if not self._playwright:
            self._playwright = await async_playwright().start()
        profile_dir = _profile_dir(self.settings, account)
        profile_dir.mkdir(parents=True, exist_ok=True)
        launch_options = _build_launch_options(self.settings)
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def _open_referer_and_login(self, page, request: BrowserRouteRequest) -> dict[str, Any]:
        referer = request.referer or DEFAULT_PAGE_URL
        if _is_login_url(page.url):
            await self._login_with_account(page, request.account, callback=referer)
        if _same_page_url(page.url, referer):
            await page.reload(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        else:
            await page.goto(referer, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        await page.wait_for_timeout(1500)
        if not await _detect_logged_in(page):
            await self._login_with_account(page, request.account, callback=referer)
            await page.goto(referer, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            await page.wait_for_timeout(1500)
        logged_in = await _detect_logged_in(page)
        if not logged_in:
            raise SellerSpriteConfigError("卖家精灵浏览器登录失败，请检查账号或浏览器 profile 登录状态")
        return {
            "mode": "browser-route",
            "profile_dir": str(_profile_dir(self.settings, request.account)),
            "current_url": page.url,
            "logged_in": logged_in,
            "browser_headless": self.settings.browser_headless,
            "browser_runtime": self.settings.browser_runtime,
            "display": os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
            "auto_xvfb": self._auto_xvfb_attached,
            "account": request.account.to_public_dict(),
        }

    async def _login_with_account(self, page, account: SellerSpriteAccount, *, callback: str) -> None:
        callback_url = _callback_path(callback)
        await page.goto(
            f"{LOGIN_URL}?callback={quote(callback_url)}",
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        await page.wait_for_timeout(1000)
        if await _detect_logged_in(page):
            return
        await _click_account_login_tab(page)
        password_input = page.locator("input[type='password']:visible").first
        try:
            await password_input.wait_for(state="visible", timeout=15000)
        except Exception as exc:
            if await _detect_logged_in(page):
                return
            raise SellerSpriteConfigError(
                f"卖家精灵登录页未显示账号登录密码框，current_url={page.url}"
            ) from exc
        username_input = page.locator(
            "input[placeholder*='手机号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='邮箱']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='子账号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='账号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='用户名']:visible:not([readonly]):not([disabled]), "
            "input[type='email']:visible:not([readonly]):not([disabled]), "
            "input[type='text']:visible:not([readonly]):not([disabled])"
        ).first
        await username_input.fill(account.username)
        await password_input.fill(account.password)
        await _click_login_submit(page)
        await page.wait_for_timeout(3000)

    async def _execute_route_fetch(
        self,
        *,
        page,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
        root_dir: Path,
        section: str,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        pattern = _route_pattern(endpoint)

        async def _handle(route) -> None:
            request = route.request
            if not _same_endpoint(request.url, endpoint):
                await route.continue_()
                return
            headers = {key: value for key, value in request.headers.items() if key.lower() != "content-length"}
            headers["accept"] = "application/json, text/plain, */*"
            if normalized_method == "GET":
                await route.continue_(
                    url=_url_with_query(endpoint, payload),
                    method="GET",
                    headers=headers,
                )
                return
            if normalized_method == "FORM":
                headers["content-type"] = "application/x-www-form-urlencoded"
                await route.continue_(
                    url=_absolute_url(endpoint),
                    method="POST",
                    headers=headers,
                    post_data=urlencode(_query_pairs(payload), doseq=True),
                )
                return
            headers["content-type"] = "application/json;charset=UTF-8"
            await route.continue_(
                url=_absolute_url(endpoint),
                method="POST",
                headers=headers,
                post_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )

        await page.route(pattern, _handle)
        try:
            response = await _trigger_request(page, endpoint=endpoint, method=normalized_method, payload=payload)
            return await _parse_response(response, method=normalized_method, root_dir=root_dir, section=section)
        finally:
            await page.unroute(pattern, _handle)


def _random_task_interval_seconds(max_seconds: float) -> float:
    """按配置上限生成同账号任务的随机间隔。"""
    upper = max(max_seconds, 0.0)
    if upper <= 0:
        return 0.0
    lower = min(TASK_INTERVAL_RANGE_SECONDS[0], upper)
    return random.uniform(lower, upper)


def _failure_cooldown_seconds(exc: Exception) -> float:
    """按失败类型计算后续任务冷却时间。"""
    if _is_session_expired_error(exc) or isinstance(exc, SellerSpriteConfigError):
        return 0.0
    if _is_risk_control_error(exc):
        return random.uniform(*RISK_COOLDOWN_RANGE_SECONDS)
    if _is_transient_network_error(exc):
        return random.uniform(*NETWORK_COOLDOWN_RANGE_SECONDS)
    return 0.0


def _is_session_expired_error(exc: Exception) -> bool:
    return isinstance(exc, SellerSpriteApiError) and exc.is_session_expired()


def _is_risk_control_error(exc: Exception) -> bool:
    if isinstance(exc, SellerSpriteApiError) and exc.status_code == 429:
        return True
    details = _error_details(exc)
    return any(
        marker in details
        for marker in ("captcha", "验证码", "risk control", "risk_control", "rate limit", "rate_limit", "too many", "风控")
    )


def _is_transient_network_error(exc: Exception) -> bool:
    if isinstance(exc, SellerSpriteApiError):
        if exc.api_code in {"ERR_BROWSER_FETCH_FAILED", "ERR_BROWSER_CONTEXT_REQUEST_FAILED"}:
            return True
        if exc.status_code in {408, 425, 500, 502, 503, 504}:
            return True
    return isinstance(exc, (TimeoutError, ConnectionError, OSError)) or exc.__class__.__name__ == "TimeoutError"


def _error_details(exc: Exception) -> str:
    values = [str(exc)]
    if isinstance(exc, SellerSpriteApiError):
        values.extend([exc.api_code or "", exc.api_message or "", exc.response_excerpt or ""])
    return " ".join(values).lower()


def _is_login_url(url: str) -> bool:
    return urlparse(url).path.rstrip("/").endswith("/w/user/login")


def _same_page_url(current_url: str, target_url: str) -> bool:
    return _normalized_page_url(current_url) == _normalized_page_url(target_url)


def _normalized_page_url(url: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True))),
    )


_WORKERS: dict[tuple[int, str], SellerSpriteBrowserRouteWorker] = {}


class _NoQueryButtonError(Exception):
    pass


def get_browser_route_worker(*, settings: SellerSpriteSettings, account: SellerSpriteAccount) -> SellerSpriteBrowserRouteWorker:
    """按事件循环和账号获取常驻 browser worker。"""
    loop_key = id(asyncio.get_running_loop())
    account_key = f"{account.name}:{account.username}"
    key = (loop_key, account_key)
    worker = _WORKERS.get(key)
    if not worker:
        worker = SellerSpriteBrowserRouteWorker(settings=settings, account=account)
        _WORKERS[key] = worker
    return worker


def get_existing_browser_route_worker(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
) -> SellerSpriteBrowserRouteWorker | None:
    """读取已存在的 browser worker，不存在时不创建新窗口或新队列。"""
    loop_key = id(asyncio.get_running_loop())
    account_key = f"{account.name}:{account.username}"
    return _WORKERS.get((loop_key, account_key))


def _ensure_headed_browser_environment(settings: SellerSpriteSettings) -> bool:
    """确保有头浏览器运行环境可用，返回是否使用了自动 Xvfb。"""
    if settings.browser_headless:
        return False
    if sys.platform.startswith("linux"):
        display = os.environ.get("DISPLAY")
        if _is_auto_xvfb_running() and display == _AUTO_XVFB_DISPLAY:
            return True
        if not (display or os.environ.get("WAYLAND_DISPLAY")):
            _ensure_auto_xvfb()
            return True
    if sys.platform == "win32" and os.environ.get("SESSIONNAME", "").lower().startswith("services"):
        raise SellerSpriteConfigError(
            "当前为 browser-route 有头浏览器模式，但 Windows 服务会话无法启动可见浏览器；"
            "请在交互式桌面/RDP 会话启动，或改用 OPSCLI_SELLER_SPRITE_MODE=api-direct"
        )
    return False


def _load_async_playwright(browser_runtime: str):
    """按配置加载 Playwright 或 Patchright 的 async API。"""
    runtime = (browser_runtime or "playwright").strip().lower()
    module_name = "patchright.async_api" if runtime == "patchright" else "playwright.async_api"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        if runtime == "patchright":
            raise SellerSpriteConfigError(
                "缺少 patchright 依赖，请安装 `pip install aukeys-opscli[seller-sprite]` 并执行 "
                "`python -m patchright install chromium`；如需真实 Chrome，可执行 "
                "`python -m patchright install chrome` 后设置 OPSCLI_SELLER_SPRITE_BROWSER_CHANNEL=chrome"
            ) from exc
        raise SellerSpriteConfigError(
            "缺少 playwright 依赖，请安装 `pip install opscli[seller-sprite]` 并执行 "
            "`python -m playwright install chromium --no-shell`"
        ) from exc
    return module.async_playwright


def _build_launch_options(settings: SellerSpriteSettings) -> dict[str, Any]:
    """构造 browser-route 持久化浏览器上下文启动参数。"""
    runtime = (settings.browser_runtime or "playwright").strip().lower()
    launch_options: dict[str, Any] = {
        "headless": settings.browser_headless,
        "locale": "zh-CN",
        "accept_downloads": True,
        "args": ["--no-sandbox"],
    }
    if runtime == "patchright":
        launch_options["no_viewport"] = True
    else:
        launch_options["viewport"] = {"width": 1440, "height": 1000}
    if settings.browser_channel:
        launch_options["channel"] = settings.browser_channel
    return launch_options


def _is_auto_xvfb_running() -> bool:
    return bool(_AUTO_XVFB_PROCESS and _AUTO_XVFB_PROCESS.poll() is None and _AUTO_XVFB_DISPLAY)


def _ensure_auto_xvfb() -> None:
    """Linux 无显示环境时自动启动 Xvfb。"""
    global _AUTO_XVFB_PROCESS, _AUTO_XVFB_DISPLAY
    if _is_auto_xvfb_running():
        os.environ["DISPLAY"] = _AUTO_XVFB_DISPLAY
        return
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        raise SellerSpriteConfigError(
            "当前为 browser-route 有头浏览器模式，但 Linux 环境未检测到 DISPLAY/WAYLAND_DISPLAY，且未找到 Xvfb；"
            "请安装 xvfb，或改用 OPSCLI_SELLER_SPRITE_MODE=api-direct"
        )
    for display_number in XVFB_DISPLAY_CANDIDATES:
        display = f":{display_number}"
        process = subprocess.Popen(
            [xvfb, display, "-screen", "0", "1920x1080x24", "-ac", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if _wait_for_xvfb(process, display):
            _AUTO_XVFB_PROCESS = process
            _AUTO_XVFB_DISPLAY = display
            os.environ["DISPLAY"] = display
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
    raise SellerSpriteConfigError(
        "自动启动 Xvfb 失败，请检查服务器显示端口占用或手动设置 DISPLAY；"
        "若不使用浏览器路线，请改用 OPSCLI_SELLER_SPRITE_MODE=api-direct"
    )


def _wait_for_xvfb(process: subprocess.Popen, display: str) -> bool:
    """等待 Xvfb 进程和 Unix socket 就绪。"""
    socket_path = Path("/tmp/.X11-unix") / f"X{display.lstrip(':')}"
    for _ in range(20):
        if process.poll() is not None:
            return False
        if socket_path.exists():
            return True
        time.sleep(0.1)
    return process.poll() is None


def _retain_auto_xvfb() -> None:
    global _AUTO_XVFB_REF_COUNT
    _AUTO_XVFB_REF_COUNT += 1


def _release_auto_xvfb() -> None:
    global _AUTO_XVFB_REF_COUNT
    if _AUTO_XVFB_REF_COUNT > 0:
        _AUTO_XVFB_REF_COUNT -= 1
    if _AUTO_XVFB_REF_COUNT == 0:
        _stop_auto_xvfb()


def _stop_auto_xvfb() -> None:
    """关闭本进程自动启动的 Xvfb。"""
    global _AUTO_XVFB_PROCESS, _AUTO_XVFB_DISPLAY, _AUTO_XVFB_REF_COUNT
    process = _AUTO_XVFB_PROCESS
    display = _AUTO_XVFB_DISPLAY
    _AUTO_XVFB_PROCESS = None
    _AUTO_XVFB_DISPLAY = None
    _AUTO_XVFB_REF_COUNT = 0
    if display and os.environ.get("DISPLAY") == display:
        os.environ.pop("DISPLAY", None)
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


atexit.register(_stop_auto_xvfb)


async def _trigger_request(page, *, endpoint: str, method: str, payload: dict[str, Any]):
    try:
        async with page.expect_response(lambda response: _same_endpoint(response.url, endpoint), timeout=15000) as info:
            if not await _click_query_button(page):
                raise _NoQueryButtonError()
        return await info.value
    except Exception:
        return await _request_with_browser_context(page, endpoint=endpoint, method=method, payload=payload)


async def _request_with_browser_context(page, *, endpoint: str, method: str, payload: dict[str, Any]):
    """使用浏览器上下文请求接口，复用当前 profile 的 cookie，避免页面内 fetch 被拦截。"""
    headers = _context_request_headers(page.url, method=method)
    try:
        if method == "GET":
            return await page.context.request.get(
                _url_with_query(endpoint, payload),
                headers=headers,
                timeout=DEFAULT_TIMEOUT_MS,
                fail_on_status_code=False,
            )
        if method == "FORM":
            return await page.context.request.post(
                _absolute_url(endpoint),
                headers=headers,
                data=urlencode(_query_pairs(payload), doseq=True),
                timeout=DEFAULT_TIMEOUT_MS,
                fail_on_status_code=False,
            )
        return await page.context.request.post(
            _absolute_url(endpoint),
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            timeout=DEFAULT_TIMEOUT_MS,
            fail_on_status_code=False,
        )
    except Exception as exc:
        raise SellerSpriteApiError(
            "卖家精灵浏览器上下文请求失败",
            response_excerpt=(f"method={method} endpoint={endpoint}\n{exc}")[:1000],
            api_code="ERR_BROWSER_CONTEXT_REQUEST_FAILED",
            api_message="浏览器已打开并登录，但通过浏览器上下文发起接口请求失败。",
        ) from exc


def _context_request_headers(referer: str, *, method: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE_URL,
        "Referer": referer if referer.startswith("http") else DEFAULT_PAGE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    if method == "FORM":
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif method != "GET":
        headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


async def _click_query_button(page) -> bool:
    selectors = [
        "button:visible:has-text('立即查询')",
        "[role='button']:visible:has-text('立即查询')",
        ".el-button:visible:has-text('立即查询')",
        ".ant-btn:visible:has-text('立即查询')",
        "button:visible:has-text('开始筛选')",
        "[role='button']:visible:has-text('开始筛选')",
        ".el-button:visible:has-text('开始筛选')",
        ".ant-btn:visible:has-text('开始筛选')",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=800):
                await locator.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


async def _trigger_fetch(page, *, endpoint: str, method: str) -> None:
    try:
        await page.evaluate(
            """
            async ({ url, method }) => {
              const init = {
                method: method === 'GET' ? 'GET' : 'POST',
                credentials: 'include',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
              };
              if (method === 'FORM') {
                init.headers['Content-Type'] = 'application/x-www-form-urlencoded';
                init.body = '_ops_probe=1';
              } else if (method !== 'GET') {
                init.headers['Content-Type'] = 'application/json;charset=UTF-8';
                init.body = JSON.stringify({ _ops_probe: true });
              }
              const response = await fetch(url, init);
              await response.text();
            }
            """,
            {"url": _absolute_url(endpoint), "method": method},
        )
    except Exception as exc:
        if _looks_like_browser_fetch_failed(exc):
            raise SellerSpriteApiError(
                "卖家精灵浏览器接口临时不可用：页面内 fetch 失败，请稍后重试",
                response_excerpt=(f"method={method} endpoint={endpoint}\n{exc}")[:1000],
                api_code="ERR_BROWSER_FETCH_FAILED",
                api_message="页面内 fetch 被浏览器判定失败，通常是卖家精灵接口临时不可达、网关异常或网络抖动。",
            ) from exc
        raise


def _looks_like_browser_fetch_failed(exc: Exception) -> bool:
    message = str(exc)
    return "Failed to fetch" in message and ("Page.evaluate" in message or "TypeError" in message)


async def _prepare_page(page) -> None:
    """执行轻量页面准备动作。"""
    await page.wait_for_timeout(800)
    viewport = page.viewport_size or {"width": 1440, "height": 1000}
    await page.mouse.move(
        viewport["width"] * random.uniform(0.45, 0.65),
        viewport["height"] * random.uniform(0.25, 0.45),
    )
    blank_point = await _find_blank_point(page)
    await page.mouse.click(blank_point["x"], blank_point["y"])
    scroll_down = random.randint(260, 520)
    scroll_up = random.randint(120, min(scroll_down - 60, 260))
    await page.evaluate(
        "distance => window.scrollBy(0, Math.min(distance, document.body.scrollHeight || distance))",
        scroll_down,
    )
    await page.wait_for_timeout(random.randint(400, 800))
    await page.evaluate("distance => window.scrollBy(0, -distance)", scroll_up)
    await page.wait_for_timeout(random.randint(250, 500))


async def _find_blank_point(page) -> dict[str, float]:
    viewport = page.viewport_size or {"width": 1440, "height": 1000}
    width = viewport["width"]
    height = viewport["height"]
    candidates = [
        [width * 0.5, height * 0.12],
        [width * 0.72, height * 0.16],
        [width * 0.28, height * 0.16],
        [width * 0.5, height * 0.88],
        [width * 0.8, height * 0.82],
        [width * 0.2, height * 0.82],
    ]
    random.shuffle(candidates)
    point = await page.evaluate(
        """
        points => {
          const blockedSelector = [
            'button', 'a', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[contenteditable="true"]',
            '.el-button', '.ant-btn'
          ].join(',');
          for (const [x, y] of points) {
            const element = document.elementFromPoint(x, y);
            if (!element || element.closest(blockedSelector)) continue;
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            if (rect.width < 20 || rect.height < 20 || style.pointerEvents === 'none') continue;
            return { x, y };
          }
          return null;
        }
        """,
        candidates,
    )
    if isinstance(point, dict) and "x" in point and "y" in point:
        return {"x": float(point["x"]), "y": float(point["y"])}
    return {
        "x": width * random.uniform(0.35, 0.65),
        "y": height * random.uniform(0.08, 0.18),
    }


async def _parse_response(response, *, method: str, root_dir: Path, section: str) -> dict[str, Any]:
    if method == "FORM":
        text = await response.text()
        if _looks_like_session_expired(response.url, response.status, text):
            raise SellerSpriteApiError(
                "卖家精灵浏览器登录态失效",
                status_code=response.status,
                response_excerpt=text[:1000],
                api_code="ERR_GLOBAL_SESSION_EXPIRED",
            )
        if response.status >= 400:
            raise SellerSpriteApiError("卖家精灵浏览器表单请求失败", status_code=response.status, response_excerpt=text[:1000])
        response_html_path = root_dir / ("response.html" if section == "main" else f"{section}.html")
        response_html_path.write_text(text, encoding="utf-8")
        rows = parse_market_research_html(text)
        return {
            "code": "OK",
            "data": {"items": rows},
            "response_html_path": str(response_html_path),
            "response_html_length": len(text),
        }
    text = await response.text()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        api_code = "ERR_GLOBAL_SESSION_EXPIRED" if _looks_like_session_expired(response.url, response.status, text) else None
        raise SellerSpriteApiError(
            "卖家精灵浏览器登录态失效" if api_code else "卖家精灵浏览器接口返回非 JSON",
            status_code=response.status,
            response_excerpt=text[:1000],
            api_code=api_code,
        ) from exc
    if response.status >= 400:
        raise SellerSpriteApiError(
            "卖家精灵浏览器接口请求失败",
            status_code=response.status,
            response_excerpt=text[:1000],
            api_code="ERR_GLOBAL_SESSION_EXPIRED" if response.status in {401, 403} else None,
        )
    code = payload.get("code") if isinstance(payload, dict) else None
    if code and code != "OK":
        api_message = payload.get("message") or payload.get("msg") if isinstance(payload, dict) else None
        raise SellerSpriteApiError(
            f"卖家精灵浏览器接口返回错误：{code}",
            status_code=response.status,
            response_excerpt=text[:1000],
            api_code=str(code),
            api_message=str(api_message) if api_message else None,
        )
    return payload


async def _detect_logged_in(page) -> bool:
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    if "/w/user/login" in page.url or "/cn/w/user/login" in page.url:
        return False
    if await _homepage_requires_login(page) or await _has_visible_text(page, "游客"):
        return False
    return True


async def _homepage_requires_login(page) -> bool:
    return (
        await _has_visible_text(page, "未登录")
        or await _has_visible_text(page, "登录/注册")
        or await _has_visible_text(page, "登录 / 注册")
    )


async def _has_visible_text(page, text: str) -> bool:
    locator = page.get_by_text(text).first
    try:
        return await locator.is_visible(timeout=1000)
    except Exception:
        return False


async def _click_account_login_tab(page) -> None:
    selectors = [
        "text=账号登录",
        "[role='tab']:visible:has-text('账号登录')",
        "a:visible:has-text('账号登录')",
        "button:visible:has-text('账号登录')",
        "div:visible:has-text('账号登录')",
    ]
    await _click_first_visible(page, selectors, timeout=5000, optional=True)


async def _click_login_submit(page) -> None:
    selectors = [
        "button:visible:has-text('立即登录')",
        "[role='button']:visible:has-text('立即登录')",
        "a:visible:has-text('立即登录')",
        "div:visible:has-text('立即登录')",
        "button:visible:has-text('登录')",
        "button:visible:has-text('登 录')",
    ]
    await _click_first_visible(page, selectors, timeout=15000, optional=False)


async def _click_first_visible(page, selectors: list[str], *, timeout: int, optional: bool) -> bool:
    last_error: Exception | None = None
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=800):
                await locator.click(timeout=timeout)
                return True
        except Exception as exc:
            last_error = exc
            continue
    if optional:
        return False
    if last_error:
        raise last_error
    raise SellerSpriteConfigError("卖家精灵登录页未找到可点击的登录按钮")


def _profile_dir(settings: SellerSpriteSettings, account: SellerSpriteAccount) -> Path:
    key = hashlib.md5(f"{account.name}:{account.username}".encode("utf-8")).hexdigest()[:12]
    safe_name = _slug(account.name or "default")
    return settings.browser_profile_dir / f"{safe_name}-{key}"


def _absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url if url.startswith('/') else '/' + url}"


def _route_pattern(endpoint: str) -> str:
    path = urlparse(_absolute_url(endpoint)).path
    return f"**{path}*"


def _same_endpoint(url: str, endpoint: str) -> bool:
    return urlparse(url).path == urlparse(_absolute_url(endpoint)).path


def _url_with_query(endpoint: str, payload: dict[str, Any]) -> str:
    parsed = urlparse(_absolute_url(endpoint))
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs.extend(_query_pairs(payload))
    return urlunparse(parsed._replace(query=urlencode(pairs, doseq=True)))


def _query_pairs(payload: dict[str, Any]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, list):
            pairs.extend((key, _query_value(item)) for item in value)
        else:
            pairs.append((key, _query_value(value)))
    return pairs


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _callback_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _looks_like_session_expired(url: str, status: int, text: str) -> bool:
    normalized = text[:1000].lower()
    return status in {301, 302, 303, 307, 308} or "user/login" in url.lower() or "user/login" in normalized


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:40] or "default"
