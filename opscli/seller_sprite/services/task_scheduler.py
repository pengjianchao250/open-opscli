"""卖家精灵多账号并行任务调度器与冷备用接替编排。"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from opscli.seller_sprite.accounts import (
    SellerSpriteAccount,
    SellerSpriteAccountProvider,
)
from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.constants import ACCOUNT_FAILURE_REASON_AUTHENTICATION
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteAccountSourceUnavailableError,
    SellerSpriteAccountUnavailableError,
    SellerSpriteAllAccountsAuthFailedError,
    SellerSpriteAllStandbyBusyError,
    SellerSpriteApiError,
    SellerSpriteAuthenticationError,
    SellerSpriteConfigError,
    SellerSpriteDedicatedAccountUnavailableError,
    SellerSpriteNoEligibleAccountError,
    SellerSpriteTaskTimeoutError,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder
from opscli.seller_sprite.services.account_pool import (
    DEFAULT_MAX_WORKING_ACCOUNTS,
    SellerSpriteAccountPool,
    seller_sprite_account_key,
)
from opscli.seller_sprite.services.api_manager import SellerSpriteApiManager, _build_job_id
from opscli.seller_sprite.services.task_queue_store import (
    ACCOUNT_ROUTE_SHARED_POOL,
    SellerSpriteTaskQueueStore,
)
from opscli.seller_sprite.services.task_status import error_to_dict


QUEUE_SCOPE = "seller_sprite"
DEFAULT_WORKER_KEY = "default"
# 一分钟检查一次足以覆盖 30 分钟空闲阈值，同时避免高频扫描 browser registry。
DEFAULT_SESSION_REAP_INTERVAL_SECONDS = 60.0
_SCHEDULERS: dict[tuple[int, str], "SellerSpriteTaskScheduler"] = {}
logger = logging.getLogger(__name__)


def _process_resource_snapshot() -> dict[str, int]:
    """读取 Linux 主进程 FD 使用量；其他平台保持空摘要。"""
    snapshot: dict[str, int] = {}
    try:
        snapshot["process_fd_count"] = len(os.listdir("/proc/self/fd"))
    except OSError:
        return snapshot
    try:
        import resource

        soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft_limit != resource.RLIM_INFINITY:
            snapshot["process_fd_limit"] = int(soft_limit)
    except (ImportError, OSError, ValueError):
        pass
    return snapshot


@dataclass(frozen=True)
class _ReplacementSelection:
    """一次备用账号选择结果，并保留账号源刷新状态。"""

    account: SellerSpriteAccount | None
    source_unavailable: bool = False
    no_eligible_account: bool = False
    all_accounts_attempted: bool = False


class SellerSpriteTaskScheduler:
    """负责多账号任务排队、工作槽调度和 browser 会话生命周期管理。"""

    def __init__(
        self,
        *,
        store: SellerSpriteTaskQueueStore | None = None,
        settings: SellerSpriteSettings | None = None,
        account_provider=None,
        account_binding_store=None,
        manager_factory: Callable[..., SellerSpriteApiManager] | None = None,
        collection_submitter: Callable[..., None] | None = None,
        auto_start: bool = True,
        poll_interval_seconds: float = 0.05,
        session_reap_interval_seconds: float = DEFAULT_SESSION_REAP_INTERVAL_SECONDS,
    ) -> None:
        """创建卖家精灵持久任务调度器。

        参数：
            store: SQLite 任务队列存储。
            settings: 卖家精灵运行配置。
            account_provider: 公共账号来源；传入旧式单账号 provider 时保留兼容调度模式。
            account_binding_store: 用户专属账号绑定仓储；测试可注入临时目录实例。
            manager_factory: 场景执行器工厂。
            collection_submitter: Collector 注入的成功任务沉淀提交函数。
            auto_start: 入队时是否自动启动后台消费。
            poll_interval_seconds: 无任务或 supervisor 循环的轮询间隔。
            session_reap_interval_seconds: browser 会话周期回收扫描间隔。

        返回：
            无。
        """
        self.settings = settings or load_settings()
        self.account_provider = account_provider
        self._account_provider_injected = account_provider is not None
        self.account_binding_store = account_binding_store
        self.store = store or SellerSpriteTaskQueueStore()
        self.auto_start = auto_start
        self.poll_interval_seconds = poll_interval_seconds
        self.session_reap_interval_seconds = max(0.01, float(session_reap_interval_seconds))
        self.task_lease_seconds = max(1.0, float(self.settings.task_lease_seconds))
        self.task_heartbeat_seconds = min(
            self.task_lease_seconds / 2,
            max(0.1, float(self.settings.task_heartbeat_seconds)),
        )
        self.shutdown_timeout_seconds = max(
            0.1,
            float(self.settings.shutdown_timeout_seconds),
        )
        self.manager_factory = manager_factory or self._default_manager_factory
        self.collection_submitter = collection_submitter
        self._runtime_auth: dict[str, tuple[str, str | None]] = {}
        self._account_credential_scope: str | None = None
        self._account_expected_user_email: str | None = None
        self._runner_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._generic_worker_tasks: dict[str, asyncio.Task] = {}
        self._generic_worker_accounts: dict[str, SellerSpriteAccount] = {}
        self._listing_worker_task: asyncio.Task | None = None
        self._listing_worker_account_key: str | None = None
        self._user_binding_tasks: set[asyncio.Task] = set()
        self._account_pool = SellerSpriteAccountPool(quarantine_store=self.store)
        self._pool_lock = asyncio.Lock()
        self._event_recorder = SellerSpriteAccountEventRecorder(store=self.store)
        # 进程级随机标识同时约束 SQLite 执行租约和 browser 会话所有权。
        self._session_owner_id = f"scheduler-{uuid4().hex}"
        self._active_attempts: dict[str, dict[str, Any]] = {}
        self._last_claim_at: str | None = None
        self._last_progress_at: str | None = None
        self._next_worker_slot_number = 1
        self._account_retry_after: dict[str, float] = {}
        self._last_account_refresh_at = 0.0
        self._last_session_reap_at = 0.0
        self._consumer_errors: set[str] = set()
        # 启动、关闭和心跳自恢复共用此锁，避免并发创建重复 Supervisor 或心跳任务。
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

    def runtime_health(self) -> dict[str, Any]:
        """基于持久运行态和当前后台任务返回脱敏健康摘要。"""
        resource_snapshot = _process_resource_snapshot()
        try:
            runtime = self.store.get_runtime_heartbeat(self._session_owner_id)
        except ValueError as exc:
            if "调度器运行态不存在" in str(exc):
                return {
                    "status": "not_ready",
                    "checks": {"queue": "ok", "scheduler": "not_started"},
                    "runtime": {
                        "lifecycle_state": "not_started",
                        **resource_snapshot,
                    },
                }
            return {
                "status": "degraded",
                "checks": {"queue": "error", "scheduler": "unknown"},
                "runtime": {"lifecycle_state": "unknown", **resource_snapshot},
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "checks": {"queue": "error", "scheduler": "unknown"},
                "runtime": {"lifecycle_state": "unknown", **resource_snapshot},
                "error_code": "QUEUE_DATABASE_UNAVAILABLE",
                "error_class": type(exc).__name__,
            }
        lifecycle = str(runtime["lifecycle_state"])
        heartbeat_fresh = _heartbeat_is_fresh(
            runtime.get("heartbeat_at"),
            max_age_seconds=max(self.task_lease_seconds, self.task_heartbeat_seconds * 3),
        )
        heartbeat_alive = bool(
            self._heartbeat_task is not None and not self._heartbeat_task.done()
        )
        consumer_alive = bool(
            self._runner_task is not None and not self._runner_task.done()
        )
        consumer_error_count = len(self._consumer_errors)
        running = (
            lifecycle == "running"
            and heartbeat_fresh
            and heartbeat_alive
            and consumer_alive
            and consumer_error_count == 0
            and not self._stop_requested
        )
        if running:
            status = "ready"
            scheduler_check = "running"
        elif lifecycle == "running" and not self._stop_requested:
            status = "degraded"
            if not heartbeat_alive:
                scheduler_check = "heartbeat_failed"
            elif not consumer_alive:
                scheduler_check = "consumer_failed"
            elif consumer_error_count:
                scheduler_check = "consumer_error"
            else:
                scheduler_check = "heartbeat_stale"
        else:
            status = "not_ready"
            scheduler_check = lifecycle
        public_runtime = {
            key: value
            for key, value in runtime.items()
            if key != "execution_owner"
        }
        public_runtime["heartbeat_fresh"] = heartbeat_fresh
        public_runtime["consumer_alive"] = consumer_alive
        public_runtime["consumer_error_count"] = consumer_error_count
        public_runtime.update(resource_snapshot)
        return {
            "status": status,
            "checks": {
                "queue": "ok",
                "scheduler": scheduler_check,
            },
            "runtime": public_runtime,
        }

    async def enqueue(
        self,
        request: SellerSpriteScenarioRequest,
        *,
        mcp_user_email: str | None = None,
        credential_scope: str | None = None,
        session_id: str | None = None,
        jwt: str | None = None,
        expected_user_email: str | None = None,
        account_route: str = ACCOUNT_ROUTE_SHARED_POOL,
        requested_account_id: str | None = None,
        requested_account_key: str | None = None,
    ) -> dict[str, Any]:
        """携带非敏感凭证作用域入队，并可原子记录 MCP 所有权。"""
        normalized = self._normalize_request(request)
        root_dir = self._build_root_dir(normalized)
        if mcp_user_email:
            # 公共 MCP 提交必须让队列行和所有权行同成同败，避免碰撞后错误授权。
            status = self.store.enqueue_owned_mcp_run(
                request=normalized,
                queue_scope=QUEUE_SCOPE,
                root_dir=root_dir,
                user_email=mcp_user_email,
                credential_scope=credential_scope,
                expected_user_email=expected_user_email,
                account_route=account_route,
                requested_account_id=requested_account_id,
                requested_account_key=requested_account_key,
            )
        else:
            status = self.store.enqueue(
                request=normalized,
                queue_scope=QUEUE_SCOPE,
                root_dir=root_dir,
                credential_scope=credential_scope,
                runtime_auth_required=bool(session_id or jwt),
                expected_user_email=expected_user_email,
                account_route=account_route,
                requested_account_id=requested_account_id,
                requested_account_key=requested_account_key,
            )
        if session_id:
            # 显式凭证仅按 job_id 短暂保存在内存中，禁止写入 SQLite 或跨任务复用。
            self._runtime_auth[str(normalized.job_id)] = (session_id, jwt)
        if credential_scope:
            # 公共账号刷新只保留非敏感凭证引用，实际 session/JWT 每次从 CredentialStore 读取。
            self._account_credential_scope = credential_scope
            self._account_expected_user_email = expected_user_email or mcp_user_email
        if (
            account_route == ACCOUNT_ROUTE_SHARED_POOL
            and not self._account_pool.working_accounts
            and not self._account_pool.standby_accounts
        ):
            # 空闲启动会把刷新计时推进到当前时刻；首个公共任务必须重新标记为立即到期。
            self._last_account_refresh_at = 0.0
        if self.auto_start:
            await self.start()
        return status

    async def start(self) -> None:
        """恢复过期任务并启动后台调度循环。"""
        async with self._start_lock:
            if self._runner_task and not self._runner_task.done():
                return
            self._stop_requested = False
            self._publish_runtime_heartbeat(lifecycle_state="starting")
            self.store.recover_expired_running_tasks()
            if self._legacy_single_account_mode:
                self._runner_task = self._create_background_task(self._run_loop())
                self._publish_runtime_heartbeat(lifecycle_state="running")
                if self._heartbeat_task is None or self._heartbeat_task.done():
                    self._heartbeat_task = self._create_background_task(
                        self._run_execution_heartbeat()
                    )
                return
            self._fail_queued_tasks_with_invalid_auth()
            await self._initialize_account_pool()
            self._start_generic_workers()
            if self._listing_worker_task is None or self._listing_worker_task.done():
                self._start_listing_worker()
            self._runner_task = self._create_background_task(self._run_pool_supervisor())
            self._publish_runtime_heartbeat(lifecycle_state="running")
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = self._create_background_task(
                    self._run_execution_heartbeat()
                )

    async def close(self) -> None:
        """停止领取、取消未完成执行并重新排队，再释放 browser 会话。"""
        async with self._start_lock:
            self._stop_requested = True
            tasks = [
                task
                for task in [
                    self._runner_task,
                    self._heartbeat_task,
                    *self._generic_worker_tasks.values(),
                    self._listing_worker_task,
                    *self._user_binding_tasks,
                ]
                if task is not None and not task.done()
            ]
            for task in tasks:
                task.cancel()
            if tasks:
                _, pending = await asyncio.wait(
                    tasks,
                    timeout=self.shutdown_timeout_seconds,
                )
                if pending:
                    logger.warning("卖家精灵调度器关闭等待超时，强制释放任务租约")
            self._active_attempts.clear()
            self._consumer_errors.clear()
            self.store.release_running_tasks(
                execution_owner=self._session_owner_id,
            )
            self.store.mark_runtime_stopped(execution_owner=self._session_owner_id)
            from opscli.seller_sprite.browser_route.worker import close_all_browser_route_workers

            try:
                await asyncio.wait_for(
                    close_all_browser_route_workers(
                        settings=self.settings,
                        reason="scheduler_close",
                        state_listener=self._record_browser_session_state_change,
                        owner_id=self._session_owner_id,
                    ),
                    timeout=self.shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("卖家精灵 browser 会话关闭等待超时")
            self._runner_task = None
            self._heartbeat_task = None
            self._generic_worker_tasks.clear()
            self._generic_worker_accounts.clear()
            self._listing_worker_task = None
            self._listing_worker_account_key = None
            self._user_binding_tasks.clear()

    def _create_background_task(self, coro: Any) -> asyncio.Task:
        """从空 Context 创建跨请求后台任务，禁止继承提交者的 MCP 身份。"""
        return contextvars.Context().run(asyncio.create_task, coro)

    async def _run_execution_heartbeat(self) -> None:
        """周期发布运行态，仅续期调度器仍主动跟踪的执行尝试。"""
        while not self._stop_requested:
            try:
                await self._restart_consumer_if_needed()
                self.store.renew_active_execution_leases(
                    execution_owner=self._session_owner_id,
                    attempts=list(self._active_attempts.values()),
                    lease_seconds=self.task_lease_seconds,
                )
                self.store.recover_expired_running_tasks()
                self._publish_runtime_heartbeat(lifecycle_state="running")
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单轮 SQLite 或运行态发布失败不得终止长期心跳，下一轮继续自愈。
                logger.exception("卖家精灵调度器心跳发布失败，下一轮继续重试")
            await asyncio.sleep(self.task_heartbeat_seconds)

    async def _restart_consumer_if_needed(self) -> bool:
        """由独立心跳监督重建意外结束的消费任务。"""
        async with self._start_lock:
            task = self._runner_task
            if self._stop_requested or task is None or not task.done():
                return False
            if task.cancelled():
                error_class = "CancelledError"
            else:
                error = task.exception()
                error_class = (
                    type(error).__name__ if error is not None else "UnexpectedExit"
                )
            logger.error(
                "卖家精灵消费监督任务意外结束，正在自动恢复：error=%s",
                error_class,
            )
            consumer = (
                self._run_loop()
                if self._legacy_single_account_mode
                else self._run_pool_supervisor()
            )
            self._runner_task = self._create_background_task(consumer)
            return True

    def _publish_runtime_heartbeat(self, *, lifecycle_state: str) -> None:
        """发布当前工作槽、容量和最近活动的脱敏运行态。"""
        generic_alive = self.generic_worker_count
        listing_alive = int(
            self._listing_worker_task is not None
            and not self._listing_worker_task.done()
        )
        # 所有执行类型共享账号互斥；专属任务若占用同一账号，也必须扣除公共可领取容量。
        shared_busy_accounts = self.store.running_account_keys(
            queue_scope=QUEUE_SCOPE
        ) | {
            str(attempt.get("account_key") or "")
            for attempt in self._active_attempts.values()
            if attempt.get("account_key")
        }
        generic_available = sum(
            not task.done()
            and seller_sprite_account_key(account) not in shared_busy_accounts
            for worker_key, task in self._generic_worker_tasks.items()
            if (account := self._generic_worker_accounts.get(worker_key)) is not None
        )
        listing_available = int(
            listing_alive
            and self._listing_worker_account_key is not None
            and self._listing_worker_account_key not in shared_busy_accounts
        )
        self.store.publish_runtime_heartbeat(
            execution_owner=self._session_owner_id,
            lifecycle_state=lifecycle_state,
            generic_workers_alive=generic_alive,
            listing_worker_alive=listing_alive,
            generic_available_capacity=generic_available,
            listing_available_capacity=listing_available,
            available_capacity=generic_available + listing_available,
            standby_capacity=self.standby_account_count,
            last_claim_at=self._last_claim_at,
            last_progress_at=self._last_progress_at,
        )

    def _track_attempt(
        self,
        claimed: dict[str, Any],
        *,
        capacity_kind: str | None = "from_task",
        attempt_id: str | None = None,
    ) -> str:
        """登记新领取的执行尝试，并返回代际安全的内存跟踪令牌。"""
        job_id = str(claimed["job_id"])
        tracked_kind = (
            str(claimed.get("task_kind") or "generic")
            if capacity_kind == "from_task"
            else capacity_kind
        )
        tracked_attempt_id = attempt_id or uuid4().hex
        self._active_attempts[job_id] = {
            "job_id": job_id,
            "account_key": str(claimed.get("assigned_account_key") or ""),
            "assignment_generation": int(claimed["assignment_generation"]),
            "capacity_kind": tracked_kind,
            "attempt_id": tracked_attempt_id,
        }
        self._last_claim_at = _now_iso()
        self._last_progress_at = str(claimed.get("progress_at") or self._last_claim_at)
        return tracked_attempt_id

    def _refresh_tracked_attempt(
        self,
        claimed: dict[str, Any],
        *,
        attempt_id: str,
    ) -> bool:
        """仅允许原 worker 用接替后的新代际刷新自己的活动跟踪。"""
        job_id = str(claimed["job_id"])
        current = self._active_attempts.get(job_id)
        if current is None or current.get("attempt_id") != attempt_id:
            return False
        self._track_attempt(
            claimed,
            capacity_kind=current.get("capacity_kind"),
            attempt_id=attempt_id,
        )
        return True

    def _untrack_attempt(self, job_id: str, *, attempt_id: str) -> bool:
        """仅移除调用方自己的活动跟踪，避免旧 worker 删除新代际。"""
        current = self._active_attempts.get(job_id)
        if current is None or current.get("attempt_id") != attempt_id:
            return False
        self._active_attempts.pop(job_id, None)
        return True

    def _report_task_progress(
        self,
        *,
        job_id: str,
        account_key: str,
        assignment_generation: int,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """使用当前执行令牌持久化 Manager 报告的脱敏进度。"""
        committed = self.store.update_task_progress(
            job_id=job_id,
            account_key=account_key,
            assignment_generation=assignment_generation,
            execution_owner=self._session_owner_id,
            stage=stage,
            metadata=metadata,
        )
        if committed:
            self._last_progress_at = _now_iso()
        return committed

    def _fail_queued_tasks_with_invalid_auth(self) -> None:
        """在账号池刷新前关闭无效的逐任务认证，避免任务永久停留 queued。"""
        for status in self.store.list_tasks(state="queued", limit=500):
            job_id = str(status["job_id"])
            has_mcp_run = False
            try:
                context = self.store.get_task_context(job_id)
                expected_user_email = context.get("expected_user_email")
                has_mcp_run = self._has_mcp_run(
                    job_id,
                    fail_closed=bool(expected_user_email),
                )
                if not expected_user_email and has_mcp_run:
                    expected_user_email = str(self.store.get_mcp_run(job_id)["user_email"])
                _resolve_task_auth(
                    context,
                    runtime_auth=self._runtime_auth.get(job_id),
                    require_auth=bool(expected_user_email or has_mcp_run),
                    expected_user_email=expected_user_email,
                )
                if (
                    self._account_credential_scope is None
                    and context.get("credential_scope")
                ):
                    self._account_credential_scope = str(context["credential_scope"])
                    self._account_expected_user_email = expected_user_email
            except Exception as exc:
                error_payload = error_to_dict(exc)
                self.store.fail_task(job_id=job_id, error_payload=error_payload)
                if has_mcp_run:
                    self.store.finish_mcp_run_failed(job_id, error_payload)
                self._runtime_auth.pop(job_id, None)

    async def _initialize_account_pool(self) -> None:
        """首次读取账号接口并建立工作账号和冷备用账号。"""
        if not self._public_account_pool_needed():
            # Collector 空闲启动时没有可归属的用户身份，不应访问 OPS 公共账号源。
            self._last_account_refresh_at = time.monotonic()
            return
        try:
            provider = self._ensure_account_provider(refresh_auth=True)
            accounts = provider.list_accounts()
        except (
            SellerSpriteAccountSourceUnavailableError,
            SellerSpriteNoEligibleAccountError,
        ) as exc:
            # 明确账号源错误必须关闭排队任务，避免生产环境无 Worker 时永久卡在 queued。
            self._event_recorder.record_account_fetch_failure(
                error=exc,
                next_action="fail_queued_shared_pool_tasks",
            )
            self._fail_queued_shared_pool_tasks(exc)
            accounts = []
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
            self._generic_worker_tasks[worker_key] = self._create_background_task(
                self._run_generic_worker(worker_key, account)
            )

    def _start_listing_worker(self) -> None:
        """为 Listing Analysis 保留独立的单账号串行消费协程。"""
        if not self._account_pool.working_accounts:
            return
        try:
            default_account = self._ensure_account_provider().get_default()
            self._listing_worker_account_key = seller_sprite_account_key(default_account)
        except Exception:
            self._listing_worker_account_key = None
        self._listing_worker_task = self._create_background_task(self._run_listing_worker())

    async def _run_pool_supervisor(self) -> None:
        """维护账号工作槽生命周期，并在无账号时周期重试账号接口。"""
        while not self._stop_requested:
            try:
                self._prune_runtime_auth()
                self._remove_finished_generic_workers()
                self._start_generic_workers()
                if self._listing_worker_task is None or self._listing_worker_task.done():
                    self._start_listing_worker()
                self._remove_finished_user_binding_tasks()
                self._start_user_binding_tasks()
                now = time.monotonic()
                refresh_interval = max(1.0, float(self.settings.account_cache_ttl_seconds))
                if self._account_pool.has_temporary_unavailable_accounts:
                    refresh_interval = min(
                        refresh_interval,
                        max(1.0, float(self.settings.browser_cooldown_seconds)),
                    )
                refresh_due = now - self._last_account_refresh_at >= refresh_interval
                if refresh_due:
                    if self._public_account_pool_needed():
                        await self._refresh_account_pool()
                    else:
                        # 空闲期只推进计时，不访问远端；新公共任务入队会将其重置为立即到期。
                        self._last_account_refresh_at = now
                if now - self._last_session_reap_at >= self.session_reap_interval_seconds:
                    await self._reap_browser_sessions()
                self._consumer_errors.discard("supervisor")
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单轮账号维护或会话回收异常不能结束 Supervisor 和全部后续恢复能力。
                first_failure = "supervisor" not in self._consumer_errors
                self._consumer_errors.add("supervisor")
                if first_failure:
                    logger.exception("卖家精灵消费监督循环异常，短暂等待后继续维护")
            await asyncio.sleep(self.poll_interval_seconds)

    def _public_account_pool_needed(self) -> bool:
        """判断已有账号池或排队公共任务是否需要访问远端账号源。"""
        return bool(
            self._account_provider_injected
            or self._account_pool.working_accounts
            or self._account_pool.standby_accounts
            or self.store.list_queued_shared_pool_job_ids()
        )

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
                        "卖家精灵账号工作槽异常退出：worker_key=%s error=%s",
                        worker_key,
                        type(error).__name__,
                    )
            self._generic_worker_accounts.pop(worker_key, None)
            self._consumer_errors.discard(worker_key)

    def _remove_finished_user_binding_tasks(self) -> None:
        """清理已结束的专属账号任务，并记录意外退出。"""
        finished = [task for task in self._user_binding_tasks if task.done()]
        for task in finished:
            self._user_binding_tasks.discard(task)
            if task.cancelled():
                continue
            error = task.exception()
            if error is not None:
                logger.error(
                    "卖家精灵专属账号任务异常退出：error=%s",
                    type(error).__name__,
                )

    def _start_user_binding_tasks(self) -> None:
        """领取有效专属账号任务，最多同时运行三个不同账号。"""
        while len(self._user_binding_tasks) < DEFAULT_MAX_WORKING_ACCOUNTS:
            candidate = self.store.next_user_binding_candidate(queue_scope=QUEUE_SCOPE)
            if candidate is None:
                return
            job_id = str(candidate["job_id"])
            try:
                account, account_id, account_key = self._resolve_user_binding_account(
                    candidate
                )
            except Exception:
                self.store.fail_queued_user_binding_task(
                    job_id=job_id,
                    reason="卖家精灵专属账号绑定已失效或无法读取，请重新绑定后提交任务",
                )
                self._runtime_auth.pop(job_id, None)
                continue

            worker_key = f"seller-sprite-user-binding-{account_id[:12]}"
            claimed = self.store.claim_user_binding_task(
                job_id=job_id,
                account_id=account_id,
                account_key=account_key,
                assigned_account=account.name,
                worker_key=worker_key,
                execution_owner=self._session_owner_id,
                lease_seconds=self.task_lease_seconds,
            )
            if claimed is None:
                return
            attempt_id = self._track_attempt(claimed, capacity_kind=None)
            task = self._create_background_task(
                self._run_user_binding_task(
                    claimed=claimed,
                    account=account,
                    attempt_id=attempt_id,
                )
            )
            self._user_binding_tasks.add(task)

    def _resolve_user_binding_account(
        self,
        candidate: dict[str, Any],
    ) -> tuple[SellerSpriteAccount, str, str]:
        """重新校验提交用户及非敏感账号引用，并在领取前解密账号。"""
        user_email = str(candidate.get("expected_user_email") or "").strip().lower()
        requested_account_id = str(candidate.get("requested_account_id") or "").strip()
        requested_account_key = str(candidate.get("requested_account_key") or "").strip()
        if not user_email or not requested_account_id or not requested_account_key:
            raise SellerSpriteDedicatedAccountUnavailableError(
                "卖家精灵专属账号任务缺少绑定引用"
            )

        binding = self._ensure_account_binding_store().get_binding(user_email)
        if binding is None:
            raise SellerSpriteDedicatedAccountUnavailableError(
                "卖家精灵专属账号绑定已解除"
            )
        account = binding.account.to_account()
        account_key = seller_sprite_account_key(account)
        if (
            binding.account.account_id != requested_account_id
            or account_key != requested_account_key
        ):
            raise SellerSpriteDedicatedAccountUnavailableError(
                "卖家精灵专属账号绑定已变更"
            )
        return account, requested_account_id, account_key

    def _ensure_account_binding_store(self):
        """延迟创建专属账号绑定仓储，避免无专属任务时创建密钥文件。"""
        if self.account_binding_store is None:
            from opscli.seller_sprite.services.account_bindings import (
                SellerSpriteAccountBindingStore,
            )

            self.account_binding_store = SellerSpriteAccountBindingStore()
        return self.account_binding_store

    async def _run_user_binding_task(
        self,
        *,
        claimed: dict[str, Any],
        account: SellerSpriteAccount,
        attempt_id: str,
    ) -> None:
        """使用领取时解密的专属账号完成任务，任何失败均禁止公共账号接替。"""
        job_id = str(claimed["job_id"])
        try:
            await self._run_one(
                job_id,
                account=account,
                close_account_on_auth_failure=True,
                execution_account_key=seller_sprite_account_key(account),
                assignment_generation=int(claimed["assignment_generation"]),
            )
            await self._reap_browser_sessions()
        finally:
            self._untrack_attempt(job_id, attempt_id=attempt_id)

    async def _refresh_account_pool(self) -> None:
        """刷新账号接口，并用新账号或新凭证版本补足空工作槽。"""
        try:
            provider = self._ensure_account_provider(refresh_auth=True)
            accounts = provider.list_accounts(refresh=True)
        except (
            SellerSpriteAccountSourceUnavailableError,
            SellerSpriteNoEligibleAccountError,
        ) as exc:
            self._event_recorder.record_account_fetch_failure(
                error=exc,
                next_action="fail_queued_shared_pool_tasks",
            )
            self._fail_queued_shared_pool_tasks(exc)
            self._last_account_refresh_at = time.monotonic()
            return
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
            try:
                claimed = self.store.claim_next_generic_for_account(
                    queue_scope=QUEUE_SCOPE,
                    account_key=seller_sprite_account_key(account),
                    assigned_account=account.name,
                    worker_key=worker_key,
                    execution_owner=self._session_owner_id,
                    lease_seconds=self.task_lease_seconds,
                )
                self._consumer_errors.discard(worker_key)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 瞬时 SQLite 或领取边界异常不能结束长期 Worker，否则队列会等待人工重启。
                first_failure = worker_key not in self._consumer_errors
                self._consumer_errors.add(worker_key)
                if first_failure:
                    logger.exception(
                        "卖家精灵账号工作槽领取异常，短暂等待后继续消费：worker_key=%s",
                        worker_key,
                    )
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            if claimed is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            attempt_id = self._track_attempt(claimed)
            job_id = str(claimed["job_id"])
            try:
                replacement = await self._run_generic_job(
                    claimed=claimed,
                    account=account,
                    worker_key=worker_key,
                    attempt_id=attempt_id,
                )
                # 每条任务结束后形成安全边界，使满 6 小时的会话无需等待下一分钟扫描。
                await self._reap_browser_sessions()
            finally:
                self._untrack_attempt(job_id, attempt_id=attempt_id)
            if replacement is None:
                return
            account = replacement
            retry_after = self._account_retry_after.pop(
                seller_sprite_account_key(account),
                0.0,
            )
            retry_delay = retry_after - time.monotonic()
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)
            self._generic_worker_accounts[worker_key] = account

    async def _run_generic_job(
        self,
        *,
        claimed: dict[str, Any],
        account: SellerSpriteAccount,
        worker_key: str,
        attempt_id: str,
    ) -> SellerSpriteAccount | None:
        """执行一条通用任务，并在明确认证失败时改绑冷备用账号。"""
        job_id = str(claimed["job_id"])
        attempted_accounts: set[SellerSpriteAccount] = set()
        status = claimed
        has_mcp_run = False
        try:
            context = self.store.get_task_context(job_id)
            expected_user_email = context.get("expected_user_email")
            has_mcp_run = self._has_mcp_run(
                job_id,
                fail_closed=bool(expected_user_email),
            )
            if not expected_user_email and has_mcp_run:
                expected_user_email = str(self.store.get_mcp_run(job_id)["user_email"])
            session_id, jwt = _resolve_task_auth(
                context,
                runtime_auth=self._runtime_auth.pop(job_id, None),
                require_auth=bool(expected_user_email or has_mcp_run),
                expected_user_email=expected_user_email,
            )
        except Exception as exc:
            await self._fail_generic_job(
                job_id=job_id,
                account_key=str(claimed["assigned_account_key"]),
                generation=int(claimed["assignment_generation"]),
                error=exc,
                has_mcp_run=has_mcp_run,
            )
            return account
        while True:
            account_key = seller_sprite_account_key(account)
            attempted_accounts.add(account)
            generation = int(status["assignment_generation"])
            failover_count = int(status["failover_count"])
            started_at = time.monotonic()
            request: SellerSpriteScenarioRequest | None = None
            try:
                request = self.store.get_request(job_id)
                attempt_dir = (
                    Path(str(status["root_dir"]))
                    / "attempts"
                    / f"generation-{generation}"
                )
                request = replace(request, attempt_output_dir=str(attempt_dir))
                manager = self.manager_factory(
                    settings=self.settings,
                    account_provider=_FixedSellerSpriteAccountProvider(account),
                    jwt=jwt,
                    session_id=session_id,
                )
                self._configure_manager_progress(
                    manager=manager,
                    job_id=job_id,
                    account_key=account_key,
                    assignment_generation=generation,
                )
                if has_mcp_run and failover_count == 0:
                    self.store.mark_mcp_run_running(job_id)
                result = await self._run_manager_with_session_reservation(
                    manager=manager,
                    request=request,
                    account=account,
                )
                export_payload = self._build_mcp_export_payload(request, result)
                committed = self.store.finish_task_and_mcp_run_if_current(
                    job_id=job_id,
                    account_key=account_key,
                    assignment_generation=generation,
                    result_path=result.result_path,
                    row_count=result.row_count,
                    export_payload=result.export.to_dict() if result.export else None,
                    mcp_export_payload=export_payload if has_mcp_run else None,
                )
                if committed:
                    self._submit_collection_result(request=request, result=result)
                return account
            except Exception as exc:
                # 认证失败通常可切换账号重试；额度型导出可能已成功派发，必须直接失败以免重复扣额。
                replay_safe = bool(
                    request is None or get_scenario(request.scenario).replay_safe
                )
                if not _is_account_authentication_failure(exc) or not replay_safe:
                    committed = await self._fail_generic_job(
                        job_id=job_id,
                        account_key=account_key,
                        generation=generation,
                        error=exc,
                        has_mcp_run=has_mcp_run,
                    )
                    if committed and isinstance(exc, SellerSpriteTaskTimeoutError):
                        await self._close_account_session(account, reason="task_timeout")
                    return account

                login_stage = _login_stage(exc, failover_count)
                self._event_recorder.record_login_failure(
                    account=account,
                    job_id=job_id,
                    worker_key=worker_key,
                    assignment_generation=generation,
                    execution_mode=str(
                        (request.mode if request is not None else None)
                        or self.settings.default_mode
                    ),
                    login_stage=login_stage,
                    error=exc,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                    failover_count=failover_count,
                    next_action="refresh_accounts",
                )
                excluded_accounts: set[SellerSpriteAccount] = set()
                selection = await self._select_replacement_account(
                    attempted_accounts=attempted_accounts,
                    excluded_accounts=excluded_accounts,
                )
                replacement = selection.account
                source_unavailable = selection.source_unavailable
                saw_replacement_busy = False
                reassigned = None
                stale_attempt = False
                while replacement is not None:
                    try:
                        reassignment = self.store.reassign_task_for_failover(
                            job_id=job_id,
                            current_account_key=account_key,
                            current_generation=generation,
                            replacement_account_key=seller_sprite_account_key(replacement),
                            replacement_account=replacement.name,
                            worker_key=worker_key,
                            error_code=str(getattr(exc, "code", type(exc).__name__)),
                            retry_reason="account_authentication_failed",
                        )
                    except Exception as failover_exc:
                        committed = await self._fail_generic_job(
                            job_id=job_id,
                            account_key=account_key,
                            generation=generation,
                            error=failover_exc,
                            has_mcp_run=has_mcp_run,
                        )
                        async with self._pool_lock:
                            self._account_pool.defer_working_account(replacement)
                        if committed:
                            return await self._finish_terminal_account_auth_failure(
                                account,
                                error=exc,
                            )
                        return None
                    if reassignment.outcome == "reassigned":
                        reassigned = reassignment.status
                        break
                    async with self._pool_lock:
                        self._account_pool.defer_working_account(replacement)
                    if reassignment.outcome == "stale_attempt":
                        stale_attempt = True
                        break
                    saw_replacement_busy = True
                    # 账号占用冲突没有执行登录，必须与真实认证尝试分开统计。
                    excluded_accounts.add(replacement)
                    selection = await self._select_replacement_account(
                        attempted_accounts=attempted_accounts,
                        excluded_accounts=excluded_accounts,
                    )
                    replacement = selection.account
                    source_unavailable = (
                        source_unavailable or selection.source_unavailable
                    )
                if stale_attempt:
                    return None
                if replacement is None or reassigned is None:
                    # 失败分类按可行动性排序：先报告资源占用，再报告账号源，最后判断凭据是否真正耗尽。
                    if saw_replacement_busy:
                        unavailable = SellerSpriteAllStandbyBusyError(
                            "卖家精灵工作账号失效，当前可用备用账号均被占用"
                        )
                    elif source_unavailable:
                        unavailable = SellerSpriteAccountSourceUnavailableError(
                            "卖家精灵工作账号失效，且远程账号源刷新失败"
                        )
                    elif selection.no_eligible_account:
                        unavailable = SellerSpriteNoEligibleAccountError(
                            "卖家精灵工作账号失效，且远程账号源没有可用账号"
                        )
                    elif selection.all_accounts_attempted:
                        unavailable = SellerSpriteAllAccountsAuthFailedError(
                            "卖家精灵当前任务已耗尽全部可尝试账号凭据"
                        )
                    else:
                        unavailable = SellerSpriteAccountUnavailableError(
                            "卖家精灵工作账号失效，且没有可用备用账号"
                        )
                    committed = await self._fail_generic_job(
                        job_id=job_id,
                        account_key=account_key,
                        generation=generation,
                        error=unavailable,
                        has_mcp_run=has_mcp_run,
                    )
                    if committed:
                        return await self._finish_terminal_account_auth_failure(
                            account,
                            error=exc,
                        )
                    return None
                if not self._refresh_tracked_attempt(
                    reassigned,
                    attempt_id=attempt_id,
                ):
                    return None
                await self._mark_account_unavailable(account, error=exc)
                self._generic_worker_accounts[worker_key] = replacement
                await self._close_account_session(
                    account,
                    reason=ACCOUNT_FAILURE_REASON_AUTHENTICATION,
                )
                account = replacement
                status = reassigned

    async def _select_replacement_account(
        self,
        *,
        attempted_accounts: set[SellerSpriteAccount],
        excluded_accounts: set[SellerSpriteAccount],
    ) -> _ReplacementSelection:
        """刷新账号接口后按原顺序选择未被当前任务尝试的冷备用。"""
        async with self._pool_lock:
            source_unavailable = False
            no_eligible_account = False
            try:
                provider = self._ensure_account_provider(refresh_auth=True)
                refreshed = provider.list_accounts(refresh=True)
            except SellerSpriteNoEligibleAccountError as exc:
                no_eligible_account = True
                self._event_recorder.record_account_fetch_failure(
                    error=exc,
                    next_action="try_cached_standby",
                )
                refreshed = []
            except Exception as exc:
                source_unavailable = True
                self._event_recorder.record_account_fetch_failure(
                    error=exc,
                    next_action="try_cached_standby",
                )
                refreshed = []
            if refreshed:
                self._account_pool.refresh(refreshed)
            elif not source_unavailable:
                no_eligible_account = True
            selection_exclusions = attempted_accounts | excluded_accounts
            return _ReplacementSelection(
                account=self._account_pool.take_standby(
                    attempted_accounts=selection_exclusions
                ),
                source_unavailable=source_unavailable,
                no_eligible_account=no_eligible_account,
                all_accounts_attempted=self._account_pool.all_accounts_attempted(
                    attempted_accounts
                ),
            )

    async def _mark_account_unavailable(
        self,
        account: SellerSpriteAccount,
        *,
        error: Exception,
    ) -> None:
        """移出当前失败凭据，仅对明确凭证拒绝持久化隔离。"""
        async with self._pool_lock:
            persist_quarantine = _is_confirmed_credential_rejection(error)
            cooldown_seconds = max(
                self.poll_interval_seconds,
                float(self.settings.browser_cooldown_seconds),
            )
            self._account_pool.mark_unavailable(
                account,
                persist_quarantine=persist_quarantine,
                temporary_cooldown_seconds=(
                    None if persist_quarantine else cooldown_seconds
                ),
            )
            if not persist_quarantine:
                self._last_account_refresh_at = time.monotonic()
            logger.warning(
                "卖家精灵账号已移出当前工作池：account_key=%s "
                "persist_quarantine=%s error_code=%s working=%d standby=%d",
                seller_sprite_account_key(account)[:12],
                persist_quarantine,
                str(getattr(error, "code", type(error).__name__)),
                len(self._account_pool.working_accounts),
                len(self._account_pool.standby_accounts),
            )

    async def _finish_terminal_account_auth_failure(
        self,
        account: SellerSpriteAccount,
        *,
        error: Exception,
    ) -> SellerSpriteAccount | None:
        """关闭失败会话；未确认的登录误判冷却后保留最后工作槽。"""
        confirmed_rejection = _is_confirmed_credential_rejection(error)
        if confirmed_rejection:
            await self._mark_account_unavailable(account, error=error)
        await self._close_account_session(
            account,
            reason=ACCOUNT_FAILURE_REASON_AUTHENTICATION,
        )
        if confirmed_rejection:
            return None
        cooldown_seconds = max(
            self.poll_interval_seconds,
            float(self.settings.browser_cooldown_seconds),
        )
        logger.warning(
            "卖家精灵账号登录失败尚未被远端明确拒绝，保留最后工作槽并冷却："
            "account_key=%s cooldown_seconds=%.2f",
            seller_sprite_account_key(account)[:12],
            cooldown_seconds,
        )
        self._account_retry_after[seller_sprite_account_key(account)] = (
            time.monotonic() + cooldown_seconds
        )
        return account

    def _fail_queued_shared_pool_tasks(self, error: Exception) -> None:
        """使用明确账号源错误关闭当前排队的公共账号池任务。

        参数：
            error: 账号源不可用或没有合格账号异常。

        返回：
            无。
        """
        error_payload = error_to_dict(error)
        for job_id in self.store.list_queued_shared_pool_job_ids():
            has_mcp_run = self._has_mcp_run(job_id, fail_closed=False)
            committed = self.store.fail_queued_task(
                job_id=job_id,
                error_payload=error_payload,
            )
            if not committed:
                continue
            if has_mcp_run:
                self.store.finish_mcp_run_failed(job_id, error_payload)
            self._runtime_auth.pop(job_id, None)

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
    ) -> bool:
        """使用当前执行令牌标记通用任务失败并同步 MCP 状态。"""
        error_payload = error_to_dict(error)
        return self.store.fail_task_and_mcp_run_if_current(
            job_id=job_id,
            account_key=account_key,
            assignment_generation=generation,
            error_payload=error_payload,
            update_mcp_run=has_mcp_run,
        )

    async def _run_listing_worker(self) -> None:
        """使用固定默认账号串行消费 Listing Analysis，不参与故障接替。"""
        while not self._stop_requested:
            try:
                account = self._ensure_account_provider().get_default()
                self._listing_worker_account_key = seller_sprite_account_key(account)
            except Exception:
                # 默认账号暂不可用时保持任务 queued，等待账号池下一轮刷新后恢复消费。
                self._listing_worker_account_key = None
                self._consumer_errors.add("listing")
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            try:
                claimed = self.store.claim_next_listing_analysis(
                    queue_scope=QUEUE_SCOPE,
                    worker_key="seller-sprite-listing-analysis",
                    assigned_account=account.name,
                    account_key=seller_sprite_account_key(account),
                    execution_owner=self._session_owner_id,
                    lease_seconds=self.task_lease_seconds,
                )
                self._consumer_errors.discard("listing")
            except asyncio.CancelledError:
                raise
            except Exception:
                # Listing 领取异常同样保持长期 Worker，并让健康检查明确暴露消费降级。
                first_failure = "listing" not in self._consumer_errors
                self._consumer_errors.add("listing")
                if first_failure:
                    logger.exception("卖家精灵 Listing 工作槽领取异常，短暂等待后继续消费")
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            if claimed is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            attempt_id = self._track_attempt(claimed)
            job_id = str(claimed["job_id"])
            try:
                await self._run_one(
                    job_id,
                    account=account,
                    execution_account_key=str(claimed["assigned_account_key"]),
                    assignment_generation=int(claimed["assignment_generation"]),
                )
                await self._reap_browser_sessions()
            finally:
                self._untrack_attempt(job_id, attempt_id=attempt_id)

    async def _reap_browser_sessions(self) -> None:
        """回收达到空闲或最大生命周期的 browser-route 会话。"""
        from opscli.seller_sprite.browser_route.worker import reap_browser_route_workers

        await reap_browser_route_workers(
            settings=self.settings,
            state_listener=self._record_browser_session_state_change,
            owner_id=self._session_owner_id,
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
                owner_id=self._session_owner_id,
            )
        except ImportError:
            return
        except Exception as exc:
            # 关闭失败详情已由脱敏生命周期事件记录，这里只保留异常类型避免凭证正文进入日志。
            logger.warning("关闭卖家精灵故障账号会话失败：error=%s", type(exc).__name__)

    def _ensure_account_provider(self, *, refresh_auth: bool = False) -> SellerSpriteAccountProvider:
        """使用最新非敏感凭证引用创建公共账号接口 provider。"""
        if self._account_provider_injected:
            return self.account_provider
        if self.account_provider is None or refresh_auth:
            from opscli.shared.integration_accounts import IntegrationAccountClient

            session_id = None
            jwt = None
            if self._account_credential_scope:
                session_id, jwt = _resolve_task_auth(
                    {
                        "credential_scope": self._account_credential_scope,
                        "runtime_auth_required": False,
                    },
                    require_auth=True,
                    expected_user_email=self._account_expected_user_email,
                )
            self.account_provider = SellerSpriteAccountProvider(
                self.settings,
                integration_client=IntegrationAccountClient(jwt=jwt, session_id=session_id),
                allow_local_fallback=False,
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
        self._prune_runtime_auth()
        claimed = self.store.claim_next(
            queue_scope=QUEUE_SCOPE,
            worker_key=DEFAULT_WORKER_KEY,
            assigned_account=self._assigned_account_name(),
            account_key=self._assigned_account_name(),
            execution_owner=self._session_owner_id,
            lease_seconds=self.task_lease_seconds,
        )
        if claimed is None:
            await asyncio.sleep(self.poll_interval_seconds)
            return
        job_id = str(claimed["job_id"])
        attempt_id = self._track_attempt(claimed)
        try:
            await self._run_one(
                job_id,
                execution_account_key=str(claimed["assigned_account_key"]),
                assignment_generation=int(claimed["assignment_generation"]),
            )
        except Exception:
            # 单条任务的审计收尾异常不能拖垮整个后台 worker，记录后继续消费后续任务。
            logger.exception("卖家精灵任务调度执行异常，继续消费后续任务：job_id=%s", job_id)
        finally:
            self._untrack_attempt(job_id, attempt_id=attempt_id)

    async def _run_one(
        self,
        job_id: str,
        *,
        account: SellerSpriteAccount | None = None,
        close_account_on_auth_failure: bool = False,
        execution_account_key: str | None = None,
        assignment_generation: int | None = None,
    ) -> None:
        """执行单账号兼容任务或已显式绑定账号的任务。"""
        has_mcp_run = False
        try:
            request = self.store.get_request(job_id)
            context = self.store.get_task_context(job_id)
            runtime_auth = self._runtime_auth.pop(job_id, None)
            expected_user_email = context.get("expected_user_email")
            has_mcp_run = self._has_mcp_run(
                job_id,
                fail_closed=bool(expected_user_email),
            )
            if not expected_user_email and has_mcp_run:
                expected_user_email = str(self.store.get_mcp_run(job_id)["user_email"])
            session_id, jwt = _resolve_task_auth(
                context,
                runtime_auth=runtime_auth,
                require_auth=bool(expected_user_email or has_mcp_run),
                expected_user_email=expected_user_email,
            )
            manager = self.manager_factory(
                settings=self.settings,
                account_provider=(
                    _FixedSellerSpriteAccountProvider(account)
                    if account is not None
                    else self.account_provider
                ),
                jwt=jwt,
                session_id=session_id,
            )
            if execution_account_key is not None and assignment_generation is not None:
                self._configure_manager_progress(
                    manager=manager,
                    job_id=job_id,
                    account_key=execution_account_key,
                    assignment_generation=assignment_generation,
                )
            if isinstance(manager, SellerSpriteApiManager):
                self._configure_listing_analysis_resume(
                    manager=manager,
                    job_id=job_id,
                    assignment_generation=assignment_generation,
                )
            if has_mcp_run:
                self.store.mark_mcp_run_running(job_id)
            if isinstance(manager, SellerSpriteApiManager):
                account = manager.account_provider.get_default()
                result = await self._run_manager_with_session_reservation(
                    manager=manager,
                    request=request,
                    account=account,
                )
            else:
                # 测试或扩展工厂未必暴露账号 provider，保持既有执行器协议兼容。
                result = await self._run_manager_with_timeout(manager, request)
            export_payload = self._build_mcp_export_payload(request, result)
            task_export = result.export.to_dict() if result.export else None
            if execution_account_key is not None and assignment_generation is not None:
                committed = self.store.finish_task_and_mcp_run_if_current(
                    job_id=job_id,
                    account_key=execution_account_key,
                    assignment_generation=assignment_generation,
                    result_path=result.result_path,
                    row_count=result.row_count,
                    export_payload=task_export,
                    mcp_export_payload=export_payload if has_mcp_run else None,
                )
            else:
                self.store.finish_task(
                    job_id=job_id,
                    result_path=result.result_path,
                    row_count=result.row_count,
                    export_payload=task_export,
                )
                if has_mcp_run:
                    self.store.finish_mcp_run_success(
                        job_id,
                        result.row_count,
                        export_payload,
                    )
                committed = True
            if committed:
                self._submit_collection_result(request=request, result=result)
        except Exception as exc:
            error_payload = error_to_dict(exc)
            if execution_account_key is not None and assignment_generation is not None:
                self.store.fail_task_and_mcp_run_if_current(
                    job_id=job_id,
                    account_key=execution_account_key,
                    assignment_generation=assignment_generation,
                    error_payload=error_payload,
                    update_mcp_run=has_mcp_run,
                )
            else:
                self.store.fail_task(job_id=job_id, error_payload=error_payload)
                if has_mcp_run:
                    self.store.finish_mcp_run_failed(job_id, error_payload)
            if isinstance(exc, SellerSpriteTaskTimeoutError) and account is not None:
                await self._close_account_session(account, reason="task_timeout")
            elif (
                close_account_on_auth_failure
                and account is not None
                and _is_account_authentication_failure(exc)
            ):
                await self._close_account_session(
                    account,
                    reason=ACCOUNT_FAILURE_REASON_AUTHENTICATION,
                )
        finally:
            self._runtime_auth.pop(job_id, None)

    def _configure_manager_progress(
        self,
        *,
        manager: Any,
        job_id: str,
        account_key: str,
        assignment_generation: int,
    ) -> None:
        """通过公开监听器属性向兼容执行器注入当前尝试的进度回调。"""

        def listener(stage: str, metadata: dict[str, Any] | None = None) -> None:
            committed = self._report_task_progress(
                job_id=job_id,
                account_key=account_key,
                assignment_generation=assignment_generation,
                stage=stage,
                metadata=metadata,
            )
            if not committed:
                raise SellerSpriteConfigError("卖家精灵任务执行代际已失效")

        if isinstance(manager, SellerSpriteApiManager) or hasattr(manager, "progress_listener"):
            manager.progress_listener = listener

    def _configure_listing_analysis_resume(
        self,
        *,
        manager: SellerSpriteApiManager,
        job_id: str,
        assignment_generation: int | None,
    ) -> None:
        """向默认执行器注入远端任务检查点及当前代际持久化回调。"""
        request = self.store.get_request(job_id)
        if request.scenario.strip().lower() != "listing-analysis":
            return
        generation = int(assignment_generation or 0)
        manager.listing_remote_task_id = self.store.get_listing_analysis_task_id(job_id)

        def save_task_id(task_id: str) -> None:
            committed = self.store.save_listing_analysis_task_id(
                job_id=job_id,
                task_id=task_id,
                execution_owner=self._session_owner_id,
                assignment_generation=generation,
            )
            if not committed:
                raise SellerSpriteConfigError("Listing Analysis 执行代际已失效")

        manager.listing_task_id_listener = save_task_id

    def _default_manager_factory(self, **kwargs) -> SellerSpriteApiManager:
        return SellerSpriteApiManager(
            **kwargs,
            session_state_listener=self._record_browser_session_state_change,
            session_owner_id=self._session_owner_id,
        )

    async def _run_manager_with_session_reservation(
        self,
        *,
        manager: SellerSpriteApiManager,
        request: SellerSpriteScenarioRequest,
        account: SellerSpriteAccount,
    ) -> SellerSpriteScenarioResult:
        """预留已有 browser 会话并执行任务，结束后可靠释放预留。

        参数：
            manager: 当前任务的场景执行器。
            request: 已领取的任务请求。
            account: 当前工作槽账号。

        返回：
            场景执行结果。

        异常：
            Exception: 透传场景执行器异常。
        """
        reservation = None
        mode = str(request.mode or self.settings.default_mode).strip().lower()
        if mode == "browser-route":
            from opscli.seller_sprite.browser_route.worker import reserve_browser_route_worker

            reservation = reserve_browser_route_worker(
                settings=self.settings,
                account=account,
                owner_id=self._session_owner_id,
            )
        try:
            return await self._run_manager_with_timeout(manager, request)
        finally:
            if reservation is not None:
                reservation.release_reservation()

    async def _run_manager_with_timeout(
        self,
        manager: Any,
        request: SellerSpriteScenarioRequest,
    ) -> SellerSpriteScenarioResult:
        """在统一时间上限内执行场景，超时时转换为稳定领域错误。"""
        timeout_seconds = max(0.01, float(self.settings.task_timeout_seconds))
        try:
            return await asyncio.wait_for(
                manager.run(request),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise SellerSpriteTaskTimeoutError(
                f"卖家精灵任务执行超过 {timeout_seconds:g} 秒，已终止"
            ) from exc

    def _record_browser_session_state_change(
        self,
        account: SellerSpriteAccount,
        payload: dict[str, Any],
    ) -> None:
        """把 browser worker 的白名单生命周期状态转交统一事件记录器。"""
        self._event_recorder.record_session_state_payload(account, payload)

    def _prune_runtime_auth(self) -> None:
        """清理已被其他进程终止的排队任务凭证，避免敏感信息滞留内存。"""
        for job_id in list(self._runtime_auth):
            try:
                state = str(self.store.get_status(job_id)["state"])
            except Exception:
                continue
            if state in {"succeeded", "failed", "cancelled"}:
                self._runtime_auth.pop(job_id, None)

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

    def _has_mcp_run(self, job_id: str, *, fail_closed: bool = False) -> bool:
        """探测任务是否存在 MCP 调用记录。"""
        try:
            self.store.get_mcp_run(job_id)
            return True
        except ValueError:
            return False
        except Exception:
            if fail_closed:
                raise
            # 兼容没有 MCP 身份标记的本地旧任务；新 MCP 任务会携带提交者并严格失败关闭。
            logger.warning("探测 MCP 调用记录失败，按普通旧任务继续执行：job_id=%s", job_id, exc_info=True)
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

    def _submit_collection_result(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        result: SellerSpriteScenarioResult,
    ) -> None:
        """提交已经成功的采集结果；沉淀异常不能回滚采集成功态。"""
        if self.collection_submitter is None:
            return
        try:
            status = self.store.get_status(result.job_id)
            if status.get("state") != "succeeded":
                return
            self.collection_submitter(request=request, result=result, status=status)
        except Exception:
            logger.exception(
                "卖家精灵成功任务提交采集数据沉淀失败：job_id=%s",
                result.job_id,
            )


def get_task_scheduler(
    *,
    settings: SellerSpriteSettings | None = None,
    account_provider=None,
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
        )
        _SCHEDULERS[key] = scheduler
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


def _now_iso() -> str:
    """返回带时区的秒级当前时间。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _heartbeat_is_fresh(value: Any, *, max_age_seconds: float) -> bool:
    """判断持久化心跳是否仍在允许的健康窗口内。"""
    if not value:
        return False
    try:
        heartbeat_at = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - heartbeat_at.astimezone(timezone.utc)
    return age.total_seconds() <= max(1.0, float(max_age_seconds))


