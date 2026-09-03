from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.models import (
    CollectionArtifact,
    CollectionDataset,
    CollectionRecord,
    CollectionSubmission,
    ParsedCollection,
)
from opscli.shared.collection_storage.mysql_repository import MySqlCollectionRepository
from opscli.shared.collection_storage.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.connection.executions.append((normalized, params))
        if normalized.startswith("INSERT INTO collection_runs"):
            self.lastrowid = 101
        elif normalized.startswith("INSERT INTO collection_datasets"):
            self.lastrowid = self.connection.next_dataset_id
            self.connection.next_dataset_id += 1
        return 1

    def executemany(self, sql, params):
        normalized = " ".join(sql.split())
        values = list(params)
        self.connection.executemany_calls.append((normalized, values))
        return len(values)


class FakeConnection:
    def __init__(self):
        self.executions = []
        self.executemany_calls = []
        self.next_dataset_id = 201
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_collection_records_sql_avoids_mysql_8_row_number_reserved_word():
    records_schema = next(
        statement
        for statement in SCHEMA_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS collection_records" in statement
    )

    assert "source_row_number BIGINT UNSIGNED NOT NULL" in records_schema
    assert "(dataset_id, source_row_number)" in records_schema


def test_schema_includes_unified_mcp_call_events_table():
    telemetry_schema = next(
        statement
        for statement in SCHEMA_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS mcp_call_events" in statement
    )

    assert "user_email VARCHAR(254) NULL" in telemetry_schema
    assert "service VARCHAR(64) NOT NULL" in telemetry_schema
    assert "endpoint VARCHAR(128) NULL" in telemetry_schema
    assert "scenario VARCHAR(128) NULL" in telemetry_schema
    assert "runtime_role VARCHAR(32) NOT NULL" in telemetry_schema
    assert "status VARCHAR(16) NOT NULL DEFAULT 'called'" in telemetry_schema
    assert "ix_mcp_call_events_service_scenario_time" in telemetry_schema
    assert "ix_mcp_call_events_service_endpoint_time" in telemetry_schema


def test_schema_v3_includes_cache_identity_and_prefetch_tables():
    runs_schema = next(
        statement
        for statement in SCHEMA_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS collection_runs" in statement
    )

    schedule_schema = next(
        statement
        for statement in SCHEMA_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS collection_prefetch_schedules" in statement
    )
    run_schema = next(
        statement
        for statement in SCHEMA_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS collection_prefetch_runs" in statement
    )

    assert SCHEMA_VERSION == 3
    assert "request_fingerprint CHAR(64) NULL" in runs_schema
    assert "cache_scope VARCHAR(128) NULL" in runs_schema
    assert "ix_collection_runs_cache_lookup" in runs_schema
    assert "next_run_at DATETIME(6) NOT NULL" in schedule_schema
    assert "created_by VARCHAR(254) NOT NULL" in schedule_schema
    assert "lease_expires_at DATETIME(6) NULL" in run_schema
    assert "source_system VARCHAR(64) NOT NULL" in run_schema
    assert "request_json JSON NOT NULL" in run_schema
    assert "FOR UPDATE" not in run_schema


