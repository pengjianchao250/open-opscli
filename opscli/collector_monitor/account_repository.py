"""Collector Monitor 账号健康与当日额度的严格只读查询。"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_MAX_ROWS = 500
_MAX_ACTIVE_TASKS_PER_ACCOUNT = 20
_MAX_BOUND_USERS_PER_ACCOUNT = 20
_ACCOUNT_TABLE = "seller_sprite_dedicated_accounts"
_BINDING_TABLE = "seller_sprite_user_account_bindings"
_TASK_TABLE = "seller_sprite_task_queue"
_ACCOUNT_EVENT_TABLE = "seller_sprite_account_events"
_QUARANTINE_TABLE = "seller_sprite_account_quarantine"
_QUOTA_TABLE = "mcp_quota_daily"

try:
    _SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    _SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class AccountMonitorRepository:
    """从 SellerSprite 与 MCP SQLite 文件读取低敏运维摘要。"""

    def __init__(
        self,
        *,
        queue_db_path: str | Path,
        binding_db_path: str | Path,
        quota_db_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.queue_db_path = Path(queue_db_path)
        self.binding_db_path = Path(binding_db_path)
        self.quota_db_path = Path(quota_db_path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def accounts(self, *, limit: int = 100) -> dict[str, Any]:
        """返回执行账号、绑定用户、占用和最近结果的脱敏摘要。"""
        safe_limit = _bounded_limit(limit)
        try:
            bindings = self._read_bindings()
            execution = self._read_execution_state()
        except (OSError, sqlite3.Error, ValueError):
            return {
                "source": {
                    "ready": False,
                    "error": {
                        "code": "account_source_unavailable",
                        "message": "SellerSprite 账号监控数据源不可用",
                    },
                },
                "accounts": [],
            }

        keys = set(bindings) | set(execution)
        accounts: list[dict[str, Any]] = []
        for account_key in keys:
            binding = bindings.get(account_key, {})
            state = execution.get(account_key, {})
            last_success = state.get("last_success")
            last_failure = state.get("last_failure")
            quarantined = bool(state.get("quarantined"))
            health = _account_health(
                last_success=last_success,
                last_failure=last_failure,
                quarantined=quarantined,
            )
            accounts.append(
                {
                    "identity": account_key[:12],
                    "name": _public_account_name(
                        str(binding.get("name") or state.get("name") or "未命名账号")
                    ),
                    "username": binding.get("username") or state.get("username") or "—",
                    "bound_users": list(binding.get("bound_users") or []),
                    "health": health,
                    "active_task_count": int(state.get("active_task_count") or 0),
                    "active_tasks": list(state.get("active_tasks") or []),
                    "last_success": last_success,
                    "last_failure": last_failure,
                }
            )
        accounts.sort(key=lambda item: (str(item["name"]).casefold(), item["identity"]))
        return {
            "source": {"ready": True, "error": None},
            "accounts": accounts[:safe_limit],
        }

    def usage_today(self, *, limit: int = 100) -> dict[str, Any]:
        """返回北京时间当日已落表的计费成功与已退款失败次数。"""
        safe_limit = _bounded_limit(limit)
        day = self.clock().astimezone(_SHANGHAI_TZ).strftime("%Y%m%d")
        try:
            with self._read_connection(self.quota_db_path) as conn:
                self._validate_schema(
                    conn,
                    {
                        _QUOTA_TABLE: {
                            "service",
                            "day",
                            "identity_hash",
                            "identity_type",
                            "identity_key",
                            "calls",
                            "failures",
                            "limit_count",
                            "reset_at",
                        }
                    },
                )
                rows = conn.execute(
                    f"""
                    SELECT service, identity_hash, identity_type, identity_key,
                           calls, failures, limit_count, reset_at
                    FROM {_QUOTA_TABLE}
                    WHERE day = ?
                    ORDER BY calls DESC, failures DESC, service ASC
                    LIMIT ?
                    """,
                    (day, safe_limit),
                ).fetchall()
        except (OSError, sqlite3.Error, ValueError):
            return {
                "day": day,
                "timezone": "Asia/Shanghai",
                "source": {
                    "ready": False,
                    "error": {
                        "code": "quota_source_unavailable",
                        "message": "MCP 当日额度数据源不可用",
                    },
                },
                "usage": [],
            }

        usage = []
        for row in rows:
            calls = max(0, int(row["calls"] or 0))
            failures = max(0, int(row["failures"] or 0))
            daily_limit = max(0, int(row["limit_count"] or 0))
            usage.append(
                {
                    "service": str(row["service"]),
                    "identity": _mask_quota_identity(
                        str(row["identity_type"] or "unknown"),
                        str(row["identity_key"] or ""),
                        str(row["identity_hash"] or ""),
                    ),
                    "identity_type": str(row["identity_type"] or "unknown"),
                    "calls": calls,
                    "failures": failures,
                    "total": calls + failures,
                    "daily_limit": daily_limit,
                    "remaining": max(daily_limit - calls, 0),
                    "reset_at": str(row["reset_at"]),
                }
            )
        return {
            "day": day,
            "timezone": "Asia/Shanghai",
            "source": {"ready": True, "error": None},
            "usage": usage,
        }

    def _read_bindings(self) -> dict[str, dict[str, Any]]:
        with self._read_connection(self.binding_db_path) as conn:
            self._validate_schema(
                conn,
                {
                    _ACCOUNT_TABLE: {"account_id", "account_name", "username"},
                    _BINDING_TABLE: {"user_email", "account_id"},
                },
            )
            account_rows = conn.execute(
                f"SELECT account_id, account_name, username FROM {_ACCOUNT_TABLE} "
                "ORDER BY account_name COLLATE NOCASE LIMIT ?",
                (_MAX_ROWS,),
            ).fetchall()
            account_ids = [str(row["account_id"]) for row in account_rows]
            users_by_id: dict[str, list[str]] = {account_id: [] for account_id in account_ids}
            for account_id in account_ids:
                user_rows = conn.execute(
                    f"SELECT user_email FROM {_BINDING_TABLE} WHERE account_id = ? "
                    "ORDER BY user_email COLLATE NOCASE LIMIT ?",
                    (account_id, _MAX_BOUND_USERS_PER_ACCOUNT),
                ).fetchall()
                users_by_id[account_id] = [
                    _mask_email(str(row["user_email"])) for row in user_rows
                ]

        result: dict[str, dict[str, Any]] = {}
        for row in account_rows:
            name = str(row["account_name"])
            username = str(row["username"])
            account_key = _seller_sprite_account_key(name, username)
            result[account_key] = {
                "name": name,
                "username": _mask_username(username),
                "bound_users": users_by_id[str(row["account_id"])],
            }
        return result

    def _read_execution_state(self) -> dict[str, dict[str, Any]]:
        with self._read_connection(self.queue_db_path) as conn:
            self._validate_schema(
                conn,
                {
                    _TASK_TABLE: {
                        "job_id",
                        "status",
                        "assigned_account",
                        "assigned_account_key",
                        "finished_at",
                        "last_error_code",
                    },
                    _ACCOUNT_EVENT_TABLE: {
                        "created_at",
                        "event_type",
                        "account_key",
                        "account_name",
                        "masked_username",
                        "job_id",
                        "error_code",
                    },
                    _QUARANTINE_TABLE: {"account_key", "expires_at"},
                },
            )
            task_rows = conn.execute(
                f"""
                SELECT job_id, status, assigned_account, assigned_account_key,
                       finished_at, last_error_code
                FROM {_TASK_TABLE}
                WHERE assigned_account_key IS NOT NULL
                ORDER BY COALESCE(finished_at, '9999') DESC
                LIMIT ?
                """,
                (_MAX_ROWS * 4,),
            ).fetchall()
            event_rows = conn.execute(
                f"""
                SELECT created_at, event_type, account_key, account_name,
                       masked_username, job_id, error_code
                FROM {_ACCOUNT_EVENT_TABLE}
                WHERE account_key IS NOT NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (_MAX_ROWS * 2,),
            ).fetchall()
            quarantine_rows = conn.execute(
                f"SELECT account_key, expires_at FROM {_QUARANTINE_TABLE} "
                "ORDER BY expires_at DESC LIMIT ?",
                (_MAX_ROWS * 2,),
            ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in task_rows:
            key = str(row["assigned_account_key"])
            item = result.setdefault(key, _empty_execution_state())
            if row["assigned_account"] and not item.get("name"):
                item["name"] = str(row["assigned_account"])
            status = str(row["status"])
            if status == "running":
                item["active_task_count"] += 1
                if len(item["active_tasks"]) < _MAX_ACTIVE_TASKS_PER_ACCOUNT:
                    item["active_tasks"].append(str(row["job_id"]))
            elif status == "succeeded" and item["last_success"] is None:
                item["last_success"] = {
                    "at": str(row["finished_at"]),
                    "job_id": str(row["job_id"]),
                }
            elif status == "failed" and item["last_failure"] is None:
                item["last_failure"] = {
                    "at": str(row["finished_at"]),
                    "job_id": str(row["job_id"]),
                    "code": str(row["last_error_code"] or "TASK_FAILED"),
                }
        for row in event_rows:
            key = str(row["account_key"])
            item = result.setdefault(key, _empty_execution_state())
            item["name"] = item.get("name") or str(row["account_name"] or "")
            item["username"] = item.get("username") or str(row["masked_username"] or "")
            if str(row["event_type"]).endswith("_failed"):
                candidate = {
                    "at": str(row["created_at"]),
                    "job_id": str(row["job_id"]) if row["job_id"] else None,
                    "code": str(row["error_code"] or "ACCOUNT_FAILED"),
                }
                if _is_later(candidate, item["last_failure"]):
                    item["last_failure"] = candidate
        now = self.clock()
        for row in quarantine_rows:
            if _is_future(str(row["expires_at"]), now):
                result.setdefault(str(row["account_key"]), _empty_execution_state())[
                    "quarantined"
                ] = True
        return result

    @contextmanager
    def _read_connection(self, path: Path) -> Iterator[sqlite3.Connection]:
        if not path.is_file():
            raise OSError("source unavailable")
        uri_path = quote(path.resolve().as_posix(), safe="/:")
        conn = sqlite3.connect(
            f"file:{uri_path}?mode=ro",
            uri=True,
            timeout=2.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _validate_schema(
        conn: sqlite3.Connection,
        contracts: dict[str, set[str]],
    ) -> None:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table, required in contracts.items():
            if table not in tables:
                raise ValueError("source schema unavailable")
            columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if required - columns:
                raise ValueError("source schema unavailable")


def _empty_execution_state() -> dict[str, Any]:
    return {
        "name": "",
        "username": "",
        "active_task_count": 0,
        "active_tasks": [],
        "last_success": None,
        "last_failure": None,
        "quarantined": False,
    }


def _seller_sprite_account_key(name: str, username: str) -> str:
    identity = f"seller_sprite:{name.strip().casefold()}:{username.strip().casefold()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _mask_username(value: str) -> str:
    return _mask_email(value) if "@" in value else _mask_text(value)


def _public_account_name(value: str) -> str:
    """账号标签若被误填为邮箱，仍不返回完整身份。"""
    return _mask_email(value) if "@" in value else value


def _mask_email(value: str) -> str:
    normalized = value.strip()
    if "@" not in normalized:
        return _mask_text(normalized)
    local, domain = normalized.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _mask_text(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 2:
        return "*" * len(normalized)
    return f"{normalized[:1]}***{normalized[-1:]}"


def _mask_quota_identity(identity_type: str, key: str, identity_hash: str) -> str:
    if identity_type == "email":
        return _mask_email(key)
    if identity_type == "api_key":
        digest = key.removeprefix("sha256:")
        return f"api_key:{digest[:6]}...{digest[-4:]}" if digest else "api_key:unknown"
    digest = identity_hash.strip()
    return f"{identity_type}:{digest[:8]}..." if digest else f"{identity_type}:unknown"


def _account_health(
    *,
    last_success: dict[str, Any] | None,
    last_failure: dict[str, Any] | None,
    quarantined: bool,
) -> str:
    if quarantined:
        return "unhealthy"
    if last_failure and _is_later(last_failure, last_success):
        return "unhealthy"
    if last_success:
        return "healthy"
    return "unknown"


def _is_later(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    return current is None or str(candidate.get("at") or "") > str(current.get("at") or "")


def _is_future(value: str, now: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) > now.astimezone(timezone.utc)


def _bounded_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_ROWS:
        raise ValueError(f"limit must be between 1 and {_MAX_ROWS}")
    return value
