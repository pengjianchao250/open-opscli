"""Create the resumable per-ASIN Sorftime task manifest."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TASKS = [
    ("product_reviews_both", "reviews_both"),
    ("product_reviews_negative", "reviews_negative"),
    ("product_traffic_terms", "traffic_terms"),
    ("competitor_product_keywords", "competitor_keywords"),
    ("product_trend_price", "trend_price"),
    ("product_trend_sales_volume", "trend_sales_volume"),
    ("product_customers_say", "customers_say"),
]


def load_deferred(output: Path) -> set[tuple[str, str, str]]:
    """Keep known remote timeouts out of the main pending worklist."""
    path = output / "timeout_tasks.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {(row["asin"], row["site"], row["tool"]) for row in payload.get("tasks", [])}


def load_no_data(output: Path) -> set[tuple[str, str, str]]:
    path = output / "no_data_tasks.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {(row["asin"], row["site"], row["tool"]) for row in payload.get("tasks", [])}


def existing(index: Path) -> set[tuple[str, str, str]]:
    if not index.exists():
        return set()
    connection = sqlite3.connect(index)
    rows = connection.execute("SELECT asin, site, tool FROM sorftime_runs WHERE status = 'success'").fetchall()
    connection.close()
    return set(rows)


def create(queue: Path, index: Path, output: Path) -> dict[str, int]:
    connection = sqlite3.connect(queue)
    rows = connection.execute("SELECT asin, site, batch_id FROM queue_items ORDER BY rowid").fetchall()
    connection.close()
    done = existing(index)
    deferred = load_deferred(output)
    no_data = load_no_data(output)
    tasks = []
    for asin, site, batch_id in rows:
        for tool, task_name in TASKS:
            tasks.append({
                "asin": asin, "site": site, "batch_id": batch_id, "tool": tool,
                "task": task_name,
                "status": (
                    "success" if (asin, site, tool) in done
                    else "no_data_after_timeout" if (asin, site, tool) in no_data
                    else "deferred_timeout" if (asin, site, tool) in deferred
                    else "pending"
                ),
            })
    output.mkdir(parents=True, exist_ok=True)
    (output / "deep_tasks.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_count": len(tasks),
        "pending_count": sum(x["status"] == "pending" for x in tasks),
        "deferred_timeout_count": sum(x["status"] == "deferred_timeout" for x in tasks),
        "no_data_after_timeout_count": sum(x["status"] == "no_data_after_timeout" for x in tasks),
        "task_types": [x[0] for x in TASKS], "tasks": tasks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "deep_tasks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["asin", "site", "batch_id", "tool", "task", "status"])
        writer.writeheader(); writer.writerows(tasks)
    return {
        "items": len(rows),
        "task_count": len(tasks),
        "pending_count": sum(x["status"] == "pending" for x in tasks),
        "deferred_timeout_count": sum(x["status"] == "deferred_timeout" for x in tasks),
        "no_data_after_timeout_count": sum(x["status"] == "no_data_after_timeout" for x in tasks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create deep Sorftime task manifest")
    parser.add_argument("--queue", type=Path, default=Path("test-data/sorftime/batch-queue/state.sqlite"))
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/deep-queue"))
    args = parser.parse_args()
    print(json.dumps(create(args.queue, args.index, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
