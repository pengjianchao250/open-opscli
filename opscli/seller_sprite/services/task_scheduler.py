"""卖家精灵单账号任务调度器。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from opscli.seller_sprite.config import SellerSpriteSettings, load_settings
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services.api_manager import SellerSpriteApiManager, _build_job_id
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore
from opscli.seller_sprite.services.task_status import error_to_dict


QUEUE_SCOPE = "seller_sprite"
DEFAULT_WORKER_KEY = "default"
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
    ) -> None:
        self.settings = settings or load_settings()
        self.account_provider = account_provider
        self.store = store or SellerSpriteTaskQueueStore()
        self.jwt = jwt
        self.session_id = session_id
        self.auto_start = auto_start
        self.poll_interval_seconds = poll_interval_seconds
        self.manager_factory = manager_factory or self._default_manager_factory
        self._runner_task: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()
        self._stop_requested = False

    async def enqueue(self, request: SellerSpriteScenarioRequest) -> dict[str, Any]:
        """入队并按需启动后台调度循环。"""
        normalized = self._normalize_request(request)
        root_dir = self._build_root_dir(normalized)
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
        """启动后台调度循环，并恢复残留运行中任务。"""
        async with self._start_lock:
            if self._runner_task and not self._runner_task.done():
                return
            self._stop_requested = False
            self.store.reset_running_tasks()
            self._runner_task = asyncio.create_task(self._run_loop())

    async def close(self) -> None:
        """停止后台调度循环。"""
        self._stop_requested = True
        if self._runner_task is None:
            return
        await self._runner_task
        self._runner_task = None

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
            account = self._get_default_account()
            claimed = self.store.claim_next(
                queue_scope=QUEUE_SCOPE,
                worker_key=DEFAULT_WORKER_KEY,
                assigned_account=account.name,
            )
            if claimed is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
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
        return SellerSpriteApiManager(**kwargs)

    def _get_default_account(self):
        if self.account_provider is None:
            manager = self._default_manager_factory(settings=self.settings, jwt=self.jwt, session_id=self.session_id)
            return manager.account_provider.get_default()
        return self.account_provider.get_default()

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
    loop_key = id(asyncio.get_running_loop())
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
