"""Flatten an Amazon listing response for Sorftime analysis.

The source response is loaded once (the current response is about 11 MB), then
all derived files are written incrementally.  Downstream jobs can read the
NDJSON one record at a time or query the SQLite database without loading the
whole response.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


LISTING_COLUMNS = (
    "record_id",
    "record_type",
    "parent_record_id",
    "parent_asin",
    "asin",
    "sku",
    "item_sku",
    "item_name",
    "channel_id",
    "channel_name",
    "site_name",
    "sales_team_name",
    "sales_team_user_name",
    "country_iso_code",
    "marketplace_id",
    "amazon_status",
    "quantity",
    "total_quantity",
    "standard_price",
    "sale_price",
    "currency",
    "feed_product_type",
    "asin_url",
    "raw_json",
)


def _number(value: Any) -> int | float | None:
    if value in (None, "", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _value(record: dict[str, Any], parent: dict[str, Any], key: str) -> Any:
    """Use child data first and parent context as a fallback."""
    value = record.get(key)
    return parent.get(key) if value in (None, "") else value


def _flatten_rows(source_rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for source_index, parent in enumerate(source_rows):
        parent_id = parent.get("id")
        parent_asin = parent.get("asin")
        yield _normalise(parent, parent, "parent", parent_id, parent_asin, source_index)

        for child in parent.get("childlist") or []:
            yield _normalise(child, parent, "child", parent_id, parent_asin, source_index)


def _normalise(
    record: dict[str, Any],
    parent: dict[str, Any],
    record_type: str,
    parent_id: Any,
    parent_asin: Any,
    source_index: int,
) -> dict[str, Any]:
    row = {
        "record_id": str(record.get("id") or f"source-{source_index}-{record_type}"),
        "record_type": record_type,
        "parent_record_id": str(parent_id) if record_type == "child" and parent_id else None,
        "parent_asin": parent_asin if record_type == "child" else None,
        "asin": record.get("asin"),
        "sku": record.get("sku"),
        "item_sku": record.get("item_sku"),
        "item_name": record.get("item_name"),
        "channel_id": _number(_value(record, parent, "channel_id")),
        "channel_name": _value(record, parent, "channel_name"),
        "site_name": _value(record, parent, "site_name"),
        "sales_team_name": _value(record, parent, "sales_team_name"),
        "sales_team_user_name": _value(record, parent, "sales_team_user_name"),
        "country_iso_code": _value(record, parent, "country_iso_code"),
        "marketplace_id": _value(record, parent, "marketplace_id"),
        "amazon_status": _value(record, parent, "amazon_status"),
        "quantity": _number(record.get("quantity")),
        "total_quantity": _number(record.get("total_quantity")),
        "standard_price": _number(record.get("standard_price")),
        "sale_price": _number(record.get("sale_price")),
        "currency": _value(record, parent, "currency"),
        "feed_product_type": _value(record, parent, "feed_product_type"),
        "asin_url": record.get("asin_url"),
        "source_index": source_index,
        "raw_json": json.dumps(record, ensure_ascii=False, separators=(",", ":")),
    }
    return row


def _create_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE listings (
            record_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            parent_record_id TEXT,
            parent_asin TEXT,
            asin TEXT,
            sku TEXT,
            item_sku TEXT,
            item_name TEXT,
            channel_id INTEGER,
            channel_name TEXT,
            site_name TEXT,
            sales_team_name TEXT,
            sales_team_user_name TEXT,
            country_iso_code TEXT,
            marketplace_id TEXT,
            amazon_status TEXT,
            quantity REAL,
            total_quantity REAL,
            standard_price REAL,
            sale_price REAL,
            currency TEXT,
            feed_product_type TEXT,
            asin_url TEXT,
            raw_json TEXT NOT NULL
        )"""
    )
    connection.execute("CREATE INDEX idx_listings_asin ON listings(asin)")
    connection.execute("CREATE INDEX idx_listings_channel ON listings(channel_name)")
    connection.execute("CREATE INDEX idx_listings_type ON listings(record_type)")
    return connection


def process(source: Path, output_dir: Path) -> dict[str, int]:
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    source_rows = payload.get("data", {}).get("data", [])
    output_dir.mkdir(parents=True, exist_ok=True)

    ndjson_path = output_dir / f"{source.stem}_flat.ndjson"
    csv_path = output_dir / f"{source.stem}_asins.csv"
    asin_txt_path = output_dir / f"{source.stem}_asins.txt"
    sqlite_path = output_dir / f"{source.stem}.sqlite"
    for path in (ndjson_path, csv_path, asin_txt_path, sqlite_path):
        if path.exists():
            path.unlink()

    asin_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "record_types": set(), "parent_asins": set(), "item_skus": set()}
    )
    connection = _create_database(sqlite_path)
    insert_sql = f"INSERT INTO listings ({','.join(LISTING_COLUMNS)}) VALUES ({','.join('?' for _ in LISTING_COLUMNS)})"
    row_count = child_count = 0
    with ndjson_path.open("w", encoding="utf-8", newline="\n") as ndjson:
        for row in _flatten_rows(source_rows):
            row_count += 1
            child_count += row["record_type"] == "child"
            ndjson.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            connection.execute(insert_sql, [row.get(column) for column in LISTING_COLUMNS])
            asin = row.get("asin")
            if asin:
                stats = asin_stats[asin]
                stats["count"] += 1
                stats["record_types"].add(row["record_type"])
                if row.get("parent_asin"):
                    stats["parent_asins"].add(row["parent_asin"])
                if row.get("item_sku"):
                    stats["item_skus"].add(row["item_sku"])
    connection.commit()
    connection.close()

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("asin", "occurrences", "record_types", "parent_asins", "item_skus"))
        writer.writeheader()
        for asin in sorted(asin_stats):
            stats = asin_stats[asin]
            writer.writerow(
                {
                    "asin": asin,
                    "occurrences": stats["count"],
                    "record_types": ";".join(sorted(stats["record_types"])),
                    "parent_asins": ";".join(sorted(stats["parent_asins"])),
                    "item_skus": ";".join(sorted(stats["item_skus"])),
                }
            )

    asin_txt_path.write_text("\n".join(sorted(asin_stats)) + "\n", encoding="utf-8")

    manifest = {
        "source": str(source),
        "top_level_rows": len(source_rows),
        "flattened_rows": row_count,
        "child_rows": child_count,
        "unique_asins": len(asin_stats),
        "files": {
            "asins_txt": str(asin_txt_path),
            "asins_csv": str(csv_path),
            "flat_ndjson": str(ndjson_path),
            "sqlite": str(sqlite_path),
        },
    }
    (output_dir / f"{source.stem}_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"top_level_rows": len(source_rows), "flattened_rows": row_count, "child_rows": child_count, "unique_asins": len(asin_stats)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten Amazon listing JSON into ASIN CSV, NDJSON, and SQLite")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output_dir = args.output_dir or args.source.parent / f"{args.source.stem}_processed"
    print(json.dumps(process(args.source, output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
