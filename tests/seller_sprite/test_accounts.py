from opscli.seller_sprite import accounts as accounts_module
from opscli.seller_sprite.accounts import SellerSpriteAccountProvider
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountRecord


class FakeIntegrationClient:
    def __init__(
        self,
        *,
        identity: str = "test-user",
        username: str = "user@example.com",
    ) -> None:
        self.identity = identity
        self.username = username
        self.calls = 0

    def cache_identity(self) -> str:
        return self.identity

    def get_accounts(self, platform: str) -> IntegrationAccountBundle:
        self.calls += 1
        return IntegrationAccountBundle(
            platform=platform,
            default_account="default",
            accounts=(
                IntegrationAccountRecord(
                    name="default",
                    username=self.username,
                    password="secret",
                ),
            ),
        )


class NoIdentityIntegrationClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_accounts(self, platform: str) -> IntegrationAccountBundle:
        self.calls += 1
        return IntegrationAccountBundle(
            platform=platform,
            default_account="default",
            accounts=(
                IntegrationAccountRecord(
                    name="default",
                    username="legacy@example.com",
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


def test_account_provider_reuses_platform_cache_across_authenticated_users():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)
    first_client = FakeIntegrationClient(identity="user-a", username="shared@example.com")
    second_client = FakeIntegrationClient(identity="user-b", username="shared@example.com")

    first = SellerSpriteAccountProvider(settings=settings, integration_client=first_client).get_default()
    second = SellerSpriteAccountProvider(settings=settings, integration_client=second_client).get_default()

    assert first.username == "shared@example.com"
    assert second.username == "shared@example.com"
    assert first_client.calls == 1
    assert second_client.calls == 0


def test_account_provider_without_identity_reuses_platform_cache():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)
    client = NoIdentityIntegrationClient()

    SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()
    SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()

    assert client.calls == 1


def test_account_provider_removes_expired_platform_cache(monkeypatch):
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    expired_bundle = IntegrationAccountBundle(
        platform="seller_sprite",
        default_account="default",
        accounts=(),
    )
    accounts_module._REMOTE_BUNDLE_CACHE["seller_sprite"] = (0, expired_bundle)
    monkeypatch.setattr(accounts_module.time, "time", lambda: 1000)
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)

    client = FakeIntegrationClient(identity="current-user")
    SellerSpriteAccountProvider(
        settings=settings,
        integration_client=client,
    ).get_default()

    assert client.calls == 1
