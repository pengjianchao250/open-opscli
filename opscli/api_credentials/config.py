"""第三方 API 凭据池 MySQL 配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from opscli.api_credentials.exceptions import ApiCredentialConfigError


# MySQL 连接信息由后端部署系统注入，不能复用业务模块的数据库账号。
ENV_MYSQL_HOST = "OPSCLI_API_CREDENTIAL_MYSQL_HOST"
ENV_MYSQL_PORT = "OPSCLI_API_CREDENTIAL_MYSQL_PORT"
ENV_MYSQL_DATABASE = "OPSCLI_API_CREDENTIAL_MYSQL_DATABASE"
ENV_MYSQL_USER = "OPSCLI_API_CREDENTIAL_MYSQL_USER"
ENV_MYSQL_PASSWORD = "OPSCLI_API_CREDENTIAL_MYSQL_PASSWORD"
ENV_MYSQL_SSL_CA = "OPSCLI_API_CREDENTIAL_MYSQL_SSL_CA"
ENV_MYSQL_CONNECT_TIMEOUT = "OPSCLI_API_CREDENTIAL_MYSQL_CONNECT_TIMEOUT_SECONDS"
@dataclass(frozen=True)
class ApiCredentialMySqlSettings:
    """凭据池 MySQL 连接参数。"""

    host: str = ""
    port: int = 3306
    database: str = ""
    user: str = ""
    password: str = ""
    ssl_ca: str = ""
    connect_timeout_seconds: int = 10

    @property
    def configured(self) -> bool:
        """判断运行期 MySQL 连接字段是否完整。

        Returns:
            主机、库名、用户名和密码均存在时返回 ``True``。
        """
        return all((self.host, self.database, self.user, self.password))


@dataclass(frozen=True)
class ApiCredentialSettings:
    """凭据池完整运行配置。"""

    mysql: ApiCredentialMySqlSettings

    def validate_mysql(self) -> None:
        """校验 MySQL 连接配置。

        Returns:
            无。

        Raises:
            ApiCredentialConfigError: MySQL 连接字段不完整。
        """
        if not self.mysql.configured:
            raise ApiCredentialConfigError("API 凭据池未配置完整 MySQL 连接信息")

    def validate(self) -> None:
        """校验后端启动所需的数据库配置。

        Returns:
            无。

        Raises:
            ApiCredentialConfigError: MySQL 字段缺失。
        """
        self.validate_mysql()

    def to_public_dict(self) -> dict[str, Any]:
        """返回不含地址和密码的配置摘要。

        Returns:
            仅包含数据库是否就绪的字典。
        """
        return {"mysql_configured": self.mysql.configured}


def load_settings(environ: Mapping[str, str] | None = None) -> ApiCredentialSettings:
    """从部署环境加载凭据池配置。

    Args:
        environ: 可注入的环境变量映射；为空时读取当前进程环境。

    Returns:
        尚未执行完整性校验的凭据池配置。
    """
    values = os.environ if environ is None else environ
    return ApiCredentialSettings(
        mysql=ApiCredentialMySqlSettings(
            host=str(values.get(ENV_MYSQL_HOST) or "").strip(),
            port=_parse_int(values.get(ENV_MYSQL_PORT), 3306),
            database=str(values.get(ENV_MYSQL_DATABASE) or "").strip(),
            user=str(values.get(ENV_MYSQL_USER) or "").strip(),
            password=str(values.get(ENV_MYSQL_PASSWORD) or ""),
            ssl_ca=str(values.get(ENV_MYSQL_SSL_CA) or "").strip(),
            connect_timeout_seconds=_parse_int(values.get(ENV_MYSQL_CONNECT_TIMEOUT), 10),
        ),
    )


def _parse_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