def _is_account_authentication_failure(exc: Exception) -> bool:
    """仅识别可确认未通过认证、允许安全换账号重放的错误。"""
    if isinstance(exc, SellerSpriteAuthenticationError):
        return True
    if not isinstance(exc, SellerSpriteApiError):
        return False
    return exc.is_session_expired() or exc.status_code in {401, 403}


def _is_confirmed_credential_rejection(exc: Exception) -> bool:
    """仅把远端明确返回的 401/403 视为可跨进程隔离的凭证拒绝。"""
    return isinstance(exc, SellerSpriteApiError) and exc.status_code in {401, 403}


def _login_stage(exc: Exception, failover_count: int) -> str:
    """根据错误与接替次数返回稳定登录失败阶段。"""
    if isinstance(exc, SellerSpriteApiError) and exc.is_session_expired():
        return "relogin"
    return "failover" if failover_count else "initial"


def _resolve_task_auth(
    context: dict[str, Any],
    *,
    runtime_auth: tuple[str, str | None] | None = None,
    require_auth: bool = False,
    expected_user_email: str | None = None,
) -> tuple[str | None, str | None]:
    """优先使用逐任务内存凭证，否则从统一 CredentialStore 读取并严格失败关闭。"""
    if runtime_auth:
        return runtime_auth
    if context.get("runtime_auth_required"):
        raise SellerSpriteConfigError("显式任务凭证已随服务重启丢失，请重新提交卖家精灵任务")
    credential_scope = context.get("credential_scope")
    if credential_scope:
        from opscli.mcp.credential_cache import get_credential_cache

        base_dir = None if credential_scope == "default" else Path(str(credential_scope))
        cache = get_credential_cache(base_dir=base_dir)
        session_id = cache.get_session_id()
        if not session_id:
            raise SellerSpriteConfigError("卖家精灵任务凭证作用域未登录，请重新完成 OPS 授权后提交任务")
        actual_user_email = cache.get_email()
        if (
            expected_user_email
            and str(actual_user_email or "").strip().lower()
            != expected_user_email.strip().lower()
        ):
            raise SellerSpriteConfigError("卖家精灵任务凭证用户与提交用户不一致，请重新完成 OPS 授权后提交任务")
        return session_id, cache.get_jwt("ops")
    # 兼容升级前已经排队的旧任务；旧字段会在任务结束时清空。
    session_id = context.get("session_id")
    if not session_id and require_auth:
        raise SellerSpriteConfigError("卖家精灵任务缺少 OPS 授权，禁止回退服务器默认账号")
    return str(session_id) if session_id else None, context.get("jwt")
