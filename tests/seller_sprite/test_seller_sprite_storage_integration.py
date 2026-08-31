import sqlite3
from pathlib import Path
from types import SimpleNamespace

from opscli.seller_sprite.collection_storage_integration import (
    SellerSpriteCollectionReconciler,
    SellerSpriteCollectionSubmitter,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


def test_seller_sprite_submitter_adds_collector_environment(tmp_path):
    class FakeRuntime:
        settings = SimpleNamespace(data_environment="production")

        def __init__(self):
            self.submissions = []

        def submit(self, submission):
            self.submissions.append(submission)
            return True

    runtime = FakeRuntime()
    request = SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="US",
        period="30d",
        params={"asin": "B012345678"},
        job_id="job-1",
    )
    result = SellerSpriteScenarioResult.empty(
        job_id="job-1",
        scenario=request.scenario,
        site=request.site,
        period=request.period,
        root_dir=tmp_path,
        params_path=tmp_path / "params.json",
        raw_path=tmp_path / "raw.json",
        result_path=tmp_path / "result.json",
    )

    accepted = SellerSpriteCollectionSubmitter(runtime)(
        request=request,
        result=result,
        status={
            "state": "succeeded",
            "started_at": "2026-08-04T10:00:00+08:00",
            "finished_at": "2026-08-04T10:01:00+08:00",
        },
    )

    assert accepted is True
    [submission] = runtime.submissions
    assert submission.source_system == "seller_sprite"
    assert submission.source_job_id == "job-1"
    assert submission.producer_service == "collector_mcp"
    assert submission.data_environment == "production"
    assert submission.ingestion_mode == "live"
    assert submission.result_path == Path(result.result_path).resolve()


def test_seller_sprite_reconciler_pages_live_successes_by_completion_cursor(tmp_path):
    store = SellerSpriteTaskQueueStore(tmp_path / "seller-queue.sqlite3")
    for job_id in ("job-1", "job-2"):
        request = SellerSpriteScenarioRequest(
            scenario="keyword-reverse",
            site="US",
            period="30d",
            params={"asin": "B012345678"},
            job_id=job_id,
        )
        store.enqueue(
            request=request,
            queue_scope="seller_sprite",
            root_dir=tmp_path / job_id,
        )
    # 后创建的任务先完成，复现任务 ID 与成功提交顺序不一致的并发场景。
    for job_id in ("job-2", "job-1"):
        store.finish_task(
            job_id=job_id,
            result_path=str(tmp_path / job_id / "result.json"),
            row_count=1,
            export_payload=None,
        )
    reconciler = SellerSpriteCollectionReconciler(
        store=store,
        data_environment="production",
    )

    first = reconciler.reconcile(
        cutover_at="2000-01-01T00:00:00+00:00",
        cursor=0,
        limit=1,
    )
    second = reconciler.reconcile(
        cutover_at="2000-01-01T00:00:00+00:00",
        cursor=first.next_cursor,
        limit=1,
    )

    assert [item.source_job_id for item in first.submissions] == ["job-2"]
    assert [item.source_job_id for item in second.submissions] == ["job-1"]
    assert second.next_cursor > first.next_cursor > 0


def test_seller_sprite_reconciler_does_not_promote_historical_result_refetch(tmp_path):
    db_path = tmp_path / "seller-queue.sqlite3"
    store = SellerSpriteTaskQueueStore(db_path)
    request = SellerSpriteScenarioRequest(
        scenario="listing-analysis",
        site="US",
        period="30d",
        params={"asin": "B012345678"},
        job_id="historical-job",
    )
    store.enqueue(
        request=request,
        queue_scope="seller_sprite",
        root_dir=tmp_path / "historical-job",
    )
    store.finish_task(
        job_id=request.job_id,
        result_path=str(tmp_path / "historical-job" / "old-result.json"),
        row_count=1,
        export_payload=None,
    )
    # 模拟升级前已成功的任务：有 succeeded 状态，但没有 v8 成功事件。
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM seller_sprite_collection_success_events WHERE job_id = ?",
            (request.job_id,),
        )

    store.finish_task(
        job_id=request.job_id,
        result_path=str(tmp_path / "historical-job" / "refetched-result.json"),
        row_count=2,
        export_payload=None,
    )
    reconciler = SellerSpriteCollectionReconciler(
        store=store,
        data_environment="production",
    )

    batch = reconciler.reconcile(
        cutover_at="2000-01-01T00:00:00+00:00",
        cursor=0,
        limit=10,
    )

    assert batch.submissions == ()
    assert store.get_status(request.job_id)["row_count"] == 2
    progress_events = store.list_task_progress_events(job_id=request.job_id)
    assert [event["stage"] for event in progress_events] == ["succeeded", "succeeded"]
