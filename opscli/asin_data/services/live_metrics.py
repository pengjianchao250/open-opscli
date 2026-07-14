"""ASIN 实时取数本地指标日志。

本模块只写本地 JSONL 指标，不依赖远端服务，避免指标链路影响取数主流程。
后续如需入库，可由服务端定时消费该 JSONL 文件。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENV_ASIN_DATA_METRICS_PATH = "OPSCLI_ASIN_DATA_METRICS_PATH"
ENV_ASIN_DATA_METRICS_DISABLED = "OPSCLI_ASIN_DATA_METRICS_DISABLED"
DEFAULT_METRICS_PATH = "output/asin-data/metrics/live-data-metrics.jsonl"

_write_lock = threading.Lock()


def append_live_data_metric(event: dict[str, Any]) -> None:
    """追加一条 ASIN 实时取数指标。

    Args:
        event: 已脱敏的指标事件。函数会补齐 `timestamp` 字段，并以 JSONL 写入本地文件。
    """
    if os.getenv(ENV_ASIN_DATA_METRICS_DISABLED) == "1":
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    path = Path(os.getenv(ENV_ASIN_DATA_METRICS_PATH) or DEFAULT_METRICS_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _write_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        # 指标日志不能影响取数主流程。
        return


def build_live_data_success_metric(
    *,
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """从成功响应中提取耗时、source 行数、诊断码等指标。"""
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "tool": tool,
        "status": "success",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "request": _sanitize_request(request),
        "summary": data.get("summary"),
        "output_dir": _nested_get(data, ("run", "output_dir")) or data.get("output_dir"),
        "asin_count": len(items) if items else _summary_count(data, "asin_count"),
        "source_row_counts": _source_row_counts(items),
        "diagnostic_codes": _diagnostic_codes(data),
        "artifact_uri_count": _artifact_uri_count(items, data),
    }


def build_live_data_error_metric(
    *,
    tool: str,
    request: dict[str, Any],
    error: dict[str, Any] | None,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """构造失败指标，保留错误码但不写入敏感凭据。"""
    return {
        "tool": tool,
        "status": "error",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "request": _sanitize_request(request),
        "error_code": (error or {}).get("code"),
        "error_message": (error or {}).get("message"),
    }


def build_fetch_file_success_metric(
    *,
    request: dict[str, Any],
    response: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """从 fetch-file 成功响应中提取文件粒度指标。"""
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    return {
        "tool": "asin_data_fetch_file",
        "status": "success",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "request": _sanitize_request(request),
        "asin_count": 1,
        "source_row_counts": _fetch_file_row_counts(data),
        "diagnostic_codes": [],
        "artifact_uri_count": 1 if data.get("file_url") else 0,
    }


def _sanitize_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in request.items()
        if key not in {"jwt", "session_id"} and value not in (None, "")
    }


def _summary_count(data: dict[str, Any], key: str) -> int:
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    value = summary.get(key)
    return value if isinstance(value, int) else 0


def _source_row_counts(items: list[Any]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        asin = str(item.get("asin") or "")
        datasets = item.get("datasets") if isinstance(item.get("datasets"), list) else []
        result[asin] = {
            str(dataset.get("source_key")): int(dataset.get("row_count") or 0)
            for dataset in datasets
            if isinstance(dataset, dict) and dataset.get("source_key")
        }
    return result


def _diagnostic_codes(data: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for diag in data.get("diagnostics") or []:
        if isinstance(diag, dict):
            diagnostics.append(_diag_item(diag))
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        asin = item.get("asin")
        for diag in item.get("diagnostics") or []:
            if isinstance(diag, dict):
                merged = _diag_item(diag)
                merged["asin"] = asin
                diagnostics.append(merged)
        for dataset in item.get("datasets") or []:
            if not isinstance(dataset, dict):
                continue
            for diag in dataset.get("diagnostics") or []:
                if isinstance(diag, dict):
                    merged = _diag_item(diag)
                    merged["asin"] = asin
                    merged["source_key"] = dataset.get("source_key")
                    diagnostics.append(merged)
    return diagnostics


def _diag_item(diag: dict[str, Any]) -> dict[str, Any]:
    return {
        "level": diag.get("level"),
        "code": diag.get("code"),
        "source_key": diag.get("source_key"),
    }


def _artifact_uri_count(items: list[Any], data: dict[str, Any]) -> int:
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        for artifact in item.get("artifacts") or []:
            if isinstance(artifact, dict) and artifact.get("uri"):
                count += 1
    if count:
        return count
    urls = data.get("split_file_urls") if isinstance(data.get("split_file_urls"), dict) else {}
    return sum(len(files) for files in urls.values() if isinstance(files, dict))


def _fetch_file_row_counts(data: dict[str, Any]) -> dict[str, dict[str, int]]:
    asin = str(data.get("asin") or "")
    file_key = str(data.get("file_key") or "")
    content = data.get("content")
    if isinstance(content, dict):
        return {
            asin: {
                f"{file_key}:{sheet}": max(len(rows) - 1, 0) if isinstance(rows, list) else 0
                for sheet, rows in content.items()
            }
        }
    if isinstance(content, str):
        return {asin: {file_key: len(content.splitlines())}}
    return {asin: {file_key: 0}}


def _nested_get(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
