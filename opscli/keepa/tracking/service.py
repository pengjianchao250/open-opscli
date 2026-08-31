"""Keepa Tracking 参数校验和状态变更安全边界。"""

from __future__ import annotations

import ipaddress
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from opscli.keepa.domain.exceptions import KeepaConfigError
from opscli.keepa.tracking.models import TrackingCreation, normalize_tracking_asin

# Keepa Add Tracking 单次 POST 最多接受 3,000 个创建对象。
MAX_TRACKING_ADD_BATCH_SIZE = 3_000

# Keepa 命名 Tracking 列表名称最长为 64 个字符。
MAX_TRACKING_LIST_NAME_LENGTH = 64

# Keepa Tracking list 的显式分页大小最大为 100,000。
MAX_TRACKING_PAGE_SIZE = 100_000


class _TrackingClient(Protocol):
    """Tracking Service 依赖的外部 Keepa 操作。"""

    async def add(self, trackings, *, list_name=None): ...

    async def get(self, asin, *, list_name=None): ...

    async def list(self, *, list_name=None, asins_only=False, page=None, per_page=None): ...

    async def list_names(self): ...

    async def notifications(
        self,
        *,
        since,
        revise,
        read_only,
        include_all,
        list_name=None,
    ): ...

    async def remove(self, asin, *, list_name=None): ...

    async def remove_all(self, *, list_name=None): ...

    async def set_webhook(self, url): ...


