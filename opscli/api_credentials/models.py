"""第三方 API 凭据领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 首期只允许三类已接入的 API Provider，防止数据库出现代码无法消费的平台值。
SUPPORTED_PROVIDERS = frozenset({"serpapi", "canopy", "scrape_do"})
# 账号状态与领取条件一一对应，cooldown 由运行状态时间字段表达。
ACCOUNT_STATUSES = frozenset({"active", "disabled", "exhausted", "invalid", "deleted"})


@dataclass(frozen=True)
class ApiCredentialAccount:
    """Provider 下的单个账号及其当前 API Key。"""

    account_id: int
    provider: str
    name: str
    api_key: str
    status: str
    priority: int = 100
    remark: str | None = None
    secret_version: int = 1
    api_key_masked: str = ""
    remaining_quota: int | None = None
    current_usage: int | None = None
    quota_reset_at: str | None = None
    last_selected_at: str | None = None
    last_used_at: str | None = None
    last_verified_at: str | None = None
    cooldown_until: str | None = None
    consecutive_failures: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    provider_metadata: dict[str, Any] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """返回不包含明文 API Key 的管理摘要。

        Returns:
            可用于 CLI、日志和管理页面的脱敏账号字典。
        """
        return {
            "account_id": self.account_id,
            "provider": self.provider,
            "name": self.name,
            "api_key_masked": self.api_key_masked,
            "status": self.status,
            "priority": self.priority,
            "remark": self.remark,
            "secret_version": self.secret_version,
            "remaining_quota": self.remaining_quota,
            "current_usage": self.current_usage,
            "quota_reset_at": self.quota_reset_at,
            "last_selected_at": self.last_selected_at,
            "last_used_at": self.last_used_at,
            "last_verified_at": self.last_verified_at,
            "cooldown_until": self.cooldown_until,
            "consecutive_failures": self.consecutive_failures,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "provider_metadata": dict(self.provider_metadata or {}),
        }


@dataclass(frozen=True)
class ApiCredentialLease:
    """一次 Provider 账号领取结果。"""

    account_id: int
    provider: str
    account_name: str
    secret: str
    secret_version: int

    def to_public_dict(self) -> dict[str, Any]:
        """返回可安全记录的租约摘要。

        Returns:
            不包含 ``secret`` 的账号租约字典。
        """
        return {
            "account_id": self.account_id,
            "provider": self.provider,
            "account_name": self.account_name,
            "secret_version": self.secret_version,
        }
