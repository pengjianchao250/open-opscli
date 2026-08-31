"""Audit queued ASIN/site records for the required Sorftime data package."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


REQUIRED = [
    "product_detail", "product_reviews_both", "product_reviews_negative",
    "product_traffic_terms", "competitor_product_keywords",
    "product_trend_price", "product_trend_sales_volume", "product_customers_say",
]


def load_no_data(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {(row["asin"], row["site"], row["tool"]) for row in payload.get("tasks", [])}


def audit(queue: Path, index: Path, output: Path, no_data_path: Path) -> dict[str, int]:
    q = sqlite3.connect(queue)
    items = q.execute("SELECT asin, site, batch_id FROM queue_items ORDER BY rowid").fetchall()
    q.close()
    db = sqlite3.connect(index)
    done = set(db.execute("SELECT asin, site, tool FROM sorftime_runs WHERE status = 'success'"))
    db.close()
    no_data = load_no_data(no_data_path)
    rows = []
    for asin, site, batch_id in items:
        no_data_tools = [tool for tool in REQUIRED if (asin, site, tool) in no_data and (asin, site, tool) not in done]
        missing = [tool for tool in REQUIRED if (asin, site, tool) not in done and (asin, site, tool) not in no_data]
        rows.append({
            "asin": asin, "site": site, "batch_id": batch_id,
            "missing_count": len(missing), "missing_tools": ",".join(missing),
            "no_data_count": len(no_data_tools), "no_data_tools": ",".join(no_data_tools),
            "complete": not missing, "complete_with_no_data": not missing and bool(no_data_tools),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    summary = {
        "items": len(rows),
        "complete": sum(x["complete"] for x in rows),
        "complete_with_data": sum(x["complete"] and not x["complete_with_no_data"] for x in rows),
        "complete_with_no_data": sum(x["complete_with_no_data"] for x in rows),
        "incomplete": sum(not x["complete"] for x in rows),
    }
    output.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit complete Sorftime optimization packages")
    parser.add_argument("--queue", type=Path, default=Path("test-data/sorftime/batch-queue/state.sqlite"))
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("test-data/sorftime/deep-queue/completeness.csv"))
    parser.add_argument("--no-data", type=Path, default=Path("test-data/sorftime/deep-queue/no_data_tasks.json"))
    args = parser.parse_args()
    print(json.dumps(audit(args.queue, args.index, args.output, args.no_data), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
