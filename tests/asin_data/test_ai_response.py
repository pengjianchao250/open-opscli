from pathlib import Path

from openpyxl import Workbook

from opscli.asin_data.services.ai_response import build_ai_ready_response


def write_workbook(path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet_name, rows in sheets:
        ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def response_for_file(
    tmp_path: Path,
    *,
    asin: str,
    file_key: str,
    sheets: list[tuple[str, list[list[object]]]],
    request: dict | None = None,
):
    file_path = tmp_path / asin / f"{file_key}.xlsx"
    write_workbook(file_path, sheets)
    url = f"https://example.oss.aliyuncs.com/asin-data/{asin}-{file_key}-live-data.xlsx"
    split_files = {
        asin: {
            file_key: {
                "asin": asin,
                "file_key": file_key,
                "file_path": file_path.as_posix(),
                "file_url": url,
            }
        }
    }
    result = {
        "success": True,
        "output_dir": (tmp_path / "run").as_posix(),
        "summary": {"asin_count": 1, "source_error_count": 0},
        "manifest": {
            "run_id": "run-ai-ready",
            "asin_data_package": {
                "items": [
                    {
                        "asin": asin,
                        "site": "US",
                        "files": {file_key: file_path.as_posix()},
                    }
                ]
            },
        },
        "split_file_paths": split_files,
        "split_file_urls": {asin: {file_key: url}},
    }
    return build_ai_ready_response(
        tool_name="asin_data_live_data",
        request={
            "asin": asin,
            "site": "US",
            "data_scope": "bi" if file_key == "bi" else "basic",
            "sales_start": "2026-07-02",
            "sales_end": "2026-07-08",
            "upload_xlsx": True,
            "return_mode": "ai_ready",
            **(request or {}),
        },
        result=result,
        data_scope="bi" if file_key == "bi" else "basic",
        site="US",
        split_files=split_files,
        elapsed_seconds=1.234,
    )


def test_ai_ready_bi_response_indexes_large_empty_and_filter_diagnostics(tmp_path: Path):
    asin = "B0TEST1234"
    sp_rows = [["channel", "asin_group", "search_term"]] + [["US", asin, f"term-{index}"] for index in range(501)]
    response = response_for_file(
        tmp_path,
        asin=asin,
        file_key="bi",
        sheets=[
            ("sales", [["ASIN", "orderQty"], [asin, 4]]),
            ("sp", sp_rows),
            ("deals", [["说明"], ["无数据"]]),
            ("inventory", [["ASIN", "stock"], [asin, 8]]),
        ],
    )

    assert response["metadata"]["protocol"] == "asin_data_ai_response"
    assert response["run"]["run_id"] == "run-ai-ready"
    assert response["split_file_urls"][asin]["bi"].endswith(f"{asin}-bi-live-data.xlsx")
    item = response["items"][0]
    assert item["artifacts"][0]["artifact_id"] == f"{asin}_bi_xlsx"
    datasets = {dataset["source_key"]: dataset for dataset in item["datasets"]}
    assert set(datasets) == {"sales_traffic", "sp_search_term", "deals", "turnover_inventory"}
    assert datasets["sp_search_term"]["row_count"] == 501
    assert len(datasets["sp_search_term"]["preview_rows"]) == 10
    assert datasets["sp_search_term"]["filter"]["effective_filter_verified"] is False
    assert {item["code"] for item in datasets["sp_search_term"]["diagnostics"]} >= {
        "LARGE_DATASET",
        "ASIN_FILTER_UNVERIFIED",
    }
    assert datasets["deals"]["row_count"] == 0
    assert datasets["deals"]["quality"]["empty"] is True
    assert "DATE_RANGE_MISSING" not in {item["code"] for item in response["diagnostics"]}


def test_ai_ready_basic_response_uses_stable_source_keys_by_position(tmp_path: Path):
    response = response_for_file(
        tmp_path,
        asin="B0TEST1234",
        file_key="basic",
        sheets=[
            ("listing-any-name", [["field", "value"], ["ASIN", "B0TEST1234"], ["title", "Bed"]]),
            ("crawler-any-name", [["ASIN", "title"], ["B0TEST1234", "Crawler title"]]),
            ("product-any-name", [["field", "value"], ["material", "metal"]]),
            ("bullets-any-name", [["index", "content"], [1, "easy assembly"], [2, "noise free"]]),
            ("images-any-name", [["type", "URL"], ["main", "https://example.com/main.jpg"]]),
            ("qa-any-name", [["question", "answer"], ["Q", "A"]]),
            ("reviews-any-name", [["rating", "content"], [5, "Good"]]),
        ],
    )

    source_keys = [dataset["source_key"] for dataset in response["items"][0]["datasets"]]
    assert source_keys == [
        "listing_basic",
        "crawler_details",
        "product_detail",
        "bullets",
        "image_links",
        "qa",
        "reviews",
    ]
    listing = response["items"][0]["datasets"][0]
    assert listing["row_count"] == 2
    assert len(listing["preview_rows"]) == 1


def test_ai_ready_flags_encoding_and_missing_bi_date_range(tmp_path: Path):
    response = response_for_file(
        tmp_path,
        asin="B0TEST1234",
        file_key="bi",
        sheets=[("骞垮憡", [["鎼滅储璇?", "value"], ["bed", 1]])],
        request={"sales_start": None, "sales_end": None},
    )

    dataset = response["items"][0]["datasets"][0]
    assert dataset["quality"]["encoding_suspected"] is True
    assert "ENCODING_SUSPECTED" in {item["code"] for item in dataset["diagnostics"]}
    assert "DATE_RANGE_MISSING" in {item["code"] for item in response["diagnostics"]}
