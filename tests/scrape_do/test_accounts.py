"""Scrape.do 统一凭据池账号来源测试。"""

from types import SimpleNamespace

import pytest

from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.api_credentials.models import ApiCredentialLease
from opscli.scrape_do.accounts import ScrapeDoCredentialProvider
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError


class FakePool:
    def __init__(self):
        self.successes = []
        self.failures = []

    def acquire(self, provider, *, exclude_account_ids=None):
        assert provider == "scrape_do"
        return ApiCredentialLease(
            account_id=12,
            provider=provider,
            account_name="backup-2",
            secret="scrape-secret",
            secret_version=4,
        )

    def report_success(self, lease, *, runtime):
        self.successes.append((lease, runtime))

    def report_failure(self, lease, **kwargs):
        self.failures.append((lease, kwargs))


def test_provider_returns_pool_account_and_reports_billing():
    pool = FakePool()
    provider = ScrapeDoCredentialProvider(pool=pool)

    credential = provider.get_default()
    provider.report_success(credential, {"remaining_credits": 88})

    assert credential.name == "backup-2"
    assert credential.token == "scrape-secret"
    assert credential.account_id == 12
    assert credential.secret_version == 4
    assert pool.successes[0][1] == {"remaining_quota": 88}


def test_provider_marks_unauthorized_account_invalid():
    pool = FakePool()
    provider = ScrapeDoCredentialProvider(pool=pool)
    credential = provider.get_default()

    provider.report_failure(
        credential,
        SimpleNamespace(status_code=401, __str__=lambda self: "unauthorized"),
    )

    assert pool.failures[0][1]["disable"] is True


def test_provider_maps_unavailable_pool_account_to_module_config_error():
    """凭据池没有可用账号时应返回 scrape.do 稳定配置异常。"""

    class EmptyPool(FakePool):
        def acquire(self, provider, *, exclude_account_ids=None):
            raise ApiCredentialUnavailableError("没有可用账号")

    provider = ScrapeDoCredentialProvider(pool=EmptyPool())

    with pytest.raises(ScrapeDoConfigError, match="获取 Scrape.do API 账号失败"):
        provider.get_default()
