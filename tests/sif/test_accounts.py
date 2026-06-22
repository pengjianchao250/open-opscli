from opscli.sif.accounts import SifAccountProvider
from opscli.sif.config import SifSettings


def test_sif_account_provider_uses_env_settings_without_remote():
    class FakeIntegrationClient:
        def get_accounts(self, platform):
            raise RuntimeError("remote unavailable")

    provider = SifAccountProvider(
        SifSettings(username="user1", password="secret1"),
        integration_client=FakeIntegrationClient(),
    )

    account = provider.get_default()

    assert account.username == "user1"
    assert account.password == "secret1"
    assert account.to_public_dict() == {
        "name": "default",
        "username": "use***r1",
        "has_password": True,
    }