def test_mysql_repository_replaces_one_run_in_a_single_transaction(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    submission = CollectionSubmission(
        source_system="seller_sprite",
        source_job_id="job-1",
        producer_service="collector_mcp",
        scenario="keyword-reverse",
        site="US",
        data_environment="production",
        ingestion_mode="live",
        result_path=result_path,
        started_at="2026-08-04T10:00:00+08:00",
        completed_at="2026-08-04T10:01:00+08:00",
        cache_key="d" * 64,
        cache_scope="shared",
    )
    document = ParsedCollection(
        submission=submission,
        parser_version="seller-sprite-v1",
        request_params={"resolved_params": {"asin": "B012345678"}},
        artifacts=(
            CollectionArtifact(
                artifact_type="result",
                path=result_path,
                filename="result.json",
                mime_type="application/json",
                size_bytes=2,
                sha256="a" * 64,
            ),
        ),
        datasets=(
            CollectionDataset(
                dataset_code="main",
                dataset_name="关键词",
                source_sheet="关键词",
                columns=(("关键词", "关键词"),),
                records=(
                    CollectionRecord(1, {"关键词": "charger"}, "b" * 64),
                    CollectionRecord(2, {"关键词": "hub"}, "c" * 64),
                ),
            ),
        ),
    )
    connection = FakeConnection()
    repository = MySqlCollectionRepository(
        settings=MySqlSettings(
            host="mysql.internal",
            database="polaris_ops_mcp",
            user="collector_writer",
            password="secret",
        ),
        batch_size=100,
        connect_factory=lambda: connection,
    )

    repository.persist(document)

    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    statements = [sql for sql, _ in connection.executions]
    assert any(sql.startswith("INSERT INTO collection_runs") for sql in statements)
    run_sql, run_params = next(
        (sql, params)
        for sql, params in connection.executions
        if sql.startswith("INSERT INTO collection_runs")
    )
    assert "request_fingerprint, cache_scope" in run_sql
    assert run_params[8:10] == ("d" * 64, "shared")
    assert "DELETE FROM collection_artifacts WHERE run_id = %s" in statements
    assert "DELETE FROM collection_datasets WHERE run_id = %s" in statements
    assert "UPDATE collection_datasets SET row_count = %s WHERE id = %s" in statements
    artifact_rows = next(
        values
        for sql, values in connection.executemany_calls
        if sql.startswith("INSERT INTO collection_artifacts")
    )
    record_rows = next(
        values
        for sql, values in connection.executemany_calls
        if sql.startswith("INSERT INTO collection_records")
    )
    record_insert = next(
        sql
        for sql, _values in connection.executemany_calls
        if sql.startswith("INSERT INTO collection_records")
    )
    assert "dataset_id, source_row_number, business_key" in record_insert
    assert len(artifact_rows) == 1
    assert len(record_rows) == 2
    assert all(row[0] == 201 for row in record_rows)
    assert any(
        sql.startswith("UPDATE collection_runs SET source_row_count")
        and params == (2, 101)
        for sql, params in connection.executions
    )


def test_mysql_repository_queries_history_by_normalized_params():
    class HistoryCursor:
        def __init__(self):
            self.calls = []
            self.phase = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.calls.append((" ".join(sql.split()), params))
            self.phase += 1

        def fetchall(self):
            if self.phase == 2:
                return [{
                    "id": 7,
                    "source_job_id": "job-7",
                    "scenario": "product",
                    "site": "US",
                    "data_environment": "production",
                    "ingestion_mode": "live",
                    "collection_status": "succeeded",
                    "request_params": '{"normalized_params":{"asin":"B0TEST"}}',
                    "source_row_count": 1,
                    "started_at": None,
                    "completed_at": None,
                    "created_at": None,
                }]
            if self.phase == 3:
                return [{
                    "id": 8,
                    "dataset_code": "main",
                    "dataset_name": "Main",
                    "source_sheet": "Main",
                    "columns_json": "[]",
                    "row_count": 1,
                }]
            return [{
                "source_row_number": 1,
                "business_key": "B0TEST",
                "payload": '{"asin":"B0TEST"}',
            }]

        def fetchone(self):
            return {"total": 3}

    class HistoryConnection:
        def __init__(self):
            self.cursor_instance = HistoryCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

    connection = HistoryConnection()
    repository = MySqlCollectionRepository(
        settings=MySqlSettings(), connect_factory=lambda: connection
    )

    result = repository.query_history(
        source_system="keepa",
        scenario="product",
        request_params={"asin": "B0TEST"},
        record_limit=1,
    )

    assert result[0]["job_id"] == "job-7"
    assert result[0]["datasets"][0]["records"][0]["payload"]["asin"] == "B0TEST"
    count_sql, count_params = connection.cursor_instance.calls[0]
    history_sql, history_params = connection.cursor_instance.calls[1]
    assert "SELECT COUNT(*) AS total" in count_sql
    assert "JSON_CONTAINS(request_params, %s, '$.normalized_params')" in history_sql
    assert "JSON_CONTAINS(request_params, %s, '$.request.params')" in history_sql
    assert count_params[0] == "keepa"
    assert history_params[0] == "keepa"
    assert '"asin":"B0TEST"' in history_params[-3]


def test_mysql_repository_history_page_returns_pagination_without_records():
    class Cursor:
        def __init__(self):
            self.phase = 0
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.phase += 1
            self.calls.append((" ".join(sql.split()), params))

        def fetchone(self):
            return {"total": 2}

        def fetchall(self):
            if self.phase == 2:
                return [{
                    "id": 1,
                    "source_job_id": "job-1",
                    "source_row_count": 5,
                    "request_params": "{}",
                }]
            return [{
                "id": 2,
                "dataset_code": "main",
                "dataset_name": "Main",
                "source_sheet": "Main",
                "columns_json": "[]",
                "row_count": 5,
            }]

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

        def close(self):
            pass

    connection = Connection()
    repository = MySqlCollectionRepository(
        settings=MySqlSettings(), connect_factory=lambda: connection
    )

    page = repository.query_history_page(
        source_system="keepa",
        site="UK",
        site_aliases=("GB", "2"),
        limit=1,
        offset=0,
        dataset_code="main",
        record_offset=2,
        include_records=False,
    )

    assert page["total"] == 2
    assert page["has_more"] is True
    assert page["runs"][0]["datasets"][0]["records"] == []
    assert page["runs"][0]["datasets"][0]["records_omitted"] == 5
    assert page["runs"][0]["datasets"][0]["records_offset"] == 2
    dataset_sql, dataset_params = connection.cursor_instance.calls[2]
    count_sql, count_params = connection.cursor_instance.calls[0]
    assert "site IN (%s, %s, %s)" in count_sql
    assert count_params == ("keepa", "UK", "GB", "2")
    assert "dataset_code = %s" in dataset_sql
    assert dataset_params == (1, "main")
    assert not any(
        "FROM collection_records" in sql
        for sql, _params in connection.cursor_instance.calls
    )


def test_mysql_repository_finds_exact_fresh_cached_result():
    class CacheCursor:
        def __init__(self):
            self.phase = 0
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.phase += 1
            self.calls.append((" ".join(sql.split()), params))

        def fetchone(self):
            return {
                "id": 7,
                "source_job_id": "job-source",
                "scenario": "product",
                "site": "US",
                "request_params": '{"_cache":{"result":{"row_count":1}}}',
                "source_row_count": 1,
                "completed_at": None,
                "persistence_completed_at": None,
            }

        def fetchall(self):
            if self.phase == 2:
                return [{
                    "id": 9,
                    "dataset_code": "main",
                    "dataset_name": "Main",
                    "source_sheet": "Main",
                    "columns_json": "[]",
                    "row_count": 1,
                }]
            return [{
                "source_row_number": 1,
                "business_key": "B0TEST",
                "payload": '{"asin":"B0TEST"}',
            }]

    class CacheConnection:
        def __init__(self):
            self.cursor_instance = CacheCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

    connection = CacheConnection()
    repository = MySqlCollectionRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    result = repository.find_cached_result(
        source_system="keepa",
        data_environment="production",
        scenario="product",
        site="US",
        cache_key="a" * 64,
        cache_scope="shared",
        ttl_seconds=86400,
    )

    assert result is not None
    assert result.source_job_id == "job-source"
    assert result.datasets[0]["records"][0]["payload"] == {"asin": "B0TEST"}
    cache_sql, cache_params = connection.cursor_instance.calls[0]
    assert "persistence_completed_at >= TIMESTAMPADD" in cache_sql
    assert "request_fingerprint = %s" in cache_sql
    assert "cache_scope = %s" in cache_sql
    assert "JSON_EXTRACT" not in cache_sql
    assert cache_params == (
        "keepa",
        "production",
        "product",
        "US",
        86400,
        "a" * 64,
        "shared",
    )
    assert connection.closed is True


def test_schema_upgrade_adds_and_backfills_cache_identity():
    class MigrationCursor:
        def __init__(self):
            self.calls = []
            self.columns = set()
            self.indexes = set()
            self.last_sql = ""
            self.last_params = None

        def execute(self, sql, params=None):
            self.last_sql = " ".join(sql.split())
            self.last_params = params
            self.calls.append((self.last_sql, params))
            if "ADD COLUMN request_fingerprint" in self.last_sql:
                self.columns.add("request_fingerprint")
            elif "ADD COLUMN cache_scope" in self.last_sql:
                self.columns.add("cache_scope")
            elif self.last_sql.startswith(
                "CREATE INDEX ix_collection_runs_cache_lookup"
            ):
                self.indexes.add("ix_collection_runs_cache_lookup")

        def fetchone(self):
            if "FROM information_schema.COLUMNS" in self.last_sql:
                return {} if self.last_params[1] in self.columns else None
            if "FROM information_schema.STATISTICS" in self.last_sql:
                return {} if self.last_params[1] in self.indexes else None
            return None

    cursor = MigrationCursor()

    MySqlCollectionRepository._ensure_cache_identity_schema(cursor)
    MySqlCollectionRepository._ensure_cache_identity_schema(cursor)

    sql = [statement for statement, _params in cursor.calls]
    assert sum("ADD COLUMN request_fingerprint" in item for item in sql) == 1
    assert sum("ADD COLUMN cache_scope" in item for item in sql) == 1
    assert sum(item.startswith("CREATE INDEX") for item in sql) == 1
    assert any(
        "JSON_EXTRACT(request_params, '$._cache.cache_key')" in item
        for item in sql
    )
