"""MCP 宿主共享的采集结果沉淀配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from opscli.config import CONFIG_DIR

# 控制所有 MCP 宿主的通用数据沉淀是否启用。
ENV_ENABLED = "OPSCLI_COLLECTION_STORAGE_ENABLED"
# 标识数据由生产任务还是调试任务产生。
ENV_DATA_ENVIRONMENT = "OPSCLI_DATA_ENVIRONMENT"
# 覆盖宿主独立 Outbox SQLite 文件所在目录。
ENV_OUTBOX_DIR = "OPSCLI_COLLECTION_STORAGE_SQLITE_DIR"
# 控制启动时是否使用迁移账号创建 MySQL 表。
ENV_AUTO_CREATE_SCHEMA = "OPSCLI_COLLECTION_STORAGE_AUTO_CREATE_SCHEMA"
# 控制单次 MySQL executemany 的记录数量。
ENV_BATCH_SIZE = "OPSCLI_COLLECTION_STORAGE_BATCH_SIZE"
# 控制空 Outbox 的后台轮询间隔。
ENV_POLL_INTERVAL = "OPSCLI_COLLECTION_STORAGE_POLL_INTERVAL_SECONDS"
# 控制来源成功任务补偿对账间隔。
ENV_RECONCILE_INTERVAL = "OPSCLI_COLLECTION_STORAGE_RECONCILE_INTERVAL_SECONDS"
# 控制 Outbox processing 状态的持有期限。
ENV_LEASE_SECONDS = "OPSCLI_COLLECTION_STORAGE_LEASE_SECONDS"
# 配置 MCP 宿主可访问的 MySQL 主机。
ENV_MYSQL_HOST = "OPSCLI_COLLECTION_MYSQL_HOST"
# 配置 MySQL TCP 端口。
ENV_MYSQL_PORT = "OPSCLI_COLLECTION_MYSQL_PORT"
# 配置统一采集数据库名称。
ENV_MYSQL_DATABASE = "OPSCLI_COLLECTION_MYSQL_DATABASE"
# 配置运行期最小权限 MySQL 账号。
ENV_MYSQL_USER = "OPSCLI_COLLECTION_MYSQL_USER"
# 配置由 Secret 注入的 MySQL 密码。
ENV_MYSQL_PASSWORD = "OPSCLI_COLLECTION_MYSQL_PASSWORD"
# 可选配置 MySQL TLS 服务端证书验证 CA 文件。
ENV_MYSQL_SSL_CA = "OPSCLI_COLLECTION_MYSQL_SSL_CA"
# 控制 MySQL 首次连接超时秒数。
ENV_MYSQL_CONNECT_TIMEOUT = "OPSCLI_COLLECTION_MYSQL_CONNECT_TIMEOUT_SECONDS"

_LEGACY_ENV: Mapping[str, str] = MappingProxyType({
    ENV_ENABLED: "OPSCLI_COLLECTOR_STORAGE_ENABLED",
    ENV_AUTO_CREATE_SCHEMA: "OPSCLI_COLLECTOR_STORAGE_AUTO_CREATE_SCHEMA",
    ENV_BATCH_SIZE: "OPSCLI_COLLECTOR_STORAGE_BATCH_SIZE",
    ENV_POLL_INTERVAL: "OPSCLI_COLLECTOR_STORAGE_POLL_INTERVAL_SECONDS",
    ENV_RECONCILE_INTERVAL: "OPSCLI_COLLECTOR_STORAGE_RECONCILE_INTERVAL_SECONDS",
    ENV_LEASE_SECONDS: "OPSCLI_COLLECTOR_STORAGE_LEASE_SECONDS",
    ENV_MYSQL_HOST: "OPSCLI_COLLECTOR_MYSQL_HOST",
    ENV_MYSQL_PORT: "OPSCLI_COLLECTOR_MYSQL_PORT",
    ENV_MYSQL_DATABASE: "OPSCLI_COLLECTOR_MYSQL_DATABASE",
    ENV_MYSQL_USER: "OPSCLI_COLLECTOR_MYSQL_USER",
    ENV_MYSQL_PASSWORD: "OPSCLI_COLLECTOR_MYSQL_PASSWORD",
    ENV_MYSQL_SSL_CA: "OPSCLI_COLLECTOR_MYSQL_SSL_CA",
    ENV_MYSQL_CONNECT_TIMEOUT: "OPSCLI_COLLECTOR_MYSQL_CONNECT_TIMEOUT_SECONDS",
})
_LEGACY_OUTBOX_PATH = "OPSCLI_COLLECTOR_STORAGE_SQLITE_PATH"

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
    """共享采集 MySQL 连接设置。"""

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
class CollectionStorageSettings:
    """单个 MCP 宿主的通用沉淀运行配置。"""

    enabled: bool
    data_environment: str | None
    outbox_db_path: Path
    mysql: MySqlSettings
    runtime_id: str = "collector"
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
    runtime_id: str,
    environ: Mapping[str, str] | None = None,
    *,
    config_dir: Path | None = None,
) -> CollectionStorageSettings:
    """加载共享数据库配置，并为每个 MCP 宿主分配独立 Outbox。"""
    values = os.environ if environ is None else environ
    base_dir = Path(CONFIG_DIR if config_dir is None else config_dir)
    normalized_runtime = _normalize_runtime_id(runtime_id)
    configured_outbox_dir = str(values.get(ENV_OUTBOX_DIR) or "").strip()
    legacy_outbox_path = str(values.get(_LEGACY_OUTBOX_PATH) or "").strip()
    if configured_outbox_dir:
        outbox_path = (
            Path(configured_outbox_dir).expanduser()
            / f"{normalized_runtime}.sqlite3"
        )
    elif normalized_runtime == "collector" and legacy_outbox_path:
        outbox_path = Path(legacy_outbox_path).expanduser()
    else:
        outbox_path = base_dir / "collection_storage" / f"{normalized_runtime}.sqlite3"
    outbox_path = outbox_path.resolve()
    enabled = _parse_bool(_setting(values, ENV_ENABLED), False)
    data_environment = (
        str(values.get(ENV_DATA_ENVIRONMENT) or "").strip().lower() or None
    )
    mysql = MySqlSettings(
        host=str(_setting(values, ENV_MYSQL_HOST) or "").strip(),
        port=_parse_int(_setting(values, ENV_MYSQL_PORT), 3306),
        database=str(_setting(values, ENV_MYSQL_DATABASE) or "").strip(),
        user=str(_setting(values, ENV_MYSQL_USER) or "").strip(),
        password=str(_setting(values, ENV_MYSQL_PASSWORD) or ""),
        ssl_ca=str(_setting(values, ENV_MYSQL_SSL_CA) or "").strip(),
        connect_timeout_seconds=_parse_int(
            _setting(values, ENV_MYSQL_CONNECT_TIMEOUT),
            10,
        ),
    )
    if enabled:
        if data_environment not in {"production", "debug"}:
            raise ValueError(
                "启用采集数据沉淀时必须设置 "
                "OPSCLI_DATA_ENVIRONMENT=production 或 debug"
            )
        if not mysql.configured:
            raise ValueError("启用采集数据沉淀时必须配置完整 MySQL 连接信息")
    return CollectionStorageSettings(
        enabled=enabled,
        data_environment=data_environment,
        outbox_db_path=outbox_path,
        mysql=mysql,
        runtime_id=normalized_runtime,
        auto_create_schema=_parse_bool(
            _setting(values, ENV_AUTO_CREATE_SCHEMA),
            False,
        ),
        batch_size=_parse_int(_setting(values, ENV_BATCH_SIZE), DEFAULT_BATCH_SIZE),
        poll_interval_seconds=_parse_float(
            _setting(values, ENV_POLL_INTERVAL), DEFAULT_POLL_INTERVAL_SECONDS
        ),
        reconcile_interval_seconds=_parse_float(
            _setting(values, ENV_RECONCILE_INTERVAL),
            DEFAULT_RECONCILE_INTERVAL_SECONDS,
        ),
        lease_seconds=_parse_float(
            _setting(values, ENV_LEASE_SECONDS), DEFAULT_LEASE_SECONDS
        ),
    )


def _setting(values: Mapping[str, str], name: str) -> str | None:
    """优先读取共享配置，并兼容已有 Collector 环境变量。"""
    if name in values:
        return values.get(name)
    legacy_name = _LEGACY_ENV.get(name)
    return values.get(legacy_name) if legacy_name else None


def _normalize_runtime_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or any(
        not (char.isalnum() or char in "-_") for char in normalized
    ):
        raise ValueError("collection storage runtime_id 只能包含字母、数字、- 和 _")
    return normalized


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
