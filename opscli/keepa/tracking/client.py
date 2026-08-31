"""Keepa Tracking Endpoint 的原始 HTTP 客户端。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opscli.keepa.api.client import DEFAULT_BASE_URL, DEFAULT_USER_AGENT, KeepaApiClient


class KeepaTrackingClient:
    """按官方参数映射调用 Keepa `/tracking` Endpoint。

    这是无权限策略的 HTTP 传输层；会直接执行 Add/Remove/Webhook 等写操作。
    业务代码应优先使用 `KeepaTrackingService`，由 Service 提供确认和 webhook
    allowlist 保护。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._api = KeepaApiClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            user_agent=user_agent,
        )

    async def __aenter__(self) -> KeepaTrackingClient:  # noqa: PYI034
        """进入异步上下文并返回客户端。"""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """退出异步上下文并关闭底层连接。"""
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接池。"""
        await self._api.aclose()

    async def add(
        self,
        trackings: Sequence[dict[str, Any]],
        *,
        list_name: str | None = None,
    ) -> dict[str, Any]:
        """通过 POST 新增或整体覆盖 Tracking。

        Args:
            trackings: 一个或多个官方 Tracking Creation Object。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._api.post_json(
            "tracking",
            {"type": "add", "list": list_name},
            list(trackings),
        )

    async def get(self, asin: str, *, list_name: str | None = None) -> dict[str, Any]:
        """读取指定 ASIN 的 Tracking。

        Args:
            asin: 待读取的 ASIN。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            包含 trackings 数组的 Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {"type": "get", "asin": asin, "list": list_name},
        )

    async def list(
        self,
        *,
        list_name: str | None = None,
        asins_only: bool = False,
        page: int | None = None,
        per_page: int | None = None,
    ) -> dict[str, Any]:
        """读取全部 Tracking 或轻量 ASIN 列表。

        Args:
            list_name: 可选的命名 Tracking 列表。
            asins_only: 是否仅返回完整 ASIN 列表。
            page: 从 0 开始的页码。
            per_page: 每页数量，官方上限为 100,000。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {
                "type": "list",
                "list": list_name,
                "asins-only": asins_only,
                "page": page,
                "perPage": per_page,
            },
        )

    async def list_names(self) -> dict[str, Any]:
        """读取所有命名 Tracking 列表。

        Returns:
            包含 trackingListNames 数组的 Keepa 原始 JSON 响应。
        """
        return await self._api.get_json("tracking", {"type": "listNames"})

    async def notifications(
        self,
        *,
        since: int,
        revise: bool,
        read_only: bool,
        include_all: bool,
        list_name: str | None = None,
    ) -> dict[str, Any]:
        """读取 Tracking 通知。

        Args:
            since: 起始 Keepa Time 分钟。
            revise: 是否包含已读通知。
            read_only: 是否避免把返回通知标记为已读。
            include_all: 是否解除默认 2,000 条返回上限。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            包含 notifications 数组的 Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {
                "type": "notification",
                "since": since,
                "revise": revise,
                "readOnly": read_only,
                "all": include_all,
                "list": list_name,
            },
        )

    async def remove(self, asin: str, *, list_name: str | None = None) -> dict[str, Any]:
        """删除单个 Tracking。

        Args:
            asin: 待删除的 ASIN。
            list_name: 可选的命名 Tracking 列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {"type": "remove", "asin": asin, "list": list_name},
        )

    async def remove_all(self, *, list_name: str | None = None) -> dict[str, Any]:
        """删除默认列表或指定命名列表内的全部 Tracking。

        Args:
            list_name: 可选的命名 Tracking 列表；为空时作用于默认列表。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {"type": "removeAll", "list": list_name},
        )

    async def set_webhook(self, url: str) -> dict[str, Any]:
        """设置账户级 Tracking webhook URL。

        Args:
            url: Keepa 推送单个 Notification Object 的 HTTPS 地址。

        Returns:
            Keepa 原始 JSON 响应。
        """
        return await self._api.get_json(
            "tracking",
            {"type": "webhook", "url": url},
        )
