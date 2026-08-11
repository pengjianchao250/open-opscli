"""第三方 API 多账号凭据池接口。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from opscli.api_credentials.config import ApiCredentialSettings, load_settings
from opscli.api_credentials.crypto import ApiKeyCipher
from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.api_credentials.models import ApiCredentialAccount, ApiCredentialLease
from opscli.api_credentials.repository import MySqlApiCredentialRepository


class ApiCredentialPool:
    """隐藏 MySQL、加密和账号选择细节的业务接口。"""

    def __init__(
        self,
        repository: MySqlApiCredentialRepository | None = None,
        *,
        settings: ApiCredentialSettings | None = None,
    ) -> None:
        """创建凭据池。

        Args:
            repository: 可注入的 MySQL 仓储 Adapter。
            settings: 未注入仓储时使用的部署配置。

        Raises:
            ApiCredentialConfigError: 默认配置不完整。
            ValueError: 主密钥格式非法。
        """
        if repository is not None:
            self.repository = repository
            return
        resolved = settings or load_settings()
        resolved.validate()
        self.repository = MySqlApiCredentialRepository(
            settings=resolved.mysql,
            cipher=ApiKeyCipher(resolved.master_key),
        )

    def acquire(
        self,
        provider: str,
        *,
        exclude_account_ids: Iterable[int] | None = None,
    ) -> ApiCredentialLease:
        """领取一个可用账号。

        Args:
            provider: Provider 标识。
            exclude_account_ids: 当前请求已经尝试过的账号 ID。

        Returns:
            包含账号身份、密钥版本和短期明文的租约。

        Raises:
            ApiCredentialUnavailableError: 没有可用账号。
            ValueError: Provider 不受支持。
        """
        account = self.repository.acquire(
            provider,
            exclude_account_ids=exclude_account_ids,
        )
        if account is None:
            raise ApiCredentialUnavailableError(f"没有可用的 {provider} API 账号")
        return _lease(account)

    def report_success(
        self,
        lease: ApiCredentialLease,
        *,
        runtime: Mapping[str, Any] | None = None,
    ) -> None:
        """记录一次成功使用，并清除连续失败和旧错误。

        Args:
            lease: 执行请求时领取的账号租约。
            runtime: Provider 返回的额度等非敏感状态。

        Returns:
            无；租约已过期或密钥已轮换时忽略本次结果。
        """
        if not self._lease_is_current(lease):
            return
        values = {
            "last_used_at": _utc_now(),
            "last_verified_at": _utc_now(),
            "consecutive_failures": 0,
            "last_error_code": None,
            "last_error_message": None,
            **dict(runtime or {}),
        }
        self.repository.update_runtime(lease.account_id, values)

    def report_failure(
        self,
        lease: ApiCredentialLease,
        *,
        error_code: str,
        message: str,
        disable: bool = False,
        exhausted: bool = False,
        runtime: Mapping[str, Any] | None = None,
    ) -> None:
        """记录失败，并按分类更新账号状态。

        Args:
            lease: 执行请求时领取的账号租约。
            error_code: 稳定错误分类。
            message: 已脱敏的错误摘要。
            disable: 是否将账号标记为失效。
            exhausted: 是否将账号标记为额度耗尽。
            runtime: Provider 返回的补充运行状态。

        Returns:
            无；租约已过期或密钥已轮换时忽略本次结果。
        """
        account = self.repository.get_account(lease.account_id)
        if account is None or account.secret_version != lease.secret_version:
            return
        failures = (account.consecutive_failures if account else 0) + 1
        self.repository.update_runtime(
            lease.account_id,
            {
                "last_verified_at": _utc_now(),
                "consecutive_failures": failures,
                "last_error_code": error_code,
                "last_error_message": message,
                **dict(runtime or {}),
            },
        )
        if disable:
            self.repository.set_status(lease.account_id, "invalid")
        elif exhausted:
            self.repository.set_status(lease.account_id, "exhausted")

    def _lease_is_current(self, lease: ApiCredentialLease) -> bool:
        """旧密钥请求不得覆盖轮换后新版本的运行状态。"""
        account = self.repository.get_account(lease.account_id)
        return bool(account and account.secret_version == lease.secret_version)


def _lease(account: ApiCredentialAccount) -> ApiCredentialLease:
    return ApiCredentialLease(
        account_id=account.account_id,
        provider=account.provider,
        account_name=account.name,
        secret=account.api_key,
        secret_version=account.secret_version,
    )


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
