"""Collector Monitor 账号健康与当日额度的严格只读查询。"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from opscli.collector_monitor.storage.sqlite import (
    connect_read_only_sqlite,
    schema_problems,
)


# API 和 SQLite 查询共享的最大账号/用户行数，避免页面请求无界扫描。
_MAX_ROWS = 500
# 每个账号只展示最近 20 个活跃任务标识；占用总数仍由聚合查询准确统计。
_MAX_ACTIVE_TASKS_PER_ACCOUNT = 20
# 单账号绑定用户展示上限，防止异常绑定数据放大响应。
_MAX_BOUND_USERS_PER_ACCOUNT = 20
# 下列固定表名来自 SellerSprite 与 MCP 已发布 schema，禁止运行时猜测。
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
    """从 SellerSprite 与 MCP SQLite 文件读取低敏运维摘要。

    Args:
        queue_db_path: SellerSprite 任务、账号事件和隔离状态数据库。
        binding_db_path: SellerSprite 专属账号绑定数据库。
        quota_db_path: MCP 每日额度数据库。
        clock: 可选时钟，测试用来冻结北京时间日界和隔离状态。
    """

    def __init__(
        self,
        *,
        queue_db_path: str | Path,
        binding_db_path: str | Path,
        quota_db_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """保存三个只读数据源路径，不打开或创建 SQLite 文件。"""
        self.queue_db_path = Path(queue_db_path)
        self.binding_db_path = Path(binding_db_path)
        self.quota_db_path = Path(quota_db_path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def accounts(self, *, limit: int = 100) -> dict[str, Any]:
        """返回执行账号、绑定用户、占用和最近结果的脱敏摘要。

        Args:
            limit: 最多返回的账号数，范围为 1 到 500。

        Returns:
            包含 source 状态和 accounts 列表的低敏字典。来源异常时返回
            固定错误摘要，不抛出 SQLite 原始异常。

        Raises:
            ValueError: limit 不在允许范围内。
        """
        safe_limit = _bounded_limit(limit)
        try:
            bindings = self._read_bindings(limit=safe_limit)
            execution = self._read_execution_state(
                preferred_keys=list(bindings),
                limit=safe_limit,
            )
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

        # 绑定账号优先进入有界结果，其余共享执行账号按最近活动补齐。
        keys = list(bindings)
        keys.extend(key for key in execution if key not in bindings)
        accounts: list[dict[str, Any]] = []
        for account_key in keys[:safe_limit]:
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
            "accounts": accounts,
        }

    def usage_today(self, *, limit: int = 100) -> dict[str, Any]:
        """返回北京时间当日已落表的计费成功与已退款失败次数。

        Args:
            limit: 最多返回的用户/服务额度行数，范围为 1 到 500。

        Returns:
            包含北京时间日期、source 状态和 usage 列表的低敏字典。

        Raises:
            ValueError: limit 不在允许范围内。
        """
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

    def _read_bindings(self, *, limit: int) -> dict[str, dict[str, Any]]:
        """读取有界账号及每个账号的有界绑定用户，不接触密码密文。"""
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
                (limit,),
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

    def _read_execution_state(
        self,
        *,
        preferred_keys: list[str],
        limit: int,
    ) -> dict[str, dict[str, Any]]:
        """按账号分区读取占用、最近结果、最近事件和隔离状态。"""
        with self._read_connection(self.queue_db_path) as conn:
            self._validate_schema(
                conn,
                {
                    _TASK_TABLE: {
                        "job_id",
                        "status",
                        "assigned_account",
                        "assigned_account_key",
                        "started_at",
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
            # 先确定最多 limit 个账号。绑定账号优先，其余账号按最近持久活动补齐；
            # 后续每条查询都只在这个集合内按账号分区，避免高频账号遮蔽低频账号。
            discovered_rows = conn.execute(
                f"""
                SELECT account_key, MAX(observed_at) AS latest_at
                FROM (
                    SELECT assigned_account_key AS account_key,
                           COALESCE(finished_at, started_at, '') AS observed_at
                    FROM {_TASK_TABLE}
                    WHERE assigned_account_key IS NOT NULL
                    UNION ALL
                    SELECT account_key, created_at AS observed_at
                    FROM {_ACCOUNT_EVENT_TABLE}
                    WHERE account_key IS NOT NULL
                    UNION ALL
                    SELECT account_key, expires_at AS observed_at
                    FROM {_QUARANTINE_TABLE}
                    WHERE account_key IS NOT NULL
                )
                GROUP BY account_key
                ORDER BY latest_at DESC, account_key ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            target_keys = list(dict.fromkeys(preferred_keys))
            target_keys.extend(
                str(row["account_key"])
                for row in discovered_rows
                if str(row["account_key"]) not in target_keys
            )
            target_keys = target_keys[:limit]
            if not target_keys:
                return {}
            placeholders = ", ".join("?" for _ in target_keys)

            active_count_rows = conn.execute(
                f"""
                SELECT assigned_account_key, COUNT(*) AS active_task_count
                FROM {_TASK_TABLE}
                WHERE status = 'running'
                  AND assigned_account_key IN ({placeholders})
                GROUP BY assigned_account_key
                """,
                target_keys,
            ).fetchall()
            # 每个账号只取最近活跃任务样本及最近一次成功/失败；COUNT 单独聚合，
            # 因而展示上限不会截断真实占用数。
            task_rows = conn.execute(
                f"""
                SELECT job_id, status, assigned_account, assigned_account_key,
                       started_at, finished_at, last_error_code
                FROM (
                    SELECT job_id, status, assigned_account, assigned_account_key,
                           started_at, finished_at, last_error_code,
                           ROW_NUMBER() OVER (
                               PARTITION BY assigned_account_key, status
                               ORDER BY CASE
                                   WHEN status = 'running' THEN started_at
                                   ELSE finished_at
                               END DESC, job_id ASC
                           ) AS account_rank
                    FROM {_TASK_TABLE}
                    WHERE assigned_account_key IN ({placeholders})
                      AND status IN ('running', 'succeeded', 'failed')
                )
                WHERE (status = 'running' AND account_rank <= ?)
                   OR (status IN ('succeeded', 'failed') AND account_rank = 1)
                ORDER BY assigned_account_key ASC, status ASC, account_rank ASC
                """,
                [*target_keys, _MAX_ACTIVE_TASKS_PER_ACCOUNT],
            ).fetchall()
            event_rows = conn.execute(
                f"""
                SELECT created_at, event_type, account_key, account_name,
                       masked_username, job_id, error_code
                FROM (
                    SELECT created_at, event_type, account_key, account_name,
                           masked_username, job_id, error_code,
                           ROW_NUMBER() OVER (
                               PARTITION BY account_key,
                                   CASE WHEN substr(event_type, -7) = '_failed'
                                       THEN 1 ELSE 0 END
                               ORDER BY created_at DESC
                           ) AS account_rank
                    FROM {_ACCOUNT_EVENT_TABLE}
                    WHERE account_key IN ({placeholders})
                )
                WHERE account_rank = 1
                ORDER BY account_key ASC, created_at DESC
                """,
                target_keys,
            ).fetchall()
            quarantine_rows = conn.execute(
                f"SELECT account_key, expires_at FROM {_QUARANTINE_TABLE} "
                f"WHERE account_key IN ({placeholders}) ORDER BY expires_at DESC",
                target_keys,
            ).fetchall()

        result = {key: _empty_execution_state() for key in target_keys}
        for row in active_count_rows:
            result[str(row["assigned_account_key"])]["active_task_count"] = int(
                row["active_task_count"] or 0
            )
        for row in task_rows:
            key = str(row["assigned_account_key"])
            item = result.setdefault(key, _empty_execution_state())
            if row["assigned_account"] and not item.get("name"):
                item["name"] = str(row["assigned_account"])
            status = str(row["status"])
            if status == "running":
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
        """在上下文结束时可靠关闭共享只读连接。"""
        conn = connect_read_only_sqlite(path)
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _validate_schema(
        conn: sqlite3.Connection,
        contracts: dict[str, set[str]],
    ) -> None:
        """将 schema 差异收敛为不泄露 SQLite 原始信息的内部异常。"""
        if schema_problems(conn, contracts):
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
