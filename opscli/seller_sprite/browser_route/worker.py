"""基于 Playwright browser-route 的卖家精灵接口执行器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
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
LOGIN_URL = "https://www.sellersprite.com/w/user/login"
DEFAULT_PAGE_URL = "https://www.sellersprite.com/v3/keyword-miner/"
DEFAULT_TIMEOUT_MS = 120000


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
    task_interval_seconds: float = 8.0
    cooldown_seconds: float = 120.0


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

    async def submit(self, request: BrowserRouteRequest) -> BrowserRouteResult:
        """入队并顺序执行任务。"""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(_QueuedTask(request=request, future=future))
        await self._drain_queue()
        return await future

    async def close(self) -> None:
        """关闭浏览器上下文。"""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _drain_queue(self) -> None:
        async with self._drain_lock:
            while not self._queue.empty():
                task = await self._queue.get()
                try:
                    result = await self._run_one(task.request)
                except Exception as exc:
                    self._cooldown_until = max(
                        self._cooldown_until,
                        time.monotonic() + max(task.request.cooldown_seconds, 0.0),
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
        await self._wait_for_cooldown(request, warnings)
        await self._wait_for_rate_limit(request, warnings)
        page = await self._ensure_page(request.account)
        login = await self._open_referer_and_login(page, request)
        if request.page_prepare:
            await _prepare_page(page)
        response = await self._execute_route_fetch(
            page=page,
            method=request.method,
            endpoint=request.endpoint,
            payload=request.payload,
            root_dir=request.root_dir,
            section="main",
        )
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
        interval = max(request.task_interval_seconds, 0.0)
        if not self._last_finished_at or interval <= 0:
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
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise SellerSpriteConfigError(
                "缺少 playwright 依赖，请安装 `pip install opscli[seller-sprite]` 并执行 "
                "`python -m playwright install chromium --no-shell`"
            ) from exc
        if not self._playwright:
            self._playwright = await async_playwright().start()
        profile_dir = _profile_dir(self.settings, account)
        profile_dir.mkdir(parents=True, exist_ok=True)
        launch_options: dict[str, Any] = {
            "headless": self.settings.browser_headless,
            "viewport": {"width": 1440, "height": 1000},
            "locale": "zh-CN",
            "accept_downloads": True,
        }
        if self.settings.browser_channel:
            launch_options["channel"] = self.settings.browser_channel
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def _open_referer_and_login(self, page, request: BrowserRouteRequest) -> dict[str, Any]:
        referer = request.referer or DEFAULT_PAGE_URL
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
            "account": request.account.to_public_dict(),
        }

    async def _login_with_account(self, page, account: SellerSpriteAccount, *, callback: str) -> None:
        callback_url = _callback_path(callback)
        await page.goto(f"{LOGIN_URL}?callback={quote(callback_url)}", wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        await page.wait_for_timeout(1000)
        password_input = page.locator("input[type='password']:visible").first
        await password_input.wait_for(state="visible", timeout=15000)
        username_input = page.locator(
            "input[placeholder*='手机号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='邮箱']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='账号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='用户名']:visible:not([readonly]):not([disabled]), "
            "input[type='email']:visible:not([readonly]):not([disabled]), "
            "input[type='text']:visible:not([readonly]):not([disabled])"
        ).first
        await username_input.fill(account.username)
        await password_input.fill(account.password)
        await page.locator(
            "button:visible:has-text('登录'), button:visible:has-text('登 录'), button:visible:has-text('立即登录')"
        ).first.click(timeout=15000)
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
            response = await _trigger_request(page, endpoint=endpoint, method=normalized_method)
            return await _parse_response(response, method=normalized_method, root_dir=root_dir, section=section)
        finally:
            await page.unroute(pattern, _handle)


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


async def _trigger_request(page, *, endpoint: str, method: str):
    try:
        async with page.expect_response(lambda response: _same_endpoint(response.url, endpoint), timeout=15000) as info:
            if not await _click_query_button(page):
                raise _NoQueryButtonError()
        return await info.value
    except Exception:
        async with page.expect_response(lambda response: _same_endpoint(response.url, endpoint), timeout=DEFAULT_TIMEOUT_MS) as info:
            await _trigger_fetch(page, endpoint=endpoint, method=method)
        return await info.value


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
    if await _has_visible_text(page, "未登录") or await _has_visible_text(page, "游客"):
        return False
    return True


async def _has_visible_text(page, text: str) -> bool:
    locator = page.get_by_text(text).first
    try:
        return await locator.is_visible(timeout=1000)
    except Exception:
        return False


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