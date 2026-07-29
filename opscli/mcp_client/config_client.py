"""CLI 侧远端 MCP 配置客户端。

通过现有 CLI 登录态请求 OPS 配置接口，
获取远端 MCP 的 HTTP 服务列表，并按名称选择目标服务。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import extract_error_message
from opscli.shared.http import parse_remote_response


class McpConfigError(RemoteError):
    """MCP 配置客户端异常基类。"""

    code = "MCP_CONFIG_ERROR"


class RemoteConfigHttpError(McpConfigError):
    """远端 MCP 配置 HTTP 错误。"""

    code = "MCP_CONFIG_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RemoteConfigBusinessError(McpConfigError):
    """远端 MCP 配置业务错误。"""

    code = "MCP_CONFIG_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class BadRemoteConfigError(McpConfigError):
    """远端 MCP 配置结构非法。"""

    code = "MCP_CONFIG_BAD_REMOTE_JSON"


@dataclass(frozen=True)
class RemoteMcpServerConfig:
    """远端 MCP 服务配置。

    Attributes:
        name: 服务名称
        transport: 传输协议名称，当前仅使用 http
        url: 远端 MCP 完整访问地址
    """

    name: str
    transport: str
    url: str


class McpConfigClient:
    """封装远端 MCP 配置接口调用与服务选择逻辑。"""

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        ops_url: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.ops_url = (ops_url or OPS_URL).rstrip("/")

    def fetch_remote_config(self) -> dict[str, Any]:
        """获取远端 MCP 配置原始载荷。"""
        headers, cookies = self.auth_client.build_request_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/mcp-api-keys/config",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=RemoteConfigHttpError,
            business_error_cls=RemoteConfigBusinessError,
            bad_json_error_cls=BadRemoteConfigError,
        )
        success = payload.get("success")

        # 该接口文档明确要求 success=true 才表示配置可用，不能只依赖通用 code 语义。
        if success is not True:
            message = extract_error_message(payload) or "远端 MCP 配置返回 success=false"
            raise RemoteConfigBusinessError("success_false", message)
        return payload

    def select_server(
        self,
        payload: dict[str, Any],
        *,
        transport: str = "http",
        preferred_name: str | None = None,
        require_preferred: bool = False,
    ) -> RemoteMcpServerConfig:
        """从配置载荷中选择远端 MCP 服务，可要求首选服务必须存在。"""
        servers = self._extract_servers(payload, transport)

        if preferred_name and preferred_name in servers:
            return self._build_server_config(preferred_name, servers[preferred_name], transport)
        if preferred_name and require_preferred:
            raise BadRemoteConfigError(
                f"remote MCP config 缺少指定服务：{preferred_name}"
            )

        # 默认保留现有回退行为，避免影响其他远端 Adapter。
        for name, item in servers.items():
            return self._build_server_config(str(name), item, transport)

        raise BadRemoteConfigError(f"remote MCP config 缺少 {transport}.mcpServers")

    def _extract_servers(self, payload: dict[str, Any], transport: str) -> dict[str, Any]:
        """提取并校验 mcpServers 结构。"""
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BadRemoteConfigError("remote MCP config 缺少 data 对象")

        transport_block = data.get(transport)
        if not isinstance(transport_block, dict):
            raise BadRemoteConfigError(f"remote MCP config 缺少有效的 {transport}.mcpServers")

        servers = transport_block.get("mcpServers")
        if not isinstance(servers, dict) or not servers:
            raise BadRemoteConfigError(f"remote MCP config 缺少有效的 {transport}.mcpServers")
        return servers

    def _build_server_config(
        self,
        name: str,
        item: Any,
        transport: str,
    ) -> RemoteMcpServerConfig:
        """校验单个服务项并构造返回对象。"""
        if not isinstance(item, dict):
            raise BadRemoteConfigError(f"remote MCP config 服务 {name} 不是对象")

        item_type = item.get("type")
        if item_type != transport:
            raise BadRemoteConfigError(f"remote MCP config 服务 {name} 的 type 必须为 {transport}")

        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            raise BadRemoteConfigError(f"remote MCP config 服务 {name} 缺少有效的 url")

        return RemoteMcpServerConfig(
            name=name,
            transport=transport,
            url=url.strip(),
        )
