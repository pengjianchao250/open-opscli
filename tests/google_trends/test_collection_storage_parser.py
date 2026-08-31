"""Google Trends 采集结果 Parser 测试。"""

import json
from pathlib import Path

from openpyxl import Workbook

from opscli.google_trends.collection_storage_parser import (
    GoogleTrendsCollectionParser,
)
from opscli.shared.collection_storage.models import CollectionSubmission


def _write_json(path: Path, payload) -> None:
    """写入测试所需 JSON 文件。"""
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_google_trends_json_export_becomes_main_dataset(tmp_path: Path):
    """JSON 导出的趋势记录应转换为可写入 MySQL 的主 Dataset。"""
    root = tmp_path / "job-json"
    root.mkdir()
    params_path = root / "params.json"
    raw_path = root / "raw.json"
    result_path = root / "result.json"
    export_path = root / "job-json.json"
    _write_json(
        params_path,
        {
            "request": {"scenario": "trends", "geo": "US"},
            "normalized_params": {"q": "flashlight", "data_type": "TIMESERIES"},
        },
    )
    _write_json(raw_path, {"response": {"interest_over_time": {}}})
    _write_json(
        export_path,
        {
            "job_id": "job-json",
            "scenario": "trends",
            "geo": "US",
            "row_count": 2,
            "rows": [
                {"date": "2026-01-01", "flashlight": 42},
                {"date": "2026-01-02", "flashlight": 56, "isPartial": False},
            ],
        },
    )
    _write_json(
        result_path,
        {
            "job_id": "job-json",
            "scenario": "trends",
            "geo": "US",
            "row_count": 2,
            "root_dir": str(root),
            "params_path": str(params_path),
            "raw_path": str(raw_path),
            "result_path": str(result_path),
            "data": [
                {"date": "2026-01-01", "flashlight": 42},
                {"date": "2026-01-02", "flashlight": 56, "isPartial": False},
            ],
            "export": {
                "path": str(export_path),
                "filename": export_path.name,
                "format": "json",
                "mime_type": "application/json",
            },
        },
    )
    submission = CollectionSubmission(
        source_system="google_trends",
        source_job_id="job-json",
        producer_service="mcp",
        scenario="trends",
        site="US",
        data_environment="production",
        ingestion_mode="live",
        result_path=result_path,
    )

    document = GoogleTrendsCollectionParser().parse(submission)

    assert document.parser_version == "google-trends-v1"
    assert document.request_params["normalized_params"]["q"] == "flashlight"
    assert [artifact.artifact_type for artifact in document.artifacts] == [
        "params",
        "raw",
        "result",
        "export",
    ]
    [dataset] = document.datasets
    assert dataset.columns == (
        ("date", "date"),
        ("flashlight", "flashlight"),
        ("isPartial", "isPartial"),
    )
    records = tuple(dataset.records)
    assert records[0].payload == {
        "date": "2026-01-01",
        "flashlight": 42,
        "isPartial": None,
    }
    assert records[0].business_key == "2026-01-01"
    assert records[1].payload["isPartial"] is False


def test_google_trends_xlsx_export_uses_normalized_result_data(tmp_path: Path):
    """XLSX 任务入库应保留规范化结果类型与完整字段。"""
    root = tmp_path / "job-xlsx"
    root.mkdir()
    params_path = root / "params.json"
    raw_path = root / "raw.json"
    result_path = root / "result.json"
    export_path = root / "job-xlsx.xlsx"
    _write_json(params_path, {"request": {"scenario": "trends", "geo": "US"}})
    _write_json(raw_path, {"response": {"interest_over_time": {}}})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "趋势-US"
    sheet.append(["日期", "flashlight", "是否部分数据"])
    sheet.append(["2026-01-01", 42, False])
    workbook.save(export_path)
    _write_json(
        result_path,
        {
            "job_id": "job-xlsx",
            "scenario": "trends",
            "geo": "US",
            "row_count": 1,
            "params_path": str(params_path),
            "raw_path": str(raw_path),
            "result_path": str(result_path),
            "data": [
                {
                    "date": "2026-01-01",
                    "flashlight": 42,
                    "isPartial": False,
                    "details": {"source": "api"},
                }
            ],
            "export": {
                "path": str(export_path),
                "filename": export_path.name,
                "format": "xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        },
    )
    submission = CollectionSubmission(
        source_system="google_trends",
        source_job_id="job-xlsx",
        producer_service="mcp",
        scenario="trends",
        site="US",
        data_environment="production",
        ingestion_mode="live",
        result_path=result_path,
    )

    document = GoogleTrendsCollectionParser().parse(submission)

    [dataset] = document.datasets
    assert dataset.source_sheet == "main"
    [record] = tuple(dataset.records)
    assert record.payload == {
        "date": "2026-01-01",
        "flashlight": 42,
        "isPartial": False,
        "details": {"source": "api"},
    }
    assert record.business_key == "2026-01-01"
