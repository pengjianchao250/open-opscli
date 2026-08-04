"""卖家精灵 Bundle 到 Collector 通用沉淀接口的适配。"""

from __future__ import annotations

from typing import Any, Protocol, cast

from opscli.collector_mcp.storage.models import (
    CollectionSubmission,
    DataEnvironment,
    ReconciliationBatch,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)


class _StorageRuntime(Protocol):
    settings: Any

    def submit(self, submission: CollectionSubmission) -> bool: ...


class SellerSpriteCollectionSubmitter:
    """将 SellerSprite 成功结果转换为通用 CollectionSubmission。"""

    def __init__(self, runtime: _StorageRuntime) -> None:
        self.runtime = runtime

    def __call__(
        self,
        *,
        request: SellerSpriteScenarioRequest,
        result: SellerSpriteScenarioResult,
        status: dict[str, Any],
    ) -> bool:
        """把已提交成功态的 Scheduler 结果幂等写入 Collector Outbox。"""
        if status.get("state") != "succeeded":
            return False
        environment = str(self.runtime.settings.data_environment or "").strip()
        submission = CollectionSubmission(
            source_system="seller_sprite",
            source_job_id=result.job_id,
            producer_service="collector_mcp",
            scenario=request.scenario,
            site=request.site,
            data_environment=cast(DataEnvironment, environment),
            ingestion_mode="live",
            result_path=result.result_path,
            started_at=(
                str(status["started_at"]) if status.get("started_at") else None
            ),
            completed_at=(
                str(status["finished_at"]) if status.get("finished_at") else None
            ),
        )
        return self.runtime.submit(submission)


class SellerSpriteCollectionReconciler:
    """补交 live cutover 之后可能遗漏的 SellerSprite 成功任务。"""

    # 稳定来源标识用于 Parser Registry、Outbox 和 MySQL 幂等键。
    source_system = "seller_sprite"

    def __init__(self, *, store: Any, data_environment: str) -> None:
        self.store = store
        self.data_environment = data_environment

    def reconcile(
        self,
        *,
        cutover_at: str,
        cursor: int,
        limit: int,
    ) -> ReconciliationBatch:
        """按成功事件游标返回 live cutover 后遗漏的成功任务。"""
        statuses = self.store.list_succeeded_for_collection_storage(
            cutover_at=cutover_at,
            cursor=cursor,
            limit=limit,
        )
        submissions: list[CollectionSubmission] = []
        next_cursor = cursor
        for status in statuses:
            next_cursor = max(next_cursor, int(status["collection_cursor"]))
            result_path = status.get("result_path")
            if not result_path:
                continue
            submissions.append(
                CollectionSubmission(
                    source_system=self.source_system,
                    source_job_id=str(status["job_id"]),
                    producer_service="collector_mcp",
                    scenario=str(status["scenario"]),
                    site=str(status["site"]),
                    data_environment=cast(DataEnvironment, self.data_environment),
                    ingestion_mode="live",
                    result_path=result_path,
                    started_at=(
                        str(status["started_at"]) if status.get("started_at") else None
                    ),
                    completed_at=(
                        str(status["finished_at"])
                        if status.get("finished_at")
                        else None
                    ),
                )
            )
        return ReconciliationBatch(tuple(submissions), next_cursor)
