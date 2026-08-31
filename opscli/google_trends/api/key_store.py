"""SerpApi API Key SQLite 存储。

本模块集中保存 Google Trends 第三方 API Key、账户额度快照和可用状态。
API Key 按运维约定以明文写入 SQLite，但所有公开读取结果均不包含明文。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.config import CONFIG_DIR


DEFAULT_SERPAPI_DB_PATH = Path(CONFIG_DIR) / "google_trends" / "serpapi.sqlite3"
VALID_KEY_STATUSES = frozenset({"active", "exhausted", "disabled"})
RENEWAL_RECHECK_COOLDOWN = timedelta(hours=1)


@dataclass(frozen=True)
class SerpApiKeyRecord:
    """单个 SerpApi API Key 及其内部状态。"""

    key_id: str
    name: str
    api_key: str
    status: str
    remark: str | None = None
    total_searches_left: int | None = None
    this_month_usage: int | None = None
    plan_name: str | None = None
    plan_renewal_date: str | None = None
    last_checked_at: str | None = None
    last_used_at: str | None = None
    exhausted_at: str | None = None
    last_error: str | None = None
    provider_metadata: dict[str, Any] | None = None
    api_key_masked: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含明文 API Key 的运维摘要。"""
        return {
            "key_id": self.key_id,
            "name": self.name,
            "api_key_masked": self.api_key_masked or _mask_api_key(self.api_key),
            "status": self.status,
            "remark": _redact_secret(self.remark, self.api_key),
            "total_searches_left": self.total_searches_left,
            "this_month_usage": self.this_month_usage,
            "plan_name": self.plan_name,
            "plan_renewal_date": self.plan_renewal_date,
            "last_checked_at": self.last_checked_at,
            "last_used_at": self.last_used_at,
            "exhausted_at": self.exhausted_at,
            "last_error": _redact_secret(self.last_error, self.api_key),
        }


