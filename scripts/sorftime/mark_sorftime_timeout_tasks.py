"""Manage deferred and terminal Sorftime timeout tasks."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Defer Sorftime timeout tasks")
    parser.add_argument("--tasks", type=Path, default=Path("test-data/sorftime/deep-queue/deep_tasks.json"))
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/deep-queue"))
    parser.add_argument("--asin", action="append", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--tool", action="append", required=True)
    parser.add_argument("--clear", action="store_true", help="Remove the specified tasks from the deferred list")
    parser.add_argument("--finalize-no-data", action="store_true", help="Classify repeated timeouts as terminal no-data tasks")
    parser.add_argument("--reason", default="远端 MCP 超时或网关 504，主队列完成后再重试")
    args = parser.parse_args()

    keys = {(asin, args.site, tool) for asin in args.asin for tool in args.tool}
    payload = {"created_at": datetime.now(timezone.utc).isoformat(), "reason": args.reason, "tasks": []}
    path = args.output_dir / "timeout_tasks.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    existing = {(x["asin"], x["site"], x["tool"]): x for x in payload.get("tasks", [])}
    if args.finalize_no_data:
        no_data_path = args.output_dir / "no_data_tasks.json"
        no_data_payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "tasks": []}
        if no_data_path.exists():
            try:
                no_data_payload = json.loads(no_data_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        no_data = {(x["asin"], x["site"], x["tool"]): x for x in no_data_payload.get("tasks", [])}
        for asin, site, tool in sorted(keys):
            previous = existing.pop((asin, site, tool), {})
            no_data[(asin, site, tool)] = {
                "asin": asin,
                "site": site,
                "tool": tool,
                "status": "no_data_after_timeout",
                "reason": args.reason,
                "last_timeout_reason": previous.get("reason"),
                "finalized_at": datetime.now(timezone.utc).isoformat(),
            }
        no_data_payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "task_count": len(no_data),
            "tasks": list(no_data.values()),
        }
        no_data_path.write_text(json.dumps(no_data_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with (args.output_dir / "no_data_tasks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            fields = ["asin", "site", "tool", "status", "reason", "last_timeout_reason", "finalized_at"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader(); writer.writerows(no_data_payload["tasks"])
    elif args.clear:
        for key in keys:
            existing.pop(key, None)
    else:
        for asin, site, tool in sorted(keys):
            existing[(asin, site, tool)] = {"asin": asin, "site": site, "tool": tool, "reason": args.reason, "marked_at": datetime.now(timezone.utc).isoformat()}
    payload["tasks"] = list(existing.values())
    payload["task_count"] = len(payload["tasks"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "timeout_tasks.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["asin", "site", "tool", "reason", "marked_at"])
        writer.writeheader(); writer.writerows(payload["tasks"])
    print(json.dumps({
        "deferred_timeout_count": len(payload["tasks"]),
        "no_data_after_timeout_count": len(no_data_payload["tasks"]) if args.finalize_no_data else None,
        "path": str(path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
