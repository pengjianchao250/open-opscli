import json
import sqlite3
from pathlib import Path

from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest


def _request(*, job_id: str, asin: str = "B07YRMT36L") -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": asin},
        job_id=job_id,
        export_format="json",
    )


def _mcp_request(*, job_id: str, asin: str = "B07YRMT36L") -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": asin},
        job_id=job_id,
        export_format="json",
        mode="mcp",
    )


def test_store_enqueue_returns_queue_position(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    first = store.enqueue(
        request=_request(job_id="job-1"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-1",
    )
    second = store.enqueue(
        request=_request(job_id="job-2", asin="B00TEST222"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-2",
    )

    assert first["job_id"] == "job-1"
    assert first["state"] == "queued"
    assert first["position"] == 1
    assert second["job_id"] == "job-2"
    assert second["state"] == "queued"
    assert second["position"] == 2


def test_store_claim_next_updates_waiting_position(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    store.enqueue(request=_request(job_id="job-2"), queue_scope="seller_sprite", root_dir=tmp_path / "job-2")

    claimed = store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")
    waiting = store.get_status("job-2")

    assert claimed is not None
    assert claimed["job_id"] == "job-1"
    assert claimed["state"] == "running"
    assert claimed["assigned_account"] == "default"
    assert waiting["job_id"] == "job-2"
    assert waiting["state"] == "queued"
    assert waiting["position"] == 1


def test_store_resets_running_tasks_back_to_queue(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    first = SellerSpriteTaskQueueStore(db_path=db_path)
    first.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    first.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

    second = SellerSpriteTaskQueueStore(db_path=db_path)
    reset_count = second.reset_running_tasks()
    status = second.get_status("job-1")

    assert reset_count == 1
    assert status["job_id"] == "job-1"
    assert status["state"] == "queued"
    assert status["position"] == 1
    assert status["assigned_account"] is None


def test_store_marks_task_finished_and_persists_result_metadata(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

    store.finish_task(
        job_id="job-1",
        result_path=str(tmp_path / "job-1" / "result.json"),
        row_count=3,
        export_payload={"path": "/tmp/job-1.json", "filename": "job-1.json"},
    )

    status = store.get_status("job-1")

    assert status["state"] == "succeeded"
    assert status["stage"] == "finished"
    assert status["row_count"] == 3
    assert status["export"]["filename"] == "job-1.json"
    assert status["position"] is None


def test_store_persists_task_auth_context(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-auth"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-auth",
        session_id="sid-1",
        jwt="jwt-1",
    )

    context = store.get_task_context("job-auth")

    assert context["session_id"] == "sid-1"
    assert context["jwt"] == "jwt-1"


def test_store_create_mcp_run_persists_initial_record(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    created = store.create_mcp_run(_mcp_request(job_id="mcp-job-1"), "user@example.com")

    assert created["job_id"] == "mcp-job-1"
    assert created["user_email"] == "user@example.com"
    assert created["scenario"] == "keyword-reverse"
    assert created["mode"] == "browser-route"
    assert created["params_json"] == {"asin": "B07YRMT36L"}
    assert created["result_state"] == "queued"
    assert created["result_row_count"] == 0
    assert created["result_export_format"] is None
    assert created["result_export_filename"] is None
    assert created["result_export_job_id"] is None
    assert created["error_json"] is None
    assert created["created_at"] is not None
    assert created["started_at"] is None
    assert created["finished_at"] is None
    assert created["updated_at"] is not None


def test_store_mcp_run_updates_from_running_to_succeeded(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.create_mcp_run(_mcp_request(job_id="mcp-job-2"), "user@example.com")

    store.mark_mcp_run_running("mcp-job-2")
    store.finish_mcp_run_success(
        "mcp-job-2",
        row_count=5,
        export_payload={
            "format": "json",
            "filename": "mcp-job-2.json",
        },
    )

    record = store.get_mcp_run("mcp-job-2")

    assert record["job_id"] == "mcp-job-2"
    assert record["result_state"] == "succeeded"
    assert record["result_row_count"] == 5
    assert record["result_export_format"] == "json"
    assert record["result_export_filename"] == "mcp-job-2.json"
    assert record["result_export_job_id"] == "mcp-job-2"
    assert record["error_json"] is None
    assert record["started_at"] is not None
    assert record["finished_at"] is not None
    assert record["updated_at"] is not None


def test_store_mcp_run_updates_to_failed(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.create_mcp_run(_mcp_request(job_id="mcp-job-3"), "user@example.com")

    store.finish_mcp_run_failed(
        "mcp-job-3",
        error_payload={"code": "SELLER_SPRITE_ERROR", "message": "任务失败"},
    )

    record = store.get_mcp_run("mcp-job-3")

    assert record["job_id"] == "mcp-job-3"
    assert record["result_state"] == "failed"
    assert record["result_row_count"] == 0
    assert record["result_export_format"] is None
    assert record["result_export_filename"] is None
    assert record["result_export_job_id"] is None
    assert record["error_json"] == {
        "code": "SELLER_SPRITE_ERROR",
        "message": "任务失败",
    }
    assert record["started_at"] is None
    assert record["finished_at"] is not None
    assert record["updated_at"] is not None


def test_store_initializes_mcp_runs_table_with_expected_columns(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    SellerSpriteTaskQueueStore(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]: {"type": row[2], "notnull": row[3], "pk": row[5]}
            for row in conn.execute("PRAGMA table_info(seller_sprite_mcp_runs)")
        }

    assert "job_id" in columns
    assert columns["job_id"]["type"] == "TEXT"
    assert columns["job_id"]["pk"] == 1
    assert "mode" in columns
    assert columns["mode"]["type"] == "TEXT"
    assert columns["mode"]["notnull"] == 1
    assert "result_state" in columns
    assert columns["result_state"]["type"] == "TEXT"
    assert columns["result_state"]["notnull"] == 1
    assert "params_json" in columns
    assert columns["params_json"]["type"] == "TEXT"
    assert columns["params_json"]["notnull"] == 1


def test_store_migrates_legacy_mcp_runs_table_and_supports_updates(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE seller_sprite_mcp_runs (
                job_id TEXT NOT NULL PRIMARY KEY,
                user_email TEXT NOT NULL,
                scenario TEXT NOT NULL,
                mode TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    store = SellerSpriteTaskQueueStore(db_path=db_path)
    store.create_mcp_run(_mcp_request(job_id="legacy-job-1"), "user@example.com")
    store.mark_mcp_run_running("legacy-job-1")
    store.finish_mcp_run_success(
        "legacy-job-1",
        row_count=2,
        export_payload={"format": "json", "filename": "legacy-job-1.json"},
    )

    record = store.get_mcp_run("legacy-job-1")

    assert record["job_id"] == "legacy-job-1"
    assert record["mode"] == "browser-route"
    assert record["result_state"] == "succeeded"
    assert record["result_row_count"] == 2
    assert record["result_export_format"] == "json"
    assert record["result_export_filename"] == "legacy-job-1.json"
    assert record["result_export_job_id"] == "legacy-job-1"
    assert record["error_json"] is None
    assert record["started_at"] is not None
    assert record["finished_at"] is not None


def test_store_mark_mcp_run_running_raises_when_job_missing(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    try:
        store.mark_mcp_run_running("missing-job")
    except ValueError as exc:
        assert "MCP 调用记录不存在" in str(exc)
    else:
        raise AssertionError("缺失 job_id 时应抛出异常")


def test_store_migrates_legacy_mcp_runs_table_without_updated_at(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE seller_sprite_mcp_runs (
                job_id TEXT NOT NULL PRIMARY KEY,
                user_email TEXT NOT NULL,
                scenario TEXT NOT NULL,
                mode TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_state TEXT NOT NULL,
                result_row_count INTEGER NOT NULL DEFAULT 0,
                result_export_format TEXT NULL,
                result_export_filename TEXT NULL,
                result_export_job_id TEXT NULL,
                error_json TEXT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NULL,
                finished_at TEXT NULL
            )
            """
        )

    store = SellerSpriteTaskQueueStore(db_path=db_path)
    record = store.create_mcp_run(_mcp_request(job_id="legacy-job-2"), "user@example.com")

    assert record["job_id"] == "legacy-job-2"
    assert record["mode"] == "browser-route"
    assert record["result_state"] == "queued"
    assert record["updated_at"] is not None
