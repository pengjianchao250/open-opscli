import json
from pathlib import Path

from openpyxl import Workbook

from opscli.collector_mcp.storage.models import CollectionSubmission
from opscli.collector_mcp.storage.seller_sprite_parser import (
    SellerSpriteCollectionParser,
)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_seller_sprite_json_export_becomes_main_and_additional_datasets(tmp_path):
    root = tmp_path / "job-1"
    root.mkdir()
    params_path = root / "params.json"
    raw_path = root / "raw.json"
    result_path = root / "result.json"
    export_path = root / "CompareKeywords-US-job-1.json"
    _write_json(
        params_path,
        {
            "request": {"scenario": "keyword-comparison", "site": "US"},
            "resolved_params": {"asin": "B012345678"},
        },
    )
    _write_json(raw_path, {"response": {"data": [{"keyword": "usb charger"}]}})
    _write_json(
        export_path,
        {
            "schema_version": "2.0",
            "sheet_name": "关键词对比",
            "columns": ["关键词", "搜索量", "搜索量"],
            "rows": [["usb charger", 1000, 900]],
            "additional_sheets": [
                {
                    "name": "ASIN",
                    "columns": ["ASIN"],
                    "rows": [["B012345678"]],
                }
            ],
        },
    )
    _write_json(
        result_path,
        {
            "job_id": "job-1",
            "scenario": "keyword-comparison",
            "site": "US",
            "period": "30d",
            "row_count": 1,
            "root_dir": str(root),
            "params_path": str(params_path),
            "raw_path": str(raw_path),
            "result_path": str(result_path),
            "export": {
                "path": str(export_path),
                "filename": export_path.name,
                "format": "json",
                "mime_type": "application/json",
            },
            "data": [{"keyword": "usb charger"}],
        },
    )
    submission = CollectionSubmission(
        source_system="seller_sprite",
        source_job_id="job-1",
        producer_service="collector_mcp",
        scenario="keyword-comparison",
        site="US",
        data_environment="production",
        ingestion_mode="live",
        result_path=result_path,
    )

    document = SellerSpriteCollectionParser().parse(submission)

    assert document.parser_version == "seller-sprite-v1"
    assert document.request_params == {
        "request": {"scenario": "keyword-comparison", "site": "US"},
        "resolved_params": {"asin": "B012345678"},
    }
    assert [artifact.artifact_type for artifact in document.artifacts] == [
        "params",
        "raw",
        "result",
        "export",
    ]
    assert all(len(artifact.sha256) == 64 for artifact in document.artifacts)
    assert [dataset.dataset_code for dataset in document.datasets] == [
        "main",
        "additional_1",
    ]
    assert document.datasets[0].columns == (
        ("关键词", "关键词"),
        ("搜索量", "搜索量"),
        ("搜索量", "搜索量__2"),
    )
    main_records = tuple(document.datasets[0].records)
    additional_records = tuple(document.datasets[1].records)
    assert main_records[0].payload == {
        "关键词": "usb charger",
        "搜索量": 1000,
        "搜索量__2": 900,
    }
    assert additional_records[0].payload == {"ASIN": "B012345678"}


def test_seller_sprite_xlsx_export_uses_each_worksheet_as_a_dataset(tmp_path):
    root = tmp_path / "job-xlsx"
    root.mkdir()
    params_path = root / "params.json"
    raw_path = root / "raw.json"
    result_path = root / "result.json"
    export_path = root / "Brand-Database.xlsx"
    _write_json(params_path, {"request": {"scenario": "branddb"}})
    _write_json(raw_path, {"response": {"file": "downloaded"}})
    workbook = Workbook()
    main = workbook.active
    main.title = "品牌列表"
    main.append(["品牌", "商品数"])
    main.append(["AUKEY", 12])
    detail = workbook.create_sheet("类目")
    detail.append(["类目", "份额"])
    detail.append(["Electronics", 0.25])
    workbook.save(export_path)
    _write_json(
        result_path,
        {
            "job_id": "job-xlsx",
            "scenario": "branddb",
            "site": "US",
            "period": "30d",
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
            "data": [],
        },
    )
    submission = CollectionSubmission(
        source_system="seller_sprite",
        source_job_id="job-xlsx",
        producer_service="collector_mcp",
        scenario="branddb",
        site="US",
        data_environment="production",
        ingestion_mode="live",
        result_path=result_path,
    )

    document = SellerSpriteCollectionParser().parse(submission)

    assert [
        (dataset.dataset_code, dataset.source_sheet) for dataset in document.datasets
    ] == [
        ("main", "品牌列表"),
        ("additional_1", "类目"),
    ]
    assert not isinstance(document.datasets[0].records, tuple)
    main_records = tuple(document.datasets[0].records)
    additional_records = tuple(document.datasets[1].records)
    assert main_records[0].payload == {"品牌": "AUKEY", "商品数": 12}
    assert additional_records[0].payload == {
        "类目": "Electronics",
        "份额": 0.25,
    }
