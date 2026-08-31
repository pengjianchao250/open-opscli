"""SerpAPI 统一 MySQL 凭据池适配器测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
import respx

from opscli.api_credentials.models import ApiCredentialAccount
from opscli.google_trends.api.mysql_key_store import MySqlSerpApiKeyStore
from opscli.google_trends.api.serpapi_client import SerpApiGoogleTrendsClient


class _InMemorySerpApiRepository:
    """模拟 MySQL 仓储返回值，验证适配器而不依赖真实数据库。"""

    def __init__(self, *accounts: ApiCredentialAccount) -> None:
        """保存测试账号。

        Args:
            accounts: 预置的统一凭据账号。
        """
        self.accounts = {account.account_id: account for account in accounts}

    def get_account(self, account_id: int) -> ApiCredentialAccount | None:
        """按 ID 返回账号。"""
        return self.accounts.get(account_id)

    def get_account_by_name(self, provider: str, name: str) -> ApiCredentialAccount | None:
        """按 Provider 和名称返回账号。"""
        return next(
            (
                account
                for account in self.accounts.values()
                if account.provider == provider and account.name == name
            ),
            None,
        )

    def list_accounts(self, provider: str | None = None) -> list[ApiCredentialAccount]:
        """按优先级返回账号列表。"""
        accounts = [
            account
            for account in self.accounts.values()
            if provider is None or account.provider == provider
        ]
        return sorted(accounts, key=lambda account: (account.priority, account.account_id))

    def acquire(
        self,
        provider: str,
        *,
        exclude_account_ids: set[int] | None = None,
    ) -> ApiCredentialAccount | None:
        """领取未排除的首个活动账号。"""
        excluded = exclude_account_ids or set()
        return next(
            (
                account
                for account in self.list_accounts(provider)
                if account.status == "active" and account.account_id not in excluded
            ),
            None,
        )

    def next_due_exhausted(
        self,
        provider: str,
        *,
        exclude_account_ids: set[int] | None = None,
    ) -> ApiCredentialAccount | None:
        """返回测试中已经到续期日的耗尽账号。"""
        excluded = exclude_account_ids or set()
        return next(
            (
                account
                for account in self.list_accounts(provider)
                if account.status == "exhausted"
                and account.account_id not in excluded
                and account.quota_reset_at is not None
                and account.quota_reset_at <= "2000-01-02"
            ),
            None,
        )

    def update_runtime(self, account_id: int, values: dict[str, object]) -> None:
        """将运行状态字段写回不可变账号模型。"""
        self.accounts[account_id] = replace(self.accounts[account_id], **values)

    def set_status(self, account_id: int, status: str) -> None:
        """更新账号状态。"""
        self.accounts[account_id] = replace(self.accounts[account_id], status=status)


def _account(
    account_id: int,
    name: str,
    api_key: str,
    *,
    status: str = "active",
    priority: int = 100,
    quota_reset_at: str | None = None,
    provider_metadata: dict[str, object] | None = None,
) -> ApiCredentialAccount:
    """构造一条统一凭据账号记录。"""
    return ApiCredentialAccount(
        account_id=account_id,
        provider="serpapi",
        name=name,
        api_key=api_key,
        api_key_masked="secr****-key",
        status=status,
        priority=priority,
        quota_reset_at=quota_reset_at,
        provider_metadata=provider_metadata,
    )


def test_mysql_adapter_maps_runtime_status_and_provider_metadata() -> None:
    """MySQL 运行字段应完整映射到 Google Trends 兼容记录。"""
    repository = _InMemorySerpApiRepository(
        _account(
            1,
            "primary",
            "secret-primary-key",
            provider_metadata={"plan_name": "Developer"},
        )
    )
    store = MySqlSerpApiKeyStore(repository=repository)

    updated = store.update_account_snapshot(
        "1",
        {
            "total_searches_left": 23,
            "this_month_usage": 7,
            "plan_name": "Production",
            "plan_renewal_date": "2026-09-01",
        },
    )

    assert updated.total_searches_left == 23
    assert updated.this_month_usage == 7
    assert updated.plan_name == "Production"
    assert updated.plan_renewal_date == "2026-09-01"
    assert isinstance(repository.accounts[1].last_verified_at, datetime)

    store.mark_exhausted("1", reason="额度为 0")
    exhausted = store.get("1")
    assert exhausted is not None
    assert exhausted.status == "exhausted"
    assert exhausted.total_searches_left == 0
    assert exhausted.exhausted_at is not None
    assert repository.accounts[1].last_error_code == "quota_exhausted"

    store.restore_active("1")
    restored = store.get("1")
    assert restored is not None
    assert restored.status == "active"
    assert restored.exhausted_at is None


@pytest.mark.parametrize("status_code", [401, 403])
@respx.mock(assert_all_called=False)
def test_mysql_adapter_rotates_to_second_account_after_auth_failure(
    respx_mock,
    status_code: int,
) -> None:
    """首账号认证失败时应禁用它，并在同一请求切换到第二账号。"""
    repository = _InMemorySerpApiRepository(
        _account(1, "primary", "secret-invalid-key", priority=10),
        _account(2, "backup", "secret-live-key", priority=20),
    )
    store = MySqlSerpApiKeyStore(repository=repository)
    search_keys: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_key = request.url.params.get("api_key")
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"total_searches_left": 5})
        search_keys.append(api_key)
        if api_key == "secret-invalid-key":
            return httpx.Response(status_code, json={"error": "invalid credential"})
        return httpx.Response(200, json={"suggestions": [{"title": "Apple"}]})

    respx_mock.get(path="/account.json").mock(side_effect=handler)
    respx_mock.get(path="/search").mock(side_effect=handler)
    client = SerpApiGoogleTrendsClient(key_store=store)

    payload = client.run("autocomplete", {"q": "Apple"})

    assert payload["suggestions"][0]["title"] == "Apple"
    assert search_keys == ["secret-invalid-key", "secret-live-key"]
    assert repository.accounts[1].status == "disabled"
    assert repository.accounts[2].status == "active"
    assert "secret-invalid-key" not in str(store.get("1").to_public_dict())


@respx.mock(assert_all_called=False)
def test_mysql_adapter_restores_due_exhausted_account(respx_mock) -> None:
    """续期日已到且额度恢复时，应重新启用耗尽账号并完成当前搜索。"""
    repository = _InMemorySerpApiRepository(
        _account(
            1,
            "renewed",
            "secret-renewed-key",
            status="exhausted",
            quota_reset_at="2000-01-01",
            provider_metadata={
                "plan_renewal_date": "2000-01-01",
                "exhausted_at": "1999-12-31T00:00:00+00:00",
            },
        )
    )
    store = MySqlSerpApiKeyStore(repository=repository)
    respx_mock.get(path="/account.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_searches_left": 100,
                "this_month_usage": 0,
                "plan_renewal_date": "2099-01-01",
            },
        )
    )
    respx_mock.get(path="/search").mock(
        return_value=httpx.Response(200, json={"trending_searches": []})
    )
    client = SerpApiGoogleTrendsClient(key_store=store)

    payload = client.run("trending-now", {"geo": "US"})

    assert payload == {"trending_searches": []}
    restored = store.get("1")
    assert restored is not None
    assert restored.status == "active"
    assert restored.total_searches_left == 100
    assert restored.this_month_usage == 0
    assert restored.plan_renewal_date == "2099-01-01"
    assert restored.exhausted_at is None
    assert repository.accounts[1].last_used_at is not None
    assert repository.accounts[1].last_verified_at.tzinfo is UTC
