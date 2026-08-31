"""Collector Monitor 业务 SQLite 的共享只读连接与 schema 检查。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote


def connect_read_only_sqlite(path: str | Path) -> sqlite3.Connection:
    """打开不可创建、不可写入的 SQLite 连接。

    Args:
        path: 已存在的业务 SQLite 文件。

    Returns:
        启用 Row 工厂和 ``query_only`` 的 SQLite 连接。调用方负责关闭。

    Raises:
        FileNotFoundError: 数据源文件不存在。
        sqlite3.Error: SQLite 无法建立或初始化只读连接。
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError("SQLite 数据源不存在")
    uri_path = quote(target.resolve().as_posix(), safe="/:")
    conn = sqlite3.connect(
        f"file:{uri_path}?mode=ro",
        uri=True,
        timeout=2.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def schema_problems(
    conn: sqlite3.Connection,
    contracts: dict[str, set[str]],
) -> list[str]:
    """返回固定表/列合同的安全差异描述。

    Args:
        conn: 已打开的只读 SQLite 连接。
        contracts: 表名到必需列集合的固定合同。

    Returns:
        仅包含固定表列名称的差异列表；空列表表示合同满足。
    """
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    problems: list[str] = []
    for table, required in contracts.items():
        if table not in tables:
            problems.append(f"缺少表 {table}")
            continue
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = sorted(required - columns)
        if missing:
            problems.append(f"表 {table} 缺少列 {', '.join(missing)}")
    return problems
