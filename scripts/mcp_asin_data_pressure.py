"""ASIN MCP 取数固定压测脚本。

直接调用 MCP tool 函数，覆盖 basic、listing_basic、bi 和 rufus 四条取数链路。
用于服务端部署前后做稳定性巡检。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from opscli.mcp.tools.asin_data import asin_data_fetch_file, asin_data_live_data


DEFAULT_INPUT = "output/asin-data/perf-asins-20260709.csv"
DEFAULT_OUTPUT_ROOT = "output/asin-data/mcp-load-tests"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ASIN MCP pressure checks.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CSV input with asin/site columns.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_ROOT, help="Directory for raw and summary JSON files.")
    parser.add_argument("--run-id", default=None, help="Optional stable run id.")
    parser.add_argument("--sales-start", default=None, help="BI start date, YYYY-MM-DD.")
    parser.add_argument("--sales-end", default=None, help="BI end date, YYYY-MM-DD.")
    parser.add_argument("--rufus-concurrency", type=int, default=4, help="Concurrent fetch-file rufus requests.")
    parser.add_argument("--no-upload-xlsx", action="store_true", help="Disable xlsx upload for live-data checks.")
    return parser.parse_args()


def _read_asins(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = []
    for row in rows:
        asin = str(row.get("asin") or "").strip().upper()
        if not asin:
            continue
        result.append({"asin": asin, "site": str(row.get("site") or "US").strip().upper()})
    return result


def _default_date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _summarize_live_response(scope: str, response: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    rows = []
    for item in items:
        artifacts = item.get("artifacts") if isinstance(item, dict) else []
        datasets = item.get("datasets") if isinstance(item, dict) else []
        diagnostics = _item_diagnostics(item if isinstance(item, dict) else {})
        rows.append(
            {
                "asin": item.get("asin") if isinstance(item, dict) else None,
                "site": item.get("site") if isinstance(item, dict) else None,
                "status": item.get("status") if isinstance(item, dict) else None,
                "artifact_uri_ok": all(bool(a.get("uri")) for a in artifacts if isinstance(a, dict)),
                "source_row_counts": {
                    dataset.get("source_key"): dataset.get("row_count")
                    for dataset in datasets
                    if isinstance(dataset, dict)
                },
                "error_codes": [d.get("code") for d in diagnostics if d.get("level") == "error"],
                "warning_codes": sorted({d.get("code") for d in diagnostics if d.get("level") == "warning"}),
            }
        )
    return {
        "scope": scope,
        "success": bool(response.get("success")),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "summary": data.get("summary"),
        "item_count": len(items),
        "items": rows,
        "error": response.get("error"),
    }


def _item_diagnostics(item: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = [d for d in item.get("diagnostics") or [] if isinstance(d, dict)]
    for dataset in item.get("datasets") or []:
        if isinstance(dataset, dict):
            diagnostics.extend(d for d in dataset.get("diagnostics") or [] if isinstance(d, dict))
    return diagnostics


async def _run_live(scope: str, *, input_path: str, output_dir: Path, sales_start: str | None, sales_end: str | None, upload_xlsx: bool, run_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    kwargs: dict[str, Any] = {
        "input_path": input_path,
        "site": "US",
        "data_scope": scope,
        "upload_xlsx": upload_xlsx,
        "return_mode": "ai_ready",
        "run_id": run_id,
    }
    if scope == "bi":
        kwargs["sales_start"] = sales_start
        kwargs["sales_end"] = sales_end
    response = await asin_data_live_data(**kwargs)
    elapsed = time.perf_counter() - started
    (output_dir / f"{scope}-raw.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    summary = _summarize_live_response(scope, response, elapsed)
    (output_dir / f"{scope}-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


async def _run_rufus(rows: list[dict[str, str]], *, output_dir: Path, concurrency: int) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(max(concurrency, 1))
    results = []

    async def fetch_one(row: dict[str, str]) -> dict[str, Any]:
        started = time.perf_counter()
        async with semaphore:
            response = await asin_data_fetch_file(row["asin"], "rufus", site=row["site"])
        return {
            "asin": row["asin"],
            "site": row["site"],
            "success": bool(response.get("success")),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": response.get("error"),
            "has_url": bool((response.get("data") or {}).get("file_url")) if isinstance(response.get("data"), dict) else False,
        }

    results = await asyncio.gather(*(fetch_one(row) for row in rows))
    summary = {
        "scope": "rufus",
        "success": all(item["success"] for item in results),
        "item_count": len(results),
        "failed_count": sum(1 for item in results if not item["success"]),
        "items": results,
    }
    (output_dir / "rufus-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


async def _main() -> int:
    args = _parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"input file not found: {input_path}")
    sales_start, sales_end = (args.sales_start, args.sales_end) if args.sales_start and args.sales_end else _default_date_range()
    run_id = args.run_id or f"mcp-asin-pressure-{int(time.time())}"
    output_dir = Path(args.output_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_asins(input_path)
    summaries = []
    upload_xlsx = not args.no_upload_xlsx
    summaries.append(await _run_live("basic", input_path=str(input_path), output_dir=output_dir, sales_start=None, sales_end=None, upload_xlsx=upload_xlsx, run_id=f"{run_id}-basic"))
    summaries.append(await _run_live("listing_basic", input_path=str(input_path), output_dir=output_dir, sales_start=None, sales_end=None, upload_xlsx=upload_xlsx, run_id=f"{run_id}-listing-basic"))
    summaries.append(await _run_live("bi", input_path=str(input_path), output_dir=output_dir, sales_start=sales_start, sales_end=sales_end, upload_xlsx=upload_xlsx, run_id=f"{run_id}-bi"))
    summaries.append(await _run_rufus(rows, output_dir=output_dir, concurrency=args.rufus_concurrency))
    combined = {
        "input": str(input_path),
        "run_id": run_id,
        "output_dir": str(output_dir),
        "sales_start": sales_start,
        "sales_end": sales_end,
        "summaries": summaries,
    }
    combined_path = output_dir / "combined-summary.json"
    combined_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": all(item.get("success") for item in summaries), "summary_path": str(combined_path)}, ensure_ascii=False))
    return 0 if all(item.get("success") for item in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
