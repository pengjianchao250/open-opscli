"""Scrape.do 统一 API 凭据池账号来源。"""

from __future__ import annotations

from typing import Any

from opscli.api_credentials.exceptions import ApiCredentialError
from opscli.api_credentials.models import ApiCredentialLease
from opscli.api_credentials.pool import ApiCredentialPool
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoCredential


class ScrapeDoCredentialProvider:
    """从 MySQL API 凭据池领取 Scrape.do 多账号凭据。"""

    def __init__(self, pool: ApiCredentialPool | None = None) -> None:
        """创建 Scrape.do 账号 Provider。

        Args:
            pool: 可注入的统一 API 凭据池。
        """
        self.pool = pool

    def get_default(
        self,
        *,
        refresh: bool = False,
        exclude_account_ids: set[int] | None = None,
    ) -> ScrapeDoCredential:
        """领取一个可用 Scrape.do 账号。

        Args:
            refresh: 兼容旧调用接口的无状态参数。
            exclude_account_ids: 当前请求已经失败的账号 ID。

        Returns:
            Scrape.do 客户端所需的账号凭据。

        Raises:
            ScrapeDoConfigError: 凭据池无可用账号或配置不可用。
        """
        del refresh
        try:
            lease = self._pool().acquire(
                "scrape_do",
                exclude_account_ids=exclude_account_ids,
            )
        except (ApiCredentialError, ValueError) as exc:
            raise ScrapeDoConfigError(f"获取 Scrape.do API 账号失败：{exc}") from exc
        return ScrapeDoCredential(
            name=lease.account_name,
            token=lease.secret,
            source="api_credential_pool",
            account_id=lease.account_id,
            secret_version=lease.secret_version,
        )

    def report_success(self, credential: ScrapeDoCredential, billing: dict[str, Any]) -> None:
        """回写 Scrape.do 剩余额度和成功状态。

        Args:
            credential: 本次请求使用的账号和密钥版本。
            billing: Scrape.do 响应中的非敏感计费摘要。

        Returns:
            无。
        """
        if credential.account_id is None:
            return
        remaining = billing.get("remaining_credits") if isinstance(billing, dict) else None
        runtime = {"remaining_quota": remaining} if remaining is not None else {}
        self._pool().report_success(_lease(credential), runtime=runtime)

    def report_failure(self, credential: ScrapeDoCredential, exc: Exception) -> None:
        """回写调用失败，并将 401/403 账号标记为失效。

        Args:
            credential: 本次请求使用的账号和密钥版本。
            exc: 已由 Scrape.do 客户端脱敏的异常。

        Returns:
            无。
        """
        if credential.account_id is None:
            return
        status_code = getattr(exc, "status_code", None)
        self._pool().report_failure(
            _lease(credential),
            error_code=type(exc).__name__,
            message=str(exc),
            disable=status_code in {401, 403},
        )

    def _pool(self) -> ApiCredentialPool:
        """延迟创建凭据池，使只读任务操作不依赖 MySQL 连接配置。"""
        if self.pool is None:
            self.pool = ApiCredentialPool()
        return self.pool


def _lease(credential: ScrapeDoCredential) -> ApiCredentialLease:
    return ApiCredentialLease(
        account_id=int(credential.account_id),
        provider="scrape_do",
        account_name=credential.name,
        secret=credential.token,
        secret_version=credential.secret_version or 1,
    )
