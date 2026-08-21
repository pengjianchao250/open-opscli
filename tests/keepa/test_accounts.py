"""Keepa API Key 来源回归测试。"""

from opscli.auth.domain.exceptions import TokenFetchError
from opscli.keepa.accounts import KeepaApiKeyProvider
from opscli.keepa.config import KeepaSettings


class _AuthFailingIntegrationClient:
    """模拟 OPS 登录态失效的集成账号客户端。"""

    def get_accounts(self, platform: str) -> None:
        """抛出认证异常，验证本地 Key 仍可兜底。"""
        raise TokenFetchError(f"获取 {platform} 集成账号需要重新登录")


def test_environment_key_falls_back_when_ops_authentication_fails():
    provider = KeepaApiKeyProvider(
        settings=KeepaSettings(api_key="local-keepa-key"),
        integration_client=_AuthFailingIntegrationClient(),
    )

    credential = provider.get_default(refresh=True)

    assert credential.api_key == "local-keepa-key"
    assert credential.source == "env"
