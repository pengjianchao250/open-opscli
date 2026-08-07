"""MCP 宿主共享的采集结果沉淀生命周期。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Protocol

from opscli.shared.collection_storage.config import (
    CollectionStorageSettings,
    load_storage_settings,
)
from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    ReconciliationBatch,
)
from opscli.shared.collection_storage.mysql_repository import MySqlCollectionRepository
from opscli.shared.collection_storage.outbox import CollectionOutbox
from opscli.shared.collection_storage.registry import (
    CollectionParser,
    CollectionParserRegistry,
)
from opscli.shared.collection_storage.worker import (
    CollectionPersistenceWorker,
    CollectionRepository,
)


class CollectionReconciler(Protocol):
    """来源模块按 live cutover 和单调游标返回成功任务的接口。"""

    source_system: str

    def reconcile(
        self, *, cutover_at: str, cursor: int, limit: int
    ) -> ReconciliationBatch:
        """返回 cutover 后位于来源单调游标之后的成功任务。"""
        ...


class CollectionStorageRuntime:
    """集中管理 Outbox、Parser Registry、MySQL Adapter 和 Worker。"""

    def __init__(
        self,
        settings: CollectionStorageSettings,
        *,
        registry: CollectionParserRegistry | None = None,
        repository: CollectionRepository | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or CollectionParserRegistry()
        self.repository = repository
        self.outbox: CollectionOutbox | None = None
        self.worker: CollectionPersistenceWorker | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._stop_requested = False
        self._mysql_ready = False
        self._mysql_error_code: str | None = None
        self._loop_error_code: str | None = None
        self._reconcilers: dict[str, CollectionReconciler] = {}
        self._cutover_at: str | None = None
        self._last_reconcile_at = 0.0
        self._reconcile_error_code: str | None = None

    async def start(self) -> None:
        """初始化持久状态并启动后台 Worker；关闭配置时保持零副作用。"""
        if not self.settings.enabled:
            return
        if self._worker_task is not None and not self._worker_task.done():
            return
        self.outbox = CollectionOutbox(self.settings.outbox_db_path)
        self._cutover_at = self.outbox.get_or_create_meta(
            "live_cutover_at",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        if self.repository is None:
            self.repository = MySqlCollectionRepository(
                settings=self.settings.mysql,
                batch_size=self.settings.batch_size,
            )
        self.worker = CollectionPersistenceWorker(
            outbox=self.outbox,
            registry=self.registry,
            repository=self.repository,
            lease_seconds=self.settings.lease_seconds,
        )
        self._stop_requested = False
        await self._ensure_schema()
        self._worker_task = asyncio.create_task(
            self._run_loop(),
            name=f"{self.settings.runtime_id}-collection-storage",
        )

    async def close(self) -> None:
        """有界停止后台 Worker，不删除未完成 Outbox。"""
        self._stop_requested = True
        self._wake_event.set()
        task = self._worker_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._worker_task = None

    def register_parser(self, parser: CollectionParser) -> None:
        """注册启用来源的 Parser。"""
        self.registry.register(parser)
        self._wake_event.set()

    def unregister_parser(self, source_system: str) -> None:
        """移除已经停止的来源 Parser。"""
        self.registry.unregister(source_system)

    def register_reconciler(self, reconciler: CollectionReconciler) -> None:
        """注册来源成功任务对账器，恢复成功态与 Outbox 之间的宕机窗口。"""
        source_system = str(reconciler.source_system or "").strip()
        if not source_system:
            raise ValueError("Collection Reconciler source_system 不能为空")
        if source_system in self._reconcilers:
            raise ValueError(f"Collection Reconciler 重复注册：{source_system}")
        self._reconcilers[source_system] = reconciler
        self._wake_event.set()

    def unregister_reconciler(self, source_system: str) -> None:
        """移除已经停止的来源成功任务对账器。"""
        self._reconcilers.pop(source_system, None)

    def register_source(
        self,
        parser: CollectionParser,
        reconciler: CollectionReconciler | None = None,
    ) -> None:
        """原子注册一个来源的 Parser 和可选 Reconciler Adapter。"""
        source_system = str(parser.source_system or "").strip()
        if reconciler is not None and reconciler.source_system != source_system:
            raise ValueError("Collection 来源 Parser 与 Reconciler 标识不一致")
        self.register_parser(parser)
        try:
            if reconciler is not None:
                self.register_reconciler(reconciler)
        except Exception:
            self.unregister_parser(source_system)
            raise

    def unregister_source(self, source_system: str) -> None:
        """逆序解除一个来源的 Reconciler 和 Parser Adapter。"""
        self.unregister_reconciler(source_system)
        self.unregister_parser(source_system)

    def submit(self, submission: CollectionSubmission) -> bool:
        """幂等提交成功采集任务，并唤醒后台 Worker。"""
        if not self.settings.enabled:
            return False
        if submission.data_environment != self.settings.data_environment:
            raise ValueError("Collection Submission 环境与 Runtime 配置不一致")
        if self.outbox is None:
            raise RuntimeError("数据沉淀 Runtime 尚未启动")
        self.outbox.submit(submission)
        self._wake_event.set()
        return True

    def health(self) -> dict[str, Any]:
        """返回不包含数据库地址、账号、密码和文件路径的健康摘要。"""
        if not self.settings.enabled:
            return {
                "status": "disabled",
                "checks": {
                    "outbox": "disabled",
                    "mysql": "disabled",
                    "worker": "disabled",
                },
            }
        worker_running = bool(
            self._worker_task is not None and not self._worker_task.done()
        )
        worker_error = self.worker.last_error_code if self.worker else None
        counts = self.outbox.status_counts() if self.outbox is not None else {}
        status = (
            "ready"
            if self._mysql_ready
            and worker_running
            and not worker_error
            and not self._loop_error_code
            and not counts.get("failed")
            else "degraded"
        )
        result: dict[str, Any] = {
            "status": status,
            "checks": {
                "outbox": "ok" if self.outbox is not None else "not_ready",
                "mysql": "ok" if self._mysql_ready else "error",
                "worker": "running" if worker_running else "stopped",
            },
            "outbox": counts,
        }
        error_code = (
            worker_error
            or self._loop_error_code
            or self._mysql_error_code
            or self._reconcile_error_code
        )
        if error_code:
            result["error_code"] = error_code
        return result

    async def _run_loop(self) -> None:
        while not self._stop_requested:
            try:
                if not self._mysql_ready:
                    await self._ensure_schema()
                now = time.monotonic()
                if (
                    self._reconcilers
                    and now - self._last_reconcile_at
                    >= self.settings.reconcile_interval_seconds
                ):
                    await self._reconcile_once()
                    self._last_reconcile_at = now
                processed = False
                if self._mysql_ready and self.worker is not None:
                    processed = await self.worker.process_once()
                self._loop_error_code = None
                if processed:
                    continue
            except asyncio.CancelledError:
                raise
            # Outbox 锁、磁盘 I/O 或完成确认异常不能永久杀死后台任务；租约会负责重放。
            except Exception as exc:  # noqa: BLE001
                self._loop_error_code = type(exc).__name__
            await self._wait_for_wake()

    async def _wait_for_wake(self) -> None:
        """等待新任务或轮询超时，并允许 close 立即唤醒循环。"""
        self._wake_event.clear()
        try:
            await asyncio.wait_for(
                self._wake_event.wait(),
                timeout=self.settings.poll_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass

    async def _ensure_schema(self) -> None:
        if self.repository is None:
            return
        try:
            action = (
                self.repository.create_schema
                if self.settings.auto_create_schema
                else self.repository.check_schema
            )
            await asyncio.to_thread(action)
        # 数据库驱动或网络异常只使存储降级，不能杀死宿主的业务 Tool。
        except Exception as exc:  # noqa: BLE001
            self._mysql_ready = False
            self._mysql_error_code = type(exc).__name__
        else:
            self._mysql_ready = True
            self._mysql_error_code = None

    async def _reconcile_once(self) -> None:
        if self.outbox is None or self._cutover_at is None:
            return
        try:
            for source_system, reconciler in tuple(self._reconcilers.items()):
                cursor_key = f"reconcile_cursor:{source_system}"
                cursor = int(self.outbox.get_meta(cursor_key) or 0)
                batch = await asyncio.to_thread(
                    reconciler.reconcile,
                    cutover_at=self._cutover_at,
                    cursor=cursor,
                    limit=500,
                )
                for submission in batch.submissions:
                    if submission.data_environment != self.settings.data_environment:
                        raise ValueError("对账任务环境与 Runtime 配置不一致")
                    await asyncio.to_thread(self.outbox.submit, submission)
                if batch.next_cursor != cursor:
                    self.outbox.set_meta(cursor_key, str(batch.next_cursor))
            self._reconcile_error_code = None
            self._wake_event.set()
        # Reconciler 来自独立来源 Adapter，异常隔离到下一轮重试。
        except Exception as exc:  # noqa: BLE001
            self._reconcile_error_code = type(exc).__name__


def build_collection_storage_runtime(runtime_id: str) -> CollectionStorageRuntime:
    """为一个 MCP App 构造由其生命周期独占的沉淀 Runtime。"""
    return CollectionStorageRuntime(load_storage_settings(runtime_id))


@asynccontextmanager
async def collection_storage_lifespan(
    runtime: CollectionStorageRuntime,
) -> AsyncIterator[CollectionStorageRuntime]:
    """供任意 MCP 宿主组合的共享存储生命周期。"""
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.close()
