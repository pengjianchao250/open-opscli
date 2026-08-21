"""把 MCP 场景调用事件异步写入统一 MySQL 表。

该模块只处理 ``mcp_tool`` 事件，且由 ``TelemetryReporter`` 的后台线程调用，
不会把数据库连接或网络延迟带入 MCP Tool 主链路。写入失败会静默丢弃，保持遥测
原有的非关键路径语义。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.collection_storage.schema import SCHEMA_STATEMENTS

ENV_ENABLED = "OPSCLI_MCP_TELEMETRY_MYSQL_ENABLED"
ENV_AUTO_CREATE_SCHEMA = "OPSCLI_MCP_TELEMETRY_MYSQL_AUTO_CREATE_SCHEMA"

_schema_lock = Lock()
_schema_ready: set[tuple[str, int, str, str]] = set()


def write_event(event: dict[str, Any]) -> bool:
    """写入一条 MCP 调用事件；未启用、配置不完整或写入失败均返回 False。"""
    if event.get("event_type") != "mcp_tool" or not _is_enabled():
        return False
    settings = _load_mysql_settings()
    if not settings.configured:
        return False

    connection = None
    try:
        connection = _connect(settings)
        with connection.cursor() as cursor:
            if _auto_create_schema():
                _ensure_schema(cursor, settings)
            dimensions = event.get("dimensions")
            dimensions = dimensions if isinstance(dimensions, dict) else {}
            service = _text(dimensions.get("service")) or _text(event.get("module"))
            operation = _text(dimensions.get("operation")) or _text(event.get("command"))
            if not service or not operation:
                return False
            cursor.execute(
                """
                INSERT INTO mcp_call_events (
                    trace_id, event_type, user_email, service, operation, endpoint, scenario,
                    runtime_role, site, period, provider, status, error_code,
                    duration_ms, skill_name, dimensions_json, occurred_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE trace_id = VALUES(trace_id)
                """,
                (
                    _text(event.get("trace_id")) or str(uuid.uuid4()),
                    "mcp_tool",
                    _text(event.get("user_email"), 254),
                    _text(service, 64),
                    _text(operation, 128),
                    _text(dimensions.get("endpoint"), 128),
                    _text(dimensions.get("scenario")),
                    _text(dimensions.get("runtime_role"), 32) or "executor",
                    _text(dimensions.get("site"), 64),
                    _text(dimensions.get("period"), 64),
                    _text(dimensions.get("provider"), 128),
                    # 公共表只记录“发生过调用”；业务 success/error 由各业务表维护。
                    "called",
                    None,
                    _duration(event.get("duration_ms")),
                    _text(event.get("skill_name"), 128),
                    json.dumps(dimensions, ensure_ascii=False, separators=(",", ":")),
                    _mysql_datetime(event.get("timestamp")),
                ),
            )
        connection.commit()
        return True
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _is_enabled() -> bool:
    value = os.environ.get(ENV_ENABLED)
    if value is None:
        value = os.environ.get("OPSCLI_COLLECTION_STORAGE_ENABLED")
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _auto_create_schema() -> bool:
    value = os.environ.get(ENV_AUTO_CREATE_SCHEMA)
    if value is None:
        value = os.environ.get("OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA")
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_mysql_settings() -> MySqlSettings:
    return MySqlSettings(
        host=os.environ.get("OPSCLI_COLLECTION_MYSQL_HOST", "").strip(),
        port=_positive_int(os.environ.get("OPSCLI_COLLECTION_MYSQL_PORT"), 3306),
        database=os.environ.get("OPSCLI_COLLECTION_MYSQL_DATABASE", "").strip(),
        user=os.environ.get("OPSCLI_COLLECTION_MYSQL_USER", "").strip(),
        password=os.environ.get("OPSCLI_COLLECTION_MYSQL_PASSWORD", ""),
        ssl_ca=os.environ.get("OPSCLI_COLLECTION_MYSQL_SSL_CA", "").strip(),
        connect_timeout_seconds=_positive_int(
            os.environ.get("OPSCLI_COLLECTION_MYSQL_CONNECT_TIMEOUT_SECONDS"), 10
        ),
    )


def _connect(settings: MySqlSettings):
    import pymysql

    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=10,
        write_timeout=10,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        ssl_ca=settings.ssl_ca or None,
        ssl_verify_cert=bool(settings.ssl_ca),
        ssl_verify_identity=bool(settings.ssl_ca),
    )


def _ensure_schema(cursor: Any, settings: MySqlSettings) -> None:
    key = (settings.host, settings.port, settings.database, settings.user)
    if key in _schema_ready:
        return
    with _schema_lock:
        if key in _schema_ready:
            return
        statement = next(
            statement
            for statement in SCHEMA_STATEMENTS
            if "CREATE TABLE IF NOT EXISTS mcp_call_events" in statement
        )
        cursor.execute(statement)
        # 兼容此前只创建了旧版公共统计表的数据库；新表创建时这些 DDL 会因重复而被忽略。
        try:
            cursor.execute(
                "ALTER TABLE mcp_call_events ADD COLUMN endpoint VARCHAR(128) NULL"
            )
        except Exception:
            pass
        try:
            cursor.execute(
                "ALTER TABLE mcp_call_events "
                "ADD KEY ix_mcp_call_events_service_endpoint_time "
                "(service, endpoint, occurred_at)"
            )
        except Exception:
            pass
        _schema_ready.add(key)


def _text(value: Any, limit: int = 128) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _duration(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


def _mysql_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
