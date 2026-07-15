"""卖家精灵多账号并行任务调度器与冷备用接替编排。"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from opscli.seller_sprite.accounts import SellerSpriteAccount, SellerSpriteAccountProvider
from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteAccountUnavailableError,
    SellerSpriteApiError,
    SellerSpriteAuthenticationError,
)
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder
from opscli.seller_sprite.services.account_pool import SellerSpriteAccountPool, seller_sprite_account_key
from opscli.seller_sprite.services.api_manager import SellerSpriteApiManager, _build_job_id
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore
from opscli.seller_sprite.services.task_status import error_to_dict


QUEUE_SCOPE = "seller_sprite"
DEFAULT_WORKER_KEY = "default"
# 一分钟检查一次足以覆盖 30 分钟空闲阈值，同时避免高频扫描 browser registry。
DEFAULT_SESSION_REAP_INTERVAL_SECONDS = 60.0
_SCHEDULERS: dict[tuple[int, str], "SellerSpriteTaskScheduler"] = {}
logger = logging.getLogger(__name__)


class SellerSpriteTaskScheduler:
    """负责单账号 FIFO 排队和后台消费。"""

    def __init__(
        self,
        *,
        store: SellerSpriteTaskQueueStore | None = None,
        settings: SellerSpriteSettings | None = None,
        account_provider=None,
        manager_factory: Callable[..., SellerSpriteApiManager] | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
        auto_start: bool = True,
        poll_interval_seconds: float = 0.05,
        session_reap_interval_seconds: float = DEFAULT_SESSION_REAP_INTERVAL_SECONDS,
    ) -> None:
        self.settings = settings or load_settings()
        self.account_provider = account_provider
        self.store = store or SellerSpriteTaskQueueStore()
        self.jwt = jwt
        self.session_id = session_id
        self.auto_start = auto_start
        self.poll_interval_seconds = poll_interval_seconds
        self.session_reap_interval_seconds = max(0.01, float(session_reap_interval_seconds))
        self.manager_factory = manager_factory or self._default_manager_factory
        self._runner_task: asyncio.Task | None = None
        self._generic_worker_tasks: dict[str, asyncio.Task] = {}
        self._generic_worker_accounts: dict[str, SellerSpriteAccount] = {}
        self._listing_worker_task: asyncio.Task | None = None
        self._account_pool = SellerSpriteAccountPool()
        self._pool_lock = asyncio.Lock()
        self._event_recorder = SellerSpriteAccountEventRecorder(store=self.store)
        self._next_worker_slot_number = 1
        self._last_account_refresh_at = 0.0
        self._last_session_reap_at = 0.0
        self._start_lock = asyncio.Lock()
        self._stop_requested = False
        self._legacy_single_account_mode = bool(
            account_provider is not None and not callable(getattr(account_provider, "list_accounts", None))
        )

    @property
    def generic_worker_count(self) -> int:
        """返回当前仍在运行的通用账号工作槽数量。"""
        return sum(not task.done() for task in self._generic_worker_tasks.values())

    @property
    def standby_account_count(self) -> int:
        """返回尚未创建工作会话的冷备用账号数量。"""
        return len(self._account_pool.standby_accounts)

    async def enqueue(
        self,
        request: SellerSpriteScenarioRequest,
        *,
        mcp_user_email: str | None = None,
    ) -> dict[str, Any]:
        """入队并按需启动后台调度循环，可原子记录 MCP 所有权。"""
        normalized = self._normalize_request(request)
        root_dir = self._build_root_dir(normalized)
        if mcp_user_email:
            # 公共 MCP 提交必须让队列行和所有权行同成同败，避免碰撞后错误授权。
            status = self.store.enqueue_owned_mcp_run(
                request=normalized,
                queue_scope=QUEUE_SCOPE,
                root_dir=root_dir,
                user_email=mcp_user_email,
                session_id=self.session_id,
                jwt=self.jwt,
            )
        else:
            status = self.store.enqueue(
                request=normalized,
                queue_scope=QUEUE_SCOPE,
                root_dir=root_dir,
                session_id=self.session_id,
                jwt=self.jwt,
            )
        if self.auto_start:
            await self.start()
        return status

    async def start(self) -> None:
        """启动后台调度循环，不隐式修改持久队列中的运行任务。"""
        async with self._start_lock:
            if self._runner_task and not self._runner_task.done():
                return
            self._stop_requested = False
            if self._legacy_single_account_mode:
                self._runner_task = asyncio.create_task(self._run_loop())
                return
            await self._initialize_account_pool()
            self._start_generic_workers()
            self._start_listing_worker()
            self._runner_task = asyncio.create_task(self._run_pool_supervisor())

    async def close(self) -> None:
        """停止后台调度循环。"""
        self._stop_requested = True
        if self._runner_task is None:
            return
        await self._runner_task
        self._runner_task = None
        pending = [
            task
            for task in [*self._generic_worker_tasks.values(), self._listing_worker_task]
            if task is not None
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        from opscli.seller_sprite.browser_route.worker import close_all_browser_route_workers

        await close_all_browser_route_workers(
            settings=self.settings,
            reason="scheduler_close",
            state_listener=self._record_browser_session_state_change,
        )
        self._generic_worker_tasks.clear()
        self._generic_worker_accounts.clear()
        self._listing_worker_task = None

    async def _initialize_account_pool(self) -> None:
        """首次读取账号接口并建立工作账号和冷备用账号。"""
        provider = self._ensure_account_provider()
        try:
            accounts = provider.list_accounts()
        except Exception as exc:
            # 首次账号接口失败时保持任务 queued，由 supervisor 后续继续刷新。
            self._event_recorder.record_account_fetch_failure(
                error=exc,
                next_action="keep_queued_until_next_ttl_refresh",
            )
            accounts = []
        self._account_pool.load(accounts)
        self._last_account_refresh_at = time.monotonic()

    def _start_generic_workers(self) -> None:
        """为账号池中的每个工作账号创建一个长期消费协程。"""
        active_account_keys = {
            seller_sprite_account_key(account)
            for worker_key, account in self._generic_worker_accounts.items()
            if worker_key in self._generic_worker_tasks
            and not self._generic_worker_tasks[worker_key].done()
        }
        for account in self._account_pool.working_accounts:
            if seller_sprite_account_key(account) in active_account_keys:
                continue
            worker_key = f"seller-sprite-slot-{self._next_worker_slot_number}"
            self._next_worker_slot_number += 1
            self._generic_worker_accounts[worker_key] = account
            self._generic_worker_tasks[worker_key] = asyncio.create_task(
                self._run_generic_worker(worker_key, account)
            )

    def _start_listing_worker(self) -> None:
        """为 Listing Analysis 保留独立的单账号串行消费协程。"""
        if not self._account_pool.working_accounts:
            return
        self._listing_worker_task = asyncio.create_task(self._run_listing_worker())

    async def _run_pool_supervisor(self) -> None:
        """维护账号工作槽生命周期，并在无账号时周期重试账号接口。"""
        while not self._stop_requested:
            self._remove_finished_generic_workers()
            now = time.monotonic()
            refresh_interval = max(1.0, float(self.settings.account_cache_ttl_seconds))
            refresh_due = now - self._last_account_refresh_at >= refresh_interval
            if refresh_due:
                await self._refresh_account_pool()
            if now - self._last_session_reap_at >= self.session_reap_interval_seconds:
                await self._reap_browser_sessions()
            await asyncio.sleep(self.poll_interval_seconds)

    def _remove_finished_generic_workers(self) -> None:
        """清理已退出工作槽的 Task 引用，允许后续账号刷新重建槽。"""
        finished = [
            worker_key
            for worker_key, task in self._generic_worker_tasks.items()
            if task.done()
        ]
        for worker_key in finished:
            task = self._generic_worker_tasks.pop(worker_key, None)
            if task is not None and not task.cancelled():
                error = task.exception()
                if error is not None:
                    logger.error(
                        "卖家精灵账号工作槽异常退出：worker_key=%s",
                        worker_key,
                        exc_info=(type(error), error, error.__traceback__),
                    )
            self._generic_worker_accounts.pop(worker_key, None)

    async def _refresh_account_pool(self) -> None:
        """刷新账号接口，并用新账号或新凭证版本补足空工作槽。"""
        provider = self._ensure_account_provider()
        try:
            accounts = provider.list_accounts(refresh=True)
        except Exception as exc:
            self._event_recorder.record_account_fetch_failure(
                error=exc,
                next_action="keep_queued_until_next_ttl_refresh",
            )
            self._last_account_refresh_at = time.monotonic()
            return
        self._last_account_refresh_at = time.monotonic()
        async with self._pool_lock:
            self._account_pool.refresh(accounts)
            self._account_pool.activate_standby_until_target()
            self._start_generic_workers()
        if self._listing_worker_task is None or self._listing_worker_task.done():
            self._start_listing_worker()

    async def _run_generic_worker(self, worker_key: str, initial_account: SellerSpriteAccount) -> None:
        """使用独立账号会话串行消费通用任务，认证失败时有限接替。"""
        account = initial_account
        while not self._stop_requested:
            if not self._is_working_account(account):
                await self._close_account_session(account, reason="account_removed_or_rebalanced")
                return
            claimed = self.store.claim_next_generic_for_account(
                queue_scope=QUEUE_SCOPE,
                account_key=seller_sprite_account_key(account),
                assigned_account=account.name,
                worker_key=worker_key,
            )
            if claimed is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            replacement = await self._run_generic_job(
                claimed=claimed,
                account=account,
                worker_key=worker_key,
            )
            # 每条任务结束后形成安全边界，使满 6 小时的会话无需等待下一分钟扫描。
            await self._reap_browser_sessions()
            if replacement is None:
                return
            account = replacement
            self._generic_worker_accounts[worker_key] = account

    async def _run_generic_job(
        self,
        *,
        claimed: dict[str, Any],
        account: SellerSpriteAccount,
        worker_key: str,
    ) -> SellerSpriteAccount | None:
        """执行一条通用任务，并在明确认证失败时改绑冷备用账号。"""
        job_id = str(claimed["job_id"])
        attempted_accounts: set[SellerSpriteAccount] = set()
        status = claimed
        while True:
            account_key = seller_sprite_account_key(account)
            attempted_accounts.add(account)
            generation = int(status["assignment_generation"])
            failover_count = int(status["failover_count"])
            request = self.store.get_request(job_id)
            attempt_dir = (
                Path(str(status["root_dir"]))
                / "attempts"
                / f"generation-{generation}"
            )
            request = replace(request, attempt_output_dir=str(attempt_dir))
            context = self.store.get_task_context(job_id)
            has_mcp_run = self._has_mcp_run(job_id)
            manager = self.manager_factory(
                settings=self.settings,
                account_provider=_FixedSellerSpriteAccountProvider(account),
                jwt=context["jwt"],
                session_id=context["session_id"],
            )
            started_at = time.monotonic()
            try:
                if has_mcp_run and failover_count == 0:
                    self.store.mark_mcp_run_running(job_id)
                result = await manager.run(request)
                export_payload = self._build_mcp_export_payload(request, result)
                self.store.finish_task_and_mcp_run_if_current(
                    job_id=job_id,
                    account_key=account_key,
                    assignment_generation=generation,
                    result_path=result.result_path,
                    row_count=result.row_count,
                    export_payload=result.export.to_dict() if result.export else None,
                    mcp_export_payload=export_payload if has_mcp_run else None,
                )
                return account
            except Exception as exc:
                if not _is_account_authentication_failure(exc):
                    await self._fail_generic_job(
                        job_id=job_id,
                        account_key=account_key,
                        generation=generation,
                        error=exc,
                        has_mcp_run=has_mcp_run,
                    )
                    return account

                login_stage = _login_stage(exc, failover_count)
                self._event_recorder.record_login_failure(
                    account=account,
                    job_id=job_id,
                    worker_key=worker_key,
                    assignment_generation=generation,
                    execution_mode=str(request.mode or self.settings.default_mode),
                    login_stage=login_stage,
                    error=exc,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                    failover_count=failover_count,
                    next_action="refresh_accounts",
                )
                replacement = await self._select_replacement_account(
                    failed_account=account,
                    attempted_accounts=attempted_accounts,
                )
                if replacement is None:
                    unavailable = SellerSpriteAccountUnavailableError(
                        "卖家精灵工作账号失效，且没有可用备用账号"
                    )
                    await self._fail_generic_job(
                        job_id=job_id,
                        account_key=account_key,
                        generation=generation,
                        error=unavailable,
                        has_mcp_run=has_mcp_run,
                    )
                    await self._close_account_session(account, reason="authentication_failed")
                    return None
                reassigned = self.store.reassign_task_for_failover(
                    job_id=job_id,
                    current_account_key=account_key,
                    current_generation=generation,
                    replacement_account_key=seller_sprite_account_key(replacement),
                    replacement_account=replacement.name,
                    worker_key=worker_key,
                    error_code=str(getattr(exc, "code", type(exc).__name__)),
                    retry_reason="account_authentication_failed",
                )
                if reassigned is None:
                    return None
                await self._close_account_session(account, reason="authentication_failed")
                account = replacement
                status = reassigned

    async def _select_replacement_account(
        self,
        *,
        failed_account: SellerSpriteAccount,
        attempted_accounts: set[SellerSpriteAccount],
    ) -> SellerSpriteAccount | None:
        """刷新账号接口后按原顺序选择未被当前任务尝试的冷备用。"""
        async with self._pool_lock:
            self._account_pool.mark_unavailable(failed_account)
            provider = self._ensure_account_provider()
            try:
                refreshed = provider.list_accounts(refresh=True)
            except Exception as exc:
                self._event_recorder.record_account_fetch_failure(
                    error=exc,
                    next_action="try_cached_standby",
                )
                refreshed = []
            if refreshed:
                self._account_pool.refresh(refreshed)
            return self._account_pool.take_standby(
                attempted_accounts=attempted_accounts
            )

    def _is_working_account(self, account: SellerSpriteAccount) -> bool:
        """判断账号当前是否仍占用工作槽；缩容账号会在任务边界退出。"""
        account_key = seller_sprite_account_key(account)
        return any(
            seller_sprite_account_key(current) == account_key
            for current in self._account_pool.working_accounts
        )

    async def _fail_generic_job(
        self,
        *,
        job_id: str,
        account_key: str,
        generation: int,
        error: Exception,
        has_mcp_run: bool,
    ) -> None:
        """使用当前执行令牌标记通用任务失败并同步 MCP 状态。"""
        error_payload = error_to_dict(error)
        self.store.fail_task_and_mcp_run_if_current(
            job_id=job_id,
            account_key=account_key,
            assignment_generation=generation,
            error_payload=error_payload,
            update_mcp_run=has_mcp_run,
        )

    async def _run_listing_worker(self) -> None:
        """串行消费 Listing Analysis，不参与通用账号池 failover。"""
        while not self._stop_requested:
            claimed = self.store.claim_next_listing_analysis(
                queue_scope=QUEUE_SCOPE,
                worker_key="seller-sprite-listing-analysis",
                assigned_account=self._assigned_account_name(),
            )
            if claimed is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            await self._run_one(str(claimed["job_id"]))
            await self._reap_browser_sessions()

    async def _reap_browser_sessions(self) -> None:
        """回收达到空闲或最大生命周期的 browser-route 会话。"""
        from opscli.seller_sprite.browser_route.worker import reap_browser_route_workers

        await reap_browser_route_workers(
            settings=self.settings,
            state_listener=self._record_browser_session_state_change,
        )
        self._last_session_reap_at = time.monotonic()

    async def _close_account_session(
        self,
        account: SellerSpriteAccount,
        *,
        reason: str,
    ) -> None:
        """关闭故障账号会话；会话 registry 接入前不影响任务主错误。"""
        try:
            from opscli.seller_sprite.browser_route.worker import close_browser_route_worker

            await close_browser_route_worker(
                settings=self.settings,
                account=account,
                reason=reason,
                state_listener=self._record_browser_session_state_change,
            )
        except ImportError:
            return
        except Exception:
            logger.warning("关闭卖家精灵故障账号会话失败", exc_info=True)

    def _ensure_account_provider(self) -> SellerSpriteAccountProvider:
        """延迟创建使用当前认证上下文的账号接口 provider。"""
        if self.account_provider is None:
            from opscli.shared.integration_accounts import IntegrationAccountClient

            self.account_provider = SellerSpriteAccountProvider(
                self.settings,
                integration_client=IntegrationAccountClient(
                    jwt=self.jwt,
                    session_id=self.session_id,
                ),
            )
        return self.account_provider

    def job_status(self, job_id: str) -> dict[str, Any]:
        """返回任务当前状态。"""
        status = self.store.get_status(job_id)
        result_path = status.get("result_path")
        if status["state"] != "succeeded" or not result_path:
            return status
        path = Path(str(result_path))
        if not path.exists():
            return status
        payload = json.loads(path.read_text(encoding="utf-8"))
        merged = dict(status)
        merged.update(payload)
        merged.setdefault("state", status["state"])
        merged.setdefault("stage", status["stage"])
        merged.setdefault("position", None)
        return merged

    async def _run_loop(self) -> None:
        while True:
            if self._stop_requested:
                return
            try:
                await self._consume_once()
            except Exception:
                # 调度循环自身异常不能让后台 worker 退出，否则后续 queued 会长期无人消费。
                logger.exception("卖家精灵任务调度循环异常，短暂等待后继续消费")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _consume_once(self) -> None:
        claimed = self.store.claim_next(
            queue_scope=QUEUE_SCOPE,
            worker_key=DEFAULT_WORKER_KEY,
            assigned_account=self._assigned_account_name(),
        )
        if claimed is None:
            await asyncio.sleep(self.poll_interval_seconds)
            return
        job_id = str(claimed["job_id"])
        try:
            await self._run_one(job_id)
        except Exception:
            # 单条任务的审计收尾异常不能拖垮整个后台 worker，记录后继续消费后续任务。
            logger.exception("卖家精灵任务调度执行异常，继续消费后续任务：job_id=%s", job_id)

    async def _run_one(self, job_id: str) -> None:
        request = self.store.get_request(job_id)
        context = self.store.get_task_context(job_id)
        has_mcp_run = self._has_mcp_run(job_id)
        manager = self.manager_factory(
            settings=self.settings,
            account_provider=self.account_provider,
            jwt=context["jwt"],
            session_id=context["session_id"],
        )
        try:
            if has_mcp_run:
                self.store.mark_mcp_run_running(job_id)
            result = await manager.run(request)
            export_payload = self._build_mcp_export_payload(request, result)
            self.store.finish_task(
                job_id=job_id,
                result_path=result.result_path,
                row_count=result.row_count,
                export_payload=result.export.to_dict() if result.export else None,
            )
            if has_mcp_run:
                self.store.finish_mcp_run_success(job_id, result.row_count, export_payload)
        except Exception as exc:
            error_payload = error_to_dict(exc)
            self.store.fail_task(job_id=job_id, error_payload=error_payload)
            if has_mcp_run:
                self.store.finish_mcp_run_failed(job_id, error_payload)

    def _default_manager_factory(self, **kwargs) -> SellerSpriteApiManager:
        return SellerSpriteApiManager(
            **kwargs,
            session_state_listener=self._record_browser_session_state_change,
        )

    def _record_browser_session_state_change(
        self,
        account: SellerSpriteAccount,
        payload: dict[str, Any],
    ) -> None:
        """把 browser worker 的白名单生命周期状态转交统一事件记录器。"""
        self._event_recorder.record_session_state_change(
            account=account,
            previous_state=str(payload.get("previous_state") or "unknown"),
            state=str(payload.get("state") or "unknown"),
            reason=str(payload.get("reason") or "unknown"),
            session_age_seconds=int(payload.get("session_age_seconds") or 0),
            idle_seconds=int(payload.get("idle_seconds") or 0),
            task_count=int(payload.get("task_count") or 0),
            is_busy=bool(payload.get("is_busy")),
            error_code=(str(payload["error_code"]) if payload.get("error_code") else None),
        )

    def _assigned_account_name(self) -> str:
        """返回队列记录里的账号标识，不在领取任务前触发账号接口。"""
        return self.settings.account_name or DEFAULT_WORKER_KEY

    def _normalize_request(self, request: SellerSpriteScenarioRequest) -> SellerSpriteScenarioRequest:
        site = (request.site or self.settings.default_site).upper()
        period = request.period or self.settings.default_period
        job_id = request.job_id or _build_job_id(request, site, period)
        return replace(request, site=site, period=period, job_id=job_id)

    def _build_root_dir(self, request: SellerSpriteScenarioRequest) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / str(request.job_id)

    def _has_mcp_run(self, job_id: str) -> bool:
        """探测任务是否存在 MCP 调用记录。"""
        try:
            self.store.get_mcp_run(job_id)
            return True
        except ValueError:
            return False
        except Exception:
            # MCP 探测阶段以主任务可执行为优先，探测异常按无 MCP 记录降级处理。
            logger.warning("探测 MCP 调用记录失败，按普通任务继续执行：job_id=%s", job_id, exc_info=True)
            return False

    def _build_mcp_export_payload(
        self,
        request: SellerSpriteScenarioRequest,
        result: Any,
    ) -> dict[str, Any]:
        """构造 MCP 成功态所需的导出信息。"""
        if result.export:
            return result.export.to_dict()
        return {
            "format": request.export_format,
            "filename": Path(result.result_path).name,
        }


def get_task_scheduler(
    *,
    settings: SellerSpriteSettings | None = None,
    account_provider=None,
    jwt: str | None = None,
    session_id: str | None = None,
) -> SellerSpriteTaskScheduler:
    """按事件循环和队列库路径复用任务调度器实例。"""
    current_settings = settings or load_settings()
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        # Sync CLI commands do not run inside an event loop, but they still need
        # a stable scheduler instance to read queued task status/export metadata.
        loop_key = -threading.get_ident()
    store_key = str(SellerSpriteTaskQueueStore().db_path.resolve())
    key = (loop_key, store_key)
    scheduler = _SCHEDULERS.get(key)
    if scheduler is None:
        scheduler = SellerSpriteTaskScheduler(
            settings=current_settings,
            account_provider=account_provider,
            jwt=jwt,
            session_id=session_id,
        )
        _SCHEDULERS[key] = scheduler
        return scheduler
    if jwt:
        scheduler.jwt = jwt
    if session_id:
        scheduler.session_id = session_id
    return scheduler


class _FixedSellerSpriteAccountProvider:
    """让单个工作槽中的 manager 始终使用显式绑定账号。"""

    def __init__(self, account: SellerSpriteAccount) -> None:
        self.account = account

    def get_default(self, *, refresh: bool = False) -> SellerSpriteAccount:
        """返回工作槽绑定账号，不在 manager 内部选择备用账号。"""
        return self.account

    def list_accounts(self, *, refresh: bool = False) -> list[SellerSpriteAccount]:
        """返回仅含绑定账号的列表，阻止 manager 自行跨账号切换。"""
        return [self.account]


def _is_account_authentication_failure(exc: Exception) -> bool:
    """仅识别可确认未通过认证、允许安全换账号重放的错误。"""
    if isinstance(exc, SellerSpriteAuthenticationError):
        return True
    if not isinstance(exc, SellerSpriteApiError):
        return False
    return exc.is_session_expired() or exc.status_code in {401, 403}


def _login_stage(exc: Exception, failover_count: int) -> str:
    """根据错误与接替次数返回稳定登录失败阶段。"""
    if isinstance(exc, SellerSpriteApiError) and exc.is_session_expired():
        return "relogin"
    return "failover" if failover_count else "initial"
