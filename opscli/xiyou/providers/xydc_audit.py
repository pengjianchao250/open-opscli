"""西柚 OpenAPI 调用审计日志。

日志采用 JSONL，记录用户查询条件、接口返回和供应商追踪字段，便于后续按
场景回放和优化。API Key 只保留账号名称和版本，绝不写入日志。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR


DEFAULT_AUDIT_PATH = CONFIG_DIR / "logs" / "xydc-openapi.jsonl"
AUDIT_PATH_ENV = "OPSCLI_XYDC_OPENAPI_AUDIT_LOG"
_SECRET_KEYS = {"api_key", "apikey", "authorization", "cookie", "token", "password", "secret"}


class XydcAuditLogger:
    """线程安全的西柚调用 JSONL 记录器。"""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.environ.get(AUDIT_PATH_ENV) or DEFAULT_AUDIT_PATH
        self.path = Path(configured).expanduser()
        self._lock = threading.Lock()

    def write_success(self, *, operation, endpoint, payload, result, attempts, duration_ms, credential) -> None:
        data = result if isinstance(result, dict) else {"result": result}
        self._write(
            {
                "event": "xydc_openapi_call",
                "status": "success",
                "operation": operation,
                "endpoint": endpoint,
                "query": _sanitize(payload, credential.secret),
                "result": _sanitize(data, credential.secret),
                "attempts": _sanitize(attempts, credential.secret),
                "duration_ms": duration_ms,
                "credential": credential.to_public_dict(),
                **_caller_context(),
            }
        )

    def write_failure(self, *, operation, endpoint, payload, error, attempts, duration_ms, credential) -> None:
        self._write(
            {
                "event": "xydc_openapi_call",
                "status": "failure",
                "operation": operation,
                "endpoint": endpoint,
                "query": _sanitize(payload, credential.secret),
                "error": _sanitize(error, credential.secret),
                "attempts": _sanitize(attempts, credential.secret),
                "duration_ms": duration_ms,
                "credential": credential.to_public_dict(),
                **_caller_context(),
            }
        )

    def _write(self, payload: dict[str, Any]) -> None:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
        try:
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            # 业务调用不能因为本地审计目录权限问题失败。
            return


def _sanitize(value: Any, secret: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_KEYS else _sanitize(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, secret) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _caller_context() -> dict[str, Any]:
    try:
        from opscli.mcp.context import get_current_client_name, get_current_user_email, get_current_user_id

        return {
            "user_id": get_current_user_id(),
            "user_email": get_current_user_email(),
            "client_name": get_current_client_name(),
        }
    except Exception:
        return {"user_id": None, "user_email": None, "client_name": None}
