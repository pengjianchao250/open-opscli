"""共享采集结果沉淀领域模型。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

# 数据环境只表示记录来源，不用于推断文件目录或数据库连接。
DataEnvironment = Literal["production", "debug"]
# 入库模式区分在线新任务与未来显式执行的历史回填。
IngestionMode = Literal["live", "backfill"]


class PermanentCollectionError(ValueError):
    """重试不会自行恢复的来源合同或文件错误。"""


@dataclass(frozen=True)
class CollectionSubmission:
    """描述一个已经成功落盘、等待写入中心数据库的采集任务。"""

    source_system: str
    source_job_id: str
    producer_service: str
    scenario: str
    site: str
    data_environment: DataEnvironment
    ingestion_mode: IngestionMode
    result_path: Path
    started_at: str | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_system",
            "source_job_id",
            "producer_service",
            "scenario",
            "site",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} 不能为空")
        if self.data_environment not in {"production", "debug"}:
            raise ValueError("data_environment 仅支持 production 或 debug")
        if self.ingestion_mode not in {"live", "backfill"}:
            raise ValueError("ingestion_mode 仅支持 live 或 backfill")
        object.__setattr__(
            self, "result_path", Path(self.result_path).expanduser().resolve()
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为可持久化字典。"""
        payload = asdict(self)
        payload["result_path"] = str(self.result_path)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CollectionSubmission:
        """从 Outbox 载荷恢复提交模型。"""
        return cls(
            source_system=str(payload["source_system"]),
            source_job_id=str(payload["source_job_id"]),
            producer_service=str(payload["producer_service"]),
            scenario=str(payload["scenario"]),
            site=str(payload["site"]),
            data_environment=cast(DataEnvironment, str(payload["data_environment"])),
            ingestion_mode=cast(IngestionMode, str(payload["ingestion_mode"])),
            result_path=Path(str(payload["result_path"])),
            started_at=(
                str(payload["started_at"]) if payload.get("started_at") else None
            ),
            completed_at=(
                str(payload["completed_at"]) if payload.get("completed_at") else None
            ),
        )


@dataclass(frozen=True)
class OutboxRecord:
    """一次 Outbox 领取结果。"""

    id: int
    submission: CollectionSubmission
    status: str
    attempt_count: int
    available_at: str
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    last_error_code: str | None = None


@dataclass(frozen=True)
class CollectionArtifact:
    """一个需要登记但不直接写入 MySQL BLOB 的任务文件。"""

    artifact_type: str
    path: Path
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CollectionRecord:
    """逻辑 Dataset 中的一行格式化记录。"""

    row_number: int
    payload: dict[str, Any]
    record_hash: str
    business_key: str | None = None


@dataclass(frozen=True)
class CollectionDataset:
    """由主工作表或附加工作表形成的逻辑数据集。"""

    dataset_code: str
    dataset_name: str
    source_sheet: str
    columns: tuple[tuple[str, str], ...]
    records: Iterable[CollectionRecord]


@dataclass(frozen=True)
class ParsedCollection:
    """Parser 输出给数据库 Adapter 的完整采集文档。"""

    submission: CollectionSubmission
    parser_version: str
    request_params: dict[str, Any]
    artifacts: tuple[CollectionArtifact, ...]
    datasets: tuple[CollectionDataset, ...]


@dataclass(frozen=True)
class ReconciliationBatch:
    """来源对账器按单调游标返回的一批成功任务。"""

    submissions: tuple[CollectionSubmission, ...]
    next_cursor: int
