"""Persist a Sorftime MCP result for reproducible report analysis.

The input is a JSON-serialized MCP CallToolResult on stdin or in a file. Each
run stores the untouched result, best-effort parsed content, and a searchable
SQLite index. API keys are intentionally not accepted as input or written.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import sys
import time
from urllib.parse import unquote
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value[:80] or "unknown"


def _parse_content(result: dict[str, Any]) -> list[Any]:
    parsed: list[Any] = []
    for block in result.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        if not isinstance(text, str):
            continue
        try:
            parsed.append(json.loads(text))
            continue
        except json.JSONDecodeError:
            pass
        # Some tools return JSON embedded in explanatory text.
        for start, end in ((text.find("{"), text.rfind("}") + 1), (text.find("["), text.rfind("]") + 1)):
            if start >= 0 and end > start:
                try:
                    parsed.append(json.loads(text[start:end]))
                    break
                except json.JSONDecodeError:
                    continue
    return parsed


def _open_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS sorftime_runs (
            run_id TEXT PRIMARY KEY,
            requested_at TEXT NOT NULL,
            tool TEXT NOT NULL,
            asin TEXT,
            site TEXT,
            arguments_json TEXT NOT NULL,
            status TEXT NOT NULL,
            raw_path TEXT NOT NULL,
            parsed_path TEXT,
            error TEXT
        )"""
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_sorftime_runs_asin ON sorftime_runs(asin)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_sorftime_runs_tool ON sorftime_runs(tool)")
    connection.commit()
    return connection


def store(
    result: dict[str, Any],
    *,
    tool: str,
    arguments: dict[str, Any],
    output_dir: Path,
    asin: str | None = None,
    site: str | None = None,
    requested_at: str | None = None,
) -> Path:
    timestamp = requested_at or datetime.now(timezone.utc).isoformat()
    date_dir = output_dir / datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    run_id = f"{datetime.now(timezone.utc).strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = date_dir / f"{_safe(tool)}_{_safe(asin or 'no-asin')}_{run_id}"
    raw_dir = run_dir / "raw"
    parsed_dir = run_dir / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / "mcp_result.json"
    raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    parsed = _parse_content(result)
    parsed_path = parsed_dir / "content.json"
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "error" if result.get("isError") else "success"
    error = None
    if status == "error":
        error = json.dumps(result.get("content", []), ensure_ascii=False)
    manifest = {
        "run_id": run_id,
        "requested_at": timestamp,
        "tool": tool,
        "asin": asin,
        "site": site,
        "arguments": arguments,
        "status": status,
        "raw_path": str(raw_path),
        "parsed_path": str(parsed_path),
        "error": error,
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    index = _open_index(output_dir / "sorftime_runs.sqlite")
    index.execute(
        "INSERT INTO sorftime_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, timestamp, tool, asin, site, json.dumps(arguments, ensure_ascii=False), status, str(raw_path), str(parsed_path), error),
    )
    index.commit()
    index.close()
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Store a Sorftime MCP JSON result")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--asin")
    parser.add_argument("--site")
    parser.add_argument("--arguments", default="{}", help="JSON request arguments without credentials")
    parser.add_argument("--response-file", type=Path)
    parser.add_argument("--response-base64", help="Base64-encoded UTF-8 MCP JSON response")
    parser.add_argument("--response-urlencoded", help="URL-encoded UTF-8 MCP JSON response")
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/runs"))
    args = parser.parse_args()
    if args.response_base64:
        source = base64.b64decode(args.response_base64).decode("utf-8")
    elif args.response_urlencoded:
        source = unquote(args.response_urlencoded)
    else:
        source = args.response_file.read_text(encoding="utf-8") if args.response_file else sys.stdin.read()
    result = json.loads(source)
    arguments = json.loads(args.arguments)
    path = store(result, tool=args.tool, arguments=arguments, output_dir=args.output_dir, asin=args.asin, site=args.site)
    print(path)


if __name__ == "__main__":
    main()
