"""共享采集结果持久化 Worker。"""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import uuid4

from opscli.shared.collection_storage.models import (
    ParsedCollection,
    PermanentCollectionError,
)
from opscli.shared.collection_storage.outbox import CollectionOutbox
from opscli.shared.collection_storage.registry import CollectionParserRegistry


class CollectionRepository(Protocol):
    """中心数据库持久化接口。"""

    def create_schema(self) -> None:
        """使用迁移权限初始化当前版本表结构。"""
        ...

    def check_schema(self) -> None:
        """验证运行账号可访问兼容版本的表结构。"""
        ...

    def persist(self, document: ParsedCollection) -> None:
        """以任务为事务单位幂等保存一个采集文档。"""
        ...


class CollectionPersistenceWorker:
    """从通用 Outbox 领取任务并通过来源 Parser 写入 Repository。"""

    def __init__(
        self,
        *,
        outbox: CollectionOutbox,
        registry: CollectionParserRegistry,
        repository: CollectionRepository,
        lease_seconds: float,
        owner: str | None = None,
    ) -> None:
        self.outbox = outbox
        self.registry = registry
        self.repository = repository
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.owner = owner or f"collection-worker-{uuid4().hex}"
        self.last_error_code: str | None = None

    async def process_once(self) -> bool:
        """处理至多一条记录；没有可执行记录时返回 False。"""
        record = await asyncio.to_thread(
            self.outbox.claim_next,
            owner=self.owner,
            lease_seconds=self.lease_seconds,
        )
        if record is None:
            return False
        try:
            parser = self.registry.resolve(record.submission.source_system)
            document = await asyncio.to_thread(parser.parse, record.submission)
            await asyncio.to_thread(self.repository.persist, document)
        except PermanentCollectionError as exc:
            self.last_error_code = type(exc).__name__
            failed = await asyncio.to_thread(
                self.outbox.fail,
                record.id,
                owner=self.owner,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            if not failed:
                raise RuntimeError("Collection Outbox 永久失败状态提交失败") from exc
            return True
        except Exception as exc:
            self.last_error_code = type(exc).__name__
            delay_seconds = min(3600.0, float(2 ** min(record.attempt_count, 10)))
            retried = await asyncio.to_thread(
                self.outbox.retry,
                record.id,
                owner=self.owner,
                error_code=type(exc).__name__,
                error_message=str(exc),
                delay_seconds=delay_seconds,
            )
            if not retried:
                raise RuntimeError("Collection Outbox 重试状态提交失败") from exc
            return True
        completed = await asyncio.to_thread(
            self.outbox.complete, record.id, owner=self.owner
        )
        if not completed:
            raise RuntimeError("Collection Outbox 完成确认失败，租约可能已失效")
        self.last_error_code = None
        return True
