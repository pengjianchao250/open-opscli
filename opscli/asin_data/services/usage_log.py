"""ASIN Data CLI 本地请求审计日志。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from opscli.config import CONFIG_DIR


ENV_USAGE_LOG_PATH = "OPSCLI_ASIN_DATA_USAGE_LOG_PATH"
ENV_USAGE_LOG_DISABLED = "OPSCLI_ASIN_DATA_USAGE_LOG_DISABLED"
DEFAULT_USAGE_LOG_PATH = CONFIG_DIR / "asin-data" / "usage.jsonl"

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "jwt",
    "password",
    "secret",
    "session_id",
    "token",
}
_write_lock = threading.Lock()


def append_usage_event(
    *,
    command: str,
    params: Mapping[str, Any],
    status: str,
    elapsed_seconds: float,
    error: Mapping[str, Any] | None = None,
    path: str | Path | None = None,
) -> None:
    """追加一条脱敏审计记录；日志异常不得影响取数主流程。"""
    if os.getenv(ENV_USAGE_LOG_DISABLED) == "1":
        return
    target = Path(path or os.getenv(ENV_USAGE_LOG_PATH) or DEFAULT_USAGE_LOG_PATH)
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "status": status,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "params": _sanitize(params),
    }
    if error:
        event["error"] = _sanitize(error)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, default=str)
        with _write_lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        return


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    normalized_key = (key or "").strip().lower().replace("-", "_")
    if normalized_key in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value
