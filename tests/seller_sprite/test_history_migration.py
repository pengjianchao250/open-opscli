"""验证卖家精灵历史扫描、脱敏与源文件清理门禁。"""

import json
from pathlib import Path

import pytest

from opscli.seller_sprite.history_migration import (
    PURGE_CONFIRMATION,
    HistoryMigrationError,
    SellerSpriteHistoryScanner,
    contains_local_path,
    purge_verified_task,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_complete_task(root: Path, job_id: str = "job-1") -> Path:
    task_dir = root / job_id
    task_dir.mkdir()
    export_path = task_dir / "export.json"
    _write_json(
        task_dir / "params.json",
        {
            "request": {
                "job_id": job_id,
                "scenario": "keyword-reverse",
                "site": "US",
                "period": "30d",
                "output_dir": "C:/private/seller_sprite/api_runs",
                "attempt_output_dir": "/root/.config/opscli/private",
                "params": {"asin": "B012345678"},
            },
            "resolved_params": {"asin": "B012345678"},
            "payload": {"asin": "B012345678"},
        },
    )
    _write_json(
        task_dir / "raw.json",
        {
            "job_id": job_id,
            "scenario": "keyword-reverse",
            "mode": "browser-route",
            "login": {"cookie_names": ["session"]},
            "payload": {"asin": "B012345678"},
            "response": {"data": [{"keyword": "usb charger"}]},
            "high_frequency_response": None,
            "warnings": [{"message": "saved at C:/private/raw.json"}],
        },
    )
    _write_json(
        export_path,
        {
            "schema_version": "2.0",
            "sheet_name": "关键词",
            "columns": ["关键词", "月搜索量"],
            "rows": [["usb charger", 1000]],
            "additional_sheets": [],
        },
    )
    _write_json(
        task_dir / "result.json",
        {
            "job_id": job_id,
            "scenario": "keyword-reverse",
            "site": "US",
            "period": "30d",
            "row_count": 1,
            "root_dir": "/root/.config/opscli/seller_sprite/api_runs/job-1",
            "params_path": "/root/.config/opscli/seller_sprite/api_runs/job-1/params.json",
            "raw_path": "/root/.config/opscli/seller_sprite/api_runs/job-1/raw.json",
            "result_path": "/root/.config/opscli/seller_sprite/api_runs/job-1/result.json",
            "export": {
                "path": "/root/.config/opscli/seller_sprite/api_runs/job-1/export.json",
                "filename": export_path.name,
                "format": "json",
                "mime_type": "application/json",
            },
            "data": [{"关键词": "usb charger", "月搜索量": 1000}],
            "warnings": [],
        },
    )
    return task_dir


def test_scanner_audits_only_complete_success_tasks(tmp_path: Path) -> None:
    _write_complete_task(tmp_path)
    incomplete = tmp_path / "job-incomplete"
    incomplete.mkdir()
    _write_json(
        incomplete / "params.json",
        {"request": {"job_id": "job-incomplete", "scenario": "keyword-miner"}},
    )

    audit = SellerSpriteHistoryScanner(tmp_path).audit()

    assert audit.discovered_tasks == 2
    assert audit.complete_tasks == 1
    assert audit.incomplete_tasks == 1
    assert audit.invalid_tasks == 0
    assert audit.dataset_count == 1
    assert audit.record_count == 1
    assert audit.by_scenario == {"keyword-reverse": 1}


def test_prepared_task_removes_local_paths_and_duplicate_operational_data(
    tmp_path: Path,
) -> None:
    task_dir = _write_complete_task(tmp_path)

    prepared = SellerSpriteHistoryScanner(tmp_path).prepare(task_dir)

    assert prepared.submission.source_job_id == "job-1"
    assert prepared.submission.ingestion_mode == "backfill"
    assert prepared.request_params["request"] == {
        "job_id": "job-1",
        "scenario": "keyword-reverse",
        "site": "US",
        "period": "30d",
        "params": {"asin": "B012345678"},
    }
    assert prepared.raw_payload == {
        "scenario": "keyword-reverse",
        "mode": "browser-route",
        "response": {"data": [{"keyword": "usb charger"}]},
        "high_frequency_response": None,
        "warnings": [{"message": "[本地路径已移除]"}],
    }
    assert prepared.entities == (("asin", "B012345678"),)
    assert prepared.dataset_count == 1
    assert prepared.record_count == 1
    assert not contains_local_path(prepared.request_params)
    assert not contains_local_path(prepared.raw_payload)
    assert all(artifact.storage_uri is None for artifact in prepared.artifacts)


def test_legacy_json_is_reformatted_into_the_same_dataset_contract(
    tmp_path: Path,
) -> None:
    task_dir = _write_complete_task(tmp_path)
    params = json.loads((task_dir / "params.json").read_text(encoding="utf-8"))
    params["request"]["scenario"] = "keyword-miner"
    _write_json(task_dir / "params.json", params)
    result = json.loads((task_dir / "result.json").read_text(encoding="utf-8"))
    result["scenario"] = "keyword-miner"
    _write_json(task_dir / "result.json", result)
    _write_json(
        task_dir / "export.json",
        {
            "job_id": "job-1",
            "scenario": "keyword-miner",
            "site": "US",
            "period": "30d",
            "rows": [{"keyword": "usb charger", "searches": 1000}],
            "high_frequency_rows": [
                {"keyword": "usb", "frequency": 2, "percentage": 0.1}
            ],
        },
    )

    prepared = SellerSpriteHistoryScanner(tmp_path).prepare(task_dir)

    assert prepared.dataset_count == 2
    assert prepared.record_count == 2
    assert prepared.datasets[0].columns[0] == ("关键词", "关键词")
    assert tuple(prepared.datasets[0].records)[0].payload["关键词"] == "usb charger"
    assert prepared.datasets[1].dataset_name == "Unique Words"


@pytest.mark.parametrize(
    "value",
    ["/data/private/result.json", "'/mnt/exports/result.json'", "( /workspace/job )"],
)
def test_local_path_detection_covers_unix_paths_in_arbitrary_directories(
    value: str,
) -> None:
    assert contains_local_path({"value": value})


def test_purge_requires_verified_manifest_and_explicit_confirmation(
    tmp_path: Path,
) -> None:
    task_dir = _write_complete_task(tmp_path)
    scanner = SellerSpriteHistoryScanner(tmp_path)
    prepared = scanner.prepare(task_dir)

    with pytest.raises(HistoryMigrationError, match="确认口令"):
        purge_verified_task(
            prepared,
            expected_manifest_sha256=prepared.manifest_sha256,
            confirmation="wrong",
        )

    with pytest.raises(HistoryMigrationError, match="manifest"):
        purge_verified_task(
            prepared,
            expected_manifest_sha256="0" * 64,
            confirmation=PURGE_CONFIRMATION,
        )

    removed = purge_verified_task(
        prepared,
        expected_manifest_sha256=prepared.manifest_sha256,
        confirmation=PURGE_CONFIRMATION,
    )

    assert removed == 4
    assert not task_dir.exists()
