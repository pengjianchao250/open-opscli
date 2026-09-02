"""共享采集结果 MySQL Adapter。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.models import ParsedCollection
from opscli.shared.collection_storage.result_cache import CachedCollectionResult
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

    def query_history(
        self,
        *,
        source_system: str,
        source_job_id: str | None = None,
        scenario: str | None = None,
        site: str | None = None,
        site_aliases: list[str] | tuple[str, ...] | None = None,
        request_params: dict[str, Any] | None = None,
        original_request_params: dict[str, Any] | None = None,
        completed_after: str | None = None,
        completed_before: str | None = None,
        limit: int = 20,
        offset: int = 0,
        dataset_code: str | None = None,
        record_limit: int = 100,
        record_offset: int = 0,
    ) -> list[dict[str, Any]]:
        """兼容入口：按任务标识或请求条件读取历史任务列表。"""
        return self.query_history_page(
            source_system=source_system,
            source_job_id=source_job_id,
            scenario=scenario,
            site=site,
            site_aliases=site_aliases,
            request_params=request_params,
            original_request_params=original_request_params,
            completed_after=completed_after,
            completed_before=completed_before,
            limit=limit,
            offset=offset,
            dataset_code=dataset_code,
            record_limit=record_limit,
            record_offset=record_offset,
        )["runs"]

    def find_cached_result(
        self,
        *,
        source_system: str,
        data_environment: str,
        scenario: str,
        site: str,
        cache_key: str,
        cache_scope: str,
        ttl_seconds: int,
        include_datasets: bool = True,
    ) -> CachedCollectionResult | None:
        """精确读取仍在新鲜窗口内的最近成功采集结果。"""
        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, source_job_id, scenario, site, request_params,
                           source_row_count, completed_at, persistence_completed_at
                    FROM collection_runs
                    WHERE source_system = %s
                      AND data_environment = %s
                      AND scenario = %s
                      AND site = %s
                      AND collection_status = 'succeeded'
                      AND persistence_completed_at IS NOT NULL
                      AND persistence_completed_at >= TIMESTAMPADD(
                          SECOND, -%s, UTC_TIMESTAMP(6)
                      )
                      AND JSON_UNQUOTE(JSON_EXTRACT(
                          request_params, '$._cache.cache_key'
                      )) = %s
                      AND JSON_UNQUOTE(JSON_EXTRACT(
                          request_params, '$._cache.cache_scope'
                      )) = %s
                    ORDER BY persistence_completed_at DESC, id DESC
                    LIMIT 1
                    """,
                    (
                        source_system,
                        data_environment,
                        scenario,
                        site,
                        max(1, int(ttl_seconds)),
                        cache_key,
                        cache_scope,
                    ),
                )
                run = cursor.fetchone()
                if not run:
                    return None
                request_params = _json_load_value(run.get("request_params"))
                cache_payload = (
                    request_params.get("_cache")
                    if isinstance(request_params, dict)
                    else None
                )
                result_metadata = (
                    cache_payload.get("result")
                    if isinstance(cache_payload, dict)
                    else None
                )
                datasets = (
                    self._cached_datasets(
                        cursor,
                        run_id=int(run.get("id") or 0),
                    )
                    if include_datasets
                    else []
                )
                return CachedCollectionResult(
                    source_job_id=str(run.get("source_job_id") or ""),
                    scenario=str(run.get("scenario") or ""),
                    site=str(run.get("site") or ""),
                    row_count=int(run.get("source_row_count") or 0),
                    completed_at=_db_datetime_value(run.get("completed_at")),
                    persistence_completed_at=_db_datetime_value(
                        run.get("persistence_completed_at")
                    ),
                    result_metadata=(
                        dict(result_metadata)
                        if isinstance(result_metadata, dict)
                        else {}
                    ),
                    datasets=tuple(datasets),
                )
        finally:
            connection.close()

    def query_history_page(
        self,
        *,
        source_system: str,
        source_job_id: str | None = None,
        scenario: str | None = None,
        site: str | None = None,
        site_aliases: list[str] | tuple[str, ...] | None = None,
        request_params: dict[str, Any] | None = None,
        original_request_params: dict[str, Any] | None = None,
        completed_after: str | None = None,
        completed_before: str | None = None,
        limit: int = 20,
        offset: int = 0,
        dataset_code: str | None = None,
        record_limit: int = 100,
        record_offset: int = 0,
        include_records: bool = True,
    ) -> dict[str, Any]:
        """分页读取已沉淀的历史采集结果和总数。

        ``request_params`` 匹配任务 params.json 中的 ``normalized_params`` 子集，
        因此可以只提供 asin、term 等关键条件。记录读取有独立上限，避免
        单个大型任务把 MCP 响应撑爆。
        """
        source = str(source_system or "").strip()
        if not source:
            raise ValueError("source_system 不能为空")
        limit = _bounded_int(limit, default=20, maximum=100)
        offset = max(0, int(offset))
        normalized_dataset_code = str(dataset_code or "").strip() or None
        record_limit = _bounded_int(record_limit, default=100, maximum=1000)
        record_offset = max(0, int(record_offset))

        clauses = ["source_system = %s"]
        values: list[Any] = [source]
        for column, value in (
            ("source_job_id", source_job_id),
            ("scenario", scenario),
        ):
            text = str(value or "").strip()
            if text:
                clauses.append(f"{column} = %s")
                values.append(text)
        sites = tuple(
            dict.fromkeys(
                text
                for value in (site, *(site_aliases or ()))
                if (text := str(value or "").strip())
            )
        )
        if len(sites) == 1:
            clauses.append("site = %s")
            values.append(sites[0])
        elif sites:
            clauses.append(f"site IN ({', '.join(['%s'] * len(sites))})")
            values.extend(sites)
        if request_params or original_request_params:
            normalized_json = _json_dump(request_params or original_request_params)
            original_json = _json_dump(original_request_params or request_params)
            clauses.append(
                "(JSON_CONTAINS(request_params, %s, '$.normalized_params') "
                "OR JSON_CONTAINS(request_params, %s, '$.request.params'))"
            )
            values.extend((normalized_json, original_json))
        if completed_after:
            clauses.append("completed_at >= %s")
            values.append(_mysql_datetime(completed_after))
        if completed_before:
            clauses.append("completed_at <= %s")
            values.append(_mysql_datetime(completed_before))

        connection = self._connect_factory()
        try:
            with connection.cursor() as cursor:
                where_sql = " AND ".join(clauses)
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM collection_runs
                    WHERE {where_sql}
                    """,
                    tuple(values),
                )
                total = _count_value(cursor.fetchone())
                cursor.execute(
                    f"""
                    SELECT id, source_job_id, scenario, site, data_environment,
                           ingestion_mode, collection_status, request_params,
                           source_row_count, started_at, completed_at, created_at
                    FROM collection_runs
                    WHERE {where_sql}
                    ORDER BY completed_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*values, limit, offset),
                )
                runs = list(cursor.fetchall() or [])
                result: list[dict[str, Any]] = []
                for run in runs:
                    run_id = int(run.get("id") or 0)
                    datasets = self._history_datasets(
                        cursor,
                        run_id=run_id,
                        dataset_code=normalized_dataset_code,
                        record_limit=record_limit,
                        record_offset=record_offset,
                        include_records=include_records,
                    )
                    result.append(
                        {
                            "job_id": str(run.get("source_job_id") or ""),
                            "scenario": run.get("scenario"),
                            "site": run.get("site"),
                            "data_environment": run.get("data_environment"),
                            "ingestion_mode": run.get("ingestion_mode"),
                            "collection_status": run.get("collection_status"),
                            "request_params": _json_load_value(run.get("request_params")),
                            "row_count": int(run.get("source_row_count") or 0),
                            "started_at": _db_datetime_value(run.get("started_at")),
                            "completed_at": _db_datetime_value(run.get("completed_at")),
                            "created_at": _db_datetime_value(run.get("created_at")),
                            "datasets": datasets,
                        }
                    )
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(result) < total,
                "runs": result,
            }
        finally:
            connection.close()

    @staticmethod
    def _history_datasets(
        cursor: Any,
        *,
        run_id: int,
        dataset_code: str | None,
        record_limit: int,
        record_offset: int,
        include_records: bool,
    ) -> list[dict[str, Any]]:
        dataset_filter = ""
        dataset_values: tuple[Any, ...] = (run_id,)
        if dataset_code:
            dataset_filter = " AND dataset_code = %s"
            dataset_values = (run_id, dataset_code)
        cursor.execute(
            f"""
            SELECT id, dataset_code, dataset_name, source_sheet, columns_json, row_count
            FROM collection_datasets
            WHERE run_id = %s{dataset_filter}
            ORDER BY id
            """,
            dataset_values,
        )
        datasets: list[dict[str, Any]] = []
        for dataset in cursor.fetchall() or []:
            dataset_id = int(dataset.get("id") or 0)
            records: list[dict[str, Any]] = []
            if include_records:
                cursor.execute(
                    """
                    SELECT source_row_number, business_key, payload
                    FROM collection_records
                    WHERE dataset_id = %s
                    ORDER BY source_row_number
                    LIMIT %s OFFSET %s
                    """,
                    (dataset_id, record_limit, record_offset),
                )
                records = [
                    {
                        "row_number": int(row.get("source_row_number") or 0),
                        "business_key": row.get("business_key"),
                        "payload": _json_load_value(row.get("payload")),
                    }
                    for row in (cursor.fetchall() or [])
                ]
            total = int(dataset.get("row_count") or 0)
            datasets.append(
                {
                    "dataset_code": dataset.get("dataset_code"),
                    "dataset_name": dataset.get("dataset_name"),
                    "source_sheet": dataset.get("source_sheet"),
                    "columns": _json_load_value(dataset.get("columns_json")) or [],
                    "row_count": total,
                    "records_offset": record_offset,
                    "records_returned": len(records),
                    "records": records,
                    "records_omitted": max(0, total - len(records)),
                    "records_omitted_before": min(record_offset, total),
                    "records_omitted_after": max(
                        0,
                        total - record_offset - len(records),
                    ),
                }
            )
        return datasets

    @staticmethod
    def _cached_datasets(cursor: Any, *, run_id: int) -> list[dict[str, Any]]:
        """读取缓存命中任务的全部 Dataset 和记录。"""
        cursor.execute(
            """
            SELECT id, dataset_code, dataset_name, source_sheet, columns_json, row_count
            FROM collection_datasets
            WHERE run_id = %s
            ORDER BY id
            """,
            (run_id,),
        )
        datasets: list[dict[str, Any]] = []
        for dataset in cursor.fetchall() or []:
            cursor.execute(
                """
                SELECT source_row_number, business_key, payload
                FROM collection_records
                WHERE dataset_id = %s
                ORDER BY source_row_number
                """,
                (int(dataset.get("id") or 0),),
            )
            records = [
                {
                    "row_number": int(row.get("source_row_number") or 0),
                    "business_key": row.get("business_key"),
                    "payload": _json_load_value(row.get("payload")),
                }
                for row in (cursor.fetchall() or [])
            ]
            datasets.append(
                {
                    "dataset_code": dataset.get("dataset_code"),
                    "dataset_name": dataset.get("dataset_name"),
                    "source_sheet": dataset.get("source_sheet"),
                    "columns": _json_load_value(dataset.get("columns_json")) or [],
                    "row_count": int(dataset.get("row_count") or 0),
                    "records": records,
                }
            )
        return datasets

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


def _count_value(row: Any) -> int:
    if isinstance(row, dict):
        value = row.get("total")
    elif isinstance(row, (tuple, list)) and row:
        value = row[0]
    else:
        value = 0
    return int(value or 0)


def _json_dump(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_load_value(value: Any) -> Any:
    """兼容 PyMySQL 返回的 JSON 字符串和已解码对象。"""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _db_datetime_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _bounded_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(1, parsed), maximum)


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
