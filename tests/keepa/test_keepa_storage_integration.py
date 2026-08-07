"""Keepa 到 Collector 通用数据沉淀的合同测试。"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from opscli.keepa.collection_storage_integration import (
    KeepaCollectionReconciler,
    KeepaCollectionSubmitter,
)
from opscli.keepa.collection_storage_parser import KeepaCollectionParser
from opscli.shared.collection_storage.models import CollectionSubmission
from opscli.shared.collection_storage.outbox import CollectionOutbox
from opscli.keepa.domain.models import (
    KeepaScenarioRequest,
    KeepaScenarioResult,
)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_keepa_xlsx_result_becomes_common_collection_document(tmp_path):
    root = tmp_path / "keepa-job-1"
    root.mkdir()
    params_path = root / "params.json"
    raw_path = root / "raw.json"
    result_path = root / "result.json"
    export_path = root / "Keepa-US-product.xlsx"
    _write_json(
        params_path,
        {
            "request": {"scenario": "product", "site": "US"},
            "normalized_params": {"asin": "B0088PUEPK"},
        },
    )
    _write_json(raw_path, {"response": {"products": [{"asin": "B0088PUEPK"}]}})
    workbook = Workbook()
    main = workbook.active
    main.title = "Keepa product"
    main.append(["ASIN", "Title"])
    main.append(["B0088PUEPK", "Test Product"])
    history = workbook.create_sheet("price_history")
    history.append(["asin", "utc", "price"])
    history.append(["B0088PUEPK", "2026-08-07T00:00:00Z", 12.99])
    workbook.save(export_path)
    _write_json(
        result_path,
        {
            "job_id": "keepa-job-1",
            "scenario": "product",
            "site": "US",
            "row_count": 1,
            "root_dir": str(root),
            "params_path": str(params_path),
            "raw_path": str(raw_path),
            "result_path": str(result_path),
            "export": {
                "path": str(export_path),
                "filename": export_path.name,
                "format": "xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        },
    )
    submission = CollectionSubmission(
        source_system="keepa",
        source_job_id="keepa-job-1",
        producer_service="collector_mcp",
        scenario="product",
        site="US",
        data_environment="debug",
        ingestion_mode="live",
        result_path=result_path,
    )

    document = KeepaCollectionParser().parse(submission)

    assert document.parser_version == "keepa-v2"
    assert document.request_params["normalized_params"] == {"asin": "B0088PUEPK"}
    assert [artifact.artifact_type for artifact in document.artifacts] == [
        "params",
        "raw",
        "result",
        "export",
    ]
    assert [dataset.dataset_code for dataset in document.datasets] == [
        "main",
        "additional_1",
    ]
    main_record = tuple(document.datasets[0].records)[0]
    history_record = tuple(document.datasets[1].records)[0]
    assert main_record.payload == {"ASIN": "B0088PUEPK", "Title": "Test Product"}
    assert main_record.business_key == "B0088PUEPK"
    assert history_record.payload["price"] == 12.99
    assert history_record.business_key == "B0088PUEPK"


def test_keepa_submitter_adds_common_collection_environment(tmp_path):
    class FakeRuntime:
        settings = SimpleNamespace(data_environment="debug")

        def __init__(self):
            self.submissions = []

        def submit(self, submission):
            self.submissions.append(submission)
            return True

    runtime = FakeRuntime()
    request = KeepaScenarioRequest(
        scenario="product",
        site="US",
        params={"asin": "B0088PUEPK"},
        job_id="keepa-job-1",
    )
    result = KeepaScenarioResult.empty(
        job_id="keepa-job-1",
        scenario=request.scenario,
        site=request.site,
        root_dir=tmp_path,
        params_path=tmp_path / "params.json",
        raw_path=tmp_path / "raw.json",
        result_path=tmp_path / "result.json",
    )

    accepted = KeepaCollectionSubmitter(runtime)(request=request, result=result)

    assert accepted is True
    [submission] = runtime.submissions
    assert submission.source_system == "keepa"
    assert submission.source_job_id == "keepa-job-1"
    assert submission.producer_service == "mcp"
    assert submission.data_environment == "debug"
    assert submission.ingestion_mode == "live"
    assert submission.result_path == Path(result.result_path).resolve()


def test_keepa_reconciler_recovers_post_cutover_result_missing_from_outbox(tmp_path):
    output_dir = tmp_path / "keepa-runs"
    old_root = output_dir / "old-job"
    new_root = output_dir / "new-job"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    old_result = old_root / "result.json"
    new_result = new_root / "result.json"
    _write_json(
        old_result,
        {
            "job_id": "old-job",
            "scenario": "product",
            "site": "US",
            "result_path": str(old_result),
        },
    )
    _write_json(
        new_result,
        {
            "job_id": "new-job",
            "scenario": "product",
            "site": "US",
            "result_path": str(new_result),
        },
    )
    os.utime(old_result, (946684800, 946684800))
    outbox = CollectionOutbox(tmp_path / "outbox.sqlite3")
    reconciler = KeepaCollectionReconciler(
        output_dir=output_dir,
        data_environment="debug",
        outbox=outbox,
    )

    first = reconciler.reconcile(
        cutover_at="2020-01-01T00:00:00+00:00",
        cursor=0,
        limit=100,
    )

    assert [item.source_job_id for item in first.submissions] == ["new-job"]
    assert first.next_cursor == new_result.stat().st_mtime_ns
    outbox.submit(first.submissions[0])
    second = reconciler.reconcile(
        cutover_at="2020-01-01T00:00:00+00:00",
        cursor=first.next_cursor,
        limit=100,
    )
    assert second.submissions == ()
    assert second.next_cursor == first.next_cursor


def test_keepa_reconciler_replays_shared_mtime_boundary_without_losing_jobs(tmp_path):
    output_dir = tmp_path / "keepa-runs"
    shared_mtime_ns = 1_800_000_000_123_456_700
    for job_id in ("job-a", "job-b"):
        root = output_dir / job_id
        root.mkdir(parents=True)
        result_path = root / "result.json"
        _write_json(
            result_path,
            {
                "job_id": job_id,
                "scenario": "product",
                "site": "US",
                "result_path": str(result_path),
            },
        )
        os.utime(result_path, ns=(shared_mtime_ns, shared_mtime_ns))

    outbox = CollectionOutbox(tmp_path / "outbox.sqlite3")
    reconciler = KeepaCollectionReconciler(
        output_dir=output_dir,
        data_environment="debug",
        outbox=outbox,
    )
    first = reconciler.reconcile(
        cutover_at="2020-01-01T00:00:00+00:00",
        cursor=0,
        limit=1,
    )
    outbox.submit(first.submissions[0])
    second = reconciler.reconcile(
        cutover_at="2020-01-01T00:00:00+00:00",
        cursor=first.next_cursor,
        limit=1,
    )

    assert [item.source_job_id for item in first.submissions] == ["job-a"]
    assert [item.source_job_id for item in second.submissions] == ["job-b"]
    assert first.next_cursor == shared_mtime_ns - 1
    assert second.next_cursor == shared_mtime_ns
