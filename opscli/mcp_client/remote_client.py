"""基于 URL 的远端 MCP 调用客户端。

保持极薄封装：
1. 仅负责建立远端 MCP HTTP 会话并调用工具
2. 对成功结果只解析首个文本片段中的 JSON 对象
3. 对远端 `isError` 结果保留原始错误语义，不在本地重映射
"""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client
from mcp.client.streamable_http import streamable_http_client


class RemoteMcpToolError(Exception):
    """远端 MCP 工具返回 `isError=true` 时抛出的薄异常。"""

    def __init__(self, message: str, *, result: Any, raw_text: str | None = None) -> None:
        super().__init__(message)
        self.result = result
        self.raw_text = raw_text


class RemoteMcpClient:
    """封装最小化的远端 MCP HTTP 调用。"""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        normalized_url = url.strip()
        if not normalized_url:
            raise ValueError("remote MCP url is required")
        self.url = normalized_url
        self.headers = dict(headers) if headers else None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """初始化 MCP 会话后调用工具，并解析首个文本结果。"""
        # `create_mcp_http_client()` 返回的是需要显式关闭的 AsyncClient。
        # 这里由当前封装拥有其生命周期，避免依赖下游 transport 帮我们兜底。
        async with create_mcp_http_client(headers=self.headers) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

        if getattr(result, "isError", False):
            # 错误分支必须优先保留远端工具失败语义。
            # 即使远端返回体结构畸形，也不能先抛本地 ValueError 覆盖掉它。
            raw_text = self._extract_error_text(result)
            message = raw_text or "remote MCP tool returned error result"
            raise RemoteMcpToolError(message, result=result, raw_text=raw_text)

        return self._parse_first_text_json(result)

    def _parse_first_text_json(self, result: Any) -> dict[str, Any]:
        """仅接受首个文本片段中的 JSON 对象。"""
        text = self._extract_first_text(result)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("remote MCP result text must decode to JSON object") from exc

        if not isinstance(payload, dict):
            raise ValueError("remote MCP result text must decode to JSON object")
        return payload

    def _extract_first_text(self, result: Any) -> str:
        """提取首个文本片段，统一成功/失败结果的基础校验。"""
        content = getattr(result, "content", None)
        if not isinstance(content, list) or not content:
            raise ValueError("remote MCP result must contain text content")

        first_item = content[0]
        text = getattr(first_item, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("remote MCP result first content must be non-empty text")

        return text

    def _extract_error_text(self, result: Any) -> str | None:
        """为错误分支安全提取首个文本片段。

        这里故意不抛本地格式异常。只要拿不到可用文本，就返回 None，
        由上层统一抛出 `RemoteMcpToolError`，保留“远端工具失败”这一主语义。
        """
        content = getattr(result, "content", None)
        if not isinstance(content, list) or not content:
            return None

        first_item = content[0]
        text = getattr(first_item, "text", None)
        if not isinstance(text, str):
            return None

        normalized_text = text.strip()
        if not normalized_text:
            return None

        return normalized_text
