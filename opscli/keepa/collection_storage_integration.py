"""Keepa 到共享数据沉淀接口的适配。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    DataEnvironment,
    ReconciliationBatch,
)
from opscli.keepa.domain.models import KeepaScenarioRequest, KeepaScenarioResult


class _StorageRuntime(Protocol):
    settings: Any

    def submit(self, submission: CollectionSubmission) -> bool: ...


class _Outbox(Protocol):
    def contains(
        self,
        *,
        source_system: str,
        source_job_id: str,
        data_environment: str,
    ) -> bool: ...


class KeepaCollectionSubmitter:
    """将 Keepa 成功结果转换为通用 CollectionSubmission。"""

    def __init__(self, runtime: _StorageRuntime) -> None:
        self.runtime = runtime

    def __call__(
        self,
        *,
        request: KeepaScenarioRequest,
        result: KeepaScenarioResult,
    ) -> bool:
        """把完整 Keepa 成功结果幂等提交到当前 MCP 宿主 Outbox。"""
        environment = str(self.runtime.settings.data_environment or "").strip()
        submission = CollectionSubmission(
            source_system="keepa",
            source_job_id=result.job_id,
            producer_service="mcp",
            scenario=request.scenario,
            site=result.site,
            data_environment=cast(DataEnvironment, environment),
            ingestion_mode="live",
            result_path=result.result_path,
        )
        return self.runtime.submit(submission)


class KeepaCollectionReconciler:
    """补交 cutover 后已落盘但尚未进入 Outbox 的 Keepa 成功任务。"""

    source_system = "keepa"

    def __init__(
        self,
        *,
        output_dir: Path,
        data_environment: str,
        outbox: _Outbox,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.data_environment = data_environment
        self.outbox = outbox

    def reconcile(
        self,
        *,
        cutover_at: str,
        cursor: int,
        limit: int,
    ) -> ReconciliationBatch:
        """按结果完成时间扫描遗漏任务，Outbox 唯一键负责幂等去重。"""
        cutover = _parse_datetime(cutover_at)
        submissions: list[CollectionSubmission] = []
        next_cursor = cursor
        max_submissions = max(1, int(limit))
        candidates = _result_candidates(
            self.output_dir,
            cutover=cutover,
            cursor=cursor,
        )
        for completed_ns, result_path, completed_at in candidates:
            if len(submissions) >= max_submissions:
                # 同一文件系统时间粒度下可能有多个结果共享 mtime；回退一个
                # 纳秒可让下一轮重读边界组，再由 Outbox 唯一键去重。
                if completed_ns == next_cursor:
                    next_cursor = max(cursor, next_cursor - 1)
                break
            next_cursor = max(next_cursor, completed_ns)
            payload = _read_success_result(result_path)
            if payload is None:
                continue
            job_id = str(payload.get("job_id") or "").strip()
            scenario = str(payload.get("scenario") or "").strip()
            site = str(payload.get("site") or "").strip()
            if not all((job_id, scenario, site)):
                continue
            if self.outbox.contains(
                source_system=self.source_system,
                source_job_id=job_id,
                data_environment=self.data_environment,
            ):
                continue
            submissions.append(
                CollectionSubmission(
                    source_system=self.source_system,
                    source_job_id=job_id,
                    producer_service="mcp",
                    scenario=scenario,
                    site=site,
                    data_environment=cast(
                        DataEnvironment,
                        self.data_environment,
                    ),
                    ingestion_mode="live",
                    result_path=result_path,
                    completed_at=completed_at.isoformat(timespec="seconds"),
                )
            )
        return ReconciliationBatch(tuple(submissions), next_cursor)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _result_candidates(
    output_dir: Path,
    *,
    cutover: datetime,
    cursor: int,
) -> list[tuple[int, Path, datetime]]:
    """只排序水位之后的结果，避免重复查询历史任务的 Outbox 状态。"""
    candidates: list[tuple[int, Path, datetime]] = []
    for path in output_dir.glob("*/result.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime_ns <= cursor:
            continue
        completed_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        if completed_at <= cutover:
            continue
        candidates.append((stat.st_mtime_ns, path, completed_at))
    return sorted(candidates, key=lambda item: (item[0], item[1].parent.name))


def _read_success_result(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
