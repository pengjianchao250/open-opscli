"""基于 Playwright browser-route 的卖家精灵接口执行器。"""

from __future__ import annotations

import asyncio
import atexit
import base64
import hashlib
import importlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.api.keyword_research import parse_keyword_research_html
from opscli.seller_sprite.api.market_research import parse_market_research_html
from opscli.seller_sprite.config import DEFAULT_OUTPUT_DIR, SellerSpriteSettings
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteApiError,
    SellerSpriteAuthenticationError,
    SellerSpriteConfigError,
)
from opscli.seller_sprite.browser_route.ocr import create_captcha_ocr_provider


BASE_URL = "https://www.sellersprite.com"
HOME_URL = "https://www.sellersprite.com/"
LOGIN_URL = "https://www.sellersprite.com/cn/w/user/login"
DEFAULT_PAGE_URL = "https://www.sellersprite.com/v3/keyword-miner/"
DEFAULT_TIMEOUT_MS = 120000
LOGIN_SUCCESS_TIMEOUT_MS = 15000
LOGIN_SETTLE_TIMEOUT_MS = 500
TEXT_DETECT_TIMEOUT_MS = 300
ROBOT_CAPTCHA_SETTLE_TIMEOUT_MS = 800
ROBOT_CAPTCHA_DIALOG_SELECTORS = [
    "[role='dialog'][aria-label='机器人检测']",
    ".el-dialog:has-text('机器人检测')",
]
logger = logging.getLogger(__name__)
KEYWORD_COMPARISON_DIAGNOSTIC_TAG = "[SELLER_SPRITE_KC_DIAG]"
ROBOT_CAPTCHA_IMAGE_SELECTORS = [
    "img[src^='data:image/gif;base64,']",
    "img[src^='data:image/png;base64,']",
    "img[src^='data:image/jpeg;base64,']",
    "img:visible",
]
ROBOT_CAPTCHA_INPUT_SELECTORS = [
    "input.el-input__inner[type='text']",
    "input[type='text']:visible",
]
ROBOT_CAPTCHA_CONFIRM_SELECTORS = [
    "button.el-button--primary[type='button']",
    "button:visible:has-text('确 定')",
    "button:visible:has-text('确定')",
]
XVFB_DISPLAY_CANDIDATES = range(99, 110)
TASK_INTERVAL_RANGE_SECONDS = (1.0, 5.0)
NETWORK_COOLDOWN_RANGE_SECONDS = (3.0, 5.0)
RISK_COOLDOWN_RANGE_SECONDS = (15.0, 20.0)
WINDOWS_COMPAT_EXPORT_PATH_LIMIT = 240
# XLSX 是 ZIP 容器；128 字节下限用于拦截短错误页，同时兼容最小测试工作簿。
MIN_XLSX_CONTENT_LENGTH = 128
# 官网导出实测会返回标准 XLSX、旧 Excel 或二进制流 MIME，统一按白名单接收。
XLSX_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msexcel",
        "application/vnd.ms-excel",
        "application/octet-stream",
    }
)
# Windows 保留设备名即使带扩展名也不能作为文件名。
WINDOWS_RESERVED_FILENAME_PATTERN = re.compile(
    r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]",
    re.I,
)

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
    cooldown_seconds: float = 10.0
    replay_safe: bool = True
    # 流量词对比页面弹窗的变体选择，默认使用畅销变体拓词。
    keyword_comparison_variant: str = "sell_well"
    # 拓展流量词页面弹窗的变体选择，默认使用全部变体拓词。
    traffic_extend_variant: str = "all"


@dataclass
class BrowserRouteResult:
    """browser-route 执行结果。"""

    login: dict[str, Any]
    response: dict[str, Any]
    high_frequency_response: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    effective_asin_list: list[str] | None = None


@dataclass
class _QueuedTask:
    request: BrowserRouteRequest
    future: asyncio.Future


class BrowserRouteWorkerClosedError(RuntimeError):
    """表示任务提交时目标 browser worker 已进入关闭流程。"""


def _record_timing(
    timings: list[dict[str, Any]] | None,
    request: BrowserRouteRequest | None,
    stage: str,
    started_at: float,
    **details: Any,
) -> dict[str, Any]:
    """记录 browser-route 阶段耗时。"""
    elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
    event: dict[str, Any] = {"stage": stage, "elapsed_ms": elapsed_ms}
    safe_details = {key: _safe_timing_value(value) for key, value in details.items() if value is not None}
    event.update(safe_details)
    if timings is not None:
        timings.append(event)
    return event


def _safe_timing_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_timing_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_timing_value(item) for item in value]
    return str(value)


