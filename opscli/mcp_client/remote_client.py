"""基于 URL 的远端 MCP 调用客户端。

保持极薄封装：
1. 仅负责建立远端 MCP HTTP 会话并调用工具
2. 对成功结果只解析首个文本片段中的 JSON 对象
3. 对远端 `isError` 结果保留原始错误语义，不在本地重映射
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


class RemoteMcpToolError(Exception):
    """远端 MCP 工具返回 `isError=true` 时抛出的薄异常。"""

    def __init__(self, message: str, *, result: Any, raw_text: str | None = None) -> None:
        super().__init__(message)
        self.result = result
        self.raw_text = raw_text


class RemoteMcpSessionTimeoutError(Exception):
    """远端 MCP 会话未能在初始化期限内就绪。"""


class RemoteMcpClient:
    """封装最小化的远端 MCP HTTP 调用。"""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        http_client: httpx.AsyncClient | None = None,
        max_response_bytes: int | None = None,
        initialize_timeout_seconds: float = 5.0,
        cleanup_timeout_seconds: float = 1.0,
    ) -> None:
        normalized_url = url.strip()
        if not normalized_url:
            raise ValueError("remote MCP url is required")
        self.url = normalized_url
        self.headers = dict(headers) if headers else None
        self.follow_redirects = bool(follow_redirects)
        self.http_client = http_client
        if max_response_bytes is not None and max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be greater than zero")
        self.max_response_bytes = max_response_bytes
        if initialize_timeout_seconds <= 0 or cleanup_timeout_seconds <= 0:
            raise ValueError("MCP session timeout values must be greater than zero")
        self.initialize_timeout_seconds = initialize_timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """初始化 MCP 会话后调用工具，并解析首个文本结果。"""
        result: Any = None
        operation_error: BaseException | None = None
        cleanup_scope = anyio.CancelScope()
        with cleanup_scope:
            async with self._http_client() as http_client:
                http_client.follow_redirects = self.follow_redirects
                async with streamable_http_client(
                    self.url,
                    http_client=http_client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        try:
                            # 只限制 initialize 本身，不能让 transport 的 TaskGroup
                            # 跨越 fail_after 边界，否则退出时会破坏 AnyIO cancel scope 栈。
                            try:
                                with anyio.fail_after(self.initialize_timeout_seconds):
                                    await session.initialize()
                            except TimeoutError as exc:
                                raise RemoteMcpSessionTimeoutError(
                                    "remote MCP session initialization timed out"
                                ) from exc
                            result = await session.call_tool(tool_name, arguments)
                        except BaseException as exc:  # noqa: BLE001
                            # 先保存业务异常，让后续有界清理不会覆盖原始失败语义。
                            operation_error = exc
                        finally:
                            # 此 scope 在所有 MCP 上下文之前进入、之后退出，既能约束
                            # 清理时间，又保持 AnyIO cancel scope 的严格 LIFO 顺序。
                            cleanup_scope.shield = True
                            cleanup_scope.deadline = (
                                anyio.current_time() + self.cleanup_timeout_seconds
                            )

        if operation_error is not None:
            raise operation_error

        if result is None:
            raise RuntimeError("remote MCP call completed without a result")

        if getattr(result, "isError", False):
            # 错误分支必须优先保留远端工具失败语义。
            # 即使远端返回体结构畸形，也不能先抛本地 ValueError 覆盖掉它。
            raw_text = self._extract_error_text(result)
            message = raw_text or "remote MCP tool returned error result"
            raise RemoteMcpToolError(message, result=result, raw_text=raw_text)

        return self._parse_first_text_json(result)

    @asynccontextmanager
    async def _http_client(self):
        """复用调用方连接池，或在单次调用结束时关闭自有客户端。"""
        if self.http_client is not None:
            yield self.http_client
            return
        async with create_mcp_http_client(headers=self.headers) as client:
            yield client

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

        if (
            self.max_response_bytes is not None
            and len(text.encode("utf-8")) > self.max_response_bytes
        ):
            raise ValueError("remote MCP result text exceeds configured size limit")

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

        if (
            self.max_response_bytes is not None
            and len(normalized_text.encode("utf-8")) > self.max_response_bytes
        ):
            return None

        return normalized_text
