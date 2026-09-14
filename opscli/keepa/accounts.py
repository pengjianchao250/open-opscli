"""Keepa API Key 来源。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from opscli.api_credentials.exceptions import ApiCredentialError
from opscli.api_credentials.models import ApiCredentialLease
from opscli.api_credentials.pool import ApiCredentialPool
from opscli.keepa.config import KeepaSettings, load_settings
from opscli.keepa.domain.exceptions import KeepaConfigError


@dataclass(frozen=True)
class KeepaApiKey:
    """Keepa API Key 记录。"""

    name: str
    api_key: str
    source: str
    account_id: int | None = None
    secret_version: int | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不暴露完整 key 的摘要。"""
        return {
            "name": self.name,
            "source": self.source,
            "account_id": self.account_id,
            "has_api_key": bool(self.api_key),
        }


class KeepaApiKeyProvider:
    """从 MySQL API 凭据池领取 Keepa Key，兜底环境变量。"""

    def __init__(
        self,
        settings: KeepaSettings | None = None,
        pool: ApiCredentialPool | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.pool = pool

    def get_default(
        self,
        *,
        refresh: bool = False,
        exclude_account_ids: set[int] | None = None,
    ) -> KeepaApiKey:
        """领取默认 Keepa API Key。"""
        del refresh
        try:
            lease = self._pool().acquire(
                "keepa",
                exclude_account_ids=exclude_account_ids,
            )
        except (ApiCredentialError, ValueError) as exc:
            if self.settings.api_key:
                return KeepaApiKey(
                    name=self.settings.account_name,
                    api_key=self.settings.api_key,
                    source="env",
                )
            raise KeepaConfigError(f"获取 Keepa API 账号失败：{exc}") from exc
        return KeepaApiKey(
            name=lease.account_name,
            api_key=lease.secret,
            source="api_credential_pool",
            account_id=lease.account_id,
            secret_version=lease.secret_version,
        )

    def report_success(self, credential: KeepaApiKey, quota: dict[str, Any]) -> None:
        """回写 Keepa 额度快照和成功状态。"""
        if credential.account_id is None:
            return
        self._pool().report_success(
            _lease(credential),
            runtime=_quota_runtime(quota),
        )

    def report_failure(
        self,
        credential: KeepaApiKey,
        exc: Exception,
        *,
        quota: dict[str, Any] | None = None,
    ) -> None:
        """回写账号错误；鉴权失败失效，额度不足进入短暂冷却。"""
        if credential.account_id is None:
            return
        status_code = getattr(exc, "status_code", None)
        error_code = str(getattr(exc, "code", type(exc).__name__))
        disable = status_code in {401, 403} or error_code in {
            "KEEPA_AUTH_ERROR",
            "KEEPA_FORBIDDEN",
        }
        quota_payload = dict(getattr(exc, "response_payload", None) or {})
        quota_payload.update(quota or {})
        runtime = _quota_runtime(quota_payload)
        if error_code in {"KEEPA_QUOTA_INSUFFICIENT", "KEEPA_RATE_LIMITED"}:
            cooldown_until = _cooldown_until(quota_payload, exc)
            if cooldown_until is not None:
                runtime["cooldown_until"] = cooldown_until
        self._pool().report_failure(
            _lease(credential),
            error_code=error_code,
            message=str(exc),
            disable=disable,
            exhausted=False,
            runtime=runtime,
        )

    def _pool(self) -> ApiCredentialPool:
        """延迟创建凭据池，使只读任务操作不依赖 MySQL 配置。"""
        if self.pool is None:
            self.pool = ApiCredentialPool()
        return self.pool


def _lease(credential: KeepaApiKey) -> ApiCredentialLease:
    return ApiCredentialLease(
        account_id=int(credential.account_id),
        provider="keepa",
        account_name=credential.name,
        secret=credential.api_key,
        secret_version=credential.secret_version or 1,
    )


def _quota_runtime(quota: dict[str, Any] | None) -> dict[str, Any]:
    payload = quota if isinstance(quota, dict) else {}
    runtime: dict[str, Any] = {}
    tokens_left = _optional_int(payload.get("tokensLeft"))
    if tokens_left is not None:
        runtime["remaining_quota"] = tokens_left
    return runtime


def _cooldown_until(quota: dict[str, Any], exc: Exception) -> datetime | None:
    refill_in = quota.get("refillIn")
    if refill_in is None:
        refill_in = getattr(exc, "refill_in_ms", None)
    try:
        milliseconds = max(0.0, float(refill_in))
    except (TypeError, ValueError):
        return None
    return datetime.now(UTC) + timedelta(milliseconds=milliseconds, seconds=1)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
