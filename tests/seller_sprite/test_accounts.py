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


def test_account_provider_cache_is_isolated_by_authenticated_user():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)
    first_client = FakeIntegrationClient(identity="user-a", username="a@example.com")
    second_client = FakeIntegrationClient(identity="user-b", username="b@example.com")

    first = SellerSpriteAccountProvider(settings=settings, integration_client=first_client).get_default()
    second = SellerSpriteAccountProvider(settings=settings, integration_client=second_client).get_default()

    assert first.username == "a@example.com"
    assert second.username == "b@example.com"
    assert first_client.calls == 1
    assert second_client.calls == 1


def test_account_provider_without_identity_does_not_use_global_cache():
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)
    client = NoIdentityIntegrationClient()

    SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()
    SellerSpriteAccountProvider(settings=settings, integration_client=client).get_default()

    assert client.calls == 2
    assert accounts_module._REMOTE_BUNDLE_CACHE == {}


def test_account_provider_removes_expired_identity_cache(monkeypatch):
    accounts_module._REMOTE_BUNDLE_CACHE.clear()
    expired_bundle = IntegrationAccountBundle(
        platform="seller_sprite",
        default_account="default",
        accounts=(),
    )
    accounts_module._REMOTE_BUNDLE_CACHE[("seller_sprite", "expired-user")] = (0, expired_bundle)
    monkeypatch.setattr(accounts_module.time, "time", lambda: 1000)
    settings = SellerSpriteSettings(account_cache_ttl_seconds=600)

    SellerSpriteAccountProvider(
        settings=settings,
        integration_client=FakeIntegrationClient(identity="current-user"),
    ).get_default()

    assert ("seller_sprite", "expired-user") not in accounts_module._REMOTE_BUNDLE_CACHE
