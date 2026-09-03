"""按来源归属消费预取运行队列的后台调度器。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from opscli.shared.prefetch_schedule.config import PrefetchScheduleSettings
from opscli.shared.prefetch_schedule.models import PrefetchRunClaim
from opscli.shared.prefetch_schedule.repository import PrefetchScheduleRepository

PrefetchExecutor = Callable[[PrefetchRunClaim], Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)


class PrefetchSchedulerRuntime:
    """为一个 MCP 宿主领取其负责来源的预取运行。"""

    def __init__(
        self,
        *,
        runtime_id: str,
        settings: PrefetchScheduleSettings,
        repository: PrefetchScheduleRepository,
        executors: dict[str, PrefetchExecutor],
    ) -> None:
        self.runtime_id = runtime_id
        self.settings = settings
        self.repository = repository
        self.executors = dict(executors)
        self.execution_owner = f"{runtime_id}-{uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self.last_error_code: str | None = None

    async def start(self) -> None:
        """在显式启用且存在来源执行器时启动后台循环。"""
        if not self.settings.enabled or not self.executors:
            return
        if self._task is not None and not self._task.done():
            return
        self._stop_requested = False
        self._task = asyncio.create_task(
            self._run_loop(),
            name=f"{self.runtime_id}-prefetch-scheduler",
        )

    async def close(self) -> None:
        """停止领取新任务，并等待当前单条运行有界收尾。"""
        self._stop_requested = True
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=15)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._task = None

    def health(self) -> dict[str, Any]:
        """返回不包含计划参数和凭证的运行状态摘要。"""
        if not self.settings.enabled:
            return {"status": "disabled", "owned_sources": sorted(self.executors)}
        running = bool(self._task is not None and not self._task.done())
        result: dict[str, Any] = {
            "status": "ready" if running and not self.last_error_code else "degraded",
            "owned_sources": sorted(self.executors),
            "worker": "running" if running else "stopped",
        }
        if self.last_error_code:
            result["error_code"] = self.last_error_code
        return result

    async def process_once(self) -> bool:
        """推进到期计划，并消费最多一条属于当前宿主的运行。"""
        sources = tuple(self.executors)
        await asyncio.to_thread(
            self.repository.enqueue_due,
            source_systems=sources,
        )
        claim = await asyncio.to_thread(
            self.repository.claim_next,
            source_systems=sources,
            execution_owner=self.execution_owner,
            lease_seconds=self.settings.lease_seconds,
        )
        if claim is None:
            return False
        await self._execute_claim(claim)
        return True

    async def _run_loop(self) -> None:
        while not self._stop_requested:
            try:
                processed = await self.process_once()
                self.last_error_code = None
                if processed:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error_code = type(exc).__name__
                logger.exception("预取计划调度循环失败，下一轮继续重试")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _execute_claim(self, claim: PrefetchRunClaim) -> None:
        executor = self.executors[claim.source_system]
        execution = asyncio.create_task(
            executor(claim),
            name=f"prefetch-execution-{claim.run_id}",
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(claim.run_id),
            name=f"prefetch-lease-{claim.run_id}",
        )
        try:
            done, _pending = await asyncio.wait(
                {execution, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                # 心跳只会在租约丢失或续租异常时提前结束，继续请求会产生重复上游调用。
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                heartbeat_error = heartbeat.exception()
                if heartbeat_error is not None:
                    raise heartbeat_error
                raise RuntimeError("预取运行租约已丢失，当前来源执行已取消")
            result = await execution
            if not isinstance(result, dict) or not result.get("success"):
                error = result.get("error") if isinstance(result, dict) else None
                code = str((error or {}).get("code") or "PREFETCH_EXECUTION_FAILED")
                message = str((error or {}).get("message") or "预取来源执行失败")
                await asyncio.to_thread(
                    self.repository.finish_run,
                    run_id=claim.run_id,
                    execution_owner=self.execution_owner,
                    status="failed",
                    source_job_id=claim.job_id,
                    error_code=code[:128],
                    error_message=_sanitize_error(message),
                )
                return
            data = result.get("data")
            source_job_id = (
                str(data.get("job_id"))
                if isinstance(data, dict) and data.get("job_id")
                else claim.job_id
            )
            await asyncio.to_thread(
                self.repository.finish_run,
                run_id=claim.run_id,
                execution_owner=self.execution_owner,
                status="succeeded",
                source_job_id=source_job_id,
            )
        except Exception as exc:  # noqa: BLE001
            await asyncio.to_thread(
                self.repository.finish_run,
                run_id=claim.run_id,
                execution_owner=self.execution_owner,
                status="failed",
                source_job_id=claim.job_id,
                error_code=type(exc).__name__[:128],
                error_message=_sanitize_error(str(exc)),
            )
        finally:
            execution.cancel()
            heartbeat.cancel()
            await asyncio.gather(execution, heartbeat, return_exceptions=True)

    async def _heartbeat(self, run_id: int) -> None:
        """执行期间周期续租，避免长任务被其他宿主重复领取。"""
        interval = max(1.0, self.settings.lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            extended = await asyncio.to_thread(
                self.repository.extend_lease,
                run_id=run_id,
                execution_owner=self.execution_owner,
                lease_seconds=self.settings.lease_seconds,
            )
            if not extended:
                return


def _sanitize_error(message: str) -> str:
    """移除常见凭证赋值片段，并限制数据库错误摘要长度。"""
    cleaned = re.sub(
        r"(?i)\b(password|passwd|pwd|token|api[_-]?key|session[_-]?id|"
        r"cookie|authorization)\s*[:=]\s*[^\s,;}\]]+",
        r"\1=***",
        message,
    )
    return cleaned[:500]
