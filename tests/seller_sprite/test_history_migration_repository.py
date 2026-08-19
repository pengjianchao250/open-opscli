"""验证卖家精灵历史仓储的事务、幂等和核验行为。"""

import json
from pathlib import Path

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.seller_sprite.history_migration import (
    HistoryArtifact,
    HistoryMigrationRepository,
    PreparedHistoryTask,
)
from opscli.shared.collection_storage.models import (
    CollectionDataset,
    CollectionRecord,
    CollectionSubmission,
)


class FakeCursor:
    """记录 SQL 调用并返回可配置结果的游标替身。"""

    def __init__(self, connection):
        """绑定所属连接并初始化游标状态。"""
        self.connection = connection
        self.lastrowid = 0
        self._row = None
        self._rows = []

    def __enter__(self):
        """返回上下文管理器中的当前游标。"""
        return self

    def __exit__(self, exc_type, exc, tb):
        """退出游标上下文且不吞掉测试异常。"""
        return False

    def execute(self, sql, params=None):
        """记录单条 SQL 并按语句类型提供模拟结果。"""
        normalized = " ".join(sql.split())
        self.connection.executions.append((normalized, params))
        if normalized.startswith("SELECT r.id, r.ingestion_mode"):
            self._row = self.connection.existing_run
        elif normalized.startswith("SELECT i.run_id"):
            self._row = self.connection.verify_row
        elif normalized.startswith("SELECT id, dataset_code"):
            self._rows = self.connection.dataset_rows
        elif normalized.startswith("SELECT source_row_number"):
            self._rows = self.connection.record_rows
        elif normalized.startswith("SELECT artifact_type"):
            self._rows = self.connection.artifact_rows
        elif normalized.startswith("SELECT entity_type"):
            self._rows = self.connection.entity_rows
        elif normalized.startswith("INSERT INTO collection_runs"):
            self.lastrowid = 101
        elif normalized.startswith("INSERT INTO collection_datasets"):
            self.lastrowid = self.connection.next_dataset_id
            self.connection.next_dataset_id += 1
        return 1

    def executemany(self, sql, params):
        """记录批量 SQL 和已物化参数。"""
        normalized = " ".join(sql.split())
        values = list(params)
        self.connection.executemany_calls.append((normalized, values))
        return len(values)

    def fetchone(self):
        """返回最近一次查询配置的单行结果。"""
        return self._row

    def fetchall(self):
        """返回最近一次查询配置的多行结果。"""
        return self._rows


class FakeConnection:
    """提供事务状态观测能力的 MySQL 连接替身。"""

    def __init__(self):
        """初始化 SQL 记录、查询结果和事务标志。"""
        self.executions = []
        self.executemany_calls = []
        self.existing_run = None
        self.verify_row = None
        self.next_dataset_id = 201
        self.dataset_rows = []
        self.record_rows = []
        self.artifact_rows = []
        self.entity_rows = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        """创建绑定当前连接的游标替身。"""
        return FakeCursor(self)

    def commit(self):
        """记录事务已提交。"""
        self.committed = True

    def rollback(self):
        """记录事务已回滚。"""
        self.rolled_back = True

    def close(self):
        """记录连接已关闭。"""
        self.closed = True


def _prepared(tmp_path: Path) -> PreparedHistoryTask:
    result_path = tmp_path / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    submission = CollectionSubmission(
        source_system="seller_sprite",
        source_job_id="job-1",
        producer_service="collector_mcp",
        scenario="keyword-reverse",
        site="US",
        data_environment="production",
        ingestion_mode="backfill",
        result_path=result_path,
        completed_at="2026-07-30T10:00:00+00:00",
    )
    return PreparedHistoryTask(
        task_dir=tmp_path,
        submission=submission,
        request_params={"request": {"params": {"asin": "B012345678"}}},
        raw_payload={"response": {"data": [{"keyword": "usb charger"}]}},
        datasets=(
            CollectionDataset(
                dataset_code="main",
                dataset_name="关键词",
                source_sheet="关键词",
                columns=(("关键词", "关键词"),),
                records=(
                    CollectionRecord(
                        row_number=1,
                        payload={"关键词": "usb charger"},
                        record_hash="b" * 64,
                        business_key="usb charger",
                    ),
                ),
            ),
        ),
        artifacts=(
            HistoryArtifact(
                artifact_type="export",
                filename="export.json",
                mime_type="application/json",
                size_bytes=123,
                sha256="a" * 64,
            ),
        ),
        entities=(("asin", "B012345678"),),
        manifest_sha256="c" * 64,
        dataset_count=1,
        record_count=1,
        source_bytes=123,
    )


