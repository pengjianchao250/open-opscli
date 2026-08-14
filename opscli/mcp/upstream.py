"""配置驱动的第三方 MCP 上游网关。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import os
import random
import re
import socket
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import anyio
import httpx
from fastmcp.tools import FunctionTool
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from mcp.types import ToolAnnotations

from opscli.config import CONFIG_DIR
from opscli.mcp_client import (
    RemoteMcpClient,
    RemoteMcpSessionTimeoutError,
    RemoteMcpToolError,
)

_logger = logging.getLogger("opscli.mcp.upstream")

# 允许部署环境覆盖审批配置位置，默认仍落在 opscli 的用户配置目录。
ENV_UPSTREAM_CONFIG_PATH = "OPSCLI_MCP_UPSTREAM_CONFIG_PATH"
DEFAULT_UPSTREAM_CONFIG_PATH = Path(CONFIG_DIR) / "mcp-upstreams.json"

# 服务标识会进入公开 Tool 名称，因此限制为短小、可预测的蛇形格式。
_SERVER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
# 远端 Tool 名遵循 MCP 常见命名字符集，但限制长度以保护日志和清单。
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
# URL 和凭证只允许通过规范的大写环境变量间接注入。
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
# 自定义认证头仅接受 RFC 兼容的保守字符集，避免请求头注入。
_HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
# 这些请求头会改变路由、报文边界或绕过网关认证，禁止由配置覆盖。
_FORBIDDEN_AUTH_HEADERS = {
    "connection",
    "content-length",
    "cookie",
    "host",
    "proxy-authorization",
    "transfer-encoding",
}


class UpstreamMcpError(Exception):
    """第三方 MCP 网关稳定异常基类。"""

    code = "UPSTREAM_MCP_ERROR"
    retryable = False

    def to_dict(self) -> dict[str, Any]:
        """返回不包含远端地址、凭证和异常文本的公开错误。"""
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }


class UpstreamMcpConfigError(UpstreamMcpError):
    """上游 MCP 审批配置无效。"""

    code = "UPSTREAM_MCP_CONFIG_INVALID"


class UpstreamMcpNotReadyError(UpstreamMcpError):
    """上游 MCP Runtime 尚未启动。"""

    code = "UPSTREAM_MCP_NOT_READY"
    retryable = True


class UpstreamMcpUnknownToolError(UpstreamMcpError):
    """请求了未审批或不存在的上游工具。"""

    code = "UPSTREAM_MCP_TOOL_NOT_ALLOWED"


class UpstreamMcpSecurityError(UpstreamMcpError):
    """上游地址或凭证违反安全约束。"""

    code = "UPSTREAM_MCP_SECURITY_REJECTED"


class UpstreamMcpBusyError(UpstreamMcpError):
    """上游并发槽位在排队期限内不可用。"""

    code = "UPSTREAM_MCP_BUSY"
    retryable = True


class UpstreamMcpTimeoutError(UpstreamMcpError):
    """上游调用超过不受心跳影响的总截止时间。"""

    code = "UPSTREAM_MCP_TIMEOUT"
    retryable = True


class UpstreamMcpCircuitOpenError(UpstreamMcpError):
    """上游连续失败后处于熔断窗口。"""

    code = "UPSTREAM_MCP_CIRCUIT_OPEN"
    retryable = True


class UpstreamMcpPayloadTooLargeError(UpstreamMcpError):
    """调用参数或远端结果超过审批上限。"""

    code = "UPSTREAM_MCP_PAYLOAD_TOO_LARGE"


class UpstreamMcpUnavailableError(UpstreamMcpError):
    """上游网络链路暂时不可用。"""

    code = "UPSTREAM_MCP_UNAVAILABLE"
    retryable = True


class UpstreamMcpCallError(UpstreamMcpError):
    """远端工具拒绝调用或返回非法结果。"""

    code = "UPSTREAM_MCP_CALL_FAILED"


@dataclass(frozen=True)
class UpstreamMcpAuth:
    """单个上游服务的出站鉴权配置。"""

    type: str
    secret_file_env: str | None = None
    header_name: str | None = None


@dataclass(frozen=True)
class UpstreamMcpTool:
    """经过审批并冻结 Schema 的上游工具。"""

    server_id: str
    remote_name: str
    exposed_name: str
    description: str
    input_schema: dict[str, Any]
    timeout_seconds: float
    idempotent: bool
    read_only: bool
    destructive: bool
    max_attempts: int
    retry_delay_seconds: float


@dataclass(frozen=True)
class UpstreamMcpServer:
    """单个第三方 MCP 的连接和隔离配置。"""

    id: str
    url_env: str
    allowed_hosts: tuple[str, ...]
    allowed_ports: tuple[int, ...]
    allow_private_networks: bool
    auth: UpstreamMcpAuth
    max_concurrent: int
    max_concurrent_per_user: int
    queue_timeout_seconds: float
    failure_threshold: int
    circuit_open_seconds: float
    max_request_bytes: int
    max_response_bytes: int
    tools: tuple[UpstreamMcpTool, ...]


@dataclass(frozen=True)
class UpstreamMcpConfig:
    """第三方 MCP 注册表的不可变快照。"""

    servers: tuple[UpstreamMcpServer, ...]

    def tool(self, exposed_name: str) -> UpstreamMcpTool:
        """按公开名称读取审批工具，不允许回退到远端动态发现。"""
        for server in self.servers:
            for tool in server.tools:
                if tool.exposed_name == exposed_name:
                    return tool
        raise UpstreamMcpUnknownToolError(f"未开放第三方 MCP 工具：{exposed_name}")

    def server(self, server_id: str) -> UpstreamMcpServer:
        """按稳定标识读取上游服务配置。"""
        for server in self.servers:
            if server.id == server_id:
                return server
        raise UpstreamMcpConfigError(f"上游 MCP 配置缺少服务：{server_id}")


def load_upstream_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> UpstreamMcpConfig:
    """读取并严格校验版本化第三方 MCP 配置。"""
    env = os.environ if environ is None else environ
    config_path = Path(path) if path is not None else Path(
        env.get(ENV_UPSTREAM_CONFIG_PATH, DEFAULT_UPSTREAM_CONFIG_PATH)
    )
    if not config_path.exists():
        return UpstreamMcpConfig(servers=())
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpstreamMcpConfigError("第三方 MCP 配置文件无法读取或不是有效 JSON") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise UpstreamMcpConfigError("第三方 MCP 配置 version 必须为 1")
    raw_servers = payload.get("servers")
    if not isinstance(raw_servers, list):
        raise UpstreamMcpConfigError("第三方 MCP 配置 servers 必须为数组")

    servers: list[UpstreamMcpServer] = []
    server_ids: set[str] = set()
    exposed_names: set[str] = set()
    for index, raw_server in enumerate(raw_servers):
        if not isinstance(raw_server, dict):
            raise UpstreamMcpConfigError(f"servers[{index}] 必须为对象")
        if raw_server.get("enabled", True) is not True:
            continue
        server = _parse_server(raw_server, index=index, exposed_names=exposed_names)
        if server.id in server_ids:
            raise UpstreamMcpConfigError(f"上游 MCP 服务 id 重复：{server.id}")
        server_ids.add(server.id)
        servers.append(server)
    return UpstreamMcpConfig(servers=tuple(servers))


def _parse_server(
    raw: dict[str, Any],
    *,
    index: int,
    exposed_names: set[str],
) -> UpstreamMcpServer:
    """校验并构造单个上游服务快照。"""
    server_id = _required_text(raw, "id", f"servers[{index}]")
    if not _SERVER_ID_PATTERN.fullmatch(server_id):
        raise UpstreamMcpConfigError(f"上游 MCP 服务 id 非法：{server_id}")
    url_env = _required_env_name(raw, "url_env", f"服务 {server_id}")
    allowed_hosts = _parse_hosts(raw.get("allowed_hosts"), server_id)
    allowed_ports = _parse_ports(raw.get("allowed_ports", [443]), server_id)
    auth = _parse_auth(raw.get("auth", {"type": "none"}), server_id)
    limits = raw.get("limits", {})
    if not isinstance(limits, dict):
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 limits 必须为对象")

    max_concurrent = _bounded_int(limits, "max_concurrent", 8, 1, 64, server_id)
    max_per_user = _bounded_int(
        limits,
        "max_concurrent_per_user",
        2,
        1,
        max_concurrent,
        server_id,
    )
    queue_timeout = _bounded_float(
        limits, "queue_timeout_seconds", 2.0, 0.01, 30.0, server_id
    )
    failure_threshold = _bounded_int(
        limits, "failure_threshold", 5, 1, 20, server_id
    )
    circuit_open = _bounded_float(
        limits, "circuit_open_seconds", 60.0, 1.0, 600.0, server_id
    )
    max_request_bytes = _bounded_int(
        limits, "max_request_bytes", 262_144, 1_024, 2_097_152, server_id
    )
    max_response_bytes = _bounded_int(
        limits, "max_response_bytes", 2_097_152, 1_024, 16_777_216, server_id
    )

    raw_tools = raw.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise UpstreamMcpConfigError(f"服务 {server_id} 至少需要一个审批工具")
    tools = tuple(
        _parse_tool(item, server_id=server_id, index=tool_index, exposed_names=exposed_names)
        for tool_index, item in enumerate(raw_tools)
    )
    allow_private_networks = raw.get("allow_private_networks", False)
    if not isinstance(allow_private_networks, bool):
        raise UpstreamMcpConfigError(
            f"服务 {server_id} 的 allow_private_networks 必须为布尔值"
        )
    return UpstreamMcpServer(
        id=server_id,
        url_env=url_env,
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
        allow_private_networks=allow_private_networks,
        auth=auth,
        max_concurrent=max_concurrent,
        max_concurrent_per_user=max_per_user,
        queue_timeout_seconds=queue_timeout,
        failure_threshold=failure_threshold,
        circuit_open_seconds=circuit_open,
        max_request_bytes=max_request_bytes,
        max_response_bytes=max_response_bytes,
        tools=tools,
    )


def _parse_tool(
    raw: Any,
    *,
    server_id: str,
    index: int,
    exposed_names: set[str],
) -> UpstreamMcpTool:
    """校验单个工具的稳定名称、Schema 和执行策略。"""
    if not isinstance(raw, dict):
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 tools[{index}] 必须为对象")
    label = f"服务 {server_id} 的 tools[{index}]"
    remote_name = _required_text(raw, "remote_name", label)
    exposed_name = _required_text(raw, "exposed_name", label)
    if not _TOOL_NAME_PATTERN.fullmatch(remote_name):
        raise UpstreamMcpConfigError(f"{label} remote_name 非法")
    required_prefix = f"ext_{server_id}_"
    if not exposed_name.startswith(required_prefix) or not _TOOL_NAME_PATTERN.fullmatch(exposed_name):
        raise UpstreamMcpConfigError(f"{label} exposed_name 必须以 {required_prefix} 开头")
    if exposed_name in exposed_names:
        raise UpstreamMcpConfigError(f"第三方 MCP 工具名重复：{exposed_name}")
    exposed_names.add(exposed_name)

    description = _required_text(raw, "description", label)
    if len(description) > 255:
        raise UpstreamMcpConfigError(f"{label} description 不能超过 255 字符")
    input_schema = raw.get("input_schema")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        raise UpstreamMcpConfigError(f"{label} input_schema 必须是 object Schema")
    schema_size = len(json.dumps(input_schema, ensure_ascii=False).encode("utf-8"))
    if schema_size > 131_072:
        raise UpstreamMcpConfigError(f"{label} input_schema 超过 128 KiB")
    try:
        validator_for(input_schema).check_schema(input_schema)
    except SchemaError as exc:
        raise UpstreamMcpConfigError(f"{label} input_schema 不是有效 JSON Schema") from exc

    timeout_seconds = _number(raw.get("timeout_seconds", 30), f"{label} timeout_seconds")
    if not 0 < timeout_seconds <= 120:
        raise UpstreamMcpConfigError(f"{label} timeout_seconds 必须在 0 到 120 之间")
    idempotent = raw.get("idempotent") is True
    read_only = raw.get("read_only", False)
    destructive = raw.get("destructive", True)
    if not isinstance(read_only, bool) or not isinstance(destructive, bool):
        raise UpstreamMcpConfigError(f"{label} read_only 和 destructive 必须为布尔值")
    if read_only and destructive:
        raise UpstreamMcpConfigError(f"{label} 只读工具不能同时标记为破坏性")
    max_attempts = raw.get("max_attempts", 1)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts not in {1, 2}:
        raise UpstreamMcpConfigError(f"{label} max_attempts 只能是 1 或 2")
    if not idempotent and max_attempts != 1:
        raise UpstreamMcpConfigError(f"{label} 非幂等工具禁止自动重试")
    retry_delay = _number(raw.get("retry_delay_seconds", 0.1), f"{label} retry_delay_seconds")
    if not 0 <= retry_delay <= 2:
        raise UpstreamMcpConfigError(f"{label} retry_delay_seconds 必须在 0 到 2 之间")
    return UpstreamMcpTool(
        server_id=server_id,
        remote_name=remote_name,
        exposed_name=exposed_name,
        description=description,
        input_schema=input_schema,
        timeout_seconds=timeout_seconds,
        idempotent=idempotent,
        read_only=read_only,
        destructive=destructive,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay,
    )


def _parse_auth(raw: Any, server_id: str) -> UpstreamMcpAuth:
    """校验无凭证、Bearer 或自定义 Header 三种鉴权方式。"""
    if not isinstance(raw, dict):
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 auth 必须为对象")
    auth_type = str(raw.get("type", "none")).strip().lower()
    if auth_type == "none":
        return UpstreamMcpAuth(type="none")
    if auth_type not in {"bearer", "header"}:
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 auth.type 不受支持")
    secret_env = _required_env_name(raw, "secret_file_env", f"服务 {server_id} auth")
    header_name = "Authorization" if auth_type == "bearer" else _required_text(
        raw, "header_name", f"服务 {server_id} auth"
    )
    if not _HEADER_NAME_PATTERN.fullmatch(header_name):
        raise UpstreamMcpConfigError(f"服务 {server_id} 的鉴权 Header 名称非法")
    if auth_type == "header" and header_name.casefold() in _FORBIDDEN_AUTH_HEADERS:
        raise UpstreamMcpConfigError(f"服务 {server_id} 禁止使用 Header：{header_name}")
    return UpstreamMcpAuth(
        type=auth_type,
        secret_file_env=secret_env,
        header_name=header_name,
    )


def _parse_hosts(raw: Any, server_id: str) -> tuple[str, ...]:
    """只接受精确域名，不允许通配符和 IP 字面量。"""
    if not isinstance(raw, list) or not raw:
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 allowed_hosts 不能为空")
    hosts: list[str] = []
    for item in raw:
        host = str(item).strip().rstrip(".").casefold()
        if not host or "*" in host or any(char.isspace() for char in host):
            raise UpstreamMcpConfigError(f"服务 {server_id} 的 allowed_hosts 包含非法域名")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise UpstreamMcpConfigError(f"服务 {server_id} 的 allowed_hosts 禁止使用 IP")
        hosts.append(host)
    return tuple(dict.fromkeys(hosts))


def _parse_ports(raw: Any, server_id: str) -> tuple[int, ...]:
    """读取允许的 TLS 端口集合。"""
    if not isinstance(raw, list) or not raw:
        raise UpstreamMcpConfigError(f"服务 {server_id} 的 allowed_ports 不能为空")
    ports: list[int] = []
    for port in raw:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise UpstreamMcpConfigError(f"服务 {server_id} 的 allowed_ports 非法")
        ports.append(port)
    return tuple(dict.fromkeys(ports))


def _required_text(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UpstreamMcpConfigError(f"{label} 缺少有效的 {key}")
    return value.strip()


def _required_env_name(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = _required_text(raw, key, label)
    if not _ENV_NAME_PATTERN.fullmatch(value):
        raise UpstreamMcpConfigError(f"{label} 的 {key} 不是合法环境变量名")
    return value


def _bounded_int(
    raw: Mapping[str, Any], key: str, default: int, minimum: int, maximum: int, label: str
) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise UpstreamMcpConfigError(f"服务 {label} 的 {key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _bounded_float(
    raw: Mapping[str, Any], key: str, default: float, minimum: float, maximum: float, label: str
) -> float:
    value = _number(raw.get(key, default), f"服务 {label} 的 {key}")
    if not minimum <= value <= maximum:
        raise UpstreamMcpConfigError(f"服务 {label} 的 {key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UpstreamMcpConfigError(f"{label} 必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise UpstreamMcpConfigError(f"{label} 必须是有限数字")
    return result


class UpstreamMcpTransport(Protocol):
    """Gateway 调用真实远端 MCP 时使用的内部 Adapter seam。"""

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def call_tool(
        self,
        server: UpstreamMcpServer,
        tool: UpstreamMcpTool,
        arguments: dict[str, Any],
    ) -> dict[str, Any]: ...


def _address_is_allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool) -> bool:
    """判断解析地址能否作为实际上游连接目标。"""
    if address.is_global:
        return True
    # 内部 MCP 只能额外开放普通私网；元数据常用的链路本地、回环、保留、
    # 未指定和组播地址始终拒绝，避免审批开关扩大为主机级 SSRF 能力。
    return bool(
        allow_private
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_multicast
    )


class _SizeLimitedStream(httpx.AsyncByteStream):
    """在 MCP 解析响应前按原始传输字节数执行硬上限。"""

    def __init__(self, stream: httpx.AsyncByteStream, limit: int) -> None:
        self._stream = stream
        self._limit = limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        received = 0
        async for chunk in self._stream:
            received += len(chunk)
            if received > self._limit:
                await self._stream.aclose()
                raise UpstreamMcpPayloadTooLargeError("第三方 MCP HTTP 响应超过大小上限")
            yield chunk

    async def aclose(self) -> None:
        """关闭被包装的实际响应流。"""
        await self._stream.aclose()


class _PinnedDnsTransport(httpx.AsyncBaseTransport):
    """把已校验 DNS 结果直接用于连接，同时保留原域名的 TLS SNI。"""

    def __init__(
        self,
        server: UpstreamMcpServer,
        *,
        resolver: Callable[..., list[tuple[Any, ...]]],
        limits: httpx.Limits,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._server = server
        self._resolver = resolver
        self._transport = transport or httpx.AsyncHTTPTransport(
            trust_env=False,
            limits=limits,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """校验目标并将本次请求固定到同一次解析得到的安全 IP。"""
        host = str(request.url.host).rstrip(".").casefold()
        port = request.url.port or 443
        if (
            request.url.scheme != "https"
            or host not in self._server.allowed_hosts
            or port not in self._server.allowed_ports
        ):
            raise UpstreamMcpSecurityError(f"服务 {self._server.id} 的请求目标越过白名单")
        records = await asyncio.to_thread(
            self._resolver,
            host,
            port,
            0,
            socket.SOCK_STREAM,
        )
        addresses = sorted({str(item[4][0]).split("%", 1)[0] for item in records if item[4]})
        allowed = [
            address
            for address in addresses
            if _address_is_allowed(
                ipaddress.ip_address(address),
                allow_private=self._server.allow_private_networks,
            )
        ]
        # 解析结果只要混入受保护地址就整体拒绝，避免负载均衡或重绑定时随机命中私网。
        if not addresses or len(allowed) != len(addresses):
            raise UpstreamMcpSecurityError(f"服务 {self._server.id} 的域名解析到受保护网络")

        # Host 请求头在改写 URL 前已经生成，继续携带审批域名；SNI 扩展让 TLS
        # 证书也按原域名校验，而底层连接只会访问这里固定的已校验 IP。
        request.url = request.url.copy_with(host=allowed[0])
        request.extensions["sni_hostname"] = host
        response = await self._transport.handle_async_request(request)
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdecimal() and int(content_length) > self._server.max_response_bytes:
            await response.aclose()
            raise UpstreamMcpPayloadTooLargeError("第三方 MCP HTTP 响应超过大小上限")
        response.stream = _SizeLimitedStream(response.stream, self._server.max_response_bytes)
        return response

    async def aclose(self) -> None:
        """关闭底层连接池。"""
        await self._transport.aclose()


class StreamableHttpUpstreamTransport:
    """复用 HTTP 连接池、按调用关闭 MCP Session 的生产 Adapter。"""

    def __init__(
        self,
        config: UpstreamMcpConfig,
        *,
        environ: Mapping[str, str] | None = None,
        resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    ) -> None:
        self.config = config
        self.environ = os.environ if environ is None else environ
        self.resolver = resolver
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._urls: dict[str, str] = {}
        self._startup_errors: dict[str, UpstreamMcpError] = {}
        self._opened = False

    async def open(self) -> None:
        """逐服务验证配置并创建隔离连接池，单个失败不阻止其他服务。"""
        if self._opened:
            return
        self._opened = True
        for server in self.config.servers:
            try:
                url = self._validated_url(server)
                headers = self._auth_headers(server)
                limits = httpx.Limits(
                    max_connections=server.max_concurrent,
                    max_keepalive_connections=max(1, server.max_concurrent // 2),
                    keepalive_expiry=30.0,
                )
                transport = _PinnedDnsTransport(
                    server,
                    resolver=self.resolver,
                    limits=limits,
                )
                client = httpx.AsyncClient(
                    headers=headers,
                    follow_redirects=False,
                    timeout=10,
                    transport=transport,
                    trust_env=False,
                )
            except UpstreamMcpError as exc:
                self._startup_errors[server.id] = exc
                _logger.error("第三方 MCP 服务 %s 启动校验失败：%s", server.id, exc.code)
                continue
            self._urls[server.id] = url
            self._clients[server.id] = client

    async def close(self) -> None:
        """关闭所有连接池，单个清理失败不阻止其他服务释放。"""
        clients = list(self._clients.values())
        self._clients.clear()
        self._urls.clear()
        self._startup_errors.clear()
        self._opened = False
        if clients:
            await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)

    async def call_tool(
        self,
        server: UpstreamMcpServer,
        tool: UpstreamMcpTool,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """在调用前复查 DNS，避免配置域名解析到受保护网络。"""
        client = self._clients.get(server.id)
        url = self._urls.get(server.id)
        if server.id in self._startup_errors:
            raise UpstreamMcpUnavailableError(f"第三方 MCP 服务 {server.id} 未通过启动校验")
        if client is None or url is None:
            raise UpstreamMcpNotReadyError("第三方 MCP 连接池尚未启动")
        remote = RemoteMcpClient(
            url,
            follow_redirects=False,
            http_client=client,
            max_response_bytes=server.max_response_bytes,
        )
        return await remote.call_tool(tool.remote_name, arguments)

    def _validated_url(self, server: UpstreamMcpServer) -> str:
        """只允许无内嵌凭证、无查询参数的精确 HTTPS 地址。"""
        value = str(self.environ.get(server.url_env, "")).strip()
        if not value:
            raise UpstreamMcpConfigError(f"服务 {server.id} 缺少 URL 环境变量 {server.url_env}")
        parsed = urlsplit(value)
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise UpstreamMcpSecurityError(f"服务 {server.id} 的 URL 端口非法") from exc
        hostname = str(parsed.hostname or "").rstrip(".").casefold()
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or hostname not in server.allowed_hosts
            or port not in server.allowed_ports
        ):
            raise UpstreamMcpSecurityError(f"服务 {server.id} 的 URL 未通过 HTTPS 白名单校验")
        return value

    def _auth_headers(self, server: UpstreamMcpServer) -> dict[str, str] | None:
        """从受保护文件读取凭证，配置和异常均不包含秘密原文。"""
        auth = server.auth
        if auth.type == "none":
            return None
        path_value = str(self.environ.get(str(auth.secret_file_env), "")).strip()
        if not path_value:
            raise UpstreamMcpConfigError(f"服务 {server.id} 缺少凭证文件环境变量")
        try:
            secret = Path(path_value).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise UpstreamMcpConfigError(f"服务 {server.id} 的凭证文件不可读") from exc
        if not secret or len(secret.encode("utf-8")) > 8192:
            raise UpstreamMcpConfigError(f"服务 {server.id} 的凭证文件内容无效")
        value = f"Bearer {secret}" if auth.type == "bearer" else secret
        return {str(auth.header_name): value}

class _ConcurrencyGate:
    """按服务和用户双层计数，并在空闲时清理用户键。"""

    def __init__(self, server: UpstreamMcpServer) -> None:
        self.server = server
        self._condition = asyncio.Condition()
        self._active = 0
        self._active_by_user: dict[str, int] = {}

    @asynccontextmanager
    async def slot(self, identity: str) -> AsyncIterator[None]:
        """在有限排队时间内获取并自动释放并发槽位。"""
        try:
            with anyio.fail_after(self.server.queue_timeout_seconds):
                # 同一个 Condition 同时保护全局和用户计数，确保两个限制的检查与
                # 递增是一个原子准入动作，不会因并发唤醒而发生超配。
                async with self._condition:
                    await self._condition.wait_for(
                        lambda: self._active < self.server.max_concurrent
                        and self._active_by_user.get(identity, 0)
                        < self.server.max_concurrent_per_user
                    )
                    self._active += 1
                    self._active_by_user[identity] = self._active_by_user.get(identity, 0) + 1
        except TimeoutError as exc:
            raise UpstreamMcpBusyError("第三方 MCP 当前繁忙，请稍后重试") from exc
        try:
            yield
        finally:
            # 取消和异常同样进入 finally；重新获取同一把锁后先恢复全部计数，
            # 再统一唤醒等待者，避免等待者观察到只更新一半的中间状态。
            async with self._condition:
                self._active -= 1
                remaining = self._active_by_user.get(identity, 1) - 1
                if remaining > 0:
                    self._active_by_user[identity] = remaining
                else:
                    self._active_by_user.pop(identity, None)
                # 通知必须位于锁内且排在计数更新之后，等待者会在重新持锁后复查条件。
                self._condition.notify_all()


@dataclass
class _ServerState:
    gate: _ConcurrencyGate
    consecutive_failures: int = 0
    open_until: float = 0.0


class UpstreamMcpGateway:
    """隐藏连接治理、重试和故障隔离的第三方 MCP 深模块。"""

    def __init__(
        self,
        config: UpstreamMcpConfig,
        *,
        transport: UpstreamMcpTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.transport = transport or StreamableHttpUpstreamTransport(config)
        self.clock = clock
        self._states = {
            server.id: _ServerState(gate=_ConcurrencyGate(server))
            for server in config.servers
        }
        self._validators = {
            tool.exposed_name: validator_for(tool.input_schema)(tool.input_schema)
            for server in config.servers
            for tool in server.tools
        }
        self._ready = False
        self._lifespan_depth = 0

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """启动连接池并兼容双传输嵌套进入同一 Runtime。"""
        if self._lifespan_depth > 0:
            self._lifespan_depth += 1
            try:
                yield
            finally:
                self._lifespan_depth -= 1
            return
        await self.transport.open()
        self._ready = True
        self._lifespan_depth = 1
        try:
            yield
        finally:
            self._ready = False
            self._lifespan_depth = 0
            with anyio.move_on_after(1.0, shield=True):
                await self.transport.close()

    async def call(
        self,
        exposed_tool_name: str,
        arguments: dict[str, Any],
        *,
        identity: str,
    ) -> dict[str, Any]:
        """通过审批工具名调用上游，并应用统一的资源和故障策略。"""
        if not self._ready:
            raise UpstreamMcpNotReadyError("第三方 MCP 网关尚未启动")
        tool = self.config.tool(exposed_tool_name)
        server = self.config.server(tool.server_id)
        state = self._states[server.id]
        self._check_request_size(arguments, server)
        self._validate_arguments(tool, arguments)
        self._check_circuit(state)
        try:
            with anyio.fail_after(tool.timeout_seconds):
                async with state.gate.slot(identity or "anonymous"):
                    result = await self._call_with_retry(server, tool, arguments)
        except TimeoutError as exc:
            self._record_failure(server, state)
            raise UpstreamMcpTimeoutError(
                f"第三方 MCP 工具 {tool.exposed_name} 超过总截止时间"
            ) from exc
        self._check_response(result, server)
        state.consecutive_failures = 0
        state.open_until = 0.0
        return result

    def _validate_arguments(
        self,
        tool: UpstreamMcpTool,
        arguments: dict[str, Any],
    ) -> None:
        """在出站前执行冻结 Schema，防止动态 Tool 只展示而不校验。"""
        try:
            self._validators[tool.exposed_name].validate(arguments)
        except ValidationError as exc:
            raise UpstreamMcpCallError(
                f"第三方 MCP 工具 {tool.exposed_name} 参数不符合审批 Schema"
            ) from exc

    async def _call_with_retry(
        self,
        server: UpstreamMcpServer,
        tool: UpstreamMcpTool,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """只重试明确幂等且属于建连类失败的调用。"""
        state = self._states[server.id]
        for attempt in range(tool.max_attempts):
            try:
                return await self.transport.call_tool(server, tool, arguments)
            except Exception as exc:
                if self._is_ambiguous_timeout(exc):
                    self._record_failure(server, state)
                    raise UpstreamMcpTimeoutError(
                        f"第三方 MCP 工具 {tool.exposed_name} 响应超时"
                    ) from None
                upstream_error = next(
                    (
                        current
                        for current in self._walk_exception_chain(exc)
                        if isinstance(current, UpstreamMcpError)
                    ),
                    None,
                )
                if upstream_error is not None:
                    raise upstream_error
                retryable = self._is_retryable_transport_error(exc)
                last_attempt = attempt + 1 >= tool.max_attempts
                if not retryable:
                    if isinstance(exc, UpstreamMcpError):
                        raise
                    raise UpstreamMcpCallError(
                        f"第三方 MCP 工具 {tool.exposed_name} 调用失败"
                    ) from None
                if last_attempt or not tool.idempotent:
                    self._record_failure(server, state)
                    raise UpstreamMcpUnavailableError(
                        f"第三方 MCP 服务 {server.id} 暂时不可用"
                    ) from None
                delay = max(tool.retry_delay_seconds, self._retry_after_seconds(exc))
                delay = min(delay, 2.0)
                if delay:
                    await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
        raise AssertionError("上游 MCP 重试循环必须返回或抛出异常")

    def _check_request_size(
        self, arguments: dict[str, Any], server: UpstreamMcpServer
    ) -> None:
        """在建立远端连接前拒绝超大参数。"""
        try:
            size = len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise UpstreamMcpCallError("第三方 MCP 工具参数必须可序列化为 JSON") from exc
        if size > server.max_request_bytes:
            raise UpstreamMcpPayloadTooLargeError("第三方 MCP 工具参数超过大小上限")

    def _check_response(self, result: Any, server: UpstreamMcpServer) -> None:
        """限制成功结果类型和序列化大小。"""
        if not isinstance(result, dict):
            raise UpstreamMcpCallError("第三方 MCP 返回格式无效")
        try:
            size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise UpstreamMcpCallError("第三方 MCP 返回内容无法序列化") from exc
        if size > server.max_response_bytes:
            raise UpstreamMcpPayloadTooLargeError("第三方 MCP 返回内容超过大小上限")

    def _check_circuit(self, state: _ServerState) -> None:
        """在熔断窗口内快速失败，不占用连接和并发槽位。"""
        if state.open_until > self.clock():
            raise UpstreamMcpCircuitOpenError("第三方 MCP 服务当前处于熔断状态")

    def _record_failure(self, server: UpstreamMcpServer, state: _ServerState) -> None:
        """累计基础设施失败并在达到阈值后打开熔断器。"""
        state.consecutive_failures += 1
        if state.consecutive_failures >= server.failure_threshold:
            state.open_until = self.clock() + server.circuit_open_seconds

    @staticmethod
    def _walk_exception_chain(error: BaseException) -> Iterator[BaseException]:
        """按对象身份去重遍历 cause、context 和异常组。"""
        seen: set[int] = set()
        pending = [error]
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            yield current
            for attribute in ("__cause__", "__context__"):
                nested = getattr(current, attribute, None)
                if isinstance(nested, BaseException):
                    pending.append(nested)
            nested_group = getattr(current, "exceptions", None)
            if isinstance(nested_group, tuple):
                pending.extend(item for item in nested_group if isinstance(item, BaseException))

    @classmethod
    def _is_retryable_transport_error(cls, error: BaseException) -> bool:
        """遍历异常链，只识别不会代表远端业务失败的网络异常。"""
        for current in cls._walk_exception_chain(error):
            if isinstance(current, RemoteMcpSessionTimeoutError):
                return True
            if (
                isinstance(current, httpx.HTTPStatusError)
                and current.response.status_code in {429, 502, 503}
            ):
                return True
            if isinstance(
                current,
                (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.NetworkError,
                    httpx.PoolTimeout,
                    httpx.ProtocolError,
                    socket.gaierror,
                ),
            ):
                return True
            if isinstance(current, RemoteMcpToolError):
                return False
        return False

    @classmethod
    def _retry_after_seconds(cls, error: BaseException) -> float:
        """读取可重试 HTTP 响应中的秒级 Retry-After，无效值按零处理。"""
        for current in cls._walk_exception_chain(error):
            if not isinstance(current, httpx.HTTPStatusError):
                continue
            value = current.response.headers.get("retry-after", "").strip()
            try:
                return max(0.0, float(value))
            except ValueError:
                return 0.0
        return 0.0

    @classmethod
    def _is_ambiguous_timeout(cls, error: BaseException) -> bool:
        """识别请求可能已经发送的超时，此类失败禁止自动重试。"""
        for current in cls._walk_exception_chain(error):
            if isinstance(current, (httpx.ReadTimeout, httpx.WriteTimeout)):
                return True
        return False


class UpstreamMcpRuntime:
    """把审批配置注册为稳定 FastMCP Tool 并持有 Gateway 生命周期。"""

    def __init__(
        self,
        *,
        config: UpstreamMcpConfig | None = None,
        gateway: UpstreamMcpGateway | None = None,
    ) -> None:
        self.configuration_error: UpstreamMcpConfigError | None = None
        if config is None:
            try:
                config = load_upstream_config()
            except UpstreamMcpConfigError as exc:
                # 外部配置损坏时禁用全部第三方 Tool，但核心 MCP 必须继续启动。
                self.configuration_error = exc
                config = UpstreamMcpConfig(servers=())
                _logger.error("第三方 MCP 配置加载失败，已禁用外部工具：%s", exc.code)
        self.config = config
        self.gateway = gateway or UpstreamMcpGateway(self.config)

    def register(self, mcp: Any) -> None:
        """按冻结 Schema 注册工具，远端 tools/list 变化不会自动进入公共接口。"""
        for server in self.config.servers:
            for spec in server.tools:
                fn = self._build_tool_function(spec)
                tool = FunctionTool(
                    name=spec.exposed_name,
                    description=spec.description,
                    parameters=spec.input_schema,
                    output_schema=None,
                    annotations=ToolAnnotations(
                        readOnlyHint=spec.read_only,
                        destructiveHint=spec.destructive,
                        idempotentHint=spec.idempotent,
                        openWorldHint=True,
                    ),
                    fn=fn,
                    return_type=dict,
                )
                mcp.add_tool(tool)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """启动和关闭 Gateway，未配置服务时保持空操作兼容。"""
        async with self.gateway.lifespan():
            yield

    def _build_tool_function(self, spec: UpstreamMcpTool):
        """创建名称稳定且参数 Schema 由配置提供的薄调用入口。"""

        async def invoke(**arguments: Any) -> dict[str, Any]:
            from opscli.mcp.context import get_current_user_email, get_current_user_id

            identity = get_current_user_id() or get_current_user_email() or "stdio"
            try:
                return await self.gateway.call(
                    spec.exposed_name,
                    arguments,
                    identity=identity,
                )
            except UpstreamMcpError as exc:
                return {"success": False, "data": None, "error": exc.to_dict()}

        invoke.__name__ = spec.exposed_name
        invoke.__doc__ = spec.description
        invoke.__opscli_catalog_module__ = f"external_{spec.server_id}"  # type: ignore[attr-defined]
        return invoke
