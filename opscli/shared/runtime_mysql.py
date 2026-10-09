"""Shared MySQL settings for runtime stores migrating away from SQLite."""

from __future__ import annotations

import os
from collections.abc import Mapping

from opscli.shared.collection_storage.config import MySqlSettings


ENV_MYSQL_HOST = "OPSCLI_RUNTIME_MYSQL_HOST"
ENV_MYSQL_PORT = "OPSCLI_RUNTIME_MYSQL_PORT"
ENV_MYSQL_DATABASE = "OPSCLI_RUNTIME_MYSQL_DATABASE"
ENV_MYSQL_USER = "OPSCLI_RUNTIME_MYSQL_USER"
ENV_MYSQL_PASSWORD = "OPSCLI_RUNTIME_MYSQL_PASSWORD"
ENV_MYSQL_SSL_CA = "OPSCLI_RUNTIME_MYSQL_SSL_CA"
ENV_MYSQL_CONNECT_TIMEOUT = "OPSCLI_RUNTIME_MYSQL_CONNECT_TIMEOUT_SECONDS"

_COLLECTION_FALLBACK = {
    ENV_MYSQL_HOST: "OPSCLI_COLLECTION_MYSQL_HOST",
    ENV_MYSQL_PORT: "OPSCLI_COLLECTION_MYSQL_PORT",
    ENV_MYSQL_DATABASE: "OPSCLI_COLLECTION_MYSQL_DATABASE",
    ENV_MYSQL_USER: "OPSCLI_COLLECTION_MYSQL_USER",
    ENV_MYSQL_PASSWORD: "OPSCLI_COLLECTION_MYSQL_PASSWORD",
    ENV_MYSQL_SSL_CA: "OPSCLI_COLLECTION_MYSQL_SSL_CA",
    ENV_MYSQL_CONNECT_TIMEOUT: "OPSCLI_COLLECTION_MYSQL_CONNECT_TIMEOUT_SECONDS",
}


def load_runtime_mysql_settings(
    environ: Mapping[str, str] | None = None,
) -> MySqlSettings:
    """Load runtime-store MySQL settings with collection settings as fallback."""
    values = os.environ if environ is None else environ
    return MySqlSettings(
        host=str(_setting(values, ENV_MYSQL_HOST) or "").strip(),
        port=_positive_int(_setting(values, ENV_MYSQL_PORT), 3306),
        database=str(_setting(values, ENV_MYSQL_DATABASE) or "").strip(),
        user=str(_setting(values, ENV_MYSQL_USER) or "").strip(),
        password=str(_setting(values, ENV_MYSQL_PASSWORD) or ""),
        ssl_ca=str(_setting(values, ENV_MYSQL_SSL_CA) or "").strip(),
        connect_timeout_seconds=_positive_int(
            _setting(values, ENV_MYSQL_CONNECT_TIMEOUT),
            10,
        ),
    )


def _setting(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is not None and str(value).strip():
        return value
    return values.get(_COLLECTION_FALLBACK[name])


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
