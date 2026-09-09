"""卖家精灵到共享数据沉淀接口的适配。"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, cast

from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    DataEnvironment,
    ReconciliationBatch,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.shared.collection_storage.result_cache import (
    build_cache_key,
    safe_result_metadata,
)
from opscli.seller_sprite.services.task_queue_store import (
    ACCOUNT_ROUTE_SHARED_POOL,
    ACCOUNT_ROUTE_USER_BINDING,
)


def seller_sprite_cache_scope(
    account_route: str | None,
    requested_account_key: str | None,
) -> str:
    """共享池结果跨用户复用，专属账号结果仅在同账号内复用。"""
    if account_route != ACCOUNT_ROUTE_USER_BINDING:
        return ACCOUNT_ROUTE_SHARED_POOL
    account_key = str(requested_account_key or "").strip()
    if not account_key:
        raise ValueError("专属账号缓存缺少 requested_account_key")
    digest = hashlib.sha256(account_key.encode("utf-8")).hexdigest()
    return f"dedicated:{digest}"


def build_seller_sprite_cache_identity(
    request: SellerSpriteScenarioRequest,
    *,
    account_route: str | None,
    requested_account_key: str | None,
) -> tuple[str, str]:
    """返回 SellerSprite 规范请求缓存键和账号隔离作用域。"""
    cache_key = build_cache_key(
        "seller_sprite",
        {
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "params": request.params,
            "page_size": request.page_size,
            "export_format": request.export_format,
            "mode": request.mode,
            "page_prepare": request.page_prepare,
        },
    )
    return cache_key, seller_sprite_cache_scope(
        account_route,
        requested_account_key,
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
        """把已提交成功态的 Scheduler 结果幂等写入宿主 Outbox。"""
        if status.get("state") != "succeeded":
            return False
        environment = str(self.runtime.settings.data_environment or "").strip()
        cache_key, cache_scope = build_seller_sprite_cache_identity(
            request,
            account_route=status.get("account_route"),
            requested_account_key=status.get("requested_account_key"),
        )
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
            cache_key=cache_key,
            cache_scope=cache_scope,
            result_metadata=safe_result_metadata(result.to_dict()),
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
            binding = self.store.get_task_account_binding(str(status["job_id"]))
            request = self.store.get_request(str(status["job_id"]))
            cache_key, cache_scope = build_seller_sprite_cache_identity(
                request,
                account_route=binding.get("account_route"),
                requested_account_key=binding.get("requested_account_key"),
            )
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
                    cache_key=cache_key,
                    cache_scope=cache_scope,
                    result_metadata=safe_result_metadata(status),
                )
            )
        return ReconciliationBatch(tuple(submissions), next_cursor)
