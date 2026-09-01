"""AppHub SQLite Engine 工厂。"""

from __future__ import annotations

import os

from opscli.app.domain.exceptions import AppProjectError


def get_engine():
    """创建带 WAL、busy_timeout 和外键配置的 SQLAlchemy Engine。"""
    db_path = os.getenv("APP_DB_PATH", "").strip()
    if not db_path:
        raise AppProjectError(
            "DB-001",
            "APP_DB_PATH 未配置。",
            fix_hint="在 app.yaml 声明 services.sqlite: true，并通过 opscli app run 或 AppHub 启动。",
        )
    try:
        from sqlalchemy import create_engine, event
    except ImportError as exc:
        raise AppProjectError(
            "PKG-001",
            "缺少 SQLAlchemy 运行时依赖。",
            fix_hint="重新安装最新版 aukeys-opscli。",
        ) from exc

    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine
