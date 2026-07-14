from opscli.seller_sprite import accounts as accounts_module
from opscli.seller_sprite.accounts import SellerSpriteAccountProvider
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountRecord


class FakeIntegrationClient:
    calls = 0

    def get_accounts(self, platform: str) -> IntegrationAccountBundle:
        self.calls += 1
        return IntegrationAccountBundle(
            platform=platform,
            default_account="default",
            accounts=(
                IntegrationAccountRecord(
                    name="default",
                    username="user@example.com",
                    password="secret",
                ),
            ),
        )


def test_account_provider_reuses_remote_bundle_cache():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    client = FakeIntegrationClient()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)

    first = SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()
    second = SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()

    assert first.username == "user@example.com"
    assert second.username == "user@example.com"
    assert client.calls == 1


def test_account_provider_refresh_bypasses_remote_bundle_cache():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    client = FakeIntegrationClient()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)
    provider = SellerSpriteAccountProvider(settings=settings, integration_client=client)

    provider.get_default()
    provider.get_default(refresh=True)

    assert client.calls == 2


def test_account_provider_lists_all_remote_accounts_in_api_order():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()

    class MultiAccountClient:
        def get_accounts(self, platform: str) -> IntegrationAccountBundle:
            return IntegrationAccountBundle(
                platform=platform,
                default_account="account-2",
                accounts=tuple(
                    IntegrationAccountRecord(
                        name=f"account-{index}",
                        username=f"user-{index}@example.com",
                        password=f"secret-{index}",
                    )
                    for index in range(1, 4)
                ),
            )

    provider = SellerSpriteAccountProvider(
        settings=SellerSpriteSettings(account_cache_ttl_seconds=600),
        integration_client=MultiAccountClient(),
    )

    accounts = provider.list_accounts()

    assert [account.name for account in accounts] == ["account-1", "account-2", "account-3"]
    assert [account.username for account in accounts] == [
        "user-1@example.com",
        "user-2@example.com",
        "user-3@example.com",
    ]


def test_account_provider_lists_local_pool_when_remote_is_empty():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()

    class EmptyAccountClient:
        def get_accounts(self, platform: str) -> IntegrationAccountBundle:
            return IntegrationAccountBundle(platform=platform, default_account=None, accounts=())

    settings = SellerSpriteSettings(
        accounts=(
            {"name": "local-1", "username": "local-1@example.com", "password": "secret-1"},
            {"name": "local-2", "username": "local-2@example.com", "password": "secret-2"},
        )
    )
    provider = SellerSpriteAccountProvider(settings=settings, integration_client=EmptyAccountClient())

    accounts = provider.list_accounts()

    assert [account.name for account in accounts] == ["local-1", "local-2"]