class SerpApiKeyStore:
    """管理 SerpApi API Key、额度快照和耗尽状态。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """初始化仓储并创建 SQLite 表。

        Args:
            db_path: SQLite 文件路径；为空时使用 opscli 全局配置目录。
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_SERPAPI_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def add_key(
        self,
        *,
        name: str,
        api_key: str,
        remark: str | None = None,
    ) -> SerpApiKeyRecord:
        """新增 API Key；同名更新时保留现有状态并同步备注。"""
        normalized_name = _required_text(name, "name")
        secret = _required_text(api_key, "api_key")
        normalized_remark = _optional_text(remark)
        now = _now_iso()
        key_id = uuid4().hex
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT key_id FROM google_trends_serpapi_keys WHERE name = ? COLLATE NOCASE",
                (normalized_name,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO google_trends_serpapi_keys (
                        key_id, name, api_key, status, remark, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (key_id, normalized_name, secret, normalized_remark, now, now),
                )
            else:
                key_id = str(existing["key_id"])
                conn.execute(
                    """
                    UPDATE google_trends_serpapi_keys
                    SET api_key = ?, remark = ?, updated_at = ?
                    WHERE key_id = ?
                    """,
                    (secret, normalized_remark, now, key_id),
                )
            conn.commit()
        record = self.get(key_id)
        if record is None:
            raise RuntimeError("SerpApi API Key 写入后无法读取")
        return record

    def get(self, key_id: str) -> SerpApiKeyRecord | None:
        """按内部 ID 读取 API Key 记录。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM google_trends_serpapi_keys WHERE key_id = ?",
                (_required_text(key_id, "key_id"),),
            ).fetchone()
        return _record_from_row(row) if row else None

    def get_by_name(self, name: str) -> SerpApiKeyRecord | None:
        """按不区分大小写的账号名称读取 API Key 记录。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM google_trends_serpapi_keys WHERE name = ? COLLATE NOCASE",
                (_required_text(name, "name"),),
            ).fetchone()
        return _record_from_row(row) if row else None

    def list_keys(self) -> list[SerpApiKeyRecord]:
        """按创建顺序列出所有 Key；该内部方法包含明文。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM google_trends_serpapi_keys ORDER BY created_at, key_id"
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def next_active_key(self, *, exclude_key_ids: set[str] | None = None) -> SerpApiKeyRecord | None:
        """返回最久未使用的 active Key，并跳过本轮已尝试项。"""
        excluded = sorted(exclude_key_ids or set())
        sql = "SELECT * FROM google_trends_serpapi_keys WHERE status = 'active'"
        params: list[Any] = []
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            sql += f" AND key_id NOT IN ({placeholders})"
            params.extend(excluded)
        sql += " ORDER BY last_used_at IS NOT NULL, last_used_at, created_at, key_id LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _record_from_row(row) if row else None

    def next_due_exhausted_key(
        self,
        *,
        exclude_key_ids: set[str] | None = None,
    ) -> SerpApiKeyRecord | None:
        """返回续期日已到且超过检查冷却时间的耗尽账号。"""
        now = datetime.now(UTC)
        excluded = sorted(exclude_key_ids or set())
        sql = """
            SELECT * FROM google_trends_serpapi_keys
            WHERE status = 'exhausted'
              AND plan_renewal_date IS NOT NULL
              AND plan_renewal_date <= ?
              AND (last_checked_at IS NULL OR last_checked_at <= ?)
        """
        params: list[Any] = [
            now.date().isoformat(),
            (now - RENEWAL_RECHECK_COOLDOWN).isoformat(timespec="microseconds"),
        ]
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            sql += f" AND key_id NOT IN ({placeholders})"
            params.extend(excluded)
        sql += " ORDER BY plan_renewal_date, last_checked_at, exhausted_at, key_id LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _record_from_row(row) if row else None

    def update_account_snapshot(
        self,
        key_id: str,
        payload: dict[str, Any],
        *,
        preserve_plan_renewal_date: bool = False,
    ) -> SerpApiKeyRecord:
        """写入 Account API 白名单字段，可在续期复查期间保留原续期日。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE google_trends_serpapi_keys
                SET total_searches_left = ?, this_month_usage = ?, plan_name = ?,
                    plan_renewal_date = CASE WHEN ? THEN plan_renewal_date ELSE ? END,
                    last_checked_at = ?, last_error = NULL, updated_at = ?
                WHERE key_id = ?
                """,
                (
                    _optional_int(payload.get("total_searches_left")),
                    _optional_int(payload.get("this_month_usage")),
                    _optional_text(payload.get("plan_name")),
                    preserve_plan_renewal_date,
                    _optional_text(payload.get("plan_renewal_date")),
                    now,
                    now,
                    _required_text(key_id, "key_id"),
                ),
            )
        record = self.get(key_id)
        if record is None:
            raise ValueError(f"SerpApi API Key 不存在：{key_id}")
        return record

    def restore_active(self, key_id: str) -> None:
        """额度续期确认后恢复耗尽账号，并清除旧耗尽状态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE google_trends_serpapi_keys
                SET status = 'active', exhausted_at = NULL, last_error = NULL,
                    updated_at = ?
                WHERE key_id = ? AND status = 'exhausted'
                """,
                (now, _required_text(key_id, "key_id")),
            )

    def record_account_check_error(self, key_id: str, *, reason: str) -> None:
        """记录 Account API 复查错误和检查时间，用于限制重复请求。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE google_trends_serpapi_keys
                SET last_checked_at = ?, last_error = ?, updated_at = ?
                WHERE key_id = ?
                """,
                (now, str(reason)[:500], now, _required_text(key_id, "key_id")),
            )

    def mark_used(self, key_id: str) -> None:
        """记录最近一次发起搜索的时间，用于轮换排序。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE google_trends_serpapi_keys SET last_used_at = ?, updated_at = ? WHERE key_id = ?",
                (now, now, _required_text(key_id, "key_id")),
            )

    def mark_exhausted(self, key_id: str, *, reason: str) -> None:
        """将已确认无剩余额度的 Key 标记为 exhausted。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE google_trends_serpapi_keys
                SET status = 'exhausted', total_searches_left = 0,
                    exhausted_at = ?, last_error = ?, updated_at = ?
                WHERE key_id = ?
                """,
                (now, str(reason)[:500], now, _required_text(key_id, "key_id")),
            )

    def record_error(self, key_id: str, *, reason: str) -> None:
        """记录非耗尽错误，但不改变 Key 状态。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE google_trends_serpapi_keys SET last_error = ?, updated_at = ? WHERE key_id = ?",
                (str(reason)[:500], now, _required_text(key_id, "key_id")),
            )

    def set_status(self, key_id: str, status: str) -> None:
        """供初始化代码或 SQLite 运维显式调整 Key 状态。"""
        normalized = str(status or "").strip().lower()
        if normalized not in VALID_KEY_STATUSES:
            raise ValueError(f"不支持的 SerpApi API Key 状态：{status}")
        now = _now_iso()
        exhausted_at = now if normalized == "exhausted" else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE google_trends_serpapi_keys
                SET status = ?, exhausted_at = ?, updated_at = ?
                WHERE key_id = ?
                """,
                (normalized, exhausted_at, now, _required_text(key_id, "key_id")),
            )

    def _ensure_schema(self) -> None:
        """初始化 API Key 表和状态索引。"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS google_trends_serpapi_keys (
                    key_id TEXT NOT NULL PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    api_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    remark TEXT,
                    total_searches_left INTEGER,
                    this_month_usage INTEGER,
                    plan_name TEXT,
                    plan_renewal_date TEXT,
                    last_checked_at TEXT,
                    last_used_at TEXT,
                    exhausted_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(status IN ('active', 'exhausted', 'disabled'))
                )
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(google_trends_serpapi_keys)"
                ).fetchall()
            }
            if "remark" not in columns:
                # SQLite 不支持通用的 ADD COLUMN IF NOT EXISTS，先检查旧库结构再迁移。
                conn.execute(
                    "ALTER TABLE google_trends_serpapi_keys ADD COLUMN remark TEXT"
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_google_trends_serpapi_key_selection
                ON google_trends_serpapi_keys(status, last_used_at, created_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """创建启用 WAL 和忙等待的 SQLite 连接。"""
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn


def _record_from_row(row: sqlite3.Row) -> SerpApiKeyRecord:
    """将 SQLite 行转换为内部 Key 记录。"""
    return SerpApiKeyRecord(
        key_id=str(row["key_id"]),
        name=str(row["name"]),
        api_key=str(row["api_key"]),
        status=str(row["status"]),
        remark=_optional_text(row["remark"]),
        total_searches_left=_optional_int(row["total_searches_left"]),
        this_month_usage=_optional_int(row["this_month_usage"]),
        plan_name=_optional_text(row["plan_name"]),
        plan_renewal_date=_optional_text(row["plan_renewal_date"]),
        last_checked_at=_optional_text(row["last_checked_at"]),
        last_used_at=_optional_text(row["last_used_at"]),
        exhausted_at=_optional_text(row["exhausted_at"]),
        last_error=_optional_text(row["last_error"]),
    )


def _required_text(value: Any, field: str) -> str:
    """读取必填文本并拒绝空白值。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text


def _optional_text(value: Any) -> str | None:
    """将可选值转换为非空文本。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    """将可选额度字段转换为整数。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mask_api_key(value: str) -> str:
    """返回仅保留首尾四位的 API Key 掩码。"""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _redact_secret(value: str | None, secret: str) -> str | None:
    """从公开文本中替换 API Key 明文。"""
    if value is None:
        return None
    return value.replace(secret, "***") if secret else value


def _now_iso() -> str:
    """返回带微秒的 UTC 时间，保证快速轮换时排序稳定。"""
    return datetime.now(UTC).isoformat(timespec="microseconds")
