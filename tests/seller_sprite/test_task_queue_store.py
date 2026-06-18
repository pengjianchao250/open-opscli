import json
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