def test_repository_persists_history_without_local_paths_in_one_transaction(
    tmp_path: Path,
) -> None:
    connection = FakeConnection()
    repository = HistoryMigrationRepository(
        settings=MySqlSettings(
            host="mysql.internal",
            database="collector",
            user="writer",
            password="secret",
        ),
        connect_factory=lambda: connection,
    )

    outcome = repository.persist("batch-1", _prepared(tmp_path))

    assert outcome == "imported"
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    artifact_rows = next(
        values
        for sql, values in connection.executemany_calls
        if sql.startswith("INSERT INTO collection_artifacts")
    )
    assert artifact_rows == [
        (101, "export", "export.json", "urn:sha256:" + "a" * 64, "application/json", 123, "a" * 64)
    ]
    statements = [sql for sql, _ in connection.executions]
    assert not any(sql.startswith("INSERT INTO collection_raw_payloads") for sql in statements)
    assert any(sql.startswith("INSERT INTO collection_backfill_items") for sql in statements)
    assert any(
        sql.startswith("INSERT INTO collection_run_entities")
        for sql, _ in connection.executemany_calls
    )
    serialized = json.dumps(
        [connection.executions, connection.executemany_calls],
        ensure_ascii=False,
        default=str,
    )
    assert "file://" not in serialized
    assert "C:/" not in serialized
    assert "/root/" not in serialized


def test_repository_skips_identical_existing_backfill_without_replacing_rows(
    tmp_path: Path,
) -> None:
    connection = FakeConnection()
    connection.existing_run = {
        "id": 88,
        "ingestion_mode": "backfill",
        "manifest_sha256": "c" * 64,
    }
    repository = HistoryMigrationRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    outcome = repository.persist("batch-2", _prepared(tmp_path))

    assert outcome == "skipped_existing"
    assert connection.committed is True
    statements = [sql for sql, _ in connection.executions]
    assert not any(sql.startswith("DELETE FROM collection_datasets") for sql in statements)


def test_repository_marks_task_verified_only_when_all_counts_and_hashes_match(
    tmp_path: Path,
) -> None:
    prepared = _prepared(tmp_path)
    connection = FakeConnection()
    connection.verify_row = {
        "run_id": 101,
        "manifest_sha256": prepared.manifest_sha256,
        "dataset_count": 1,
        "record_count": 1,
        "actual_dataset_count": 1,
        "actual_record_count": 1,
    }
    connection.dataset_rows = [
        {
            "id": 201,
            "dataset_code": "main",
            "dataset_name": "关键词",
            "source_sheet": "关键词",
            "columns_json": json.dumps([{"name": "关键词", "key": "关键词"}]),
            "row_count": 1,
        }
    ]
    connection.record_rows = [
        {
            "source_row_number": 1,
            "business_key": "usb charger",
            "record_hash": "b" * 64,
            "payload": json.dumps({"关键词": "usb charger"}, ensure_ascii=False),
        }
    ]
    connection.artifact_rows = [
        {
            "artifact_type": "export",
            "filename": "export.json",
            "storage_uri": "urn:sha256:" + "a" * 64,
            "mime_type": "application/json",
            "size_bytes": 123,
            "sha256": "a" * 64,
        }
    ]
    connection.entity_rows = [
        {"entity_type": "asin", "entity_value": "B012345678"}
    ]
    repository = HistoryMigrationRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    verified = repository.verify_task("batch-1", prepared)

    assert verified is True
    assert connection.committed is True
    assert any(
        sql.startswith("UPDATE collection_backfill_items SET status = 'verified'")
        for sql, _ in connection.executions
    )
