"""Run the resumable Sorftime report queue through MCP."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import subprocess
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from create_sorftime_deep_tasks import create as create_tasks
from merge_sorftime_run import merge
from store_sorftime_mcp_result import store


TOOL_CALLS = {
    "product_reviews_both": ("product_reviews", lambda asin, site: {"asin": asin, "amz_site": site, "review_type": "Both"}),
    "product_reviews_negative": ("product_reviews", lambda asin, site: {"asin": asin, "amz_site": site, "review_type": "Negative"}),
    "product_traffic_terms": ("product_traffic_terms", lambda asin, site: {"asin": asin, "amz_site": site, "page": 1}),
    "competitor_product_keywords": ("competitor_product_keywords", lambda asin, site: {"asin": asin, "keyword_support_site": site, "page": 1}),
    "product_trend_price": ("product_trend", lambda asin, site: {"asin": asin, "amz_site": site, "product_trend_type": "Price"}),
    "product_trend_sales_volume": ("product_trend", lambda asin, site: {"asin": asin, "amz_site": site, "product_trend_type": "SalesVolume"}),
    "product_customers_say": ("product_customers_say", lambda asin, site: {"asin": asin, "site": site}),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_url(config: Path | None, codex_config: Path) -> str:
    url: Any = None
    if codex_config.exists():
        payload = tomllib.loads(codex_config.read_text(encoding="utf-8"))
        url = payload.get("mcp_servers", {}).get("sorftime", {}).get("url")
    if not url and config:
        payload = json.loads(config.read_text(encoding="utf-8"))
        url = payload.get("mcpServers", {}).get("sorftime", {}).get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("Sorftime MCP URL is missing from the configured Codex or JSON settings")
    return url


def read_tasks(path: Path, max_products: int) -> list[dict[str, str]]:
    rows = [row for row in json.loads(path.read_text(encoding="utf-8"))["tasks"] if row["status"] == "pending"]
    if not max_products:
        return rows
    products: list[tuple[str, str]] = []
    for row in rows:
        key = (row["asin"], row["site"])
        if key not in products:
            products.append(key)
    allowed = set(products[:max_products])
    return [row for row in rows if (row["asin"], row["site"]) in allowed]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_issue(path: Path, row: dict[str, Any]) -> None:
    payload = {"updated_at": now(), "issues": []}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    payload.setdefault("issues", []).append(row)
    payload["updated_at"] = now()
    payload["issue_count"] = len(payload["issues"])
    write_json(path, payload)


def defer_timeout(root: Path, asin: str, site: str, tool: str, reason: str) -> None:
    subprocess.run(
        ["python", "scripts/sorftime/mark_sorftime_timeout_tasks.py", "--asin", asin, "--site", site,
         "--tool", tool, "--reason", reason],
        check=False,
    )


def is_remote_timeout(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("timeout", "timed out", "502", "504", "bad gateway", "gateway timeout"))


def error_text(exc: BaseException) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, BaseExceptionGroup):
        parts.extend(error_text(child) for child in exc.exceptions)
    return " | ".join(parts)


def is_auth_error(message: str) -> bool:
    lowered = message.lower()
    return "authentication required" in lowered or "unauthorized" in lowered


async def call_tool(url: str, name: str, arguments: dict[str, Any], timeout: int) -> dict[str, Any]:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout)) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments, read_timeout_seconds=timedelta(seconds=timeout))
            return result.model_dump(mode="json", exclude_none=True)


async def run(args: argparse.Namespace) -> int:
    url = load_url(args.config, args.codex_config)
    summary = create_tasks(args.queue, args.index, args.deep_queue)
    tasks = read_tasks(args.deep_queue / "deep_tasks.json", args.max_products)
    progress_path = args.deep_queue / "runner_progress.json"
    issues_path = args.deep_queue / "error_tasks.json"
    started_at = now()
    completed = 0
    deferred = 0
    errors = 0
    current_product: tuple[str, str] | None = None

    print(json.dumps({"event": "start", "pending": len(tasks), "queue": summary}, ensure_ascii=False), flush=True)
    for position, task in enumerate(tasks, 1):
        asin, site, tool = task["asin"], task["site"], task["tool"]
        product = (asin, site)
        if current_product and product != current_product:
            merge(args.index, current_product[0], current_product[1], args.runs)
        current_product = product
        remote_name, argument_factory = TOOL_CALLS[tool]
        arguments = argument_factory(asin, site)
        event = {"asin": asin, "site": site, "tool": tool, "position": position, "total": len(tasks)}
        print(json.dumps({"event": "call", **event}, ensure_ascii=False), flush=True)
        try:
            result = await call_tool(url, remote_name, arguments, args.timeout)
            if result.get("isError"):
                message = json.dumps(result.get("content", []), ensure_ascii=False)
                raise RuntimeError(message)
            store(result, tool=tool, arguments=arguments, output_dir=args.runs, asin=asin, site=site)
            completed += 1
            print(json.dumps({"event": "success", **event}, ensure_ascii=False), flush=True)
        except Exception as exc:
            message = error_text(exc)
            issue = {**event, "occurred_at": now(), "error": message}
            if is_remote_timeout(message):
                defer_timeout(args.deep_queue, asin, site, tool, message[:500])
                deferred += 1
                print(json.dumps({"event": "deferred_timeout", **issue}, ensure_ascii=False), flush=True)
            else:
                append_issue(issues_path, issue)
                errors += 1
                print(json.dumps({"event": "error", **issue}, ensure_ascii=False), flush=True)
                if is_auth_error(message):
                    write_json(progress_path, {
                        "started_at": started_at, "updated_at": now(), "status": "stopped_auth_error",
                        "task_total": len(tasks), "task_position": position, "completed": completed,
                        "deferred_timeout": deferred, "errors": errors, "current": event,
                    })
                    return 2
        write_json(progress_path, {
            "started_at": started_at, "updated_at": now(), "task_total": len(tasks),
            "task_position": position, "completed": completed, "deferred_timeout": deferred,
            "errors": errors, "current": event,
        })

    if current_product:
        merge(args.index, current_product[0], current_product[1], args.runs)
    final = create_tasks(args.queue, args.index, args.deep_queue)
    subprocess.run(["python", "scripts/sorftime/audit_sorftime_complete_reports.py"], check=False)
    write_json(progress_path, {
        "started_at": started_at, "finished_at": now(), "status": "finished",
        "task_total": len(tasks), "completed": completed, "deferred_timeout": deferred,
        "errors": errors, "queue": final,
    })
    print(json.dumps({"event": "finished", "completed": completed, "deferred": deferred, "errors": errors, "queue": final}, ensure_ascii=False), flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pending Sorftime deep-report tasks serially")
    parser.add_argument("--config", type=Path, default=Path("test-data/sorftime/mcp.example.json"))
    parser.add_argument("--codex-config", type=Path, default=Path.home() / ".codex" / "config.toml")
    parser.add_argument("--queue", type=Path, default=Path("test-data/sorftime/batch-queue/state.sqlite"))
    parser.add_argument("--index", type=Path, default=Path("test-data/sorftime/runs/sorftime_runs.sqlite"))
    parser.add_argument("--runs", type=Path, default=Path("test-data/sorftime/runs"))
    parser.add_argument("--deep-queue", type=Path, default=Path("test-data/sorftime/deep-queue"))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-products", type=int, default=0, help="Process at most N products; zero means all")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
