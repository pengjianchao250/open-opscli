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
