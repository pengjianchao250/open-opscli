"""Google Trends 到共享数据沉淀接口的适配。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from opscli.google_trends.domain.models import (
    GoogleTrendsScenarioRequest,
    GoogleTrendsScenarioResult,
)
from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    DataEnvironment,
    ReconciliationBatch,
)


class _StorageRuntime(Protocol):
    """约束提交器依赖的最小共享存储接口。"""

    settings: Any

    def submit(self, submission: CollectionSubmission) -> bool: ...


class _Outbox(Protocol):
    """约束对账器依赖的 Outbox 查询接口。"""

    def contains(
        self,
        *,
        source_system: str,
        source_job_id: str,
        data_environment: str,
    ) -> bool: ...


class GoogleTrendsCollectionSubmitter:
    """将 Google Trends 成功结果转换为通用 CollectionSubmission。"""

    def __init__(self, runtime: _StorageRuntime) -> None:
        """初始化提交器。

        Args:
            runtime: 当前 MCP 宿主共享的存储 Runtime。
        """
        self.runtime = runtime

    def __call__(
        self,
        *,
        request: GoogleTrendsScenarioRequest,
        result: GoogleTrendsScenarioResult,
    ) -> bool:
        """把完整 Google Trends 成功结果幂等提交到当前 MCP 宿主 Outbox。

        Args:
            request: 本次 Google Trends 场景请求。
            result: 已完整落盘的成功结果。

        Returns:
            Runtime 是否接受提交。

        Raises:
            ValueError: 提交字段或数据环境不合法。
            RuntimeError: 共享存储 Runtime 尚未启动。
        """
        environment = str(self.runtime.settings.data_environment or "").strip()
        submission = CollectionSubmission(
            source_system="google_trends",
            source_job_id=result.job_id,
            producer_service="mcp",
            scenario=request.scenario,
            site=result.geo,
            data_environment=cast(DataEnvironment, environment),
            ingestion_mode="live",
            result_path=result.result_path,
        )
        return self.runtime.submit(submission)


class GoogleTrendsCollectionReconciler:
    """补交 cutover 后已落盘但尚未进入 Outbox 的 Google Trends 成功任务。"""

    source_system = "google_trends"

    def __init__(
        self,
        *,
        output_dir: Path,
        data_environment: str,
        outbox: _Outbox,
    ) -> None:
        """初始化文件结果对账器。

        Args:
            output_dir: Google Trends 服务端任务根目录。
            data_environment: 共享存储的数据环境。
            outbox: 用于幂等查询的共享 Outbox。
        """
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
        """按结果完成时间扫描遗漏任务，Outbox 唯一键负责幂等去重。

        Args:
            cutover_at: 只补交该时间之后完成的任务。
            cursor: 上一轮已处理的文件时间水位。
            limit: 本轮最多返回的遗漏任务数。

        Returns:
            待补交任务与下一轮单调水位。

        Raises:
            ValueError: cutover 时间或通用提交字段不合法。
        """
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
                # 同一文件系统时间粒度可能对应多个结果；回退一纳秒让下一轮重读边界组。
                if completed_ns == next_cursor:
                    next_cursor = max(cursor, next_cursor - 1)
                break
            next_cursor = max(next_cursor, completed_ns)
            payload = _read_success_result(result_path)
            if payload is None:
                continue
            job_id = str(payload.get("job_id") or "").strip()
            scenario = str(payload.get("scenario") or "").strip()
            geo = str(payload.get("geo") or "").strip()
            if not all((job_id, scenario, geo)):
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
                    site=geo,
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
    """把 cutover 时间统一为 UTC 时区时间。"""
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
    """只返回水位与 cutover 之后的结果文件，并按稳定顺序排列。"""
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
    """读取成功结果；损坏文件留给后续运维处理，不阻断本轮对账。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