class KeepaTrackingService:
    """在调用 Tracking Client 前执行官方限制和副作用保护。"""

    def __init__(
        self,
        client: _TrackingClient,
        *,
        allowed_webhook_hosts: Collection[str] = (),
    ) -> None:
        """创建带状态变更保护的 Tracking Service。

        Args:
            client: Keepa Tracking HTTP 传输客户端。
            allowed_webhook_hosts: 受控管理面预登记的精确 webhook 主机名。
                为空时拒绝全部 webhook 配置，避免任意 URL 变成 SSRF 入口。
        """
        self.client = client
        self.allowed_webhook_hosts = frozenset(
            _normalize_webhook_host(item) for item in allowed_webhook_hosts
        )

    async def add(
        self,
        trackings: Sequence[TrackingCreation | Mapping[str, Any]],
        *,
        list_name: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """新增或整体覆盖一批 Tracking。

        Args:
            trackings: 一个至 3,000 个创建模型或官方字段映射。
            list_name: 可选的命名 Tracking 列表。
            confirm: 必须显式为 True，确认新增或整体覆盖现有 Tracking。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: 批量、列表名、创建对象或确认条件不符合限制。
        """
        _require_confirmation(confirm, operation="add")
        _validate_list_name(list_name)
        if not trackings:
            raise KeepaConfigError("Tracking Add 至少需要一个创建对象")
        if len(trackings) > MAX_TRACKING_ADD_BATCH_SIZE:
            raise KeepaConfigError("Tracking Add 单次最多提交 3,000 个创建对象")
        payload = [_coerce_creation(item).to_api_dict() for item in trackings]
        return await self.client.add(payload, list_name=list_name)

    async def get(self, asin: str, *, list_name: str | None = None) -> dict[str, Any]:
        """读取一个 Tracking。

        Args:
            asin: 待读取的 ASIN。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        _validate_list_name(list_name)
        return await self.client.get(normalize_tracking_asin(asin), list_name=list_name)

    async def list(
        self,
        *,
        list_name: str | None = None,
        asins_only: bool = False,
        page: int | None = None,
        per_page: int | None = None,
    ) -> dict[str, Any]:
        """读取 Tracking 列表。

        Args:
            list_name: 可选的命名 Tracking 列表。
            asins_only: 是否只返回完整 ASIN 列表。
            page: 从 0 开始的页码。
            per_page: 每页数量，最大为 100,000。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: 分页与 asins_only 冲突或超出官方边界。
        """
        _validate_list_name(list_name)
        _validate_bool(asins_only, "asins_only")
        if asins_only and (page is not None or per_page is not None):
            raise KeepaConfigError("asins_only=True 时 Keepa 会忽略 page/perPage，请勿同时传分页参数")
        if page is not None:
            _validate_non_negative_int(page, "page")
        if per_page is not None:
            _validate_positive_int(per_page, "perPage")
            if per_page > MAX_TRACKING_PAGE_SIZE:
                raise KeepaConfigError("perPage 最大为 100,000")
        return await self.client.list(
            list_name=list_name,
            asins_only=asins_only,
            page=page,
            per_page=per_page,
        )

    async def list_names(self) -> dict[str, Any]:
        """读取所有命名 Tracking 列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self.client.list_names()

    async def preview_notifications(
        self,
        *,
        since: int,
        revise: bool = False,
        include_all: bool = False,
        list_name: str | None = None,
    ) -> dict[str, Any]:
        """以 readOnly 模式预览通知，不改变通知已读状态。

        Args:
            since: 起始 Keepa Time 分钟。
            revise: 是否包含已读通知。
            include_all: 是否解除默认 2,000 条限制。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._notifications(
            since=since,
            revise=revise,
            read_only=True,
            include_all=include_all,
            list_name=list_name,
        )

    async def consume_notifications(
        self,
        *,
        since: int,
        revise: bool = False,
        include_all: bool = False,
        list_name: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """读取并把返回通知标记为已读。

        Args:
            since: 起始 Keepa Time 分钟。
            revise: 是否包含已读通知。
            include_all: 是否解除默认 2,000 条限制。
            list_name: 可选的命名 Tracking 列表。
            confirm: 必须显式为 True，确认接受已读副作用。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: 未显式确认状态变更。
        """
        _require_confirmation(confirm, operation="consume_notifications")
        return await self._notifications(
            since=since,
            revise=revise,
            read_only=False,
            include_all=include_all,
            list_name=list_name,
        )

    async def remove(
        self,
        asin: str,
        *,
        list_name: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """删除单个 Tracking。

        Args:
            asin: 待删除的 ASIN。
            list_name: 可选的命名 Tracking 列表。
            confirm: 必须显式为 True，确认删除。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: ASIN、列表名或确认条件不合法。
        """
        _require_confirmation(confirm, operation="remove")
        _validate_list_name(list_name)
        return await self.client.remove(normalize_tracking_asin(asin), list_name=list_name)

    async def remove_all(
        self,
        *,
        list_name: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """清空默认列表或删除指定命名列表及其全部 Tracking。

        Args:
            list_name: 可选的命名 Tracking 列表；为空时清空默认列表。
            confirm: 必须显式为 True，确认批量删除。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: 列表名不合法或未显式确认批量删除。
        """
        _validate_list_name(list_name)
        _require_confirmation(confirm, operation="remove_all")
        return await self.client.remove_all(list_name=list_name)

    async def set_webhook(self, url: str, *, confirm: bool = False) -> dict[str, Any]:
        """更新 Keepa 账户级 Tracking webhook。

        Args:
            url: 可公开访问的 HTTPS webhook URL。
            confirm: 必须显式为 True，确认修改账户配置。

        Returns:
            Keepa 原始 JSON 响应。

        Raises:
            KeepaConfigError: URL 不安全或未显式确认账户配置变更。
        """
        _require_confirmation(confirm, operation="set_webhook")
        if not isinstance(url, str):
            raise KeepaConfigError("webhook URL 必须是字符串")
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise KeepaConfigError("webhook URL 必须是包含主机名的 HTTPS 地址")
        if parsed.username or parsed.password:
            raise KeepaConfigError("webhook URL 不得包含用户名或密码")
        host = _normalize_webhook_host(parsed.hostname or "")
        if host not in self.allowed_webhook_hosts:
            raise KeepaConfigError("webhook 主机未在受控 allowlist 中登记")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise KeepaConfigError("webhook URL 不允许使用 IP 地址")
        return await self.client.set_webhook(url.strip())

    async def _notifications(
        self,
        *,
        since: int,
        revise: bool,
        read_only: bool,
        include_all: bool,
        list_name: str | None,
    ) -> dict[str, Any]:
        _validate_list_name(list_name)
        _validate_non_negative_int(since, "since")
        _validate_bool(revise, "revise")
        _validate_bool(include_all, "include_all")
        return await self.client.notifications(
            since=since,
            revise=revise,
            read_only=read_only,
            include_all=include_all,
            list_name=list_name,
        )


def _coerce_creation(value: TrackingCreation | Mapping[str, Any]) -> TrackingCreation:
    if isinstance(value, TrackingCreation):
        return value
    if isinstance(value, Mapping):
        return TrackingCreation.from_api_dict(value)
    raise KeepaConfigError("Tracking 创建对象必须是 TrackingCreation 或 JSON 对象")


def _validate_list_name(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise KeepaConfigError("Tracking list 名称必须是字符串")
    if not value.strip():
        raise KeepaConfigError("Tracking list 名称不能为空")
    if len(value) > MAX_TRACKING_LIST_NAME_LENGTH:
        raise KeepaConfigError("Tracking list 名称最长 64 个字符")


def _require_confirmation(value: bool, *, operation: str) -> None:
    if value is not True:
        raise KeepaConfigError(f"{operation} 会改变 Keepa 账户状态，必须显式传入 confirm=True")


def _validate_bool(value: Any, field_name: str) -> None:
    if type(value) is not bool:
        raise KeepaConfigError(f"{field_name} 必须是布尔值")


def _validate_non_negative_int(value: Any, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise KeepaConfigError(f"{field_name} 必须是大于或等于 0 的整数")


def _validate_positive_int(value: Any, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise KeepaConfigError(f"{field_name} 必须是正整数")


def _normalize_webhook_host(value: str) -> str:
    host = str(value).strip().lower().rstrip(".")
    if not host or any(char.isspace() for char in host):
        raise KeepaConfigError("webhook allowlist 主机名不能为空或包含空白字符")
    return host
