"""预取计划后台调度配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_ENABLED = "OPSCLI_PREFETCH_SCHEDULER_ENABLED"
ENV_POLL_INTERVAL = "OPSCLI_PREFETCH_POLL_INTERVAL_SECONDS"
ENV_LEASE_SECONDS = "OPSCLI_PREFETCH_LEASE_SECONDS"
ENV_SERVICE_CREDENTIAL_SCOPE = "OPSCLI_PREFETCH_SERVICE_CREDENTIAL_SCOPE"
ENV_SERVICE_USER_EMAIL = "OPSCLI_PREFETCH_SERVICE_USER_EMAIL"

DEFAULT_POLL_INTERVAL_SECONDS = 15.0
DEFAULT_LEASE_SECONDS = 1800.0


@dataclass(frozen=True)
class PrefetchScheduleSettings:
    """预取调度器运行配置，不包含任何明文凭证。"""

    enabled: bool = False
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    service_credential_scope: str | None = None
    service_user_email: str | None = None


def load_prefetch_settings(
    environ: Mapping[str, str] | None = None,
) -> PrefetchScheduleSettings:
    """从环境变量读取预取调度器配置。"""
    values = os.environ if environ is None else environ
    scope = str(values.get(ENV_SERVICE_CREDENTIAL_SCOPE) or "").strip() or None
    email = str(values.get(ENV_SERVICE_USER_EMAIL) or "").strip().lower() or None
    return PrefetchScheduleSettings(
        enabled=_parse_bool(values.get(ENV_ENABLED), False),
        poll_interval_seconds=_parse_float(
            values.get(ENV_POLL_INTERVAL), DEFAULT_POLL_INTERVAL_SECONDS
        ),
        lease_seconds=_parse_float(values.get(ENV_LEASE_SECONDS), DEFAULT_LEASE_SECONDS),
        service_credential_scope=scope,
        service_user_email=email,
    )


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
