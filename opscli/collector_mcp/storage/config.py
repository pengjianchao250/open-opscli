"""Collector 采集结果沉淀配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR

# 控制 Collector 通用数据沉淀是否启用。
ENV_ENABLED = "OPSCLI_COLLECTOR_STORAGE_ENABLED"
# 标识数据由生产任务还是调试任务产生。
ENV_DATA_ENVIRONMENT = "OPSCLI_DATA_ENVIRONMENT"
# 覆盖 Collector 独立 Outbox SQLite 文件位置。
ENV_OUTBOX_DB_PATH = "OPSCLI_COLLECTOR_STORAGE_SQLITE_PATH"
# 控制启动时是否使用迁移账号创建 MySQL 表。
ENV_AUTO_CREATE_SCHEMA = "OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA"
# 控制单次 MySQL executemany 的记录数量。
ENV_BATCH_SIZE = "OPSCLI_COLLECTOR_STORAGE_BATCH_SIZE"
# 控制空 Outbox 的后台轮询间隔。
ENV_POLL_INTERVAL = "OPSCLI_COLLECTOR_STORAGE_POLL_INTERVAL_SECONDS"
# 控制来源成功任务补偿对账间隔。
ENV_RECONCILE_INTERVAL = "OPSCLI_COLLECTOR_STORAGE_RECONCILE_INTERVAL_SECONDS"
# 控制 Outbox processing 状态的持有期限。
ENV_LEASE_SECONDS = "OPSCLI_COLLECTOR_STORAGE_LEASE_SECONDS"
# 配置 Collector 可访问的 MySQL 内网主机。
ENV_MYSQL_HOST = "OPSCLI_COLLECTOR_MYSQL_HOST"
# 配置 MySQL TCP 端口。
ENV_MYSQL_PORT = "OPSCLI_COLLECTOR_MYSQL_PORT"
# 配置统一采集数据库名称。
ENV_MYSQL_DATABASE = "OPSCLI_COLLECTOR_MYSQL_DATABASE"
# 配置运行期最小权限 MySQL 账号。
ENV_MYSQL_USER = "OPSCLI_COLLECTOR_MYSQL_USER"
# 配置由 Secret 注入的 MySQL 密码。
ENV_MYSQL_PASSWORD = "OPSCLI_COLLECTOR_MYSQL_PASSWORD"
# 配置生产 MySQL TLS 服务端证书验证 CA 文件。
ENV_MYSQL_SSL_CA = "OPSCLI_COLLECTOR_MYSQL_SSL_CA"
# 控制 MySQL 首次连接超时秒数。
ENV_MYSQL_CONNECT_TIMEOUT = "OPSCLI_COLLECTOR_MYSQL_CONNECT_TIMEOUT_SECONDS"

# 默认批量大小在事务吞吐和单批内存之间取保守值。
DEFAULT_BATCH_SIZE = 500
# 默认轮询间隔避免空队列持续占用 CPU。
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
# 默认每分钟补偿一次成功态到 Outbox 的宕机窗口。
DEFAULT_RECONCILE_INTERVAL_SECONDS = 60.0
# 默认租约覆盖常规 SellerSprite 文件解析和数据库写入时长。
DEFAULT_LEASE_SECONDS = 300.0


@dataclass(frozen=True)
class MySqlSettings:
    """Collector 内网 MySQL 连接设置。"""

    host: str = ""
    port: int = 3306
    database: str = ""
    user: str = ""
    password: str = ""
    ssl_ca: str = ""
    connect_timeout_seconds: int = 10

    @property
    def configured(self) -> bool:
        """返回 MySQL 基础连接字段是否已经完整配置。"""
        return all((self.host, self.database, self.user, self.password))


@dataclass(frozen=True)
class CollectorStorageSettings:
    """Collector 通用沉淀运行配置。"""

    enabled: bool
    data_environment: str | None
    outbox_db_path: Path
    mysql: MySqlSettings
    auto_create_schema: bool = False
    batch_size: int = DEFAULT_BATCH_SIZE
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    reconcile_interval_seconds: float = DEFAULT_RECONCILE_INTERVAL_SECONDS
    lease_seconds: float = DEFAULT_LEASE_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含主机、账号、密码和本地路径的配置摘要。"""
        return {
            "enabled": self.enabled,
            "data_environment": self.data_environment,
            "mysql_configured": self.mysql.configured,
            "auto_create_schema": self.auto_create_schema,
            "batch_size": self.batch_size,
        }


def load_storage_settings(
    environ: Mapping[str, str] | None = None,
    *,
    config_dir: Path | None = None,
) -> CollectorStorageSettings:
    """加载并校验 Collector 存储配置。"""
    values = os.environ if environ is None else environ
    base_dir = Path(CONFIG_DIR if config_dir is None else config_dir)
    configured_outbox = str(values.get(ENV_OUTBOX_DB_PATH) or "").strip()
    outbox_path = (
        Path(configured_outbox).expanduser()
        if configured_outbox
        else base_dir / "collector" / "collection_storage.sqlite3"
    ).resolve()
    enabled = _parse_bool(values.get(ENV_ENABLED), False)
    data_environment = (
        str(values.get(ENV_DATA_ENVIRONMENT) or "").strip().lower() or None
    )
    mysql = MySqlSettings(
        host=str(values.get(ENV_MYSQL_HOST) or "").strip(),
        port=_parse_int(values.get(ENV_MYSQL_PORT), 3306),
        database=str(values.get(ENV_MYSQL_DATABASE) or "").strip(),
        user=str(values.get(ENV_MYSQL_USER) or "").strip(),
        password=str(values.get(ENV_MYSQL_PASSWORD) or ""),
        ssl_ca=str(values.get(ENV_MYSQL_SSL_CA) or "").strip(),
        connect_timeout_seconds=_parse_int(values.get(ENV_MYSQL_CONNECT_TIMEOUT), 10),
    )
    if enabled:
        if data_environment not in {"production", "debug"}:
            raise ValueError(
                "启用 Collector 数据沉淀时必须设置 "
                "OPSCLI_DATA_ENVIRONMENT=production 或 debug"
            )
        if not mysql.configured:
            raise ValueError("启用 Collector 数据沉淀时必须配置完整 MySQL 连接信息")
        if data_environment == "production" and not mysql.ssl_ca:
            raise ValueError(
                "生产数据沉淀必须设置 OPSCLI_COLLECTOR_MYSQL_SSL_CA 验证 MySQL TLS"
            )
    return CollectorStorageSettings(
        enabled=enabled,
        data_environment=data_environment,
        outbox_db_path=outbox_path,
        mysql=mysql,
        auto_create_schema=_parse_bool(values.get(ENV_AUTO_CREATE_SCHEMA), False),
        batch_size=_parse_int(values.get(ENV_BATCH_SIZE), DEFAULT_BATCH_SIZE),
        poll_interval_seconds=_parse_float(
            values.get(ENV_POLL_INTERVAL), DEFAULT_POLL_INTERVAL_SECONDS
        ),
        reconcile_interval_seconds=_parse_float(
            values.get(ENV_RECONCILE_INTERVAL), DEFAULT_RECONCILE_INTERVAL_SECONDS
        ),
        lease_seconds=_parse_float(
            values.get(ENV_LEASE_SECONDS), DEFAULT_LEASE_SECONDS
        ),
    )


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _parse_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
