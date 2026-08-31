"""共享采集结果 MySQL Adapter。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.models import ParsedCollection
from opscli.shared.collection_storage.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION


class CollectionSchemaError(RuntimeError):
    """MySQL 采集表结构不存在或版本不兼容。"""


class MySqlCollectionRepository:
    """以任务为事务单位幂等保存采集文件和格式化 Dataset。"""

    def __init__(
        self,
        *,
        settings: MySqlSettings,
        batch_size: int = 500,
        connect_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.batch_size = max(1, int(batch_size))
        self._connect_factory = connect_factory or self._connect

    def create_schema(self) -> None:
        """创建 v1 表结构；仅应使用具备 DDL 权限的迁移账号执行。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute(
                    """
                    INSERT INTO collection_schema_versions (module_name, schema_version)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE schema_version = schema_version
                    """,
                    ("collector_storage", SCHEMA_VERSION),
                )
                cursor.execute(
                    """
                    SELECT schema_version FROM collection_schema_versions
                    WHERE module_name = %s
                    """,
                    ("collector_storage",),
                )
                version = _schema_version(cursor.fetchone())
                if version != SCHEMA_VERSION:
                    raise CollectionSchemaError(
                        f"采集数据 MySQL Schema 版本不匹配：需要 {SCHEMA_VERSION}，实际 {version}"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def check_schema(self) -> None:
        """确认运行账号能够读取兼容的表结构版本。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT schema_version FROM collection_schema_versions
                    WHERE module_name = %s
                    """,
                    ("collector_storage",),
                )
                row = cursor.fetchone()
            version = _schema_version(row)
            if version != SCHEMA_VERSION:
                raise CollectionSchemaError(
                    f"采集数据 MySQL Schema 版本不匹配：需要 {SCHEMA_VERSION}，实际 {version}"
                )
        except CollectionSchemaError:
            raise
        except Exception as exc:
            raise CollectionSchemaError(
                "采集数据 MySQL Schema 尚未初始化或不可读"
            ) from exc
        finally:
            connection.close()

    def persist(self, document: ParsedCollection) -> None:
        """在单个事务内替换一个来源任务的全部沉淀数据。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                run_id = self._upsert_run(cursor, document)
                cursor.execute(
                    "DELETE FROM collection_artifacts WHERE run_id = %s", (run_id,)
                )
                cursor.execute(
                    "DELETE FROM collection_datasets WHERE run_id = %s", (run_id,)
                )
                self._insert_artifacts(cursor, run_id, document)
                source_row_count = self._insert_datasets(cursor, run_id, document)
                cursor.execute(
                    """
                    UPDATE collection_runs
                    SET source_row_count = %s,
                        persistence_completed_at = UTC_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (source_row_count, run_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _upsert_run(self, cursor: Any, document: ParsedCollection) -> int:
        submission = document.submission
        cursor.execute(
            """
            INSERT INTO collection_runs (
                data_environment, source_system, source_job_id, producer_service,
                scenario, site, ingestion_mode, collection_status, request_params,
                parser_version, source_row_count, started_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'succeeded', %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                id = LAST_INSERT_ID(id),
                producer_service = VALUES(producer_service),
                scenario = VALUES(scenario),
                site = VALUES(site),
                ingestion_mode = VALUES(ingestion_mode),
                collection_status = 'succeeded',
                request_params = VALUES(request_params),
                parser_version = VALUES(parser_version),
                source_row_count = VALUES(source_row_count),
                started_at = VALUES(started_at),
                completed_at = VALUES(completed_at),
                persistence_completed_at = NULL
            """,
            (
                submission.data_environment,
                submission.source_system,
                submission.source_job_id,
                submission.producer_service,
                submission.scenario,
                submission.site,
                submission.ingestion_mode,
                _json_dump(document.request_params),
                document.parser_version,
                0,
                _mysql_datetime(submission.started_at),
                _mysql_datetime(submission.completed_at),
            ),
        )
        run_id = int(cursor.lastrowid or 0)
        if run_id <= 0:
            raise RuntimeError("MySQL 未返回 collection_runs ID")
        return run_id

    def _insert_artifacts(
        self, cursor: Any, run_id: int, document: ParsedCollection
    ) -> None:
        rows = [
            (
                run_id,
                artifact.artifact_type,
                artifact.filename,
                artifact.path.as_uri(),
                artifact.mime_type,
                artifact.size_bytes,
                artifact.sha256,
            )
            for artifact in document.artifacts
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
        self, cursor: Any, run_id: int, document: ParsedCollection
    ) -> int:
        source_row_count = 0
        for dataset in document.datasets:
            columns = [
                {"name": original, "key": normalized}
                for original, normalized in dataset.columns
            ]
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
                    0,
                ),
            )
            dataset_id = int(cursor.lastrowid or 0)
            if dataset_id <= 0:
                raise RuntimeError("MySQL 未返回 collection_datasets ID")
            rows = (
                (
                    dataset_id,
                    record.row_number,
                    record.business_key,
                    record.record_hash,
                    _json_dump(record.payload),
                )
                for record in dataset.records
            )
            dataset_row_count = 0
            for batch in _batches(rows, self.batch_size):
                cursor.executemany(
                    """
                    INSERT INTO collection_records (
                        dataset_id, source_row_number, business_key, record_hash, payload
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    batch,
                )
                dataset_row_count += len(batch)
            cursor.execute(
                "UPDATE collection_datasets SET row_count = %s WHERE id = %s",
                (dataset_row_count, dataset_id),
            )
            source_row_count += dataset_row_count
        return source_row_count

    def _connect(self):
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 PyMySQL 依赖，无法连接采集数据 MySQL") from exc
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            connect_timeout=self.settings.connect_timeout_seconds,
            read_timeout=60,
            write_timeout=60,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            ssl_ca=self.settings.ssl_ca or None,
            ssl_verify_cert=bool(self.settings.ssl_ca),
            ssl_verify_identity=bool(self.settings.ssl_ca),
        )


def _schema_version(row: Any) -> int | None:
    if isinstance(row, dict):
        value = row.get("schema_version")
    elif isinstance(row, (tuple, list)) and row:
        value = row[0]
    else:
        value = None
    return int(value) if value is not None else None


def _json_dump(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _mysql_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _batches(
    values: Iterable[tuple[Any, ...]], size: int
) -> Iterable[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