class SellerSpriteBrowserRouteWorker:
    """同账号串行消费 browser-route 任务，复用浏览器上下文。"""

    def __init__(
        self,
        *,
        settings: SellerSpriteSettings,
        account: SellerSpriteAccount,
        state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """创建账号隔离 worker。

        参数：
            settings: browser-route 运行配置。
            account: 该 worker 独占的卖家精灵账号。
            state_listener: 接收脱敏会话状态变化的同步监听器。
            clock: 用于生命周期判断的单调时钟，测试可注入。

        返回：
            无。
        """
        self.settings = settings
        self.account = account
        self._clock = clock
        self._state_listener = state_listener
        self._queue: asyncio.Queue[_QueuedTask] = asyncio.Queue()
        # 生命周期锁只保护“是否接受新任务”的切换；绝不与 drain 锁同时持有，避免锁序反转。
        self._lifecycle_lock = asyncio.Lock()
        self._drain_lock = asyncio.Lock()
        self._reservation_count = 0
        self._closing = False
        self._closed = False
        self._last_finished_at = 0.0
        self._opened_at = 0.0
        self._task_count = 0
        self._session_state = "registered"
        self._cooldown_until = 0.0
        self._playwright = None
        self._context = None
        self._page = None
        self._auto_xvfb_attached = False
        self._automatic_reap_task: asyncio.Task | None = None
        self._notify_state_change(
            previous_state="none",
            state="registered",
            reason="worker_registered",
        )

    async def submit(self, request: BrowserRouteRequest) -> BrowserRouteResult:
        """入队并顺序执行任务。

        参数：
            request: 待执行的 browser-route 请求。

        返回：
            browser-route 请求结果。

        异常：
            BrowserRouteWorkerClosedError: worker 已开始关闭，调用方应获取新 worker 重试。
            Exception: 透传具体任务执行异常。
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        # 先在生命周期锁内完成入队；关闭方一旦取得该锁并标记 closing，旧引用便不能复活会话。
        async with self._lifecycle_lock:
            if self._closing or self._closed:
                raise BrowserRouteWorkerClosedError("browser worker 已进入关闭流程")
            await self._queue.put(_QueuedTask(request=request, future=future))
        await self._drain_queue()
        return await future

    @property
    def is_busy(self) -> bool:
        """判断当前 worker 是否正在执行、排队或已被任务预留。"""
        return (
            self._reservation_count > 0
            or self._drain_lock.locked()
            or not self._queue.empty()
        )

    @property
    def accepts_tasks(self) -> bool:
        """返回 worker 是否仍接受新任务。"""
        return not self._closing and not self._closed

    def reserve(self) -> bool:
        """为已领取但尚未提交的任务预留会话。

        返回：
            预留成功返回 ``True``；worker 已关闭时返回 ``False``。
        """
        if not self.accepts_tasks:
            return False
        self._reservation_count += 1
        return True

    def release_reservation(self) -> None:
        """释放一次任务预留；重复释放不会产生负数。

        返回：
            无。
        """
        self._reservation_count = max(0, self._reservation_count - 1)
        if self._reservation_count == 0 and self._opened_at and self.accepts_tasks:
            self._schedule_automatic_reap()

    async def close(self, *, reason: str = "manual_close") -> None:
        """等待内部队列排空后关闭浏览器上下文并报告状态。

        参数：
            reason: 关闭或轮换原因。

        返回：
            无。

        异常：
            Exception: 清理任一浏览器资源失败时，在完成其余清理后抛出首个异常。
        """
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
        if self._automatic_reap_task is not None:
            current_task = asyncio.current_task()
            if self._automatic_reap_task is not current_task:
                self._automatic_reap_task.cancel()
            self._automatic_reap_task = None
        errors: list[Exception] = []
        # close 与 drain 使用同一把锁：显式关闭会等待已入队任务完成，周期回收则只会选择非忙 worker。
        async with self._drain_lock:
            # 必须在队列排空后再进入 closing，避免任务收尾把状态从 closing 错误覆盖为 idle。
            closing_state = "recycling" if reason in {"idle_timeout", "max_lifetime"} else "closing"
            self._transition_state(closing_state, reason=reason)
            if self._context:
                try:
                    await self._context.close()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self._context = None
                    self._page = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self._playwright = None
            if self._auto_xvfb_attached:
                try:
                    _release_auto_xvfb()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self._auto_xvfb_attached = False
        self._closed = True
        if errors:
            first_error = errors[0]
            self._transition_state(
                "close_failed",
                reason=reason,
                error_code=type(first_error).__name__,
            )
            self._opened_at = 0.0
            raise first_error
        self._transition_state("closed", reason=reason)
        self._opened_at = 0.0

    async def _drain_queue(self) -> None:
        async with self._drain_lock:
            while not self._queue.empty():
                task = await self._queue.get()
                if self._opened_at:
                    self._transition_state("busy", reason="task_started")
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
                    self._last_finished_at = self._clock()
                    self._task_count += 1
                    self._queue.task_done()
            if self._opened_at:
                self._transition_state("idle", reason="queue_drained")
                self._schedule_automatic_reap()

    def _schedule_automatic_reap(self) -> None:
        """按空闲阈值和剩余最大寿命安排 worker 自回收。"""
        if self._closing or self._closed or not self._opened_at:
            return
        if self._automatic_reap_task is not None:
            self._automatic_reap_task.cancel()
        current = self._clock()
        idle_base = self._last_finished_at or self._opened_at
        idle_remaining = self.settings.browser_idle_ttl_seconds - (current - idle_base)
        lifetime_remaining = self.settings.browser_max_lifetime_seconds - (
            current - self._opened_at
        )
        delay = max(0.0, min(idle_remaining, lifetime_remaining))
        self._automatic_reap_task = asyncio.create_task(
            self._automatic_reap_after(delay),
            name=f"seller-sprite-session-reaper-{self.account.name}",
        )

    async def _automatic_reap_after(self, delay: float) -> None:
        """等待当前最早生命周期阈值，并安全移除和关闭自身。"""
        try:
            await asyncio.sleep(delay)
            reason = self.recycle_reason()
            if reason is None:
                return
            registry_entry = next(
                ((key, worker) for key, worker in _WORKERS.items() if worker is self),
                None,
            )
            if registry_entry is None:
                return
            key, worker = registry_entry
            if _WORKERS.pop(key, None) is not worker:
                return
            await self.close(reason=reason)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            # close_failed 已由状态监听器审计；这里只记录异常类型并避免后台 Task 泄露异常。
            logger.warning(
                "卖家精灵 browser 会话自动回收失败：account=%s error=%s",
                self.account.name,
                type(exc).__name__,
            )


    def mark_session_ready(self, *, context: Any, page: Any) -> None:
        """登记已创建的 browser context/page，并记录首次 ready 状态。

        参数：
            context: 当前持久化浏览器上下文。
            page: 当前复用页面。

        返回：
            无。
        """
        self._context = context
        self._page = page
        if not self._opened_at:
            self._opened_at = self._clock()
            self._transition_state("ready", reason="browser_context_opened")

    def set_state_listener(
        self,
        listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None,
    ) -> None:
        """更新会话状态监听器。

        参数：
            listener: 接收脱敏状态载荷的同步监听器；空值不会覆盖已有监听器。

        返回：
            无。
        """
        if listener is not None:
            self._state_listener = listener

    def session_snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """返回不含凭证的会话生命周期快照。

        参数：
            now: 指定计算时刻；不传则读取注入的单调时钟。

        返回：
            包含状态、会话年龄、空闲时长和任务数的白名单字典。
        """
        current = self._clock() if now is None else now
        idle_base = self._last_finished_at or self._opened_at
        return {
            "state": self._session_state,
            "session_age_seconds": max(0, int(current - self._opened_at)) if self._opened_at else 0,
            "idle_seconds": max(0, int(current - idle_base)) if idle_base else 0,
            "task_count": self._task_count,
            "is_busy": self.is_busy,
            "has_open_session": bool(self._opened_at),
        }

    def recycle_reason(
        self,
        *,
        settings: SellerSpriteSettings | None = None,
        now: float | None = None,
    ) -> str | None:
        """返回当前安全回收原因。

        参数：
            settings: 当前调度器配置，用于配置热更新后的新阈值。
            now: 指定计算时刻。

        返回：
            达到阈值时返回 ``idle_timeout`` 或 ``max_lifetime``；否则返回空。
        """
        snapshot = self.session_snapshot(now=now)
        if not snapshot["has_open_session"] or snapshot["is_busy"]:
            return None
        lifecycle_settings = settings or self.settings
        if snapshot["session_age_seconds"] >= max(1, lifecycle_settings.browser_max_lifetime_seconds):
            return "max_lifetime"
        if snapshot["idle_seconds"] >= max(1, lifecycle_settings.browser_idle_ttl_seconds):
            return "idle_timeout"
        return None

    def _transition_state(self, state: str, *, reason: str, **metadata: Any) -> None:
        """仅在状态真实变化时同步通知生命周期监听器。"""
        previous_state = self._session_state
        if previous_state == state:
            return
        self._session_state = state
        if self._state_listener is None:
            return
        payload = {
            "previous_state": previous_state,
            **self.session_snapshot(),
            "reason": reason,
            **metadata,
        }
        self._state_listener(self.account, payload)

    def _notify_state_change(self, *, previous_state: str, state: str, reason: str) -> None:
        """在初始化阶段直接发送一次状态事件。"""
        if self._state_listener is None:
            return
        payload = {
            "previous_state": previous_state,
            **self.session_snapshot(),
            "state": state,
            "reason": reason,
        }
        self._state_listener(self.account, payload)

    async def _run_one(self, request: BrowserRouteRequest) -> BrowserRouteResult:
        warnings: list[dict[str, Any]] = []
        timings: list[dict[str, Any]] = []
        total_started_at = time.monotonic()
        referer = request.referer or DEFAULT_PAGE_URL
        stage_started_at = time.monotonic()
        await self._wait_for_cooldown(request, warnings)
        _record_timing(timings, request, "wait_for_cooldown", stage_started_at)
        stage_started_at = time.monotonic()
        await self._wait_for_rate_limit(request, warnings)
        _record_timing(timings, request, "wait_for_rate_limit", stage_started_at)
        stage_started_at = time.monotonic()
        had_page = bool(self._page and not self._page.is_closed())
        page = await self._ensure_page(request.account)
        self.mark_session_ready(context=self._context, page=page)
        self._transition_state("busy", reason="task_started")
        _record_timing(
            timings,
            request,
            "ensure_page",
            stage_started_at,
            reused=had_page,
            url=getattr(page, "url", ""),
        )
        stage_started_at = time.monotonic()
        login = await self._open_referer_and_login(page, request, timings=timings)
        _record_timing(
            timings,
            request,
            "open_referer_and_login",
            stage_started_at,
            current_url=getattr(page, "url", ""),
        )
        await self._handle_robot_captcha_if_enabled(
            page,
            request,
            warnings,
            timings,
            stage="after_open_referer",
        )
        if request.page_prepare:
            stage_started_at = time.monotonic()
            await _prepare_page(page)
            _record_timing(timings, request, "page_prepare", stage_started_at)
        else:
            _record_timing(timings, request, "page_prepare", time.monotonic(), skipped=True)
        # 每次重试都从页面真实主请求重新取得畅销变体顺序，禁止复用上次交互状态。
        effective_asin_list: list[str] | None = None
        # 额度型导出没有幂等键；请求发出后结果不明时禁止在当前 worker 内重放。
        for attempt in range(2 if request.replay_safe else 1):
            # 失败尝试即使已经捕获主请求，也不能把其 ASIN 顺序带到下一次结果。
            effective_asin_list = None
            try:
                route_metadata: dict[str, Any] = {}
                stage_started_at = time.monotonic()
                response = await self._execute_route_fetch(
                    page=page,
                    method=request.method,
                    endpoint=request.endpoint,
                    payload=request.payload,
                    root_dir=request.root_dir,
                    section="main",
                    timings=timings,
                    request=request,
                    route_metadata=route_metadata,
                )
                captured_asins = route_metadata.get("asinList")
                if isinstance(captured_asins, list):
                    effective_asin_list = list(captured_asins)
                _record_timing(timings, request, "execute_route_fetch.main", stage_started_at, attempt=attempt + 1)
                if (
                    request.scenario == "association-traffic"
                    and _looks_like_guest_limited_association_response(
                        response,
                        page_size=request.payload.get("pageSize"),
                    )
                ):
                    # 游客接口也返回 code=OK，但固定截断为 20 条；必须按登录失效处理后重试。
                    raise SellerSpriteApiError(
                        "卖家精灵关联流量返回游客限制数据",
                        api_code="ERR_GLOBAL_SESSION_EXPIRED",
                        api_message="检测到每页 20 条的游客响应，已尝试恢复登录态。",
                    )
                break
            except SellerSpriteApiError as exc:
                _record_timing(
                    timings,
                    request,
                    "execute_route_fetch.main_error",
                    stage_started_at,
                    attempt=attempt + 1,
                    api_code=exc.api_code,
                    status_code=exc.status_code,
                )
                if not request.replay_safe:
                    raise
                if exc.is_session_expired():
                    if attempt > 0:
                        raise
                    stage_started_at = time.monotonic()
                    await self._login_with_account(page, request.account, callback=referer, timings=timings, request=request)
                    _record_timing(timings, request, "session_expired_relogin", stage_started_at)
                    stage_started_at = time.monotonic()
                    login = await self._open_referer_and_login(page, request, timings=timings)
                    _record_timing(timings, request, "session_expired_reopen", stage_started_at, current_url=getattr(page, "url", ""))
                    await self._handle_robot_captcha_if_enabled(
                        page,
                        request,
                        warnings,
                        timings,
                        stage="after_session_expired_reopen",
                    )
                    if request.page_prepare:
                        stage_started_at = time.monotonic()
                        await _prepare_page(page)
                        _record_timing(timings, request, "session_expired_page_prepare", stage_started_at)
                    continue
                if exc.api_code in {
                    "ERR_KEYWORD_COMPARISON_REQUEST_MISSED",
                    "ERR_KEYWORD_COMPARISON_ENDPOINT_CHANGED",
                    "ERR_KEYWORD_COMPARISON_RESPONSE_MISSED",
                }:
                    # 变体按钮已点击，远端查询结果未知；禁止验证码恢复分支重放完整查询。
                    raise
                if attempt == 0:
                    captcha_result = await self._handle_robot_captcha_if_enabled(
                        page,
                        request,
                        warnings,
                        timings,
                        stage="after_main_error",
                    )
                    if captcha_result:
                        if request.page_prepare:
                            stage_started_at = time.monotonic()
                            await _prepare_page(page)
                            _record_timing(timings, request, "robot_captcha_page_prepare", stage_started_at)
                        continue
                raise
        high_frequency_response = None
        if request.high_frequency_endpoint and request.high_frequency_payload:
            try:
                stage_started_at = time.monotonic()
                if request.scenario == "keyword-miner":
                    # 页面一次查询已完成主词交互；高频词直接复用浏览器登录态，避免重复点击和等待页面响应。
                    high_frequency_response = await self._execute_context_fetch(
                        page=page,
                        method="POST",
                        endpoint=request.high_frequency_endpoint,
                        payload=request.high_frequency_payload,
                        root_dir=request.root_dir,
                        section="high_frequency",
                        timings=timings,
                        request=request,
                    )
                else:
                    high_frequency_response = await self._execute_route_fetch(
                        page=page,
                        method="POST",
                        endpoint=request.high_frequency_endpoint,
                        payload=request.high_frequency_payload,
                        root_dir=request.root_dir,
                        section="high_frequency",
                        timings=timings,
                        request=request,
                    )
                _record_timing(timings, request, "execute_route_fetch.high_frequency", stage_started_at)
            except SellerSpriteApiError as exc:
                _record_timing(
                    timings,
                    request,
                    "execute_route_fetch.high_frequency_error",
                    stage_started_at,
                    api_code=exc.api_code,
                    status_code=exc.status_code,
                )
                warnings.append(
                    {
                        "stage": "high_frequency",
                        "message": "browser-route 高频词接口请求失败，主表继续导出",
                        "error": exc.to_dict(),
                    }
                )
        _record_timing(timings, request, "total", total_started_at)
        warnings.append(
            {
                "stage": "browser_route_timing",
                "message": "卖家精灵 browser-route 阶段耗时诊断",
                "timings": timings,
            }
        )
        return BrowserRouteResult(
            login=login,
            response=response,
            high_frequency_response=high_frequency_response,
            warnings=warnings,
            effective_asin_list=effective_asin_list,
        )

    async def fetch_listing_analysis_report(
        self,
        *,
        task_id: str,
        root_dir: Path,
        page_prepare: bool = True,
        task_interval_seconds: float = 5.0,
        cooldown_seconds: float = 10.0,
    ) -> BrowserRouteResult:
        """打开 Listing Analysis 报告详情页并捕获结构化结果。

        参数：
            task_id: Listing Analysis 远端任务标识。
            root_dir: 原始响应和诊断文件目录。
            page_prepare: 是否执行页面准备脚本。
            task_interval_seconds: 同账号任务间隔上限。
            cooldown_seconds: 风控或网络失败冷却上限。

        返回：
            报告页捕获结果和诊断警告。

        异常：
            BrowserRouteWorkerClosedError: worker 已进入关闭流程。
            Exception: 透传登录、验证码或报告捕获异常。
        """
        async with self._lifecycle_lock:
            if self._closing or self._closed:
                raise BrowserRouteWorkerClosedError("browser worker 已进入关闭流程")
        try:
            return await self._fetch_listing_analysis_report_once(
                task_id=task_id,
                root_dir=root_dir,
                page_prepare=page_prepare,
                task_interval_seconds=task_interval_seconds,
                cooldown_seconds=cooldown_seconds,
            )
        finally:
            # 成功和失败都形成任务边界，避免异常路径永久停在 busy 且没有自回收计时器。
            self._last_finished_at = self._clock()
            self._task_count += 1
            if self._opened_at:
                self._transition_state("idle", reason="queue_drained")
                self._schedule_automatic_reap()

    async def _fetch_listing_analysis_report_once(
        self,
        *,
        task_id: str,
        root_dir: Path,
        page_prepare: bool,
        task_interval_seconds: float,
        cooldown_seconds: float,
    ) -> BrowserRouteResult:
        """在账号 drain 锁内执行一次 Listing Analysis 报告捕获。"""
        request = BrowserRouteRequest(
            scenario="listing-analysis",
            method="PAGE_CAPTURE",
            endpoint="/v3/api/competing-lookup",
            payload={},
            referer="https://www.sellersprite.com/v3/ai-history?module=LA",
            account=self.account,
            root_dir=root_dir,
            page_prepare=page_prepare,
            task_interval_seconds=task_interval_seconds,
            cooldown_seconds=cooldown_seconds,
        )
        warnings: list[dict[str, Any]] = []
        timings: list[dict[str, Any]] = []
        total_started_at = time.monotonic()
        async with self._drain_lock:
            stage_started_at = time.monotonic()
            await self._wait_for_cooldown(request, warnings)
            _record_timing(timings, request, "wait_for_cooldown", stage_started_at)
            stage_started_at = time.monotonic()
            await self._wait_for_rate_limit(request, warnings)
            _record_timing(timings, request, "wait_for_rate_limit", stage_started_at)
            had_page = bool(self._page and not self._page.is_closed())
            stage_started_at = time.monotonic()
            page = await self._ensure_page(self.account)
            self.mark_session_ready(context=self._context, page=page)
            self._transition_state("busy", reason="task_started")
            _record_timing(timings, request, "ensure_page", stage_started_at, reused=had_page)
            stage_started_at = time.monotonic()
            login = await self._open_referer_and_login(page, request, timings=timings)
            _record_timing(timings, request, "open_referer_and_login", stage_started_at, current_url=getattr(page, "url", ""))
            await self._handle_robot_captcha_if_enabled(
                page,
                request,
                warnings,
                timings,
                stage="before_listing_analysis_report",
            )
            if page_prepare:
                stage_started_at = time.monotonic()
                await _prepare_page(page)
                _record_timing(timings, request, "page_prepare", stage_started_at)
            report_url = _listing_analysis_report_url(task_id)
            # 报告页可能在任务生成期间失效，重新登录并恢复页面后仅重试一次捕获。
            for attempt in range(2):
                try:
                    stage_started_at = time.monotonic()
                    response = await _open_listing_analysis_report_and_capture(
                        page,
                        task_id=task_id,
                        report_url=report_url,
                        root_dir=root_dir,
                    )
                    _record_timing(
                        timings,
                        request,
                        "listing_analysis_report.capture",
                        stage_started_at,
                        attempt=attempt + 1,
                    )
                    break
                except SellerSpriteApiError as exc:
                    _record_timing(
                        timings,
                        request,
                        "listing_analysis_report.capture_error",
                        stage_started_at,
                        attempt=attempt + 1,
                        api_code=exc.api_code,
                        status_code=exc.status_code,
                    )
                    if not exc.is_session_expired() or attempt > 0:
                        raise
                    stage_started_at = time.monotonic()
                    await self._login_with_account(
                        page,
                        request.account,
                        callback=request.referer or DEFAULT_PAGE_URL,
                        timings=timings,
                        request=request,
                    )
                    _record_timing(timings, request, "listing_analysis_report.session_expired_relogin", stage_started_at)
                    stage_started_at = time.monotonic()
                    login = await self._open_referer_and_login(page, request, timings=timings)
                    _record_timing(
                        timings,
                        request,
                        "listing_analysis_report.session_expired_reopen",
                        stage_started_at,
                        current_url=getattr(page, "url", ""),
                    )
                    await self._handle_robot_captcha_if_enabled(
                        page,
                        request,
                        warnings,
                        timings,
                        stage="after_listing_analysis_report_session_expired_reopen",
                    )
                    if page_prepare:
                        stage_started_at = time.monotonic()
                        await _prepare_page(page)
                        _record_timing(
                            timings,
                            request,
                            "listing_analysis_report.session_expired_page_prepare",
                            stage_started_at,
                        )
                except Exception as exc:
                    if await _has_visible_text(page, "正在分析中"):
                        response = {
                            "code": "OK",
                            "success": True,
                            "data": {
                                "taskId": task_id,
                                "taskStatus": "RUNNING",
                                "analyzing": True,
                            },
                        }
                        _record_timing(
                            timings,
                            request,
                            "listing_analysis_report.analyzing",
                            stage_started_at,
                            error=type(exc).__name__,
                        )
                        break
                    raise SellerSpriteApiError(
                        "卖家精灵 Listing Analysis 报告页未捕获 competing-lookup 结构化数据",
                        response_excerpt=(f"task_id={task_id} url={report_url}\n{exc}")[:1000],
                        api_code="ERR_LISTING_ANALYSIS_REPORT_CAPTURE_MISSED",
                    ) from exc
            _record_timing(timings, request, "total", total_started_at)
            warnings.append(
                {
                    "stage": "browser_route_timing",
                    "message": "卖家精灵 Listing Analysis 报告页 browser-route 阶段耗时诊断",
                    "timings": timings,
                }
            )
            return BrowserRouteResult(login=login, response=response, warnings=warnings)

    async def _handle_robot_captcha_if_enabled(
        self,
        page,
        request: BrowserRouteRequest,
        warnings: list[dict[str, Any]],
        timings: list[dict[str, Any]],
        *,
        stage: str,
    ) -> dict[str, Any] | None:
        stage_started_at = time.monotonic()
        try:
            result = await _solve_robot_image_captcha(
                page,
                settings=self.settings,
                stage=stage,
            )
        except Exception as exc:
            _record_timing(
                timings,
                request,
                f"robot_captcha.{stage}",
                stage_started_at,
                enabled=self.settings.browser_captcha_ocr_enabled,
                error=type(exc).__name__,
            )
            raise
        _record_timing(
            timings,
            request,
            f"robot_captcha.{stage}",
            stage_started_at,
            enabled=self.settings.browser_captcha_ocr_enabled,
            detected=bool(result),
            attempts=result.get("attempts") if result else None,
            provider=result.get("provider") if result else None,
        )
        if not result:
            return None
        warnings.append(
            {
                "stage": "robot_captcha",
                "message": "卖家精灵机器人检测验证码已通过 ddddocr 尝试处理",
                "trigger_stage": stage,
                "provider": result["provider"],
                "attempts": result["attempts"],
            }
        )
        return result

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
        context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        self.mark_session_ready(context=context, page=page)
        return self._page

    async def _open_referer_and_login(
        self,
        page,
        request: BrowserRouteRequest,
        timings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        referer = request.referer or DEFAULT_PAGE_URL
        just_logged_in = False
        if _is_login_url(page.url):
            stage_started_at = time.monotonic()
            await self._login_with_account(page, request.account, callback=referer, timings=timings, request=request)
            _record_timing(timings, request, "login_from_login_url", stage_started_at, current_url=page.url)
            just_logged_in = True
        if _same_page_url(page.url, referer):
            if not just_logged_in:
                stage_started_at = time.monotonic()
                await page.reload(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                _record_timing(timings, request, "referer_reload", stage_started_at, current_url=page.url)
                stage_started_at = time.monotonic()
                await page.wait_for_timeout(1500)
                _record_timing(timings, request, "referer_settle", stage_started_at, reason="reload")
            else:
                _record_timing(timings, request, "referer_reload", time.monotonic(), skipped=True, reason="just_logged_in")
        else:
            stage_started_at = time.monotonic()
            await page.goto(referer, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            _record_timing(timings, request, "referer_goto", stage_started_at, current_url=page.url)
            stage_started_at = time.monotonic()
            await page.wait_for_timeout(1500)
            _record_timing(timings, request, "referer_settle", stage_started_at, reason="goto")
        stage_started_at = time.monotonic()
        logged_in = await _detect_logged_in(page)
        _record_timing(timings, request, "detect_logged_in.initial", stage_started_at, logged_in=logged_in)
        if not logged_in:
            stage_started_at = time.monotonic()
            await self._login_with_account(page, request.account, callback=referer, timings=timings, request=request)
            _record_timing(timings, request, "login_after_referer", stage_started_at, current_url=page.url)
            if not _same_page_url(page.url, referer):
                stage_started_at = time.monotonic()
                await page.goto(referer, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                _record_timing(timings, request, "referer_goto_after_login", stage_started_at, current_url=page.url)
                stage_started_at = time.monotonic()
                await page.wait_for_timeout(1500)
                _record_timing(timings, request, "referer_settle_after_login", stage_started_at)
        stage_started_at = time.monotonic()
        logged_in = await _detect_logged_in(page)
        _record_timing(timings, request, "detect_logged_in.final", stage_started_at, logged_in=logged_in)
        if not logged_in:
            raise SellerSpriteAuthenticationError(
                "卖家精灵浏览器登录失败，请检查账号或浏览器 profile 登录状态"
            )
        return self._login_snapshot(page, request, logged_in=logged_in)

    def _login_snapshot(
        self,
        page,
        request: BrowserRouteRequest,
        *,
        logged_in: bool,
    ) -> dict[str, Any]:
        """返回当前 browser-route 会话的脱敏登录摘要。"""
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

    async def _login_with_account(
        self,
        page,
        account: SellerSpriteAccount,
        *,
        callback: str,
        timings: list[dict[str, Any]] | None = None,
        request: BrowserRouteRequest | None = None,
    ) -> None:
        callback_url = _callback_path(callback)
        stage_started_at = time.monotonic()
        await page.goto(
            f"{LOGIN_URL}?callback={quote(callback_url)}",
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )
        _record_timing(timings, request, "login.goto", stage_started_at, current_url=page.url)
        stage_started_at = time.monotonic()
        await page.wait_for_timeout(1000)
        _record_timing(timings, request, "login.page_settle", stage_started_at)
        stage_started_at = time.monotonic()
        logged_in = await _detect_logged_in(page)
        _record_timing(timings, request, "login.detect_existing", stage_started_at, logged_in=logged_in)
        if logged_in:
            return
        stage_started_at = time.monotonic()
        await _click_account_login_tab(page)
        _record_timing(timings, request, "login.click_account_tab", stage_started_at)
        password_input = page.locator("input[type='password']:visible").first
        try:
            stage_started_at = time.monotonic()
            await password_input.wait_for(state="visible", timeout=5000)
            _record_timing(timings, request, "login.wait_password_input", stage_started_at)
        except Exception as exc:
            _record_timing(timings, request, "login.wait_password_input_error", stage_started_at)
            stage_started_at = time.monotonic()
            logged_in = await _detect_logged_in(page)
            _record_timing(timings, request, "login.detect_after_password_missing", stage_started_at, logged_in=logged_in)
            if logged_in:
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
        stage_started_at = time.monotonic()
        await username_input.fill(account.username)
        await password_input.fill(account.password)
        _record_timing(timings, request, "login.fill_credentials", stage_started_at)
        stage_started_at = time.monotonic()
        await _click_login_submit(page)
        _record_timing(timings, request, "login.click_submit", stage_started_at)
        stage_started_at = time.monotonic()
        await _wait_for_login_success(page, callback=callback)
        _record_timing(timings, request, "login.wait_success", stage_started_at, current_url=page.url)

    async def _execute_context_fetch(
        self,
        *,
        page,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
        root_dir: Path,
        section: str,
        timings: list[dict[str, Any]] | None = None,
        request: BrowserRouteRequest | None = None,
    ) -> dict[str, Any]:
        """复用浏览器登录态直接请求接口，并保留分阶段耗时诊断。"""
        normalized_method = method.upper()
        stage_started_at = time.monotonic()
        response = await _request_with_browser_context(
            page,
            endpoint=endpoint,
            method=normalized_method,
            payload=payload,
        )
        _record_timing(
            timings,
            request,
            f"route_fetch.{section}.context_request",
            stage_started_at,
            status=getattr(response, "status", None),
        )
        stage_started_at = time.monotonic()
        parsed = await _parse_response(
            response,
            method=normalized_method,
            root_dir=root_dir,
            section=section,
        )
        _record_timing(
            timings,
            request,
            f"route_fetch.{section}.parse_response",
            stage_started_at,
            transport="context_request",
            status=getattr(response, "status", None),
        )
        return parsed

    async def _execute_route_fetch(
        self,
        *,
        page,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
        root_dir: Path,
        section: str,
        timings: list[dict[str, Any]] | None = None,
        request: BrowserRouteRequest | None = None,
        route_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        if normalized_method in {"GET_XLSX", "POST_XLSX"}:
            stage_started_at = time.monotonic()
            response = await _request_with_browser_context(
                page,
                endpoint=endpoint,
                method=normalized_method,
                payload=payload,
            )
            parsed = await _parse_response(
                response,
                method=normalized_method,
                root_dir=root_dir,
                section=section,
            )
            _record_timing(
                timings,
                request,
                f"route_fetch.{section}.context_xlsx",
                stage_started_at,
                status=getattr(response, "status", None),
            )
            return parsed
        pattern = _route_pattern(endpoint)
        route_error = asyncio.get_running_loop().create_future()

        async def _handle(route) -> None:
            intercepted_request = route.request
            if not _same_endpoint(intercepted_request.url, endpoint):
                await route.continue_()
                return
            headers = {
                key: value
                for key, value in intercepted_request.headers.items()
                if key.lower() != "content-length"
            }
            headers["accept"] = "application/json, text/plain, */*"
            if normalized_method == "PAGE_CAPTURE":
                await route.continue_()
                return
            if normalized_method == "GET":
                await route.continue_(
                    url=_url_with_query(endpoint, payload),
                    method="GET",
                    headers=headers,
                )
                return
            if normalized_method == "GET_PAGE":
                headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
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
            if normalized_method == "POST_QUERY":
                headers["content-type"] = "application/json;charset=UTF-8"
                await route.continue_(
                    url=_url_with_query(endpoint, payload),
                    method="POST",
                    headers=headers,
                    post_data="{}",
                )
                return
            headers["content-type"] = "application/json;charset=UTF-8"
            effective_payload = payload
            if request and request.scenario == "keyword-comparison":
                try:
                    effective_payload = _keyword_comparison_route_payload(
                        payload,
                        intercepted_request.post_data,
                    )
                except SellerSpriteApiError as exc:
                    # 先通知主协程再中止请求；即使浏览器中止动作异常，也不能退化成响应超时。
                    if not route_error.done():
                        route_error.set_exception(exc)
                    await route.abort("blockedbyclient")
                    return
                if route_metadata is not None:
                    route_metadata["asinList"] = list(effective_payload["asinList"])
            elif request and request.scenario == "traffic-extend":
                try:
                    effective_payload = _traffic_extend_route_payload(
                        payload,
                        intercepted_request.post_data,
                    )
                except SellerSpriteApiError as exc:
                    if not route_error.done():
                        route_error.set_exception(exc)
                    await route.abort("blockedbyclient")
                    return
            await route.continue_(
                url=_absolute_url(endpoint),
                method="POST",
                headers=headers,
                post_data=json.dumps(
                    effective_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

        stage_started_at = time.monotonic()
        await page.route(pattern, _handle)
        _record_timing(timings, request, f"route_fetch.{section}.route_setup", stage_started_at, endpoint=endpoint)
        try:
            trigger_task = asyncio.create_task(
                _trigger_request(
                    page,
                    endpoint=endpoint,
                    method=normalized_method,
                    payload=payload,
                    timings=timings,
                    request=request,
                    section=section,
                )
            )
            await asyncio.wait(
                {trigger_task, route_error},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if route_error.done():
                # 被拦截请求已中止，优先透传校验错误，避免外层等待页面响应超时。
                if not trigger_task.done():
                    trigger_task.cancel()
                try:
                    await trigger_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                raise route_error.exception()
            response, transport = await trigger_task
            stage_started_at = time.monotonic()
            parsed = await _parse_response(response, method=normalized_method, root_dir=root_dir, section=section)
            _record_timing(
                timings,
                request,
                f"route_fetch.{section}.parse_response",
                stage_started_at,
                transport=transport,
                status=getattr(response, "status", None),
            )
            return parsed
        finally:
            stage_started_at = time.monotonic()
            if page.is_closed():
                # 页面关闭会自动移除 route；此时不再调用 unroute，避免清理异常覆盖主结果。
                _record_timing(
                    timings,
                    request,
                    f"route_fetch.{section}.unroute",
                    stage_started_at,
                    skipped=True,
                    reason="target_closed",
                )
            else:
                try:
                    await page.unroute(pattern, _handle)
                except Exception as exc:
                    # is_closed 检查后仍可能发生关闭竞态，仅忽略明确的目标关闭异常。
                    if not _is_target_closed_error(exc):
                        raise
                    _record_timing(
                        timings,
                        request,
                        f"route_fetch.{section}.unroute",
                        stage_started_at,
                        skipped=True,
                        reason="target_closed",
                    )
                else:
                    _record_timing(
                        timings,
                        request,
                        f"route_fetch.{section}.unroute",
                        stage_started_at,
                    )


def _keyword_comparison_route_payload(
    payload: dict[str, Any],
    post_data: str | None,
) -> dict[str, Any]:
    """仅保留流量词对比页面生成的最终畅销变体列表。"""
    try:
        page_payload = json.loads(post_data or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise SellerSpriteApiError(
            "卖家精灵流量词对比主请求体不是合法 JSON",
            api_code="ERR_KEYWORD_COMPARISON_REQUEST_BODY",
        ) from exc
    asin_values = page_payload.get("asinList") if isinstance(page_payload, dict) else None
    if not isinstance(asin_values, list):
        raise SellerSpriteApiError(
            "卖家精灵流量词对比主请求缺少畅销变体列表",
            api_code="ERR_KEYWORD_COMPARISON_ASIN_LIST",
        )
    asin_list = [str(value).strip().upper() for value in asin_values]
    if (
        not 2 <= len(asin_list) <= 11
        or len(set(asin_list)) != len(asin_list)
        or any(not re.fullmatch(r"[A-Z0-9]{10}", asin) for asin in asin_list)
    ):
        raise SellerSpriteApiError(
            "卖家精灵流量词对比畅销变体列表无效",
            api_code="ERR_KEYWORD_COMPARISON_ASIN_LIST",
        )
    # 页面只能覆盖 prepare 生成的 asinList，其他筛选和分页继续以后端校验结果为准。
    return {**payload, "asinList": asin_list, "page": 1, "size": 100}


def _traffic_extend_route_payload(
    payload: dict[str, Any],
    post_data: str | None,
) -> dict[str, Any]:
    """保留页面变体按钮生成的范围，同时锁定第一页 100 条。"""
    try:
        page_payload = json.loads(post_data or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise SellerSpriteApiError(
            "卖家精灵拓展流量词主请求体不是合法 JSON",
            api_code="ERR_TRAFFIC_EXTEND_REQUEST_BODY",
        ) from exc
    if not isinstance(page_payload, dict):
        raise SellerSpriteApiError(
            "卖家精灵拓展流量词主请求体无效",
            api_code="ERR_TRAFFIC_EXTEND_REQUEST_BODY",
        )
    asin_values = page_payload.get("asinList")
    asin_list = (
        [str(value).strip().upper() for value in asin_values]
        if isinstance(asin_values, list)
        else []
    )
    if (
        not asin_list
        or len(asin_list) > 20
        or len(set(asin_list)) != len(asin_list)
        or any(not re.fullmatch(r"[A-Z0-9]{10}", asin) for asin in asin_list)
    ):
        raise SellerSpriteApiError(
            "卖家精灵拓展流量词变体 ASIN 列表无效",
            api_code="ERR_TRAFFIC_EXTEND_ASIN_LIST",
        )
    return {
        **payload,
        "asinList": asin_list,
        "originAsinList": list(payload.get("originAsinList") or asin_list),
        "queryVariations": bool(page_payload.get("queryVariations")),
        "page": 1,
        "size": 100,
    }


def _is_target_closed_error(exc: Exception) -> bool:
    """判断异常是否为 Playwright/Patchright 明确的目标关闭错误。"""
    return type(exc).__name__ == "TargetClosedError"


def build_default_session_state_listener(
    settings: SellerSpriteSettings,
) -> Callable[[SellerSpriteAccount, dict[str, Any]], None]:
    """为非 scheduler 直调路径创建延迟初始化的 SQLite 状态监听器。

    参数：
        settings: 当前卖家精灵配置；自定义输出目录时审计库也落在该目录内。

    返回：
        可直接传给 browser worker 的同步状态监听器。
    """
    recorder = None
    initialization_failed = False

    def listener(account: SellerSpriteAccount, payload: dict[str, Any]) -> None:
        nonlocal recorder, initialization_failed
        if initialization_failed:
            return
        if recorder is None:
            try:
                from opscli.seller_sprite.services.account_events import (
                    SellerSpriteAccountEventRecorder,
                )
                from opscli.seller_sprite.services.task_queue_store import (
                    SellerSpriteTaskQueueStore,
                )

                if settings.output_dir == DEFAULT_OUTPUT_DIR:
                    store = SellerSpriteTaskQueueStore()
                else:
                    store = SellerSpriteTaskQueueStore(
                        db_path=settings.output_dir / ".seller_sprite_session_events.sqlite3"
                    )
                recorder = SellerSpriteAccountEventRecorder(store=store)
            except Exception as exc:
                initialization_failed = True
                # 审计初始化是旁路；只记录异常类型，绝不能覆盖浏览器主任务。
                logger.error(
                    "卖家精灵 browser 会话审计初始化失败：error=%s",
                    type(exc).__name__,
                    extra={
                        "seller_sprite_event": {
                            "event_type": "account_audit_persistence_failed",
                            "error_code": type(exc).__name__,
                        }
                    },
                )
                return
        recorder.record_session_state_payload(account, payload)

    return listener


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
        for marker in (
            "captcha",
            "验证码",
            "机器人检测",
            "risk control",
            "risk_control",
            "rate limit",
            "rate_limit",
            "too many",
            "风控",
        )
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


def _absolute_callback_url(callback: str) -> str:
    if callback.startswith("http"):
        return callback
    path = callback if callback.startswith("/") else f"/{callback}"
    return f"{BASE_URL}{path}"


def _normalized_page_url(url: str) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True))),
    )


_WORKERS: dict[tuple[int, str, str, str], SellerSpriteBrowserRouteWorker] = {}


class _NoQueryButtonError(Exception):
    pass


def get_browser_route_worker(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    owner_id: str = "default",
) -> SellerSpriteBrowserRouteWorker:
    """按事件循环、所有者、浏览器配置和账号获取常驻 worker。

    参数：
        settings: browser-route 运行配置。
        account: worker 独占账号。
        state_listener: 会话状态监听器。
        clock: 生命周期单调时钟。
        owner_id: 调度器运行期所有权标识，用于隔离同配置的并发调度器。

    返回：
        可接受任务的账号隔离 worker。
    """
    key = _worker_registry_key(settings=settings, account=account, owner_id=owner_id)
    worker = _WORKERS.get(key)
    if not worker or not worker.accepts_tasks:
        worker = SellerSpriteBrowserRouteWorker(
            settings=settings,
            account=account,
            state_listener=state_listener,
            clock=clock,
        )
        _WORKERS[key] = worker
    else:
        worker.set_state_listener(state_listener)
    return worker


def get_existing_browser_route_worker(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    owner_id: str = "default",
) -> SellerSpriteBrowserRouteWorker | None:
    """读取已存在且可接受任务的 browser worker。

    参数：
        settings: browser-route 运行配置。
        account: 目标账号。
        owner_id: 调度器运行期所有权标识。

    返回：
        已存在的 worker；不存在或正在关闭时返回空。
    """
    worker = _WORKERS.get(
        _worker_registry_key(settings=settings, account=account, owner_id=owner_id)
    )
    return worker if worker and worker.accepts_tasks else None


def reserve_browser_route_worker(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    owner_id: str = "default",
) -> SellerSpriteBrowserRouteWorker | None:
    """预留已存在的 worker，避免已领取任务在提交前遭周期回收。

    参数：
        settings: browser-route 运行配置。
        account: 已领取任务绑定的账号。
        owner_id: 调度器运行期所有权标识。

    返回：
        预留成功的 worker；会话尚未创建或已关闭时返回空。
    """
    worker = get_existing_browser_route_worker(
        settings=settings,
        account=account,
        owner_id=owner_id,
    )
    if worker is None or not worker.reserve():
        return None
    return worker


async def close_browser_route_worker(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    reason: str = "account_unavailable",
    state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
    owner_id: str = "default",
) -> bool:
    """关闭并移除指定账号在当前所有者中的 browser worker。

    参数：
        settings: browser-route 运行配置。
        account: 目标账号。
        reason: 关闭原因。
        state_listener: 会话状态监听器。
        owner_id: 调度器运行期所有权标识。

    返回：
        实际找到并关闭 worker 时返回 ``True``，否则返回 ``False``。

    异常：
        Exception: 透传浏览器资源清理异常。
    """
    owner_prefix = _worker_owner_prefix(owner_id=owner_id)
    account_key = f"{account.name}:{account.username}"
    selected = [
        (key, worker)
        for key, worker in list(_WORKERS.items())
        if key[:2] == owner_prefix and key[3] == account_key
    ]
    if not selected:
        return False
    errors: list[Exception] = []
    for key, worker in selected:
        if _WORKERS.pop(key, None) is not worker:
            continue
        # 配置热更新可能留下不同启动命名空间的旧会话，因此按所有者和账号完整清理。
        try:
            if isinstance(worker, SellerSpriteBrowserRouteWorker):
                worker.set_state_listener(state_listener)
                await worker.close(reason=reason)
            else:
                await worker.close()
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise errors[0]
    return True


async def reap_browser_route_workers(
    *,
    settings: SellerSpriteSettings,
    now: float | None = None,
    state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
    owner_id: str = "default",
) -> list[dict[str, str]]:
    """回收当前所有者中达到空闲或最大生命周期的安全会话。

    参数：
        settings: 当前生命周期阈值和浏览器配置。
        now: 指定生命周期计算时刻。
        state_listener: 会话状态监听器。
        owner_id: 调度器运行期所有权标识。

    返回：
        成功回收的账号名和原因列表。
    """
    owner_prefix = _worker_owner_prefix(owner_id=owner_id)
    recycled: list[dict[str, str]] = []
    for key, worker in list(_WORKERS.items()):
        if key[:2] != owner_prefix:
            continue
        reason = worker.recycle_reason(settings=settings, now=now)
        if reason is None:
            continue
        # 先移除再关闭，确保下一任务只能取得全新的 worker。
        if _WORKERS.pop(key, None) is not worker:
            continue
        worker.set_state_listener(state_listener)
        try:
            await worker.close(reason=reason)
        except Exception as exc:
            # 状态监听器已记录 close_failed；单个关闭失败不能阻断其他会话回收。
            logger.warning(
                "卖家精灵 browser 会话回收失败：account=%s error=%s",
                worker.account.name,
                type(exc).__name__,
            )
            continue
        recycled.append({"account_name": worker.account.name, "reason": reason})
    return recycled


async def close_all_browser_route_workers(
    *,
    settings: SellerSpriteSettings,
    reason: str = "scheduler_close",
    state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
    owner_id: str = "default",
) -> int:
    """关闭当前所有者管理的全部 browser-route 会话。

    参数：
        settings: browser-route 运行配置。
        reason: 批量关闭原因。
        state_listener: 会话状态监听器。
        owner_id: 调度器运行期所有权标识。

    返回：
        成功关闭的 worker 数量。
    """
    owner_prefix = _worker_owner_prefix(owner_id=owner_id)
    closed_count = 0
    for key, worker in list(_WORKERS.items()):
        if key[:2] != owner_prefix:
            continue
        if _WORKERS.pop(key, None) is not worker:
            continue
        worker.set_state_listener(state_listener)
        try:
            await worker.close(reason=reason)
        except Exception as exc:
            # 继续关闭其他账号，失败账号已通过监听器报告 close_failed。
            logger.warning(
                "卖家精灵 browser 会话批量关闭失败：account=%s error=%s",
                worker.account.name,
                type(exc).__name__,
            )
            continue
        closed_count += 1
    return closed_count


def _worker_registry_prefix(
    *,
    settings: SellerSpriteSettings,
    owner_id: str,
) -> tuple[int, str, str]:
    """构造事件循环、所有者和浏览器启动配置组成的 registry 前缀。"""
    launch_identity = {
        "profile_dir": str(settings.browser_profile_dir.expanduser().resolve()),
        "runtime": settings.browser_runtime.strip().lower(),
        "channel": (settings.browser_channel or "").strip().lower(),
        "headless": bool(settings.browser_headless),
    }
    namespace = hashlib.sha256(
        json.dumps(launch_identity, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return (id(asyncio.get_running_loop()), str(owner_id or "default"), namespace)


def _worker_owner_prefix(*, owner_id: str) -> tuple[int, str]:
    """构造跨配置热更新稳定的事件循环与所有者前缀。"""
    return (id(asyncio.get_running_loop()), str(owner_id or "default"))


def _worker_registry_key(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    owner_id: str,
) -> tuple[int, str, str, str]:
    """构造不写入日志的完整 worker registry 键。"""
    account_key = f"{account.name}:{account.username}"
    return (*_worker_registry_prefix(settings=settings, owner_id=owner_id), account_key)


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


async def fetch_listing_analysis_report_with_browser_route(
    *,
    settings: SellerSpriteSettings,
    account: SellerSpriteAccount,
    task_id: str,
    root_dir: Path,
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    state_listener: Callable[[SellerSpriteAccount, dict[str, Any]], None] | None = None,
    owner_id: str = "default",
) -> BrowserRouteResult:
    """通过 browser-route 打开 Listing Analysis 报告详情页并捕获结果。"""
    worker = get_browser_route_worker(
        settings=settings,
        account=account,
        state_listener=(
            state_listener or build_default_session_state_listener(settings)
        ),
        owner_id=owner_id,
    )
    return await worker.fetch_listing_analysis_report(
        task_id=task_id,
        root_dir=root_dir,
        page_prepare=settings.browser_page_prepare if page_prepare is None else page_prepare,
        task_interval_seconds=(
            settings.browser_task_interval_seconds
            if task_interval_seconds is None
            else task_interval_seconds
        ),
        cooldown_seconds=(
            settings.browser_cooldown_seconds
            if cooldown_seconds is None
            else cooldown_seconds
        ),
    )


async def _open_listing_analysis_report_and_capture(
    page,
    *,
    task_id: str,
    report_url: str,
    root_dir: Path,
) -> dict[str, Any]:
    """进入 Listing Analysis 报告页并捕获 competing-lookup 响应。"""
    async with page.expect_response(
        lambda response: _same_endpoint(response.url, "/v3/api/competing-lookup"),
        timeout=DEFAULT_TIMEOUT_MS,
    ) as info:
        await page.goto(report_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    response = await info.value
    payload = await _parse_response(response, method="PAGE_CAPTURE", root_dir=root_dir, section="listing_analysis_report")
    if isinstance(payload.get("data"), dict):
        payload["data"].setdefault("taskId", task_id)
    return payload


async def _trigger_request(
    page,
    *,
    endpoint: str,
    method: str,
    payload: dict[str, Any],
    timings: list[dict[str, Any]] | None = None,
    request: BrowserRouteRequest | None = None,
    section: str = "main",
):
    stage_started_at = time.monotonic()
    wait_started_at = stage_started_at
    listing_analysis_clicked = False
    keyword_miner_interaction = bool(
        request and request.scenario == "keyword-miner"
    )
    association_traffic_interaction = bool(
        request and request.scenario == "association-traffic"
    )
    keyword_comparison_interaction = bool(
        request and request.scenario == "keyword-comparison"
    )
    traffic_extend_interaction = bool(
        request and request.scenario == "traffic-extend"
    )
    keyword_conversion_rate_interaction = bool(
        request and request.scenario == "keyword-conversion-rate"
    )
    try:
        if keyword_comparison_interaction:
            # prepare 和弹窗等待不应占用主接口响应预算；只在最终变体按钮点击前监听主响应。
            response = await _trigger_keyword_comparison_query(
                page,
                payload,
                endpoint=endpoint,
                variant_selection=request.keyword_comparison_variant,
                root_dir=request.root_dir,
            )
            if response is None:
                raise _NoQueryButtonError()
            _record_timing(
                timings,
                request,
                f"route_fetch.{section}.wait_page_response",
                stage_started_at,
                status=getattr(response, "status", None),
            )
            return response, "page_response"
        if traffic_extend_interaction:
            # prepare 完成后才监听主接口，避免弹窗等待消耗主响应预算。
            response = await _trigger_traffic_extend_query(
                page,
                payload,
                endpoint=endpoint,
                variant_selection=request.traffic_extend_variant,
                root_dir=request.root_dir,
            )
            if response is None:
                raise _NoQueryButtonError()
            return response, "page_response"
        if keyword_conversion_rate_interaction:
            # 1—1000 个标签的录入不占用主响应监听预算；只在单次查询点击前监听。
            query_button = await _prepare_keyword_conversion_rate_query(
                page,
                payload,
            )
            if query_button is None:
                raise _NoQueryButtonError()
            async with page.expect_response(
                lambda response: _same_endpoint(response.url, endpoint),
                timeout=30000,
            ) as info:
                _record_timing(
                    timings,
                    request,
                    f"route_fetch.{section}.expect_response_ready",
                    stage_started_at,
                )
                stage_started_at = time.monotonic()
                await query_button.click(timeout=5000)
                _record_timing(
                    timings,
                    request,
                    f"route_fetch.{section}.click_query_button",
                    stage_started_at,
                    clicked=True,
                )
                wait_started_at = time.monotonic()
            response = await info.value
            _record_timing(
                timings,
                request,
                f"route_fetch.{section}.wait_page_response",
                wait_started_at,
                status=getattr(response, "status", None),
            )
            return response, "page_response"

        response_timeout = (
            30000
            if association_traffic_interaction
            else 15000
        )
        async with page.expect_response(
            lambda response: _same_endpoint(response.url, endpoint),
            timeout=response_timeout,
        ) as info:
            _record_timing(timings, request, f"route_fetch.{section}.expect_response_ready", stage_started_at)
            stage_started_at = time.monotonic()
            if request and request.scenario == "listing-analysis":
                # Listing Analysis 必须先在页面输入 ASIN 再点击查询，避免只走静默接口提交。
                listing_analysis_clicked = await _trigger_listing_analysis_query(page, payload)
                clicked = listing_analysis_clicked
            elif keyword_miner_interaction:
                # 关键词挖掘必须先填写关键词；空点查询只会触发页面校验且不会发送接口请求。
                clicked = await _trigger_keyword_miner_query(page, payload)
            elif association_traffic_interaction:
                # 关联流量必须先校验准备接口，再在弹窗中显式选择全部变体。
                clicked = await _trigger_association_traffic_query(
                    page,
                    payload,
                    root_dir=request.root_dir,
                )
            else:
                clicked = await _click_query_button(page)
            _record_timing(timings, request, f"route_fetch.{section}.click_query_button", stage_started_at, clicked=clicked)
            if not clicked:
                raise _NoQueryButtonError()
            wait_started_at = time.monotonic()
        response = await info.value
        _record_timing(
            timings,
            request,
            f"route_fetch.{section}.wait_page_response",
            wait_started_at,
            status=getattr(response, "status", None),
        )
        return response, "page_response"
    except Exception as exc:
        _record_timing(
            timings,
            request,
            f"route_fetch.{section}.page_response_fallback",
            wait_started_at,
            error=type(exc).__name__,
        )
        if request and request.scenario == "listing-analysis" and listing_analysis_clicked:
            raise SellerSpriteApiError(
                "卖家精灵 Listing Analysis 已点击提交但未捕获接口响应，请稍后确认结果，避免重复提交",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_LISTING_ANALYSIS_RESPONSE_MISSED",
                api_message="已完成页面点击，不再自动 fallback 重复创建 AI 任务。",
            ) from exc
        if association_traffic_interaction:
            if isinstance(exc, SellerSpriteApiError):
                raise
            raise SellerSpriteApiError(
                "卖家精灵关联流量页面交互后未捕获主查询响应",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_ASSOCIATION_TRAFFIC_RESPONSE_MISSED",
                api_message="页面交互已完成，不再自动 fallback 重复查询。",
            ) from exc
        if traffic_extend_interaction:
            if isinstance(exc, SellerSpriteApiError):
                raise
            raise SellerSpriteApiError(
                "卖家精灵拓展流量词页面交互后未捕获主查询响应",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_TRAFFIC_EXTEND_RESPONSE_MISSED",
                api_message="页面交互已完成，不再自动 fallback 重复查询。",
            ) from exc
        if keyword_comparison_interaction:
            if isinstance(exc, SellerSpriteApiError):
                raise
            raise SellerSpriteApiError(
                "卖家精灵流量词对比页面交互后未捕获主查询响应",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_KEYWORD_COMPARISON_RESPONSE_MISSED",
                api_message="页面交互已完成，不再自动 fallback 重复查询。",
            ) from exc
        if keyword_conversion_rate_interaction:
            if isinstance(exc, SellerSpriteApiError):
                raise
            raise SellerSpriteApiError(
                "卖家精灵关键词转化率页面交互后未捕获主查询响应",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_KEYWORD_CONVERSION_RATE_RESPONSE_MISSED",
                api_message="关键词标签已提交或查询按钮已点击，不再自动 fallback 重复查询。",
            ) from exc
        stage_started_at = time.monotonic()
        response = await _request_with_browser_context(page, endpoint=endpoint, method=method, payload=payload)
        _record_timing(
            timings,
            request,
            f"route_fetch.{section}.context_request",
            stage_started_at,
            status=getattr(response, "status", None),
        )
        return response, "context_request"


async def _request_with_browser_context(page, *, endpoint: str, method: str, payload: dict[str, Any]):
    """使用浏览器上下文请求接口，复用当前 profile 的 cookie，避免页面内 fetch 被拦截。"""
    headers = _context_request_headers(page.url, method=method)
    try:
        if method in {"GET", "GET_PAGE", "GET_XLSX", "PAGE_CAPTURE"}:
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
        if method == "POST_QUERY":
            return await page.context.request.post(
                _url_with_query(endpoint, payload),
                headers=headers,
                data="{}",
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
    if method in {"FORM", "GET_PAGE"}:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        if method == "FORM":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif method in {"GET_XLSX", "POST_XLSX"}:
        headers["Accept"] = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/msexcel,application/octet-stream,*/*"
        )
        if method == "POST_XLSX":
            headers["Content-Type"] = "application/json;charset=UTF-8"
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
    locator = await _first_visible_page_locator(page, selectors)
    if locator is None:
        return False
    await locator.click(timeout=5000)
    return True


async def _trigger_keyword_miner_query(page, payload: dict[str, Any]) -> bool:
    """在关键词挖掘页面填写关键词并点击查询按钮。"""
    keyword = str(payload.get("keyword") or "").strip()
    if not keyword:
        return False
    query_button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            ".el-button:visible:has-text('立即查询')",
            ".ant-btn:visible:has-text('立即查询')",
        ],
    )
    if query_button is None:
        return False
    input_box = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='输入关键词']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='搜索关键词']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='关键词']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='keyword' i]:visible:not([readonly]):not([disabled])",
            "input[placeholder*='flashlight' i]:visible:not([readonly]):not([disabled])",
            "input[aria-label*='输入关键词']:visible:not([readonly]):not([disabled])",
            "input[aria-label*='关键词']:visible:not([readonly]):not([disabled])",
            "input[aria-label*='keyword' i]:visible:not([readonly]):not([disabled])",
            "input[name*='keyword' i]:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        # 页面文案变化时，从查询按钮逐层向上寻找最近的可见文本框，避免误填下方筛选项。
        input_box = await _keyword_miner_input_near_button(query_button)
    if input_box is None:
        return False
    await input_box.fill(keyword)
    await query_button.click(timeout=5000)
    return True


async def _keyword_miner_input_near_button(query_button):
    """从查询按钮最近祖先开始寻找唯一可见文本框。"""
    input_selector = (
        "input:visible:not([readonly]):not([disabled])"
        ":is(:not([type]), [type='text'], [type='search'])"
    )
    for depth in range(1, 7):
        container = query_button.locator(f"xpath=ancestor::*[{depth}]")
        locator = container.locator(input_selector)
        try:
            count = await locator.count()
            if count == 1:
                candidate = locator.first
                if await candidate.is_visible(timeout=800):
                    return candidate
        except Exception:
            continue
    return None


async def _trigger_listing_analysis_query(page, payload: dict[str, Any]) -> bool:
    """在 Listing Analysis 页面填写 ASIN 并点击查询按钮。"""
    asin = str(payload.get("asin") or "").strip().upper()
    if not asin:
        return False
    input_box = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='asin']:visible:not([readonly]):not([disabled])",
            "input[type='text']:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        return False
    await input_box.fill(asin)
    try:
        await input_box.press("Enter", timeout=5000)
        return True
    except Exception:
        pass
    button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即分析')",
            "[role='button']:visible:has-text('立即分析')",
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            "button:visible:has-text('查询')",
            "[role='button']:visible:has-text('查询')",
            ".el-button:visible:has-text('立即分析')",
            ".el-button:visible:has-text('立即查询')",
            ".el-button:visible:has-text('查询')",
            ".ant-btn:visible:has-text('立即分析')",
            ".ant-btn:visible:has-text('立即查询')",
            ".ant-btn:visible:has-text('查询')",
        ],
    )
    if button is None:
        return False
    await button.click(timeout=5000)
    return True


async def _trigger_keyword_comparison_query(
    page,
    payload: dict[str, Any],
    *,
    endpoint: str,
    variant_selection: str,
    root_dir: Path,
):
    """填写流量词对比条件，校验 prepare 后选择变体并捕获主响应。"""
    own_asin = str(payload.get("asin") or "").strip().upper()
    competitor_values = payload.get("asinList")
    competitor_asins = (
        [str(value).strip().upper() for value in competitor_values]
        if isinstance(competitor_values, list)
        else []
    )
    if not own_asin or not competitor_asins:
        return None

    own_input = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='自己的ASIN']:visible:not([readonly]):not([disabled])",
            "textarea[placeholder*='自己的ASIN']:visible:not([readonly]):not([disabled])",
        ],
    )
    competitor_input = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='竞品ASIN']:visible:not([readonly]):not([disabled])",
            "textarea[placeholder*='竞品ASIN']:visible:not([readonly]):not([disabled])",
        ],
    )
    if own_input is None or competitor_input is None:
        return None
    await own_input.fill(own_asin)
    await competitor_input.fill(" ".join(competitor_asins))

    query_button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            ".el-button:visible:has-text('立即查询')",
        ],
    )
    if query_button is None:
        return None

    # 必须先解析 prepare 业务响应；失败时立即结束，不能继续空等弹窗。
    async with page.expect_response(
        lambda response: _same_endpoint(
            response.url,
            "/v3/api/keyword-comparison/prepare",
        ),
        timeout=15000,
    ) as prepare_info:
        try:
            await query_button.click(timeout=5000)
        except Exception as exc:
            raise SellerSpriteApiError(
                "卖家精灵流量词对比“立即查询”按钮点击失败",
                api_code="ERR_KEYWORD_COMPARISON_QUERY_CLICK",
            ) from exc
    prepare_response = await prepare_info.value
    prepare_payload = await _parse_response(
        prepare_response,
        method="POST",
        root_dir=root_dir,
        section="keyword_comparison_prepare",
    )
    prepare_data = (
        prepare_payload.get("data")
        if isinstance(prepare_payload, dict)
        else None
    )
    api_message = (
        prepare_payload.get("message") or prepare_payload.get("msg")
        if isinstance(prepare_payload, dict)
        else None
    )
    # prepare 必须同时明确返回 code=OK 和 success=true；缺失或类型异常也视为失败。
    prepare_code = (
        prepare_payload.get("code")
        if isinstance(prepare_payload, dict)
        else None
    )
    prepare_success = (
        prepare_payload.get("success")
        if isinstance(prepare_payload, dict)
        else None
    )
    if prepare_code != "OK" or prepare_success is not True:
        raise SellerSpriteApiError(
            "卖家精灵流量词对比准备接口返回错误",
            status_code=getattr(prepare_response, "status", None),
            response_excerpt=json.dumps(prepare_payload, ensure_ascii=False)[:1000],
            api_code=(
                str(prepare_code)
                if prepare_code not in {None, "", "OK"}
                else "ERR_KEYWORD_COMPARISON_PREPARE"
            ),
            api_message=str(api_message) if api_message else None,
        )
    diamond_list = (
        prepare_data.get("diamondList")
        if isinstance(prepare_data, dict)
        else None
    )
    if (
        not isinstance(diamond_list, list)
        or not diamond_list
        or any(not isinstance(value, str) or not value.strip() for value in diamond_list)
    ):
        raise SellerSpriteApiError(
            "卖家精灵流量词对比准备接口未返回有效畅销变体列表",
            status_code=getattr(prepare_response, "status", None),
            response_excerpt=json.dumps(prepare_payload, ensure_ascii=False)[:1000],
            api_code="ERR_KEYWORD_COMPARISON_PREPARE_DATA",
            api_message=str(api_message) if api_message else None,
        )

    button_text = (
        "用当前变体拓词"
        if variant_selection == "current"
        else "用畅销变体拓词"
    )
    variant_button = None
    for _ in range(30):
        variant_button = await _first_visible_page_locator(
            page,
            [
                f"button:visible:has-text('{button_text}')",
                f"[role='button']:visible:has-text('{button_text}')",
                f".el-button:visible:has-text('{button_text}')",
            ],
        )
        if variant_button is not None:
            break
        await page.wait_for_timeout(500)
    if variant_button is None:
        raise SellerSpriteApiError(
            f"卖家精灵流量词对比页面未出现“{button_text}”按钮",
            api_code="ERR_KEYWORD_COMPARISON_VARIANT_DIALOG",
        )

    # Element UI 弹窗刚出现时仍可能处于过渡阶段；等待稳定并固定单次鼠标激活坐标。
    await page.wait_for_timeout(300)
    # 首次读取会安装只计数的 DOM 监听器，后续失败快照可判断鼠标是否产生了 click。
    await _keyword_comparison_button_diagnostics(variant_button)
    try:
        await variant_button.scroll_into_view_if_needed(timeout=5000)
        button_box = await variant_button.bounding_box(timeout=5000)
        if not button_box or button_box["width"] <= 0 or button_box["height"] <= 0:
            raise RuntimeError("variant button has no clickable bounding box")
        activation_x = button_box["x"] + button_box["width"] / 2
        activation_y = button_box["y"] + button_box["height"] / 2
    except Exception as exc:
        diagnostic = await _log_keyword_comparison_diagnostics(
            variant_button,
            phase="activation_target_failed",
        )
        raise SellerSpriteApiError(
            f"卖家精灵流量词对比“{button_text}”按钮激活位置无效",
            response_excerpt=diagnostic,
            api_code="ERR_KEYWORD_COMPARISON_VARIANT_CLICK",
        ) from exc

    # 同时观察请求和响应：请求监听用于区分按钮未提交、官网路径变化和响应丢失。
    observed_path = urlparse(endpoint).path
    try:
        async with page.expect_response(
            lambda response: _same_endpoint(response.url, endpoint),
            timeout=DEFAULT_TIMEOUT_MS,
        ) as main_info:
            try:
                async with page.expect_request(
                    _is_keyword_comparison_post_request,
                    timeout=15000,
                ) as request_info:
                    try:
                        # 仅发送一次完整鼠标激活；失败后禁止补按 Enter 或重试，避免重复提交。
                        await page.mouse.click(
                            activation_x,
                            activation_y,
                            delay=100,
                        )
                    except Exception as exc:
                        diagnostic = await _log_keyword_comparison_diagnostics(
                            variant_button,
                            phase="activation_failed",
                        )
                        raise SellerSpriteApiError(
                            f"卖家精灵流量词对比“{button_text}”按钮激活失败",
                            response_excerpt=diagnostic,
                            api_code="ERR_KEYWORD_COMPARISON_VARIANT_CLICK",
                        ) from exc
            except SellerSpriteApiError:
                raise
            except Exception as exc:
                # Playwright 会在退出 expect_request 上下文时等待事件，必须在主响应上下文内分类。
                diagnostic = await _log_keyword_comparison_diagnostics(
                    variant_button,
                    phase="request_missed",
                )
                raise SellerSpriteApiError(
                    "卖家精灵流量词对比变体按钮激活后未触发主查询请求",
                    response_excerpt=diagnostic,
                    api_code="ERR_KEYWORD_COMPARISON_REQUEST_MISSED",
                    api_message="变体按钮已单次激活，不再自动 fallback 重复查询。",
                ) from exc

            observed_request = await request_info.value
            observed_path = urlparse(observed_request.url).path
            if not _same_endpoint(observed_request.url, endpoint):
                # 路径变化后立即退出并取消旧接口响应监听，不能继续空等 120 秒。
                raise SellerSpriteApiError(
                    "卖家精灵流量词对比主查询接口路径已变化",
                    response_excerpt=(
                        f"method={observed_request.method} path={observed_path}"
                    ),
                    api_code="ERR_KEYWORD_COMPARISON_ENDPOINT_CHANGED",
                    api_message=(
                        "仅记录脱敏请求方法和路径，未记录请求体、Cookie 或 Header。"
                    ),
                )
            return await main_info.value
    except SellerSpriteApiError:
        raise
    except Exception as exc:
        # Playwright 同样会在退出 expect_response 上下文时等待事件并抛出超时。
        diagnostic = await _log_keyword_comparison_diagnostics(
            variant_button,
            phase="response_missed",
        )
        raise SellerSpriteApiError(
            "卖家精灵流量词对比主查询请求已发出但未捕获响应",
            response_excerpt=(
                f"method=POST path={observed_path} diagnostics={diagnostic}"
            )[:1000],
            api_code="ERR_KEYWORD_COMPARISON_RESPONSE_MISSED",
            api_message="变体按钮已单次激活，不再自动 fallback 重复查询。",
        ) from exc


async def _trigger_association_traffic_query(
    page,
    payload: dict[str, Any],
    *,
    root_dir: Path,
) -> bool:
    """在关联流量页面录入 ASIN，校验准备响应并选择全部变体查询。"""
    asin_values = payload.get("asinList")
    asins: list[str] = []
    if isinstance(asin_values, list):
        asins = [
            str(value).strip().upper()
            for value in asin_values
            if str(value).strip()
        ]
    if not asins:
        return False
    input_box = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='已录入'][placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        return False

    clear_button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('清除')",
            "[role='button']:visible:has-text('清除')",
            ".el-button:visible:has-text('清除')",
        ],
    )
    if clear_button is not None:
        await clear_button.click(timeout=5000)
        await page.wait_for_timeout(200)

    for asin in asins:
        await input_box.fill(asin)
        await input_box.press("Enter", timeout=5000)
        await page.wait_for_timeout(100)

    placeholder = await input_box.get_attribute("placeholder")
    expected_count = f"已录入{len(asins)}/20个ASIN"
    if placeholder and "已录入" in placeholder and expected_count != placeholder.strip():
        raise SellerSpriteApiError(
            "关联流量 ASIN 未完整写入页面输入框",
            response_excerpt=f"expected={expected_count} actual={placeholder}",
            api_code="ERR_ASSOCIATION_TRAFFIC_ASIN_INPUT",
        )

    query_button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            ".el-button:visible:has-text('立即查询')",
        ],
    )
    if query_button is None:
        return False
    # 官网仅在准备接口成功后展示查询方式弹窗；先解析该响应可保留真实业务错误。
    async with page.expect_response(
        lambda response: _same_endpoint(
            response.url,
            "/v3/api/relation/traffic/prepare",
        ),
        timeout=15000,
    ) as prepare_info:
        await query_button.click(timeout=5000)
    prepare_response = await prepare_info.value
    await _parse_response(
        prepare_response,
        method="POST",
        root_dir=root_dir,
        section="association_traffic_prepare",
    )

    all_variants_button = None
    for _ in range(30):
        all_variants_button = await _first_visible_page_locator(
            page,
            [
                "button:visible:has-text('用全部变体查询')",
                "[role='button']:visible:has-text('用全部变体查询')",
                ".el-button:visible:has-text('用全部变体查询')",
            ],
        )
        if all_variants_button is not None:
            break
        await page.wait_for_timeout(500)
    if all_variants_button is None:
        raise SellerSpriteApiError(
            "关联流量页面未出现“用全部变体查询”按钮",
            api_code="ERR_ASSOCIATION_TRAFFIC_VARIANT_DIALOG",
        )
    await all_variants_button.click(timeout=5000)
    return True


async def _prepare_keyword_conversion_rate_query(
    page,
    payload: dict[str, Any],
) -> Any | None:
    """逐条提交并校验关键词标签，返回尚未点击的查询按钮。"""
    keywords = [
        part.strip()
        for part in str(payload.get("keyword") or "").split(",")
        if part.strip()
    ]
    if not keywords:
        return None

    await _select_keyword_conversion_rate_filters(page, payload)

    clear_button = await _first_visible_page_locator(
        page,
        [
            ".multi-miner:visible button:visible:has-text('清除')",
            "button:visible:has-text('清除')",
        ],
    )
    if clear_button is not None:
        await clear_button.click(timeout=5000)
        await page.wait_for_timeout(200)

    tags = page.locator(
        ".multi-miner:visible .kcr--tags-list .el-tag:visible"
    )
    if await tags.count():
        raise SellerSpriteApiError(
            "关键词转化率页面未清空既有关键词",
            api_code="ERR_KEYWORD_CONVERSION_RATE_CLEAR",
        )

    input_box = await _first_visible_page_locator(
        page,
        [
            ".multi-miner:visible .batch-input "
            "input[aria-autocomplete='list']:visible:not([readonly]):not([disabled])",
            ".batch-input input[role='textbox']:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        return None

    for expected_count, keyword in enumerate(keywords, start=1):
        await input_box.fill(keyword)
        press_error: Exception | None = None
        try:
            # 每个词组只发送一次 Enter；异常后只检查标签状态，绝不补按。
            await input_box.press("Enter", timeout=5000)
        except Exception as exc:
            press_error = exc

        actual_count = await tags.count()
        for _ in range(20):
            if actual_count == expected_count:
                break
            await page.wait_for_timeout(100)
            actual_count = await tags.count()
        if actual_count != expected_count:
            raise SellerSpriteApiError(
                "关键词转化率关键词未完整提交为页面标签",
                response_excerpt=(
                    f"expected={expected_count} actual={actual_count} "
                    f"press_error={type(press_error).__name__ if press_error else 'none'}"
                ),
                api_code="ERR_KEYWORD_CONVERSION_RATE_INPUT",
                api_message="未重复发送 Enter，避免误提交或重复标签。",
            ) from press_error

    placeholder = await input_box.get_attribute("placeholder")
    expected_placeholder = f"已录入{len(keywords)}/1000个关键词"
    if str(placeholder or "").strip() != expected_placeholder:
        raise SellerSpriteApiError(
            "关键词转化率页面关键词计数与输入不一致",
            response_excerpt=(
                f"expected={expected_placeholder} actual={placeholder}"
            ),
            api_code="ERR_KEYWORD_CONVERSION_RATE_INPUT",
            api_message="未点击查询，避免使用不完整关键词集合。",
        )

    query_button = await _first_visible_page_locator(
        page,
        [
            ".multi-miner:visible button.el-button--primary:visible:has-text('立即查询')",
            "button:visible:has-text('立即查询')",
        ],
    )
    if query_button is None:
        return None
    return query_button


async def _select_keyword_conversion_rate_filters(
    page,
    payload: dict[str, Any],
) -> None:
    """在录入关键词前选择站点和按周/近90天周期。"""
    market_label = {
        "US": "美国站",
        "JP": "日本站",
        "UK": "英国站",
        "DE": "德国站",
        "FR": "法国站",
        "IT": "意大利",
        "ES": "西班牙",
        "CA": "加拿大",
        "IN": "印度站",
    }.get(str(payload.get("market") or "US").upper())
    if market_label is None:
        raise SellerSpriteApiError(
            "关键词转化率页面不支持当前站点",
            response_excerpt=f"market={payload.get('market')}",
            api_code="ERR_KEYWORD_CONVERSION_RATE_MARKET",
        )
    market_select = await _first_visible_page_locator(
        page,
        [
            ".multi-miner:visible .market-select > "
            ".el-select:not(.interval-select) "
            "input[placeholder='请选择']:visible",
            ".multi-miner:visible .market-select input[readonly]:visible",
        ],
    )
    if market_select is None:
        raise SellerSpriteApiError(
            "关键词转化率页面未找到站点选择器",
            api_code="ERR_KEYWORD_CONVERSION_RATE_MARKET",
        )
    await market_select.click(timeout=5000)
    market_option = await _first_visible_page_locator(
        page,
        [
            f"li.el-select-dropdown__item:visible:has-text('{market_label}')",
            f".el-select-dropdown__item:visible:has-text('{market_label}')",
        ],
    )
    if market_option is None:
        raise SellerSpriteApiError(
            f"关键词转化率页面未找到“{market_label}”站点",
            api_code="ERR_KEYWORD_CONVERSION_RATE_MARKET",
        )
    await market_option.click(timeout=5000)
    await page.wait_for_timeout(100)

    period_label = "近90天" if payload.get("timeType") == "90D" else "按周"
    period_select = await _first_visible_page_locator(
        page,
        [
            ".multi-miner:visible .market-select > "
            ".el-select.interval-select "
            "input[placeholder='请选择']:visible",
            ".multi-miner:visible .interval-select input[readonly]:visible",
        ],
    )
    if period_select is None:
        raise SellerSpriteApiError(
            "关键词转化率页面未找到周期选择器",
            api_code="ERR_KEYWORD_CONVERSION_RATE_PERIOD",
        )
    await period_select.click(timeout=5000)
    period_option = await _first_visible_page_locator(
        page,
        [
            f"li.el-select-dropdown__item:visible:has-text('{period_label}')",
            f".el-select-dropdown__item:visible:has-text('{period_label}')",
        ],
    )
    if period_option is None:
        raise SellerSpriteApiError(
            f"关键词转化率页面未找到“{period_label}”周期",
            api_code="ERR_KEYWORD_CONVERSION_RATE_PERIOD",
        )
    await period_option.click(timeout=5000)
    await page.wait_for_timeout(100)


async def _trigger_traffic_extend_query(
    page,
    payload: dict[str, Any],
    *,
    endpoint: str,
    variant_selection: str,
    root_dir: Path,
) -> Any:
    """填写拓展流量词条件并选择指定变体模式。"""
    asin_values = payload.get("originAsinList") or payload.get("asinList")
    asins = (
        [str(value).strip().upper() for value in asin_values if str(value).strip()]
        if isinstance(asin_values, list)
        else []
    )
    if not asins:
        return False
    await _select_traffic_extend_period(page, payload.get("month"))
    input_box = await _first_visible_page_locator(
        page,
        [
            "textarea[placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        return False
    await input_box.fill(" ".join(asins))

    query_button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            ".el-button:visible:has-text('立即查询')",
        ],
    )
    if query_button is None:
        return False
    # prepare 的业务结果决定弹窗是否可用；必须先完成解析，失败时不得继续点击变体。
    async with page.expect_response(
        lambda response: _same_endpoint(
            response.url,
            "/v3/api/traffic/extend/prepare",
        ),
        timeout=15000,
    ) as prepare_info:
        await query_button.click(timeout=5000)
    prepare_response = await prepare_info.value
    await _parse_response(
        prepare_response,
        method="POST",
        root_dir=root_dir,
        section="traffic_extend_prepare",
    )

    button_text = {
        "sell_well": "用畅销变体拓词",
        "current": "用当前变体拓词",
    }.get(variant_selection, "用全部变体拓词")
    variant_button = None
    # Element UI 弹窗有过渡动画，最多等待 15 秒；期间不占用主接口响应预算。
    for _ in range(30):
        variant_button = await _first_visible_page_locator(
            page,
            [
                f"button:visible:has-text('{button_text}')",
                f"[role='button']:visible:has-text('{button_text}')",
                f".el-button:visible:has-text('{button_text}')",
            ],
        )
        if variant_button is not None:
            break
        await page.wait_for_timeout(500)
    if variant_button is None:
        raise SellerSpriteApiError(
            f"拓展流量词页面未出现“{button_text}”按钮",
            api_code="ERR_TRAFFIC_EXTEND_VARIANT_DIALOG",
        )
    # 只在最终按钮点击前监听主接口，并且只点击一次，避免重复查询。
    async with page.expect_response(
        lambda response: _same_endpoint(response.url, endpoint),
        timeout=DEFAULT_TIMEOUT_MS,
    ) as main_info:
        await variant_button.click(timeout=5000)
    return await main_info.value


async def _select_traffic_extend_period(page, month: Any) -> None:
    """在点击 prepare 前同步历史周期，最近 30 天无需操作页面。"""
    text = str(month or "").strip()
    if not text:
        return
    if re.fullmatch(r"\d{6}", text):
        text = f"{text[:4]}-{text[4:]}"
    period_select = await _first_visible_page_locator(
        page,
        [".date-select input[placeholder='请选择']:visible"],
    )
    if period_select is None:
        raise SellerSpriteApiError(
            "拓展流量词页面未找到周期选择器",
            api_code="ERR_TRAFFIC_EXTEND_PERIOD_SELECT",
        )
    await period_select.click(timeout=5000)
    period_option = await _first_visible_page_locator(
        page,
        [
            f".el-select-dropdown__item:visible:has-text('{text}')",
        ],
    )
    if period_option is None:
        raise SellerSpriteApiError(
            f"拓展流量词页面不支持周期：{text}",
            api_code="ERR_TRAFFIC_EXTEND_PERIOD_OPTION",
        )
    # 周期由页面状态写入 prepare；主请求重写不能替代这一步，否则畅销变体范围会错期。
    await period_option.click(timeout=5000)


async def _first_visible_page_locator(page, selectors: list[str]):
    """返回页面中第一个可见 locator。"""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=800):
                return locator
        except Exception:
            continue
    return None


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


async def _solve_robot_image_captcha(
    page,
    *,
    settings: SellerSpriteSettings,
    stage: str,
) -> dict[str, Any] | None:
    """检测并处理卖家精灵机器人检测图片验证码。"""
    if not settings.browser_captcha_ocr_enabled:
        return None
    dialog = await _robot_captcha_dialog(page)
    if dialog is None:
        return None
    provider = create_captcha_ocr_provider()
    max_attempts = max(settings.browser_captcha_ocr_max_attempts, 1)
    for attempt in range(1, max_attempts + 1):
        image = await _first_visible_locator(dialog, ROBOT_CAPTCHA_IMAGE_SELECTORS)
        input_box = await _first_visible_locator(dialog, ROBOT_CAPTCHA_INPUT_SELECTORS)
        confirm_button = await _first_visible_locator(dialog, ROBOT_CAPTCHA_CONFIRM_SELECTORS)
        if image is None or input_box is None or confirm_button is None:
            raise SellerSpriteConfigError(f"卖家精灵机器人检测验证码结构不完整，stage={stage}")
        image_bytes = await _captcha_image_bytes(image)
        answer = provider.recognize(image_bytes)
        if not answer:
            if attempt < max_attempts:
                await image.click(timeout=3000)
                await page.wait_for_timeout(ROBOT_CAPTCHA_SETTLE_TIMEOUT_MS)
                continue
            raise SellerSpriteConfigError(f"卖家精灵机器人检测验证码 OCR 未返回有效结果，stage={stage} attempts={attempt}")
        await input_box.fill(answer)
        await confirm_button.click(timeout=5000)
        await page.wait_for_timeout(ROBOT_CAPTCHA_SETTLE_TIMEOUT_MS)
        if not await _robot_captcha_visible(page):
            return {"provider": provider.name, "attempts": attempt}
        if attempt < max_attempts:
            await image.click(timeout=3000)
            await page.wait_for_timeout(ROBOT_CAPTCHA_SETTLE_TIMEOUT_MS)
    raise SellerSpriteConfigError(f"卖家精灵机器人检测验证码 OCR 处理后仍未通过，stage={stage} attempts={max_attempts}")


async def _robot_captcha_visible(page) -> bool:
    return await _robot_captcha_dialog(page) is not None


async def _robot_captcha_dialog(page):
    if not hasattr(page, "locator"):
        return None
    for selector in ROBOT_CAPTCHA_DIALOG_SELECTORS:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=TEXT_DETECT_TIMEOUT_MS):
                return locator
        except Exception:
            continue
    return None


async def _first_visible_locator(scope, selectors: list[str]):
    for selector in selectors:
        locator = scope.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=800):
                return locator
        except Exception:
            continue
    return None


async def _captcha_image_bytes(image) -> bytes:
    try:
        src = await image.get_attribute("src")
    except Exception:
        src = None
    if src and src.startswith("data:image/") and "," in src:
        try:
            return base64.b64decode(src.split(",", 1)[1])
        except Exception:
            pass
    return await image.screenshot()


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
    if method in {"GET_XLSX", "POST_XLSX"}:
        content = await response.body()
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type") or "").lower()
        text_excerpt = (
            content[:1000].decode("utf-8", errors="replace")
            if "text" in content_type or "html" in content_type or "json" in content_type
            else ""
        )
        if _looks_like_session_expired(response.url, response.status, text_excerpt):
            raise SellerSpriteApiError(
                "卖家精灵浏览器登录态失效",
                status_code=response.status,
                response_excerpt=text_excerpt,
                api_code="ERR_GLOBAL_SESSION_EXPIRED",
            )
        if response.status >= 400:
            raise SellerSpriteApiError(
                "卖家精灵浏览器文件下载失败",
                status_code=response.status,
                response_excerpt=text_excerpt or f"content_type={content_type} content_length={len(content)}",
            )
        normalized_content_type = content_type.partition(";")[0].strip()
        # 同时校验 MIME、最小长度和 ZIP 签名，避免把登录页或 JSON 错误体保存成 XLSX。
        if (
            normalized_content_type not in XLSX_CONTENT_TYPES
            or len(content) < MIN_XLSX_CONTENT_LENGTH
            or not content.startswith(b"PK")
        ):
            raise SellerSpriteApiError(
                "卖家精灵浏览器文件下载未返回 XLSX",
                status_code=response.status,
                response_excerpt=text_excerpt or f"content_type={content_type} content_length={len(content)}",
                api_code="ERR_SELLER_SPRITE_XLSX_INVALID",
            )
        official_filename = _safe_response_filename(
            _response_filename(headers.get("content-disposition"))
        )
        if section == "main":
            response_filename = official_filename
            if len(str(root_dir / response_filename)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
                response_filename = "export.xlsx"
        else:
            response_filename = f"{section}.xlsx"
        response_path = root_dir / response_filename
        response_path.write_bytes(content)
        return {
            "code": "OK",
            "data": {
                "official_xlsx_path": str(response_path),
                "official_filename": official_filename,
                "content_length": len(content),
            },
        }
    if method in {"FORM", "GET_PAGE"}:
        text = await response.text()
        if _looks_like_session_expired(response.url, response.status, text):
            raise SellerSpriteApiError(
                "卖家精灵浏览器登录态失效",
                status_code=response.status,
                response_excerpt=text[:1000],
                api_code="ERR_GLOBAL_SESSION_EXPIRED",
            )
        if response.status >= 400:
            request_kind = "页面" if method == "GET_PAGE" else "表单"
            raise SellerSpriteApiError(
                f"卖家精灵浏览器{request_kind}请求失败",
                status_code=response.status,
                response_excerpt=text[:1000],
            )
        response_html_path = root_dir / ("response.html" if section == "main" else f"{section}.html")
        response_html_path.write_text(text, encoding="utf-8")
        rows = parse_keyword_research_html(text) if method == "GET_PAGE" else parse_market_research_html(text)
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


async def _wait_for_login_success(page, *, callback: str) -> None:
    callback_url = _absolute_callback_url(callback)
    try:
        await page.wait_for_url(
            lambda url: not _is_login_url(str(url)) or _same_page_url(str(url), callback_url),
            timeout=LOGIN_SUCCESS_TIMEOUT_MS,
        )
    except Exception:
        pass
    await page.wait_for_timeout(LOGIN_SETTLE_TIMEOUT_MS)


async def _detect_logged_in(page) -> bool:
    if _is_login_url(page.url):
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
        return await locator.is_visible(timeout=TEXT_DETECT_TIMEOUT_MS)
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


def _listing_analysis_report_url(task_id: str) -> str:
    """构造 Listing Analysis 历史报告详情页地址。"""
    return f"{BASE_URL}/v3/ai-report?id={quote(str(task_id).strip())}&from=history"


def _absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{BASE_URL}{url if url.startswith('/') else '/' + url}"


def _route_pattern(endpoint: str) -> str:
    path = urlparse(_absolute_url(endpoint)).path
    return f"**{path}*"


def _same_endpoint(url: str, endpoint: str) -> bool:
    return urlparse(url).path == urlparse(_absolute_url(endpoint)).path


def _is_keyword_comparison_post_request(request) -> bool:
    """识别变体按钮点击后产生的流量词对比 POST，仅检查方法和脱敏路径。"""
    path = urlparse(request.url).path
    return (
        str(request.method).upper() == "POST"
        and path.startswith("/v3/api/keyword-comparison/")
        and path != "/v3/api/keyword-comparison/prepare"
    )


async def _keyword_comparison_button_diagnostics(button) -> dict[str, Any]:
    """读取变体按钮的脱敏 DOM 状态和事件计数，不采集页面文本或请求数据。"""
    try:
        result = await button.evaluate(
            """element => {
                const elementKey = '__opscliKeywordComparisonElementDiagnostics';
                const pageKey = '__opscliKeywordComparisonPageDiagnostics';
                if (!element[elementKey]) {
                    const events = {
                        clickCount: 0,
                        keydownCount: 0,
                        keyupCount: 0,
                        mousedownCount: 0,
                        mouseupCount: 0,
                        pointerdownCount: 0,
                        pointerupCount: 0,
                        clickTrusted: null,
                        clickDetail: null,
                    };
                    element.addEventListener('click', event => {
                        events.clickCount += 1;
                        events.clickTrusted = event.isTrusted;
                        events.clickDetail = event.detail;
                    }, true);
                    element.addEventListener('keydown', () => events.keydownCount += 1, true);
                    element.addEventListener('keyup', () => events.keyupCount += 1, true);
                    element.addEventListener('mousedown', () => events.mousedownCount += 1, true);
                    element.addEventListener('mouseup', () => events.mouseupCount += 1, true);
                    element.addEventListener('pointerdown', () => events.pointerdownCount += 1, true);
                    element.addEventListener('pointerup', () => events.pointerupCount += 1, true);
                    element[elementKey] = events;
                }
                if (!window[pageKey]) {
                    const pageEvents = {errorCount: 0, rejectionCount: 0};
                    window.addEventListener('error', () => pageEvents.errorCount += 1, true);
                    window.addEventListener(
                        'unhandledrejection',
                        () => pageEvents.rejectionCount += 1,
                        true,
                    );
                    window[pageKey] = pageEvents;
                }
                const isVisible = node => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const dialog = element.closest('[role="dialog"], .el-dialog');
                const events = element[elementKey];
                const pageEvents = window[pageKey];
                return {
                    connected: element.isConnected,
                    visible: isVisible(element),
                    enabled: !element.disabled
                        && element.getAttribute('aria-disabled') !== 'true',
                    focused: document.activeElement === element,
                    dialogVisible: isVisible(dialog),
                    clickCount: events.clickCount,
                    keydownCount: events.keydownCount,
                    keyupCount: events.keyupCount,
                    mousedownCount: events.mousedownCount,
                    mouseupCount: events.mouseupCount,
                    pointerdownCount: events.pointerdownCount,
                    pointerupCount: events.pointerupCount,
                    clickTrusted: events.clickTrusted,
                    clickDetail: events.clickDetail,
                    pageErrorCount: pageEvents.errorCount,
                    rejectionCount: pageEvents.rejectionCount,
                };
            }"""
        )
    except Exception as exc:
        return {"snapshotError": type(exc).__name__}
    if not isinstance(result, dict):
        return {"snapshotError": "InvalidResult"}
    return {
        key: result.get(key)
        for key in (
            "connected",
            "visible",
            "enabled",
            "focused",
            "dialogVisible",
            "clickCount",
            "keydownCount",
            "keyupCount",
            "mousedownCount",
            "mouseupCount",
            "pointerdownCount",
            "pointerupCount",
            "clickTrusted",
            "clickDetail",
            "pageErrorCount",
            "rejectionCount",
        )
        if key in result
    }


async def _log_keyword_comparison_diagnostics(
    button,
    *,
    phase: str,
) -> str:
    """输出统一标记的脱敏交互诊断，并返回可放入错误摘要的 JSON。"""
    diagnostic = {
        "phase": phase,
        "button": await _keyword_comparison_button_diagnostics(button),
    }
    serialized = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
    logger.warning("%s %s", KEYWORD_COMPARISON_DIAGNOSTIC_TAG, serialized)
    return serialized[:900]


def _looks_like_guest_limited_association_response(
    response: dict[str, Any],
    *,
    page_size: Any,
) -> bool:
    """判断关联流量响应是否被游客权限固定截断为 20 条。"""
    try:
        requested_size = int(page_size)
    except (TypeError, ValueError):
        requested_size = 100
    if requested_size <= 20:
        return False
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return False
    pager = data.get("pagerDto")
    if not isinstance(pager, dict):
        return False
    items = pager.get("items")
    try:
        returned_size = int(pager.get("size"))
    except (TypeError, ValueError):
        returned_size = 0
    return bool(
        isinstance(items, list)
        and len(items) == 20
        and (
            returned_size == 20
            or data.get("guestId")
            or data.get("guestVisited") is True
        )
    )


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


def _safe_response_filename(value: str | None) -> str:
    filename = re.split(r"[/\\]", str(value or ""))[-1].strip()
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)
    filename = re.sub(r'[<>:"|?*]+', "-", filename).rstrip(". ")
    if not filename or filename in {".", ".."}:
        return "official-export.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    stem = filename[:-5].rstrip(". ")
    reserved_name = stem.split(".", 1)[0]
    if WINDOWS_RESERVED_FILENAME_PATTERN.fullmatch(reserved_name):
        filename = f"official-{filename}"
    return filename


def _response_filename(value: str | None) -> str | None:
    if not value:
        return None
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    quoted = re.search(r'filename="([^"]+)"', value, re.I)
    plain = re.search(r"filename=([^;]+)", value, re.I)
    match = encoded or quoted or plain
    if not match:
        return None
    filename = unquote(match.group(1).strip().strip('"'))
    return Path(filename).name or None


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:40] or "default"
