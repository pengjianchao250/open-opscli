"""监控自有 SQLite 状态库与事故生命周期。"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from opscli.collector_monitor.classifier import IncidentCandidate

_STATE_SCHEMA_VERSION = 2
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_ALLOWED_STATUS = {"active", "resolved"}
_ALLOWED_RULES = {"stalled", "orphaned", "queue_starved", "worker_unavailable"}


@dataclass(frozen=True)
class IncidentAction:
    """待发送的事故通知动作。"""

    kind: str
    rule: str
    subject: str
    severity: str
    message: str


class MonitorStateStore:
    """持久化事故、连续观测、扫描结果和通知投递状态。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        cooldown_seconds: float,
        protected_db_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.protected_db_path = (
            Path(protected_db_path) if protected_db_path is not None else None
        )
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def observe_consecutive(self, rule: str, subjects: set[str]) -> dict[str, int]:
        """原子递增本轮对象计数，并删除该规则下已消失对象。"""
        normalized_rule = str(rule).strip()
        normalized_subjects = {
            str(subject).strip() for subject in subjects if str(subject).strip()
        }
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if normalized_subjects:
                placeholders = ", ".join("?" for _ in normalized_subjects)
                conn.execute(
                    f"DELETE FROM consecutive_observations WHERE rule = ? "
                    f"AND subject NOT IN ({placeholders})",
                    [normalized_rule, *sorted(normalized_subjects)],
                )
                for subject in sorted(normalized_subjects):
                    conn.execute(
                        """
                        INSERT INTO consecutive_observations (rule, subject, observation_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(rule, subject) DO UPDATE
                        SET observation_count = observation_count + 1
                        """,
                        (normalized_rule, subject),
                    )
            else:
                conn.execute(
                    "DELETE FROM consecutive_observations WHERE rule = ?",
                    (normalized_rule,),
                )
            rows = conn.execute(
                "SELECT subject, observation_count FROM consecutive_observations "
                "WHERE rule = ?",
                (normalized_rule,),
            ).fetchall()
            conn.commit()
        return {str(row["subject"]): int(row["observation_count"]) for row in rows}

    def reconcile(
        self,
        candidates: Iterable[IncidentCandidate],
        *,
        now: datetime,
    ) -> list[IncidentAction]:
        """在事务中去重、开启、升级、提醒或解决事故。"""
        observed_at = _iso(now)
        current = {(item.rule, item.subject): item for item in candidates}
        actions: list[IncidentAction] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_rows = conn.execute("SELECT * FROM incidents").fetchall()
            existing = {
                (str(row["rule"]), str(row["subject"])): row for row in existing_rows
            }
            for key, candidate in current.items():
                row = existing.get(key)
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO incidents (
                            rule, subject, severity, message, status,
                            opened_at, last_seen_at, resolved_at,
                            alert_status, pending_alert_kind, last_alert_at,
                            recovery_status, last_recovery_at,
                            delivery_error_class, delivery_result
                        ) VALUES (?, ?, ?, ?, 'active', ?, ?, NULL,
                                  'pending', 'opening', NULL,
                                  'not_applicable', NULL, NULL, NULL)
                        """,
                        (
                            candidate.rule,
                            candidate.subject,
                            candidate.severity,
                            candidate.message,
                            observed_at,
                            observed_at,
                        ),
                    )
                    actions.append(_action("opening", candidate))
                    continue
                if str(row["status"]) == "resolved":
                    conn.execute(
                        """
                        UPDATE incidents
                        SET severity = ?, message = ?, status = 'active',
                            opened_at = ?, last_seen_at = ?, resolved_at = NULL,
                            alert_status = 'pending', pending_alert_kind = 'opening',
                            last_alert_at = NULL,
                            recovery_status = 'not_applicable', last_recovery_at = NULL,
                            delivery_error_class = NULL, delivery_result = NULL
                        WHERE rule = ? AND subject = ?
                        """,
                        (
                            candidate.severity,
                            candidate.message,
                            observed_at,
                            observed_at,
                            candidate.rule,
                            candidate.subject,
                        ),
                    )
                    actions.append(_action("opening", candidate))
                    continue

                previous_severity = str(row["severity"])
                escalated = _severity_rank(candidate.severity) > _severity_rank(
                    previous_severity
                )
                conn.execute(
                    """
                    UPDATE incidents
                    SET severity = ?, message = ?, last_seen_at = ?
                    WHERE rule = ? AND subject = ?
                    """,
                    (
                        candidate.severity,
                        candidate.message,
                        observed_at,
                        candidate.rule,
                        candidate.subject,
                    ),
                )
                if escalated:
                    conn.execute(
                        """
                        UPDATE incidents
                        SET alert_status = 'pending', pending_alert_kind = 'escalation',
                            delivery_error_class = NULL, delivery_result = NULL
                        WHERE rule = ? AND subject = ?
                        """,
                        (candidate.rule, candidate.subject),
                    )
                    actions.append(_action("escalation", candidate))
                    continue

                alert_status = str(row["alert_status"])
                if alert_status in {"pending", "failed"}:
                    kind = str(row["pending_alert_kind"] or "opening")
                    actions.append(_action(kind, candidate))
                elif alert_status != "disabled" and _cooldown_elapsed(
                    row["last_alert_at"],
                    now,
                    self.cooldown_seconds,
                ):
                    conn.execute(
                        """
                        UPDATE incidents
                        SET alert_status = 'pending', pending_alert_kind = 'reminder'
                        WHERE rule = ? AND subject = ?
                        """,
                        (candidate.rule, candidate.subject),
                    )
                    actions.append(_action("reminder", candidate))

            for key, row in existing.items():
                if key in current:
                    continue
                if str(row["status"]) == "resolved":
                    if str(row["recovery_status"]) in {"pending", "failed"} and _cooldown_elapsed(
                        row["last_recovery_at"], now, self.cooldown_seconds
                    ):
                        conn.execute(
                            """
                            UPDATE incidents
                            SET recovery_status = 'pending', last_recovery_at = ?
                            WHERE rule = ? AND subject = ?
                            """,
                            (observed_at, key[0], key[1]),
                        )
                        actions.append(
                            IncidentAction(
                                "recovery",
                                key[0],
                                key[1],
                                str(row["severity"]),
                                str(row["message"]),
                            )
                        )
                    continue
                conn.execute(
                    """
                    UPDATE incidents
                    SET status = 'resolved', resolved_at = ?,
                        recovery_status = 'pending', last_recovery_at = ?,
                        delivery_error_class = NULL, delivery_result = NULL
                    WHERE rule = ? AND subject = ?
                    """,
                    (observed_at, observed_at, key[0], key[1]),
                )
                actions.append(
                    IncidentAction(
                        "recovery",
                        key[0],
                        key[1],
                        str(row["severity"]),
                        str(row["message"]),
                    )
                )
            conn.commit()
        return actions

    def record_delivery(
        self,
        action: IncidentAction,
        *,
        success: bool,
        error_class: str | None = None,
        result: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """记录通知投递结果，只保留安全类名和固定结果。"""
        delivered_at = _iso(now or datetime.now(timezone.utc))
        safe_error = None if success else _sanitize_error_class(error_class)
        safe_result = _sanitize_delivery_result(result, success=success)
        delivery_status = "disabled" if safe_result == "disabled" else (
            "delivered" if success else "failed"
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if action.kind == "recovery":
                conn.execute(
                    """
                    UPDATE incidents
                    SET recovery_status = ?, last_recovery_at = ?,
                        delivery_error_class = ?, delivery_result = ?
                    WHERE rule = ? AND subject = ?
                    """,
                    (
                        delivery_status,
                        delivered_at,
                        safe_error,
                        safe_result,
                        action.rule,
                        action.subject,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE incidents
                    SET alert_status = ?, last_alert_at = ?,
                        delivery_error_class = ?, delivery_result = ?
                    WHERE rule = ? AND subject = ?
                    """,
                    (
                        delivery_status,
                        delivered_at if success else None,
                        safe_error,
                        safe_result,
                        action.rule,
                        action.subject,
                    ),
                )
            conn.commit()

    def record_scan(self, *, success: bool, now: datetime, error_code: str | None) -> None:
        """保存最近扫描结果，不保存业务载荷或路径。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_state (singleton, last_scan_at, last_success_at, error_code)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    last_scan_at = excluded.last_scan_at,
                    last_success_at = CASE
                        WHEN excluded.last_success_at IS NULL THEN scan_state.last_success_at
                        ELSE excluded.last_success_at
                    END,
                    error_code = excluded.error_code
                """,
                (_iso(now), _iso(now) if success else None, None if success else _safe_code(error_code)),
            )

    def scan_status(self) -> dict[str, object]:
        """返回最近扫描的公开状态。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_scan_at, last_success_at, error_code FROM scan_state WHERE singleton = 1"
            ).fetchone()
        if row is None:
            return {"last_scan_at": None, "last_success_at": None, "error_code": None}
        return dict(row)

    def count_incidents(self, *, status: str | None = None) -> int:
        """使用 SQL 返回完整事故计数，不受展示行数限制。"""
        if status is not None and status not in _ALLOWED_STATUS:
            raise ValueError(f"unsupported incident status: {status}")
        where = "WHERE status = ?" if status is not None else ""
        values = (status,) if status is not None else ()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM incidents {where}", values
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def list_incidents(
        self,
        *,
        status: str | None = None,
        rule: str | None = None,
        limit: int = 100,
        active_only: bool | None = None,
    ) -> list[dict[str, object]]:
        """按白名单条件和有界行数列出事故公开字段。"""
        if active_only is True:
            status = "active"
        if status is not None and status not in _ALLOWED_STATUS:
            raise ValueError(f"unsupported incident status: {status}")
        if rule is not None and rule not in _ALLOWED_RULES:
            raise ValueError(f"unsupported incident rule: {rule}")
        safe_limit = _bounded_limit(limit)
        clauses: list[str] = []
        values: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        if rule is not None:
            clauses.append("rule = ?")
            values.append(rule)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(safe_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rule, subject, severity, message, status,
                       opened_at, last_seen_at, resolved_at,
                       alert_status, last_alert_at,
                       recovery_status, last_recovery_at,
                       delivery_error_class, delivery_result
                FROM incidents
                {where}
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,
                         last_seen_at DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def _ensure_schema(self) -> None:
        """以最小增量 schema 初始化监控自有状态库。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    rule TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT NULL,
                    alert_status TEXT NOT NULL,
                    pending_alert_kind TEXT NULL,
                    last_alert_at TEXT NULL,
                    recovery_status TEXT NOT NULL,
                    last_recovery_at TEXT NULL,
                    delivery_error_class TEXT NULL,
                    delivery_result TEXT NULL,
                    PRIMARY KEY (rule, subject)
                )
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(incidents)")
            }
            if "pending_alert_kind" not in columns:
                conn.execute("ALTER TABLE incidents ADD COLUMN pending_alert_kind TEXT NULL")
                conn.execute(
                    "UPDATE incidents SET pending_alert_kind = 'opening' WHERE alert_status IN ('pending', 'failed')"
                )
            if "delivery_result" not in columns:
                conn.execute("ALTER TABLE incidents ADD COLUMN delivery_result TEXT NULL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consecutive_observations (
                    rule TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    observation_count INTEGER NOT NULL,
                    PRIMARY KEY (rule, subject)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_state (
                    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
                    last_scan_at TEXT NULL,
                    last_success_at TEXT NULL,
                    error_code TEXT NULL
                )
                """
            )
            conn.execute(f"PRAGMA user_version = {_STATE_SCHEMA_VERSION}")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """打开监控自有状态库连接，并拒绝业务库物理文件别名。"""
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None)
        try:
            self._assert_not_protected_file(conn)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn
        except Exception:
            conn.close()
            raise

    def _assert_not_protected_file(self, conn: sqlite3.Connection) -> None:
        """复核状态路径及已打开连接都未绑定受保护业务库。"""
        if self.protected_db_path is None or not self.protected_db_path.exists():
            return
        try:
            opened_path = _main_database_path(conn)
            if self.db_path.samefile(self.protected_db_path) or opened_path.samefile(
                self.protected_db_path
            ):
                raise ValueError("state db must not reference the queue database")
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("state db physical identity check failed") from exc


def _main_database_path(conn: sqlite3.Connection) -> Path:
    """读取 SQLite 已打开主库报告的文件路径。"""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if str(row[1]) == "main" and str(row[2] or "").strip():
            return Path(str(row[2]))
    raise ValueError("state db connection identity is unavailable")


def _action(kind: str, candidate: IncidentCandidate) -> IncidentAction:
    """将事故候选转换为通知动作。"""
    return IncidentAction(
        kind,
        candidate.rule,
        candidate.subject,
        candidate.severity,
        candidate.message,
    )


def _severity_rank(value: str) -> int:
    """返回稳定严重度序位。"""
    return _SEVERITY_RANK.get(str(value).lower(), 0)


def _cooldown_elapsed(value: object, now: datetime, cooldown_seconds: float) -> bool:
    """判断最近成功提醒是否已经超过冷却期。"""
    if not value:
        return True
    try:
        previous = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return (
        current.astimezone(timezone.utc) - previous.astimezone(timezone.utc)
    ).total_seconds() >= cooldown_seconds


def _sanitize_error_class(value: str | None) -> str:
    """只保留 Python 风格异常类名，避免 URL 和密钥落库。"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)", value or "")
    return tokens[-1] if tokens else "NotificationError"


def _sanitize_delivery_result(value: str | None, *, success: bool) -> str:
    """只允许固定投递结果，避免远端正文进入状态库。"""
    normalized = str(value or ("sent" if success else "failed")).lower()
    return normalized if normalized in {"sent", "failed", "disabled"} else "failed"


def _safe_code(value: str | None) -> str:
    """将扫描错误约束为低敏稳定代码。"""
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "scan_failed").lower())
    return normalized[:80] or "scan_failed"


def _bounded_limit(value: int) -> int:
    """校验事故查询行数。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1 or parsed > 500:
        raise ValueError("limit must be between 1 and 500")
    return parsed


def _iso(value: datetime) -> str:
    """输出 UTC 秒级 ISO 时间。"""
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")
