"""Merge stored Sorftime results for one ASIN/site into an analyzable run."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path


TOOL_FILES = {
    "product_detail": "product_detail.json",
    "product_reviews": "product_reviews_both.json",
    "product_reviews_both": "product_reviews_both.json",
    "product_reviews_negative": "product_reviews_negative.json",
    "product_traffic_terms": "product_traffic_terms.json",
    "competitor_product_keywords": "competitor_product_keywords.json",
    "product_customers_say": "product_customers_say.json",
    "product_trend_price": "product_trend_price.json",
    "product_trend_sales_volume": "product_trend_sales_volume.json",
    "product_variations": "product_variations.json",
    "category_keywords": "category_keywords.json",
}


def merge(index_path: Path, asin: str, site: str, output_dir: Path, run_analyzer: bool = True) -> Path:
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT * FROM sorftime_runs
           WHERE asin = ? AND site = ? AND status = 'success'
           ORDER BY requested_at DESC""",
        (asin, site),
    ).fetchall()
    connection.close()
    run_dir = output_dir / f"optimization_{asin}_{site}"
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    selected: set[str] = set()
    manifests = []
    for row in rows:
        filename = TOOL_FILES.get(row["tool"])
        if not filename or filename in selected:
            continue
        source = Path(row["raw_path"])
        if not source.exists():
            continue
        shutil.copyfile(source, raw_dir / filename)
        selected.add(filename)
        manifests.append({"tool": row["tool"], "run_id": row["run_id"], "source": str(source)})
    no_data_tasks = []
    no_data_path = output_dir.parent / "deep-queue" / "no_data_tasks.json"
    if no_data_path.exists():
        try:
            no_data_tasks = [
                row for row in json.loads(no_data_path.read_text(encoding="utf-8")).get("tasks", [])
                if row.get("asin") == asin and row.get("site") == site
            ]
        except (OSError, json.JSONDecodeError):
            pass
    (run_dir / "run.json").write_text(json.dumps({
        "asin": asin, "site": site, "tools": manifests, "no_data_tasks": no_data_tasks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if run_analyzer and (raw_dir / "product_detail.json").exists():
        subprocess.run(["python", "scripts/sorftime/analyze_sorftime_optimization_run.py", str(run_dir)], check=False)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge stored Sorftime results into one optimization run")
    parser.add_argument("asin")
    parser.add_argument("site")
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/runs"))
    parser.add_argument("--no-analyze", action="store_true")
    args = parser.parse_args()
    print(merge(args.index, args.asin, args.site, args.output_dir, not args.no_analyze))


if __name__ == "__main__":
    main()
