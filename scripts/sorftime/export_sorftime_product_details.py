"""Reconcile and export the latest stored Sorftime product details."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORE_FIELDS = [
    "asin", "site", "parent_asin", "title", "brand", "price", "coupon",
    "star_rating", "review_count", "node_id", "category", "top_category",
    "subcategory", "monthly_sales_volume", "monthly_sales_amount",
    "delivery_type", "seller_name", "online_date", "days_on_shelf",
    "variation_count", "fba_fee", "fbm_delivery_fee", "gross_profit",
    "gross_profit_rate", "a_plus", "package_size_cm", "weight_g",
    "run_id", "requested_at", "raw_path", "parsed_path",
]


def load_latest(index_path: Path) -> dict[tuple[str, str], sqlite3.Row]:
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT * FROM sorftime_runs
           WHERE tool = 'product_detail' AND status = 'success'
           ORDER BY requested_at DESC"""
    ).fetchall()
    connection.close()
    latest: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        latest.setdefault((row["asin"], row["site"]), row)
    return latest


def read_detail(row: sqlite3.Row) -> dict[str, Any]:
    parsed_path = Path(row["parsed_path"])
    content = json.loads(parsed_path.read_text(encoding="utf-8"))
    for value in content:
        if isinstance(value, dict) and isinstance(value.get("data"), dict):
            return value["data"]
    return {}


def export(queue_path: Path, index_path: Path, output_dir: Path) -> dict[str, int]:
    latest = load_latest(index_path)
    queue = sqlite3.connect(queue_path)
    queue.row_factory = sqlite3.Row
    items = queue.execute("SELECT asin, site, batch_id FROM queue_items ORDER BY rowid").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for item in items:
        key = (item["asin"], item["site"])
        row = latest.get(key)
        if row is None:
            missing.append(dict(item))
            queue.execute(
                "UPDATE queue_items SET status = 'failed', error = ?, updated_at = ? WHERE asin = ? AND site = ?",
                ("product_detail result not stored", now, *key),
            )
            continue
        data = read_detail(row)
        record = {**data, "asin": item["asin"], "site": item["site"],
                  "run_id": row["run_id"], "requested_at": row["requested_at"],
                  "raw_path": row["raw_path"], "parsed_path": row["parsed_path"]}
        records.append(record)
        queue.execute(
            "UPDATE queue_items SET status = 'success', run_dir = ?, error = NULL, updated_at = ? WHERE asin = ? AND site = ?",
            (str(Path(row["raw_path"]).parent.parent), now, *key),
        )
    queue.commit()
    queue.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "product_details.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (output_dir / "product_details.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CORE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    with (output_dir / "missing.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["asin", "site", "batch_id"])
        writer.writeheader()
        writer.writerows(missing)
    summary = {"total": len(items), "stored": len(records), "missing": len(missing)}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export stored Sorftime product details")
    parser.add_argument("--queue", type=Path, default=Path("test-data/sorftime/batch-queue/state.sqlite"))
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/product-details"))
    args = parser.parse_args()
    print(json.dumps(export(args.queue, args.index, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
