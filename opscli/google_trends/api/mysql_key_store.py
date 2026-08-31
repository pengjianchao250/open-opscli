"""SerpAPI 多账号状态到统一 MySQL 凭据池的适配器。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opscli.api_credentials.pool import ApiCredentialPool
from opscli.api_credentials.repository import MySqlApiCredentialRepository
from opscli.google_trends.api.key_store import SerpApiKeyRecord


class MySqlSerpApiKeyStore:
    """保持 Google Trends 原接口，同时将账号与状态保存到 MySQL。"""

    PROVIDER = "serpapi"

    def __init__(
        self,
        repository: MySqlApiCredentialRepository | None = None,
    ) -> None:
        """创建 SerpAPI 到统一仓储的适配器。

        Args:
            repository: 可注入的 MySQL 凭据仓储。

        Raises:
            ApiCredentialConfigError: 默认凭据池配置不完整。
        """
        self.repository = repository or ApiCredentialPool().repository

    def add_key(
        self,
        *,
        name: str,
        api_key: str,
        remark: str | None = None,
    ) -> SerpApiKeyRecord:
        """新增或轮换命名 SerpAPI 账号。

        Args:
            name: Provider 内账号名称。
            api_key: 明文 API Key。
            remark: 账号备注。

        Returns:
            兼容 Google Trends 客户端的账号记录。
        """
        account = self.repository.upsert_account(
            provider=self.PROVIDER,
            name=name,
            api_key=api_key,
            remark=remark,
        )
        return _record(account)

    def get(self, key_id: str) -> SerpApiKeyRecord | None:
        """按账号 ID 读取 SerpAPI 记录。

        Args:
            key_id: 字符串形式的统一账号 ID。

        Returns:
            SerpAPI 账号记录，不存在或不属于 SerpAPI 时返回 ``None``。
        """
        try:
            account_id = int(key_id)
        except (TypeError, ValueError):
            return None
        account = self.repository.get_account(account_id)
        if account is None or account.provider != self.PROVIDER:
            return None
        return _record(account)

    def get_by_name(self, name: str) -> SerpApiKeyRecord | None:
        """按名称读取 SerpAPI 账号。

        Args:
            name: Provider 内账号名称。

        Returns:
            匹配账号记录，不存在时返回 ``None``。
        """
        account = self.repository.get_account_by_name(self.PROVIDER, name)
        return _record(account) if account else None

    def list_keys(self) -> list[SerpApiKeyRecord]:
        """列出全部 SerpAPI 账号。

        Returns:
            Google Trends 兼容账号记录列表。
        """
        return [_record(account) for account in self.repository.list_accounts(self.PROVIDER)]

    def next_active_key(self, *, exclude_key_ids: set[str] | None = None) -> SerpApiKeyRecord | None:
        """领取下一个活动 SerpAPI 账号。

        Args:
            exclude_key_ids: 当前请求已经尝试的账号 ID。

        Returns:
            可用账号；候选为空时返回 ``None``。
        """
        account = self.repository.acquire(
            self.PROVIDER,
            exclude_account_ids=_account_ids(exclude_key_ids),
        )
        return _record(account) if account else None

    def next_due_exhausted_key(
        self,
        *,
        exclude_key_ids: set[str] | None = None,
    ) -> SerpApiKeyRecord | None:
        """读取额度重置时间已到的耗尽账号。

        Args:
            exclude_key_ids: 当前请求已经复查的账号 ID。

        Returns:
            待复查账号；没有候选时返回 ``None``。
        """
        account = self.repository.next_due_exhausted(
            self.PROVIDER,
            exclude_account_ids=_account_ids(exclude_key_ids),
        )
        return _record(account) if account else None

    def update_account_snapshot(
        self,
        key_id: str,
        payload: dict[str, Any],
        *,
        preserve_plan_renewal_date: bool = False,
    ) -> SerpApiKeyRecord:
        """同步 SerpAPI Account API 的额度快照。

        Args:
            key_id: 账号 ID。
            payload: 已脱敏的 Account API 响应。
            preserve_plan_renewal_date: 无法确认新额度时是否保留旧重置日。

        Returns:
            更新后的 SerpAPI 账号记录。

        Raises:
            ValueError: 账号不存在。
        """
        record = self._required(key_id)
        metadata = dict(record.provider_metadata or {})
        reset_at = record.plan_renewal_date if preserve_plan_renewal_date else payload.get("plan_renewal_date")
        metadata.update(
            {
                "plan_name": _optional_text(payload.get("plan_name")),
                "plan_renewal_date": _optional_text(reset_at),
                "exhausted_at": record.exhausted_at,
            }
        )
        self.repository.update_runtime(
            int(key_id),
            {
                "remaining_quota": _optional_int(payload.get("total_searches_left")),
                "current_usage": _optional_int(payload.get("this_month_usage")),
                "quota_reset_at": _optional_text(reset_at),
                "last_verified_at": datetime.now(UTC),
                "last_error_code": None,
                "last_error_message": None,
                "provider_metadata": metadata,
            },
        )
        return self._required(key_id)

    def restore_active(self, key_id: str) -> None:
        """在确认额度恢复后重新启用账号。

        Args:
            key_id: 账号 ID。

        Returns:
            无。
        """
        record = self._required(key_id)
        metadata = dict(record.provider_metadata or {})
        metadata["exhausted_at"] = None
        self.repository.update_runtime(
            int(key_id),
            {"provider_metadata": metadata, "last_error_code": None, "last_error_message": None},
        )
        self.repository.set_status(int(key_id), "active")

    def record_account_check_error(self, key_id: str, *, reason: str) -> None:
        """记录免费 Account API 复查错误。

        Args:
            key_id: 账号 ID。
            reason: 已脱敏错误摘要。

        Returns:
            无。
        """
        self._required(key_id)
        self.repository.update_runtime(
            int(key_id),
            {
                "last_verified_at": datetime.now(UTC),
                "last_error_code": "account_check_failed",
                "last_error_message": reason,
            },
        )

    def mark_used(self, key_id: str) -> None:
        """记录账号最近实际使用时间。

        Args:
            key_id: 账号 ID。

        Returns:
            无。
        """
        self._required(key_id)
        self.repository.update_runtime(int(key_id), {"last_used_at": datetime.now(UTC)})

    def mark_exhausted(self, key_id: str, *, reason: str) -> None:
        """将账号标记为额度耗尽。

        Args:
            key_id: 账号 ID。
            reason: 已脱敏耗尽原因。

        Returns:
            无。
        """
        record = self._required(key_id)
        metadata = dict(record.provider_metadata or {})
        metadata["exhausted_at"] = datetime.now(UTC).isoformat()
        self.repository.update_runtime(
            int(key_id),
            {
                "remaining_quota": 0,
                "last_error_code": "quota_exhausted",
                "last_error_message": reason,
                "provider_metadata": metadata,
            },
        )
        self.repository.set_status(int(key_id), "exhausted")

    def record_error(self, key_id: str, *, reason: str) -> None:
        """记录不改变账号状态的 Provider 错误。

        Args:
            key_id: 账号 ID。
            reason: 已脱敏错误摘要。

        Returns:
            无。
        """
        self._required(key_id)
        self.repository.update_runtime(
            int(key_id),
            {"last_error_code": "provider_error", "last_error_message": reason},
        )

    def set_status(self, key_id: str, status: str) -> None:
        """显式设置 SerpAPI 账号状态。

        Args:
            key_id: 账号 ID。
            status: 目标状态。

        Returns:
            无。

        Raises:
            ValueError: 账号不存在或状态非法。
        """
        self._required(key_id)
        self.repository.set_status(int(key_id), status)

    def _required(self, key_id: str) -> SerpApiKeyRecord:
        record = self.get(key_id)
        if record is None:
            raise ValueError(f"SerpApi API Key 不存在：{key_id}")
        return record


def _record(account) -> SerpApiKeyRecord:
    metadata = dict(account.provider_metadata or {})
    return SerpApiKeyRecord(
        key_id=str(account.account_id),
        name=account.name,
        api_key=account.api_key,
        status=account.status,
        remark=account.remark,
        total_searches_left=account.remaining_quota,
        this_month_usage=account.current_usage,
        plan_name=_optional_text(metadata.get("plan_name")),
        plan_renewal_date=_optional_text(metadata.get("plan_renewal_date")),
        last_checked_at=account.last_verified_at,
        last_used_at=account.last_used_at,
        exhausted_at=_optional_text(metadata.get("exhausted_at")),
        last_error=account.last_error_message,
        provider_metadata=metadata,
        api_key_masked=account.api_key_masked,
    )


def _account_ids(values: set[str] | None) -> set[int]:
    result: set[int] = set()
    for value in values or set():
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
