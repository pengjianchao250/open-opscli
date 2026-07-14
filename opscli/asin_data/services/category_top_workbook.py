"""Render the internal category Top ASIN workbook."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from opscli.asin_data.services.split_package_builder import (
    collect_headers,
    new_workbook,
    remove_crawler_listing_conflict_fields,
    save_workbook,
    write_rows,
)


SHEET_CATEGORY_TOP = "类目top10"
SHEET_LISTING = "刊登数据"
SHEET_CRAWLER = "爬虫数据"
ITEM_HIGHLIGHT = "商品亮点"


def write_category_top_workbook(path: Path, document: Mapping[str, Any]) -> None:
    """Write one row per Top ASIN into the fixed three-sheet workbook."""
    top_rows = _one_row_per_item(document, "category_top")
    listing_rows = _one_row_per_item(document, "listing_basic")
    crawler_rows = remove_crawler_listing_conflict_fields(
        _one_row_per_item(document, "crawler_details")
    )
    listing_headers = collect_headers(listing_rows)
    if ITEM_HIGHLIGHT not in listing_headers:
        listing_headers.append(ITEM_HIGHLIGHT)

    workbook = new_workbook()
    write_rows(workbook.create_sheet(SHEET_CATEGORY_TOP), top_rows)
    write_rows(workbook.create_sheet(SHEET_LISTING), listing_rows, listing_headers)
    write_rows(workbook.create_sheet(SHEET_CRAWLER), crawler_rows)
    save_workbook(workbook, path)


def _one_row_per_item(document: Mapping[str, Any], source_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    items = document.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        asin = str(item.get("asin") or "").strip()
        source_rows = _dataset_rows(item, source_key)
        row = dict(source_rows[0]) if source_rows else {}
        if asin:
            row.setdefault("ASIN", asin)
        if source_key == "listing_basic":
            row[ITEM_HIGHLIGHT] = _item_highlight(row)
        rows.append(row)
    return rows


def _dataset_rows(item: Mapping[str, Any], source_key: str) -> list[dict[str, Any]]:
    datasets = item.get("datasets")
    for dataset in datasets if isinstance(datasets, list) else []:
        if not isinstance(dataset, dict) or dataset.get("source_key") != source_key:
            continue
        rows = dataset.get("rows")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return []


def _item_highlight(row: Mapping[str, Any]) -> Any:
    for key in (ITEM_HIGHLIGHT, "title_differentiation.value", "title_differentiation"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return ""
