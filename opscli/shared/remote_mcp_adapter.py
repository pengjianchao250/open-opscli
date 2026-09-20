"""远端 MCP CLI 适配层共享基座。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from opscli.mcp_client import McpConfigClient, RemoteMcpClient


class RemoteMcpAdapter:
    """封装正式 CLI 调远端 MCP 的公共行为。"""

    def __init__(
        self,
        config_client: McpConfigClient | None = None,
        remote_client_factory=None,
        *,
        preferred_name: str = "BI运营系统",
        require_preferred: bool = False,
    ) -> None:
        self.config_client = config_client or McpConfigClient()
        self.remote_client_factory = remote_client_factory or RemoteMcpClient
        self.preferred_name = preferred_name
        self.require_preferred = require_preferred

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """同步调用远端工具，兼容当前线程已有运行中事件循环的宿主。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.call_tool_async(tool_name, arguments))

        # 同步 API 不能在当前 loop 上嵌套 asyncio.run；在线程中创建独立
        # loop，同时保留旧调用方的阻塞返回语义。
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="opscli-mcp") as executor:
            future = executor.submit(self._run_async_call_in_thread, tool_name, arguments)
            return future.result()

    async def call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """异步调用远端工具，遇到 401 时刷新配置后重试一次。"""
        normalized_arguments = self._filter_none_values(arguments)
        client = self._build_remote_client()
        try:
            return await client.call_tool(tool_name, normalized_arguments)
        except Exception as exc:
            if not self._is_unauthorized_error(exc):
                raise

        refreshed_client = self._build_remote_client()
        return await refreshed_client.call_tool(tool_name, normalized_arguments)

    def _run_async_call_in_thread(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """在线程内创建并销毁独立事件循环，避免跨 loop 复用客户端。"""
        return asyncio.run(self.call_tool_async(tool_name, arguments))

    def _build_remote_client(self) -> RemoteMcpClient:
        """读取远端配置并构造远端 MCP 客户端。"""
        payload = self.config_client.fetch_remote_config()
        select_kwargs = {
            "transport": "http",
            "preferred_name": self.preferred_name,
        }
        if self.require_preferred:
            select_kwargs["require_preferred"] = True
        server = self.config_client.select_server(payload, **select_kwargs)
        return self.remote_client_factory(server.url)

    def _filter_none_values(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """过滤顶层值为 None 的参数，避免向远端透传空字段。"""
        return {key: value for key, value in arguments.items() if value is not None}

    def _is_unauthorized_error(self, error: BaseException) -> bool:
        """识别远端链路中的 401 异常，兼容嵌套异常组。"""
        seen: set[int] = set()
        pending: list[BaseException] = [error]

        while pending:
            current = pending.pop()
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)

            if isinstance(current, PermissionError) and "401" in str(current):
                return True

            if isinstance(current, httpx.HTTPStatusError) and current.response.status_code == 401:
                return True

            response = getattr(current, "response", None)
            if getattr(response, "status_code", None) == 401:
                return True

            message = str(current).lower()
            if "401" in message and "unauthorized" in message:
                return True

            cause = getattr(current, "__cause__", None)
            if isinstance(cause, BaseException):
                pending.append(cause)

            context = getattr(current, "__context__", None)
            if isinstance(context, BaseException):
                pending.append(context)

            nested_errors = getattr(current, "exceptions", None)
            if isinstance(nested_errors, tuple):
                pending.extend(item for item in nested_errors if isinstance(item, BaseException))

        return False
