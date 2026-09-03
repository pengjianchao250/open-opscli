"""Collector MCP 的 SellerSprite 预取计划执行器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from opscli.mcp.service_credentials import load_prefetch_service_auth
from opscli.shared.prefetch_schedule import (
    PrefetchRunClaim,
    PrefetchScheduleRepository,
    PrefetchSchedulerRuntime,
    load_prefetch_settings,
)


class CollectorPrefetchRuntime:
    """只领取 SellerSprite 来源，并复用 Collector 已启动的任务队列。"""

    def __init__(self, storage_runtime: Any, *, seller_sprite_enabled: bool) -> None:
        self.settings = load_prefetch_settings()
        self.scheduler = None
        mysql_settings = getattr(storage_runtime.settings, "mysql", None)
        if (
            storage_runtime.settings.enabled
            and seller_sprite_enabled
            and mysql_settings is not None
        ):
            repository = PrefetchScheduleRepository(
                settings=mysql_settings
            )
            self.scheduler = PrefetchSchedulerRuntime(
                runtime_id="collector",
                settings=self.settings,
                repository=repository,
                executors={"seller_sprite": self._execute_seller_sprite},
            )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """在 SellerSprite Bundle 就绪后启动预取调度器。"""
        if self.scheduler is not None:
            await self.scheduler.start()
        try:
            yield
        finally:
            if self.scheduler is not None:
                await self.scheduler.close()

    async def _execute_seller_sprite(
        self,
        claim: PrefetchRunClaim,
    ) -> dict[str, Any]:
        """用显式服务凭证作用域向共享账号池提交任务并等待终态。"""
        from opscli.seller_sprite.config import DEFAULT_MODE
        from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
        from opscli.seller_sprite.services import get_task_scheduler

        # 先验证服务凭证存在且邮箱匹配；实际凭证仍由 SellerSprite Worker 按作用域读取。
        load_prefetch_service_auth(self.settings, required=True)
        scope = str(self.settings.service_credential_scope)
        expected_email = str(self.settings.service_user_email)
        scheduler = get_task_scheduler()
        request = claim.request
        source_request = SellerSpriteScenarioRequest(
            scenario=claim.scenario,
            site=str(request.get("site") or "US"),
            period=str(request.get("period") or "30d"),
            params=dict(request.get("params") or {}),
            page_size=int(request.get("page_size") or 100),
            job_id=claim.job_id,
            export_format=str(request.get("export_format") or "json"),
            mode=DEFAULT_MODE,
        )
        try:
            status = scheduler.job_status(claim.job_id)
        except ValueError:
            status = await scheduler.enqueue(
                source_request,
                credential_scope=scope,
                expected_user_email=expected_email,
            )
        deadline = asyncio.get_running_loop().time() + max(
            900.0,
            float(scheduler.settings.task_timeout_seconds) + 300.0,
        )
        while str(status.get("state")) not in {"succeeded", "failed"}:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("SellerSprite 预取任务等待终态超时")
            await asyncio.sleep(2)
            status = scheduler.job_status(claim.job_id)
        if status.get("state") == "failed":
            return {
                "success": False,
                "data": None,
                "error": status.get("error")
                or {"code": "SELLER_SPRITE_PREFETCH_FAILED", "message": "任务失败"},
            }
        return {
            "success": True,
            "data": {"job_id": claim.job_id, "state": "succeeded"},
            "error": None,
        }
