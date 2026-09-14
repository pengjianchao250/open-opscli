"""Keepa API Key 来源回归测试。"""

from datetime import datetime

import pytest

from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.api_credentials.models import ApiCredentialLease
from opscli.keepa.accounts import KeepaApiKeyProvider
from opscli.keepa.config import KeepaSettings
from opscli.keepa.domain.exceptions import KeepaApiError, KeepaConfigError, KeepaQuotaError


class _FakePool:
    def __init__(self, lease=None, error=None):
        self.lease = lease
        self.error = error
        self.acquire_calls = []
        self.successes = []
        self.failures = []

    def acquire(self, provider, *, exclude_account_ids=None):
        self.acquire_calls.append((provider, exclude_account_ids))
        if self.error:
            raise self.error
        return self.lease

    def report_success(self, lease, *, runtime):
        self.successes.append((lease, runtime))

    def report_failure(self, lease, **kwargs):
        self.failures.append((lease, kwargs))


def _lease():
    return ApiCredentialLease(
        account_id=12,
        provider="keepa",
        account_name="keepa-primary",
        secret="mysql-keepa-key",
        secret_version=3,
    )


def test_provider_acquires_keepa_account_from_mysql_pool():
    pool = _FakePool(lease=_lease())
    provider = KeepaApiKeyProvider(settings=KeepaSettings(), pool=pool)

    credential = provider.get_default(exclude_account_ids={7})

    assert credential.name == "keepa-primary"
    assert credential.api_key == "mysql-keepa-key"
    assert credential.source == "api_credential_pool"
    assert credential.account_id == 12
    assert credential.secret_version == 3
    assert pool.acquire_calls == [("keepa", {7})]
    assert "mysql-keepa-key" not in str(credential.to_public_dict())


def test_environment_key_falls_back_when_mysql_pool_is_unavailable():
    provider = KeepaApiKeyProvider(
        settings=KeepaSettings(api_key="local-keepa-key"),
        pool=_FakePool(error=ApiCredentialUnavailableError("没有可用账号")),
    )

    credential = provider.get_default(refresh=True)

    assert credential.api_key == "local-keepa-key"
    assert credential.source == "env"
    assert credential.account_id is None


def test_provider_maps_missing_mysql_account_to_keepa_config_error():
    provider = KeepaApiKeyProvider(
        settings=KeepaSettings(api_key=None),
        pool=_FakePool(error=ApiCredentialUnavailableError("没有可用账号")),
    )

    with pytest.raises(KeepaConfigError, match="获取 Keepa API 账号失败"):
        provider.get_default()


def test_provider_reports_success_and_quota_cooldown_without_leaking_key():
    pool = _FakePool(lease=_lease())
    provider = KeepaApiKeyProvider(settings=KeepaSettings(), pool=pool)
    credential = provider.get_default()

    provider.report_success(
        credential,
        {"tokensLeft": 91, "refillIn": 5000, "refillRate": 5, "timestamp": 123},
    )
    provider.report_failure(
        credential,
        KeepaQuotaError("额度不足", tokens_left=1, refill_in_ms=5000),
        quota={"tokensLeft": 1, "refillIn": 5000, "refillRate": 5},
    )

    assert pool.successes[0][1]["remaining_quota"] == 91
    failure = pool.failures[0][1]
    assert failure["disable"] is False
    assert failure["exhausted"] is False
    assert failure["runtime"]["remaining_quota"] == 1
    assert isinstance(failure["runtime"]["cooldown_until"], datetime)


def test_provider_marks_unauthorized_mysql_account_invalid():
    pool = _FakePool(lease=_lease())
    provider = KeepaApiKeyProvider(settings=KeepaSettings(), pool=pool)
    credential = provider.get_default()

    provider.report_failure(
        credential,
        KeepaApiError("invalid key", status_code=401),
    )

    failure = pool.failures[0][1]
    assert failure["error_code"] == "KEEPA_AUTH_ERROR"
    assert failure["disable"] is True
    assert failure["exhausted"] is False
