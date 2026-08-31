"""卖家精灵历史导出扫描、脱敏与安全清理。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.models import (
    CollectionDataset,
    CollectionSubmission,
)
from opscli.shared.collection_storage.parser_utils import (
    CollectionParseError,
    json_datasets,
    read_json_object,
    xlsx_datasets,
)
from opscli.shared.collection_storage.schema import SCHEMA_VERSION
from opscli.seller_sprite.export.xlsx import build_export_worksheets

# 解析器版本写入运行记录，用于后续识别历史格式化规则是否发生变化。
PARSER_VERSION = "seller-sprite-history-formatted-v2"
# 清理操作使用固定长口令，避免误把普通迁移命令当成删除授权。
PURGE_CONFIRMATION = "DELETE_VERIFIED_SOURCE"
# 脱敏时保留“曾有值”的语义，但不保留任何可反推主机目录的信息。
_PATH_REPLACEMENT = "[本地路径已移除]"
# 这些字段在旧结果中专门承载本机位置，迁移时必须整键移除。
_FORBIDDEN_KEYS = {
    "root_dir",
    "params_path",
    "raw_path",
    "result_path",
    "output_dir",
    "attempt_output_dir",
    "storage_uri",
}
# 路径可能位于引号或括号后；识别盘符和 UNC，不依赖固定主机目录。
_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'(=:\[])(?:[a-z]:[\\/]|\\\\)")
# 严格模式把任意非 URL 的 Unix 绝对路径视为敏感值，宁可多脱敏也不泄露目录。
_UNIX_PATH = re.compile(r"(?:^|[\s\"'(=:\[])/(?!/)[^\s\"'<>]*")
# file URI 与操作系统无关，但同样会泄露原文件位置。
_FILE_URI = re.compile(r"(?i)file://")

# 历史扩展表不改变在线五表合同，只补充查询实体和回填审计状态；数据本体仍只进 Dataset/Record。
HISTORY_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS collection_run_entities (
        run_id BIGINT UNSIGNED NOT NULL,
        entity_type VARCHAR(32) NOT NULL,
        entity_value VARCHAR(255) NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        PRIMARY KEY (run_id, entity_type, entity_value),
        KEY ix_collection_entity_lookup (entity_type, entity_value, run_id),
        CONSTRAINT fk_collection_run_entities_run
            FOREIGN KEY (run_id) REFERENCES collection_runs(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_backfill_batches (
        batch_id VARCHAR(64) NOT NULL PRIMARY KEY,
        source_system VARCHAR(64) NOT NULL,
        data_environment VARCHAR(16) NOT NULL,
        status VARCHAR(32) NOT NULL,
        discovered_tasks BIGINT UNSIGNED NOT NULL DEFAULT 0,
        complete_tasks BIGINT UNSIGNED NOT NULL DEFAULT 0,
        incomplete_tasks BIGINT UNSIGNED NOT NULL DEFAULT 0,
        invalid_tasks BIGINT UNSIGNED NOT NULL DEFAULT 0,
        dataset_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
        record_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
        source_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_backfill_items (
        batch_id VARCHAR(64) NOT NULL,
        source_job_id VARCHAR(191) NOT NULL,
        run_id BIGINT UNSIGNED NOT NULL,
        manifest_sha256 CHAR(64) NOT NULL,
        dataset_count BIGINT UNSIGNED NOT NULL,
        record_count BIGINT UNSIGNED NOT NULL,
        source_bytes BIGINT UNSIGNED NOT NULL,
        status VARCHAR(32) NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),
        PRIMARY KEY (batch_id, source_job_id),
        KEY ix_collection_backfill_item_run (run_id),
        KEY ix_collection_backfill_item_status (batch_id, status),
        CONSTRAINT fk_collection_backfill_item_batch
            FOREIGN KEY (batch_id) REFERENCES collection_backfill_batches(batch_id)
                ON DELETE CASCADE,
        CONSTRAINT fk_collection_backfill_item_run
            FOREIGN KEY (run_id) REFERENCES collection_runs(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
)


class HistoryMigrationError(RuntimeError):
    """历史迁移输入、合同或安全门禁不满足。"""


class IncompleteHistoryTask(HistoryMigrationError):
    """任务没有形成可迁移的完整成功合同。"""


@dataclass(frozen=True)
class HistoryArtifact:
    """不包含目录或 URI 的源文件审计信息。

    字段保存文件类型、基础文件名、媒体类型、大小和摘要；`storage_uri`
    固定为空，确保扫描阶段不会把原文件位置带入数据库参数。
    """

    artifact_type: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    storage_uri: None = None


@dataclass(frozen=True)
class PreparedHistoryTask:
    """一个已解析且可安全写入 MySQL 的历史任务。

    `task_dir` 仅用于当前进程核验和清理，仓储层不会持久化该字段；raw_payload
    只在当前进程用于安全检查，不会写入 MySQL；其余字段承载格式化数据集和摘要。
    """

    task_dir: Path
    submission: CollectionSubmission
    request_params: dict[str, Any]
    raw_payload: dict[str, Any]
    datasets: tuple[CollectionDataset, ...]
    artifacts: tuple[HistoryArtifact, ...]
    entities: tuple[tuple[str, str], ...]
    manifest_sha256: str
    dataset_count: int
    record_count: int
    source_bytes: int


@dataclass(frozen=True)
class HistoryAudit:
    """历史目录只读审计汇总，不包含主机名和本地路径。"""

    discovered_tasks: int
    complete_tasks: int
    incomplete_tasks: int
    invalid_tasks: int
    dataset_count: int
    record_count: int
    source_bytes: int
    by_scenario: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """返回不包含源路径的可输出摘要。

        Returns:
            可安全输出到终端或日志的审计字典。
        """
        return {
            "discovered_tasks": self.discovered_tasks,
            "complete_tasks": self.complete_tasks,
            "incomplete_tasks": self.incomplete_tasks,
            "invalid_tasks": self.invalid_tasks,
            "dataset_count": self.dataset_count,
            "record_count": self.record_count,
            "source_bytes": self.source_bytes,
            "by_scenario": dict(self.by_scenario),
        }


class SellerSpriteHistoryScanner:
    """从显式目录发现并解析卖家精灵历史成功任务。

    Args:
        source_dir: 历史 `api_runs` 根目录，仅在当前进程内使用。

    Raises:
        HistoryMigrationError: 源目录不存在或不可读。
    """

    def __init__(self, source_dir: Path) -> None:
        """初始化只读扫描器。

        Args:
            source_dir: 历史 `api_runs` 根目录。

        Raises:
            HistoryMigrationError: 目录不存在或不是目录。
        """
        self.source_dir = Path(source_dir).expanduser().resolve()
        if not self.source_dir.is_dir():
            raise HistoryMigrationError("历史源目录不存在或不可读")

    def task_directories(self) -> tuple[Path, ...]:
        """以 `params.json` 所在目录作为稳定任务边界。

        Returns:
            去重并稳定排序后的任务目录元组。
        """
        return tuple(sorted({path.parent for path in self.source_dir.rglob("params.json")}))

    def audit(
        self,
        task_directories: tuple[Path, ...] | None = None,
    ) -> HistoryAudit:
        """完整解析历史目录，但不连接数据库也不修改文件。

        Args:
            task_directories: 可选任务目录子集；为空时扫描整个源目录。

        Returns:
            完整、缺失和无效任务以及数据量的无路径汇总。
        """
        complete = 0
        incomplete = 0
        invalid = 0
        dataset_count = 0
        record_count = 0
        source_bytes = 0
        scenarios: Counter[str] = Counter()
        selected = task_directories or self.task_directories()
        for task_dir in selected:
            try:
                prepared = self.prepare(task_dir)
            except IncompleteHistoryTask:
                incomplete += 1
                continue
            except (HistoryMigrationError, CollectionParseError, OSError, ValueError):
                invalid += 1
                continue
            complete += 1
            dataset_count += prepared.dataset_count
            record_count += prepared.record_count
            source_bytes += prepared.source_bytes
            scenarios[prepared.submission.scenario] += 1
        return HistoryAudit(
            discovered_tasks=len(selected),
            complete_tasks=complete,
            incomplete_tasks=incomplete,
            invalid_tasks=invalid,
            dataset_count=dataset_count,
            record_count=record_count,
            source_bytes=source_bytes,
            by_scenario=dict(sorted(scenarios.items())),
        )

    def prepare(self, task_dir: Path) -> PreparedHistoryTask:
        """读取单个成功任务，并生成无本地路径的数据库载荷。

        Args:
            task_dir: 位于源目录内的单个任务目录。

        Returns:
            已解析、脱敏并计算摘要的迁移任务。

        Raises:
            IncompleteHistoryTask: 任务尚未形成完整成功合同。
            HistoryMigrationError: 合同字段不一致、格式不支持或仍含路径。
            CollectionParseError: JSON 或 XLSX 无法按采集合同解析。
            OSError: 文件读取或元数据访问失败。
        """
        resolved_dir = Path(task_dir).resolve()
        self._assert_inside_source(resolved_dir)
        params_path = resolved_dir / "params.json"
        raw_path = resolved_dir / "raw.json"
        result_path = resolved_dir / "result.json"
        if not all(path.is_file() for path in (params_path, raw_path, result_path)):
            raise IncompleteHistoryTask("任务缺少 params/raw/result 成功文件")

        params = read_json_object(params_path, source_name="卖家精灵历史")
        raw = read_json_object(raw_path, source_name="卖家精灵历史")
        result = read_json_object(result_path, source_name="卖家精灵历史")
        request = params.get("request")
        if not isinstance(request, dict):
            raise HistoryMigrationError("params.json 缺少 request 对象")
        job_id = str(result.get("job_id") or request.get("job_id") or "").strip()
        if not job_id:
            raise HistoryMigrationError("历史任务缺少 job_id")
        request_job_id = str(request.get("job_id") or "").strip()
        if request_job_id and request_job_id != job_id:
            raise HistoryMigrationError("params 与 result 的 job_id 不一致")
        scenario = str(result.get("scenario") or request.get("scenario") or "").strip()
        site = str(result.get("site") or request.get("site") or "").strip().upper()
        if not scenario or not site:
            raise HistoryMigrationError("历史任务缺少 scenario 或 site")

        export_path = self._resolve_export(resolved_dir, result)
        datasets = self._materialize_datasets(
            export_path,
            result,
            scenario,
            request_params=request.get("params")
            if isinstance(request.get("params"), dict)
            else {},
        )
        # 旧文件混有本地路径和登录上下文；只保留查询合同，并在入库前递归脱敏。
        request_params = _sanitize_payload(
            {
                "request": request,
                "resolved_params": params.get("resolved_params") or {},
                "payload": params.get("payload") or {},
            }
        )
        # raw 只保留业务响应和告警，主动舍弃登录信息及与格式化结果重复的字段。
        raw_payload = _sanitize_payload(
            {
                "scenario": raw.get("scenario") or scenario,
                "mode": raw.get("mode"),
                "response": raw.get("response"),
                "high_frequency_response": raw.get("high_frequency_response"),
                "warnings": raw.get("warnings") or [],
            }
        )
        if contains_local_path(request_params) or contains_local_path(raw_payload):
            raise HistoryMigrationError("待入库载荷仍包含本地路径")

        # manifest 仅由文件名、大小和摘要构成，因此既能验证源文件又不会暴露目录。
        artifacts = _history_artifacts(resolved_dir, export_path)
        manifest_sha256 = _manifest_sha256(artifacts)
        submission = CollectionSubmission(
            source_system="seller_sprite",
            source_job_id=job_id,
            producer_service="collector_mcp",
            scenario=scenario,
            site=site,
            data_environment="production",
            ingestion_mode="backfill",
            result_path=result_path,
            completed_at=datetime.fromtimestamp(
                result_path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        )
        entities = _request_entities(request_params)
        return PreparedHistoryTask(
            task_dir=resolved_dir,
            submission=submission,
            request_params=request_params,
            raw_payload=raw_payload,
            datasets=datasets,
            artifacts=artifacts,
            entities=entities,
            manifest_sha256=manifest_sha256,
            dataset_count=len(datasets),
            record_count=sum(len(tuple(dataset.records)) for dataset in datasets),
            source_bytes=sum(artifact.size_bytes for artifact in artifacts),
        )

    def _assert_inside_source(self, task_dir: Path) -> None:
        try:
            task_dir.relative_to(self.source_dir)
        except ValueError as exc:
            raise HistoryMigrationError("任务目录不在历史源目录内") from exc

    def _resolve_export(self, task_dir: Path, result: dict[str, Any]) -> Path:
        export = result.get("export")
        if not isinstance(export, dict):
            raise IncompleteHistoryTask("成功任务缺少 export 合同")
        filename = Path(str(export.get("filename") or "")).name
        if filename:
            candidate = task_dir / filename
            if candidate.is_file():
                return candidate.resolve()
        candidates = [
            path
            for path in task_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".json", ".xlsx"}
            and path.name not in {"params.json", "raw.json", "result.json"}
        ]
        if len(candidates) != 1:
            raise IncompleteHistoryTask("无法唯一定位格式化导出文件")
        return candidates[0].resolve()

    def _materialize_datasets(
        self,
        export_path: Path,
        result: dict[str, Any],
        scenario: str,
        *,
        request_params: dict[str, Any],
    ) -> tuple[CollectionDataset, ...]:
        business_keys = _business_key_fields(scenario)
        export = result.get("export") or {}
        export_format = str(export.get("format") or export_path.suffix.lstrip(".")).lower()
        if export_format == "json" or export_path.suffix.lower() == ".json":
            payload = read_json_object(export_path, source_name="卖家精灵历史")
            if _is_canonical_json_export(payload):
                parsed = json_datasets(
                    payload,
                    source_name="卖家精灵历史",
                    business_key_fields=business_keys,
                )
            else:
                # 旧 JSON 只有对象行，没有统一列定义；复用生产 XLSX 格式化器，
                # 保证历史 JSON 与同任务 XLSX 使用完全相同的列和附加工作表。
                rows = payload.get("rows")
                if not isinstance(rows, list) or not all(
                    isinstance(row, dict) for row in rows
                ):
                    raise CollectionParseError(
                        "卖家精灵旧 JSON 缺少可格式化的对象 rows 数组"
                    )
                worksheets = build_export_worksheets(
                    rows=rows,
                    scenario=str(payload.get("scenario") or result.get("scenario") or scenario),
                    site=str(payload.get("site") or result.get("site") or "US"),
                    period=str(payload.get("period") or result.get("period") or "30d"),
                    params=request_params,
                    high_frequency_rows=(
                        payload.get("high_frequency_rows")
                        if isinstance(payload.get("high_frequency_rows"), list)
                        else None
                    ),
                )
                canonical_payload = {
                    "sheet_name": worksheets[0].name,
                    "columns": worksheets[0].columns,
                    "rows": worksheets[0].rows,
                    "additional_sheets": [
                        worksheet.to_dict() for worksheet in worksheets[1:]
                    ],
                }
                parsed = json_datasets(
                    canonical_payload,
                    source_name="卖家精灵历史旧 JSON",
                    business_key_fields=business_keys,
                )
        elif export_format in {"xls", "xlsx"} or export_path.suffix.lower() == ".xlsx":
            parsed = xlsx_datasets(
                export_path,
                source_name="卖家精灵历史",
                business_key_fields=business_keys,
            )
        else:
            raise HistoryMigrationError("历史导出格式仅支持 JSON 或 XLSX")
        materialized = []
        for dataset in parsed:
            materialized.append(
                CollectionDataset(
                    dataset_code=dataset.dataset_code,
                    dataset_name=dataset.dataset_name,
                    source_sheet=dataset.source_sheet,
                    columns=dataset.columns,
                    records=tuple(dataset.records),
                )
            )
        return tuple(materialized)


class HistoryMigrationRepository:
    """把历史任务以单任务事务写入现有采集 MySQL。

    Args:
        settings: 现有采集 MySQL 连接配置。
        batch_size: 单次批量插入的最大记录数。
        batch_byte_limit: 单次批量插入的近似最大字节数。
        connect_factory: 可选连接工厂，测试时用于注入替身连接。
    """

    def __init__(
        self,
        *,
        settings: MySqlSettings,
        batch_size: int = 500,
        batch_byte_limit: int = 4 * 1024 * 1024,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        """初始化 MySQL 历史仓储。

        Args:
            settings: 现有采集 MySQL 连接配置。
            batch_size: 单次批量写入的记录上限。
            batch_byte_limit: 单次批量写入的近似字节上限。
            connect_factory: 可选连接工厂，用于测试替换真实连接。
        """
        self.settings = settings
        self.batch_size = max(1, int(batch_size))
        self.batch_byte_limit = max(1024, int(batch_byte_limit))
        self._connect_factory = connect_factory or self._connect

    def create_extension_schema(self) -> None:
        """在既有 collection v1 五表之上创建无路径历史扩展表。

        Returns:
            无返回值。

        Raises:
            HistoryMigrationError: 基础 Schema 版本不兼容。
            Exception: 建表或事务提交失败，事务会回滚。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                self._check_base_schema(cursor)
                for statement in HISTORY_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def check_schema(self) -> None:
        """确认基础 Schema 与三张历史扩展表均可读。

        Returns:
            无返回值。

        Raises:
            HistoryMigrationError: 基础版本不匹配或扩展表未初始化。
            Exception: 数据库查询失败。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                self._check_base_schema(cursor)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS table_count
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name IN (
                        'collection_run_entities',
                        'collection_backfill_batches',
                        'collection_backfill_items'
                      )
                    """
                )
                row = cursor.fetchone()
                count = int((row or {}).get("table_count") or 0)
                if count != 3:
                    raise HistoryMigrationError("历史迁移扩展表尚未初始化")
        finally:
            connection.close()

    def begin_batch(self, batch_id: str, audit: HistoryAudit) -> None:
        """创建或刷新一个不含源目录的回填批次。

        Args:
            batch_id: 运维指定的稳定批次标识。
            audit: 迁移前只读审计结果。

        Returns:
            无返回值。

        Raises:
            ValueError: 批次标识格式不合法。
            Exception: 数据库写入失败，事务会回滚。
        """
        _validate_batch_id(batch_id)
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO collection_backfill_batches (
                        batch_id, source_system, data_environment, status,
                        discovered_tasks, complete_tasks, incomplete_tasks,
                        invalid_tasks, dataset_count, record_count, source_bytes
                    ) VALUES (%s, 'seller_sprite', 'production', 'importing',
                              %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = IF(status IN ('verified', 'completed'), status, 'importing'),
                        discovered_tasks = VALUES(discovered_tasks),
                        complete_tasks = VALUES(complete_tasks),
                        incomplete_tasks = VALUES(incomplete_tasks),
                        invalid_tasks = VALUES(invalid_tasks),
                        dataset_count = VALUES(dataset_count),
                        record_count = VALUES(record_count),
                        source_bytes = VALUES(source_bytes)
                    """,
                    (
                        batch_id,
                        audit.discovered_tasks,
                        audit.complete_tasks,
                        audit.incomplete_tasks,
                        audit.invalid_tasks,
                        audit.dataset_count,
                        audit.record_count,
                        audit.source_bytes,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_batch(self, batch_id: str, status: str) -> None:
        """更新批次状态，不接受任意自由文本状态。

        Args:
            batch_id: 已创建的回填批次标识。
            status: `imported`、`verified`、`completed` 或 `failed`。

        Returns:
            无返回值。

        Raises:
            ValueError: 状态不在允许集合中。
            Exception: 数据库更新失败，事务会回滚。
        """
        if status not in {"imported", "verified", "completed", "failed"}:
            raise ValueError("不支持的历史迁移批次状态")
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE collection_backfill_batches SET status = %s WHERE batch_id = %s",
                    (status, batch_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def persist(self, batch_id: str, prepared: PreparedHistoryTask) -> str:
        """幂等写入单个历史任务。

        Args:
            batch_id: 当前回填批次标识。
            prepared: 已完成解析和脱敏的历史任务。

        Returns:
            新写入时返回 `imported`，相同历史任务已存在时返回
            `skipped_existing`。

        Raises:
            HistoryMigrationError: 载荷含路径、已存在在线数据或摘要冲突。
            Exception: 任一数据库写入失败，单任务事务会整体回滚。
        """
        _validate_batch_id(batch_id)
        if contains_local_path(prepared.request_params) or contains_local_path(
            prepared.raw_payload
        ):
            raise HistoryMigrationError("待入库任务包含本地路径")
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                # job_id 是在线表唯一业务键；历史回填不得覆盖在线写入或不同版本历史。
                existing = self._find_existing(cursor, prepared)
                if existing:
                    run_id = int(existing["id"])
                    if existing.get("ingestion_mode") != "backfill":
                        raise HistoryMigrationError("同 job_id 已存在非 backfill 数据，拒绝覆盖")
                    if existing.get("manifest_sha256") != prepared.manifest_sha256:
                        raise HistoryMigrationError("同 job_id 的历史 manifest 已变化，拒绝覆盖")
                    self._upsert_item(cursor, batch_id, run_id, prepared)
                    connection.commit()
                    return "skipped_existing"

                # run、实体、数据集和批次项必须原子落库，避免留下无法核验的半任务。
                run_id = self._insert_run(cursor, prepared)
                self._insert_artifacts(cursor, run_id, prepared)
                if prepared.entities:
                    cursor.executemany(
                        """
                        INSERT INTO collection_run_entities (
                            run_id, entity_type, entity_value
                        ) VALUES (%s, %s, %s)
                        """,
                        [
                            (run_id, entity_type, entity_value)
                            for entity_type, entity_value in prepared.entities
                        ],
                    )
                source_row_count = self._insert_datasets(cursor, run_id, prepared)
                cursor.execute(
                    """
                    UPDATE collection_runs
                    SET source_row_count = %s,
                        persistence_completed_at = UTC_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (source_row_count, run_id),
                )
                self._upsert_item(cursor, batch_id, run_id, prepared)
            connection.commit()
            return "imported"
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def verified_manifests(self, batch_id: str) -> dict[str, str]:
        """返回批次内已核验任务的 job id 和 manifest。

        Args:
            batch_id: 回填批次标识。

        Returns:
            以源 job id 为键、文件 manifest 为值的字典。

        Raises:
            Exception: 数据库查询失败。
        """
        return self.batch_manifests(batch_id, status="verified")

    def batch_manifests(
        self,
        batch_id: str,
        *,
        status: str | None = None,
    ) -> dict[str, str]:
        """返回批次任务 manifest，可选按状态过滤。

        Args:
            batch_id: 回填批次标识。
            status: 可选的批次项状态过滤值。

        Returns:
            以源 job id 为键、文件 manifest 为值的字典。

        Raises:
            Exception: 数据库查询失败。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                if status:
                    cursor.execute(
                        """
                        SELECT source_job_id, manifest_sha256
                        FROM collection_backfill_items
                        WHERE batch_id = %s AND status = %s
                        ORDER BY source_job_id
                        """,
                        (batch_id, status),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT source_job_id, manifest_sha256
                        FROM collection_backfill_items
                        WHERE batch_id = %s
                        ORDER BY source_job_id
                        """,
                        (batch_id,),
                    )
                rows = cursor.fetchall() or []
            return {
                str(row["source_job_id"]): str(row["manifest_sha256"])
                for row in rows
            }
        finally:
            connection.close()

    def mark_purged(self, batch_id: str, source_job_id: str) -> None:
        """标记一个已核验任务的源文件已经清理。

        Args:
            batch_id: 回填批次标识。
            source_job_id: 已清理任务的源 job id。

        Returns:
            无返回值。

        Raises:
            Exception: 数据库更新失败，事务会回滚。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE collection_backfill_items
                    SET status = 'purged'
                    WHERE batch_id = %s
                      AND source_job_id = %s
                      AND status = 'verified'
                    """,
                    (batch_id, source_job_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def verify_task(
        self,
        batch_id: str,
        prepared: PreparedHistoryTask,
    ) -> bool:
        """核对 manifest、raw、Dataset 和 Record 内容后标记 verified。

        Args:
            batch_id: 回填批次标识。
            prepared: 从当前源文件重新解析得到的任务。

        Returns:
            所有摘要和数量一致时返回真，否则返回假。

        Raises:
            Exception: 数据库查询或状态更新失败，事务会回滚。
        """
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.run_id,
                        i.manifest_sha256,
                        i.dataset_count,
                        i.record_count,
                        (SELECT COUNT(*) FROM collection_datasets d
                         WHERE d.run_id = i.run_id) AS actual_dataset_count,
                        (SELECT COALESCE(SUM(d.row_count), 0) FROM collection_datasets d
                         WHERE d.run_id = i.run_id) AS actual_record_count,
                    FROM collection_backfill_items i
                    WHERE i.batch_id = %s AND i.source_job_id = %s
                    """,
                    (batch_id, prepared.submission.source_job_id),
                )
                row = cursor.fetchone()
                # 同时比对源 manifest、格式化数据摘要和两级行数，防止“有记录”被误当成完整迁移。
                valid = bool(
                    row
                    and row.get("manifest_sha256") == prepared.manifest_sha256
                    and int(row.get("dataset_count") or 0) == prepared.dataset_count
                    and int(row.get("actual_dataset_count") or 0)
                    == prepared.dataset_count
                    and int(row.get("record_count") or 0) == prepared.record_count
                    and int(row.get("actual_record_count") or 0)
                    == prepared.record_count
                )
                if valid:
                    # 删除源文件前必须从数据库反读内容；仅比对行数无法发现错位或篡改。
                    valid = (
                        self._database_dataset_manifest(cursor, int(row["run_id"]))
                        == _dataset_manifest_sha256(prepared.datasets)
                        and self._database_artifact_manifest(cursor, int(row["run_id"]))
                        == _artifact_manifest_sha256(prepared.artifacts)
                        and self._database_entity_manifest(cursor, int(row["run_id"]))
                        == _entity_manifest_sha256(prepared.entities)
                    )
                if valid:
                    cursor.execute(
                        """
                        UPDATE collection_backfill_items
                        SET status = 'verified'
                        WHERE batch_id = %s AND source_job_id = %s
                        """,
                        (batch_id, prepared.submission.source_job_id),
                    )
            connection.commit()
            return valid
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _database_dataset_manifest(self, cursor: Any, run_id: int) -> str:
        cursor.execute(
            """
            SELECT id, dataset_code, dataset_name, source_sheet,
                   columns_json, row_count
            FROM collection_datasets
            WHERE run_id = %s
            ORDER BY id
            """,
            (run_id,),
        )
        datasets = []
        for dataset in cursor.fetchall() or []:
            cursor.execute(
                """
                SELECT source_row_number, business_key, record_hash, payload
                FROM collection_records
                WHERE dataset_id = %s
                ORDER BY source_row_number, id
                """,
                (dataset["id"],),
            )
            records = [
                {
                    "row_number": int(record["source_row_number"]),
                    "business_key": record.get("business_key"),
                    "record_hash": str(record["record_hash"]),
                    "payload": _json_value(record["payload"]),
                }
                for record in (cursor.fetchall() or [])
            ]
            datasets.append(
                {
                    "dataset_code": str(dataset["dataset_code"]),
                    "dataset_name": str(dataset["dataset_name"]),
                    "source_sheet": dataset.get("source_sheet"),
                    "columns": _json_value(dataset["columns_json"]),
                    "row_count": int(dataset["row_count"]),
                    "records": records,
                }
            )
        return _canonical_sha256(datasets)

    def _database_artifact_manifest(self, cursor: Any, run_id: int) -> str:
        cursor.execute(
            """
            SELECT artifact_type, filename, storage_uri, mime_type,
                   size_bytes, sha256
            FROM collection_artifacts
            WHERE run_id = %s
            ORDER BY artifact_type, filename
            """,
            (run_id,),
        )
        artifacts = [
            {
                "artifact_type": str(row["artifact_type"]),
                "filename": str(row["filename"]),
                "storage_uri": str(row["storage_uri"]),
                "mime_type": str(row["mime_type"]),
                "size_bytes": int(row["size_bytes"]),
                "sha256": str(row["sha256"]),
            }
            for row in (cursor.fetchall() or [])
        ]
        return _canonical_sha256(artifacts)

    def _database_entity_manifest(self, cursor: Any, run_id: int) -> str:
        cursor.execute(
            """
            SELECT entity_type, entity_value
            FROM collection_run_entities
            WHERE run_id = %s
            ORDER BY entity_type, entity_value
            """,
            (run_id,),
        )
        entities = [
            [str(row["entity_type"]), str(row["entity_value"])]
            for row in (cursor.fetchall() or [])
        ]
        return _canonical_sha256(entities)

    def _check_base_schema(self, cursor: Any) -> None:
        cursor.execute(
            """
            SELECT schema_version FROM collection_schema_versions
            WHERE module_name = 'collector_storage'
            """
        )
        row = cursor.fetchone()
        version = int((row or {}).get("schema_version") or 0)
        if version != SCHEMA_VERSION:
            raise HistoryMigrationError(
                f"采集 MySQL Schema 版本不匹配：需要 {SCHEMA_VERSION}，实际 {version}"
            )

    def _find_existing(
        self,
        cursor: Any,
        prepared: PreparedHistoryTask,
    ) -> dict[str, Any] | None:
        submission = prepared.submission
        cursor.execute(
            """
            SELECT r.id, r.ingestion_mode,
                   (SELECT i.manifest_sha256
                    FROM collection_backfill_items i
                    WHERE i.run_id = r.id
                    ORDER BY i.updated_at DESC LIMIT 1) AS manifest_sha256
            FROM collection_runs r
            WHERE r.data_environment = %s
              AND r.source_system = %s
              AND r.source_job_id = %s
            """,
            (
                submission.data_environment,
                submission.source_system,
                submission.source_job_id,
            ),
        )
        row = cursor.fetchone()
        return row if isinstance(row, dict) else None

    def _insert_run(self, cursor: Any, prepared: PreparedHistoryTask) -> int:
        submission = prepared.submission
        cursor.execute(
            """
            INSERT INTO collection_runs (
                data_environment, source_system, source_job_id, producer_service,
                scenario, site, ingestion_mode, collection_status, request_params,
                parser_version, source_row_count, started_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'backfill', 'succeeded',
                      %s, %s, 0, NULL, %s)
            """,
            (
                submission.data_environment,
                submission.source_system,
                submission.source_job_id,
                submission.producer_service,
                submission.scenario,
                submission.site,
                _json_dump(prepared.request_params),
                PARSER_VERSION,
                _mysql_datetime(submission.completed_at),
            ),
        )
        run_id = int(cursor.lastrowid or 0)
        if run_id <= 0:
            raise RuntimeError("MySQL 未返回 collection_runs ID")
        return run_id

    def _insert_artifacts(
        self,
        cursor: Any,
        run_id: int,
        prepared: PreparedHistoryTask,
    ) -> None:
        rows = [
            (
                run_id,
                artifact.artifact_type,
                artifact.filename,
                f"urn:sha256:{artifact.sha256}",
                artifact.mime_type,
                artifact.size_bytes,
                artifact.sha256,
            )
            for artifact in prepared.artifacts
        ]
        if rows:
            cursor.executemany(
                """
                INSERT INTO collection_artifacts (
                    run_id, artifact_type, filename, storage_uri,
                    mime_type, size_bytes, sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

    def _insert_datasets(
        self,
        cursor: Any,
        run_id: int,
        prepared: PreparedHistoryTask,
    ) -> int:
        source_row_count = 0
        for dataset in prepared.datasets:
            columns = [
                {"name": original, "key": normalized}
                for original, normalized in dataset.columns
            ]
            records = tuple(dataset.records)
            cursor.execute(
                """
                INSERT INTO collection_datasets (
                    run_id, dataset_code, dataset_name, source_sheet,
                    columns_json, row_count
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    dataset.dataset_code,
                    dataset.dataset_name,
                    dataset.source_sheet,
                    _json_dump(columns),
                    len(records),
                ),
            )
            dataset_id = int(cursor.lastrowid or 0)
            if dataset_id <= 0:
                raise RuntimeError("MySQL 未返回 collection_datasets ID")
            rows = []
            for record in records:
                if contains_local_path(record.payload):
                    raise HistoryMigrationError("格式化记录包含本地路径")
                encoded = _json_dump(record.payload)
                rows.append(
                    (
                        dataset_id,
                        record.row_number,
                        record.business_key,
                        record.record_hash,
                        encoded,
                    )
                )
            for batch in _byte_limited_batches(
                rows,
                row_limit=self.batch_size,
                byte_limit=self.batch_byte_limit,
            ):
                cursor.executemany(
                    """
                    INSERT INTO collection_records (
                        dataset_id, source_row_number, business_key,
                        record_hash, payload
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    batch,
                )
            source_row_count += len(records)
        return source_row_count

    def _upsert_item(
        self,
        cursor: Any,
        batch_id: str,
        run_id: int,
        prepared: PreparedHistoryTask,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO collection_backfill_items (
                batch_id, source_job_id, run_id, manifest_sha256,
                dataset_count, record_count, source_bytes, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'imported')
            ON DUPLICATE KEY UPDATE
                run_id = VALUES(run_id),
                manifest_sha256 = VALUES(manifest_sha256),
                dataset_count = VALUES(dataset_count),
                record_count = VALUES(record_count),
                source_bytes = VALUES(source_bytes),
                status = IF(status = 'verified', status, 'imported')
            """,
            (
                batch_id,
                prepared.submission.source_job_id,
                run_id,
                prepared.manifest_sha256,
                prepared.dataset_count,
                prepared.record_count,
                prepared.source_bytes,
            ),
        )

    def _connect(self):
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 PyMySQL 依赖，无法连接历史迁移 MySQL") from exc
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            connect_timeout=self.settings.connect_timeout_seconds,
            read_timeout=60,
            write_timeout=120,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            ssl_ca=self.settings.ssl_ca or None,
            ssl_verify_cert=bool(self.settings.ssl_ca),
            ssl_verify_identity=bool(self.settings.ssl_ca),
        )


def contains_local_path(payload: Any) -> bool:
    """递归检查数据库载荷中是否仍存在本地绝对路径。

    Args:
        payload: 任意嵌套字典、序列或标量。

    Returns:
        任一键或字符串值疑似本地绝对路径时返回真。
    """
    if isinstance(payload, dict):
        return any(contains_local_path(key) or contains_local_path(value) for key, value in payload.items())
    if isinstance(payload, (list, tuple)):
        return any(contains_local_path(value) for value in payload)
    return isinstance(payload, str) and _looks_like_local_path(payload)


def purge_verified_task(
    prepared: PreparedHistoryTask,
    *,
    expected_manifest_sha256: str,
    confirmation: str,
) -> int:
    """校验 manifest 后只删除已登记文件，不执行递归删除。

    Args:
        prepared: 从待清理目录实时解析得到的任务。
        expected_manifest_sha256: 数据库中已核验的文件清单摘要。
        confirmation: 必须与固定清理口令完全一致。

    Returns:
        实际删除的普通文件数量。

    Raises:
        HistoryMigrationError: 口令错误或源文件自核验后发生变化。
        OSError: 已登记文件无法删除。
    """
    if confirmation != PURGE_CONFIRMATION:
        raise HistoryMigrationError("源文件清理确认口令不正确")
    current_artifacts = _history_artifacts(
        prepared.task_dir,
        _export_path_from_artifacts(prepared),
    )
    current_manifest = _manifest_sha256(current_artifacts)
    if current_manifest != expected_manifest_sha256:
        raise HistoryMigrationError("源文件 manifest 已变化，拒绝清理")
    removed = 0
    # 只逐个删除 manifest 中登记的普通文件；新增文件和嵌套任务必须原样保留。
    for artifact in current_artifacts:
        path = prepared.task_dir / artifact.filename
        path.unlink()
        removed += 1
    try:
        prepared.task_dir.rmdir()
    except OSError:
        # 非空目录可能包含嵌套任务或后来新增的文件，不能递归删除。
        pass
    return removed


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in _FORBIDDEN_KEYS or normalized_key.endswith("_path"):
                continue
            sanitized[str(key)] = _sanitize_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(value) for value in payload]
    if isinstance(payload, tuple):
        return tuple(_sanitize_payload(value) for value in payload)
    if isinstance(payload, str) and _looks_like_local_path(payload):
        return _PATH_REPLACEMENT
    return payload


def _looks_like_local_path(value: str) -> bool:
    return bool(
        _FILE_URI.search(value)
        or _WINDOWS_PATH.search(value)
        or _UNIX_PATH.search(value)
    )


def _is_canonical_json_export(payload: dict[str, Any]) -> bool:
    """判断 JSON 是否已经符合 v2 工作表合同。"""
    rows = payload.get("rows")
    columns = payload.get("columns")
    return isinstance(columns, list) and isinstance(rows, list) and all(
        isinstance(row, list) for row in rows
    )


def _history_artifacts(task_dir: Path, export_path: Path) -> tuple[HistoryArtifact, ...]:
    standard_names = {
        "params.json": "params",
        "raw.json": "raw",
        "result.json": "result",
        export_path.name: "export",
        "response.html": "diagnostic",
    }
    artifacts = []
    for path in sorted(item for item in task_dir.iterdir() if item.is_file()):
        artifact_type = standard_names.get(path.name, "supplemental")
        artifacts.append(
            HistoryArtifact(
                artifact_type=artifact_type,
                filename=path.name,
                mime_type=_mime_type(path),
                size_bytes=path.stat().st_size,
                sha256=_file_sha256(path),
            )
        )
    return tuple(artifacts)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_sha256(artifacts: tuple[HistoryArtifact, ...]) -> str:
    payload = [
        {
            "artifact_type": artifact.artifact_type,
            "filename": artifact.filename,
            "mime_type": artifact.mime_type,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }
        for artifact in artifacts
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dataset_manifest_sha256(datasets: tuple[CollectionDataset, ...]) -> str:
    payload = []
    for dataset in datasets:
        records = tuple(dataset.records)
        payload.append(
            {
                "dataset_code": dataset.dataset_code,
                "dataset_name": dataset.dataset_name,
                "source_sheet": dataset.source_sheet,
                "columns": [
                    {"name": original, "key": normalized}
                    for original, normalized in dataset.columns
                ],
                "row_count": len(records),
                "records": [
                    {
                        "row_number": record.row_number,
                        "business_key": record.business_key,
                        "record_hash": record.record_hash,
                        "payload": record.payload,
                    }
                    for record in records
                ],
            }
        )
    return _canonical_sha256(payload)


def _artifact_manifest_sha256(artifacts: tuple[HistoryArtifact, ...]) -> str:
    payload = [
        {
            "artifact_type": artifact.artifact_type,
            "filename": artifact.filename,
            "storage_uri": f"urn:sha256:{artifact.sha256}",
            "mime_type": artifact.mime_type,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }
        for artifact in sorted(
            artifacts,
            key=lambda item: (item.artifact_type, item.filename),
        )
    ]
    return _canonical_sha256(payload)


def _entity_manifest_sha256(entities: tuple[tuple[str, str], ...]) -> str:
    return _canonical_sha256([list(entity) for entity in sorted(entities)])


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def _mime_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
    }.get(path.suffix.lower(), "application/octet-stream")


def _business_key_fields(scenario: str) -> tuple[str, ...]:
    if scenario in {"keyword-reverse", "keyword-miner", "market-research"}:
        return ("关键词", "keyword")
    if scenario in {"competitor-lookup", "product-research", "traffic-source"}:
        return ("ASIN", "asin")
    if scenario == "listing-analysis":
        return ("taskId", "task_id")
    return ()


def _request_entities(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    entities: set[tuple[str, str]] = set()

    def visit(key: str, value: Any) -> None:
        normalized = key.casefold()
        entity_type = None
        if "asin" in normalized:
            entity_type = "asin"
        elif "keyword" in normalized or "关键词" in key:
            entity_type = "keyword"
        elif "category" in normalized or "类目" in key:
            entity_type = "category"
        if entity_type:
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item or "").strip()
                if text and text != _PATH_REPLACEMENT:
                    entities.add((entity_type, text[:255]))
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(str(child_key), child_value)
        elif isinstance(value, list):
            for child_value in value:
                if isinstance(child_value, dict):
                    for child_key, nested_value in child_value.items():
                        visit(str(child_key), nested_value)

    for top_key, top_value in payload.items():
        visit(str(top_key), top_value)
    return tuple(sorted(entities))


def _export_path_from_artifacts(prepared: PreparedHistoryTask) -> Path:
    exports = [artifact for artifact in prepared.artifacts if artifact.artifact_type == "export"]
    if len(exports) != 1:
        raise HistoryMigrationError("源文件 manifest 缺少唯一 export")
    return prepared.task_dir / exports[0].filename


def _json_dump(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(_json_dump(payload).encode("utf-8")).hexdigest()


def _mysql_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _byte_limited_batches(
    values: Iterable[tuple[Any, ...]],
    *,
    row_limit: int,
    byte_limit: int,
) -> Iterable[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    batch_bytes = 0
    for value in values:
        value_bytes = sum(len(str(item).encode("utf-8")) for item in value)
        if batch and (len(batch) >= row_limit or batch_bytes + value_bytes > byte_limit):
            yield batch
            batch = []
            batch_bytes = 0
        batch.append(value)
        batch_bytes += value_bytes
    if batch:
        yield batch


def _validate_batch_id(batch_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(batch_id or "")):
        raise ValueError("batch_id 只能包含字母、数字、点、下划线和短横线")


__all__ = [
    "HistoryArtifact",
    "HistoryAudit",
    "HistoryMigrationError",
    "HistoryMigrationRepository",
    "HISTORY_SCHEMA_STATEMENTS",
    "IncompleteHistoryTask",
    "PARSER_VERSION",
    "PURGE_CONFIRMATION",
    "PreparedHistoryTask",
    "SellerSpriteHistoryScanner",
    "contains_local_path",
    "purge_verified_task",
]
