from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.models import (
    CollectionArtifact,
    CollectionDataset,
    CollectionRecord,
    CollectionSubmission,
    ParsedCollection,
)
from opscli.shared.collection_storage.mysql_repository import MySqlCollectionRepository
from opscli.shared.collection_storage.schema import SCHEMA_STATEMENTS


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
