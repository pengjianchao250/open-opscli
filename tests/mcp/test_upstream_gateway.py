"""第三方 MCP 上游网关的公开接口测试。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastmcp import FastMCP

import opscli.mcp.upstream as upstream_module
from opscli.mcp.app_factory import InstrumentedMcpProxy
from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tool_catalog import ToolCatalog
from opscli.mcp.upstream import (
    StreamableHttpUpstreamTransport,
    UpstreamMcpBusyError,
    UpstreamMcpCallError,
    UpstreamMcpCircuitOpenError,
    UpstreamMcpConfigError,
    UpstreamMcpGateway,
    UpstreamMcpPayloadTooLargeError,
    UpstreamMcpRuntime,
    UpstreamMcpSecurityError,
    UpstreamMcpTimeoutError,
    UpstreamMcpUnavailableError,
    _PinnedDnsTransport,
    _SizeLimitedStream,
    load_upstream_config,
)


def _config_payload(*, idempotent: bool = True) -> dict:
    return {
        "version": 1,
        "servers": [
            {
                "id": "vendor",
                "enabled": True,
                "url_env": "OPSCLI_UPSTREAM_VENDOR_URL",
                "allowed_hosts": ["mcp.vendor.example"],
                "auth": {"type": "none"},
                "limits": {
                    "max_concurrent": 4,
                    "max_concurrent_per_user": 2,
                    "queue_timeout_seconds": 0.05,
                    "failure_threshold": 3,
                    "circuit_open_seconds": 30,
                },
                "tools": [
                    {
                        "remote_name": "search",
                        "exposed_name": "ext_vendor_search",
                        "description": "查询 Vendor 数据。",
                        "timeout_seconds": 0.05,
                        "idempotent": idempotent,
                        "max_attempts": 2,
                        "retry_delay_seconds": 0,
                        "input_schema": {
                            "type": "object",
                            "properties": {"keyword": {"type": "string"}},
                            "required": ["keyword"],
                            "additionalProperties": False,
                        },
                    }
                ],
            }
        ],
    }


def _write_config(tmp_path, payload: dict):
    path = tmp_path / "mcp-upstreams.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _inline_config_payload() -> dict:
    """构造 URL、固定鉴权和调用者邮箱均由单文件声明的配置。"""
    payload = _config_payload()
    server = payload["servers"][0]
    server.pop("url_env")
    server.pop("allowed_hosts")
    server.update(
        {
            "url": "http://10.1.6.13:8008/mcp",
            "transport": "streamable_http",
            "allow_private_networks": True,
            "auth": {
                "type": "header",
                "header_name": "Authorization",
                "value": "Basic fixed-secret",
            },
            "caller_identity": {
                "source": "email",
                "location": "header",
                "header_name": "X-Opscli-User-Email",
                "required": True,
            },
        }
    )
    return payload


class FakeTransport:
    def __init__(self, outcomes=None) -> None:
        self.outcomes = list(outcomes or [{"success": True, "data": {"items": []}}])
        self.calls = []
        self.opened = 0
        self.closed = 0

    async def open(self) -> None:
        self.opened += 1

    async def close(self) -> None:
        self.closed += 1

    async def call_tool(self, server, tool, arguments, *, email=None):
        self.calls.append((server.id, tool.remote_name, arguments))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_load_upstream_config_supports_multiple_servers(tmp_path):
    payload = _config_payload()
    second = json.loads(json.dumps(payload["servers"][0]))
    second["id"] = "analytics"
    second["url_env"] = "OPSCLI_UPSTREAM_ANALYTICS_URL"
    second["allowed_hosts"] = ["mcp.analytics.example"]
    second["tools"][0]["exposed_name"] = "ext_analytics_search"
    payload["servers"].append(second)

    config = load_upstream_config(_write_config(tmp_path, payload))

    assert [server.id for server in config.servers] == ["vendor", "analytics"]
    assert config.tool("ext_analytics_search").server_id == "analytics"


def test_load_upstream_config_accepts_inline_connection_and_identity(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))

    server = config.server("vendor")
    assert server.url == "http://10.1.6.13:8008/mcp"
    assert server.url_env is None
    assert server.allowed_hosts == ("10.1.6.13",)
    assert server.allowed_ports == (8008,)
    assert server.auth.header_name == "Authorization"
    assert server.auth.value == "Basic fixed-secret"
    assert server.caller_identity.header_name == "X-Opscli-User-Email"
    assert server.caller_identity.required is True


def test_inline_auth_value_is_redacted_from_config_repr(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))

    rendered = repr(config.server("vendor"))

    assert "fixed-secret" not in rendered
    assert "UpstreamMcpAuth" in rendered


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda server: server.__setitem__(
                "url_env", "OPSCLI_UPSTREAM_VENDOR_URL"
            ),
            "url 或 url_env",
        ),
        (
            lambda server: server["auth"].__setitem__(
                "secret_file_env", "OPSCLI_UPSTREAM_VENDOR_TOKEN_FILE"
            ),
            "value 或 secret_file_env",
        ),
    ],
)
def test_load_upstream_config_rejects_ambiguous_inline_sources(tmp_path, mutate, message):
    payload = _inline_config_payload()
    mutate(payload["servers"][0])

    with pytest.raises(UpstreamMcpConfigError, match=message):
        load_upstream_config(_write_config(tmp_path, payload))


def test_load_upstream_config_rejects_public_ip_over_http(tmp_path):
    payload = _inline_config_payload()
    payload["servers"][0]["url"] = "http://8.8.8.8:8008/mcp"

    with pytest.raises(UpstreamMcpConfigError, match="HTTP url"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_load_upstream_config_rejects_identity_auth_header_collision(tmp_path):
    payload = _inline_config_payload()
    server = payload["servers"][0]
    server["auth"]["header_name"] = "X-PND-Key"
    server["caller_identity"]["header_name"] = "x-pnd-key"

    with pytest.raises(UpstreamMcpConfigError, match="不能与鉴权 Header 重名"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_transport_opens_inline_url_with_fixed_authorization(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))
    transport = StreamableHttpUpstreamTransport(config)

    async def run():
        await transport.open()
        try:
            assert transport._urls == {"vendor": "http://10.1.6.13:8008/mcp"}
            assert transport._clients["vendor"].headers["Authorization"] == "Basic fixed-secret"
        finally:
            await transport.close()

    asyncio.run(run())


def test_transport_uses_largest_approved_tool_deadline_as_http_timeout(tmp_path):
    payload = _inline_config_payload()
    first_tool = payload["servers"][0]["tools"][0]
    first_tool["timeout_seconds"] = 17
    second_tool = json.loads(json.dumps(first_tool))
    second_tool["remote_name"] = "slow_search"
    second_tool["exposed_name"] = "ext_vendor_slow_search"
    second_tool["timeout_seconds"] = 37
    payload["servers"][0]["tools"].append(second_tool)
    config = load_upstream_config(_write_config(tmp_path, payload))
    transport = StreamableHttpUpstreamTransport(config)

    async def run():
        await transport.open()
        try:
            client_timeout = transport._clients["vendor"].timeout
            assert client_timeout.connect == 37
            assert client_timeout.read == 37
            assert client_timeout.write == 37
            assert client_timeout.pool == 37
        finally:
            await transport.close()

    asyncio.run(run())


def test_transport_isolates_email_header_between_concurrent_calls(tmp_path, monkeypatch):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))
    captured_headers = []

    class RecordingPinnedTransport(httpx.AsyncBaseTransport):
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def handle_async_request(self, request):
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, request=request, json={"ok": True})

        async def aclose(self):
            return None

    class ConcurrentRemoteClient:
        ready = None
        started = 0

        def __init__(self, url, *, http_client, **kwargs) -> None:
            self.url = url
            self.http_client = http_client

        async def call_tool(self, tool_name, arguments):
            type(self).started += 1
            if type(self).started == 2:
                type(self).ready.set()
            await type(self).ready.wait()
            await self.http_client.post(self.url, json={"tool": tool_name})
            return {"success": True}

    monkeypatch.setattr(upstream_module, "_PinnedDnsTransport", RecordingPinnedTransport)
    monkeypatch.setattr(upstream_module, "RemoteMcpClient", ConcurrentRemoteClient)
    transport = StreamableHttpUpstreamTransport(config)
    server = config.server("vendor")
    tool = config.tool("ext_vendor_search")

    async def run():
        ConcurrentRemoteClient.ready = asyncio.Event()
        await transport.open()
        try:
            await asyncio.gather(
                transport.call_tool(
                    server,
                    tool,
                    {"keyword": "first"},
                    email="first@example.com",
                ),
                transport.call_tool(
                    server,
                    tool,
                    {"keyword": "second"},
                    email="second@example.com",
                ),
            )
        finally:
            await transport.close()

    asyncio.run(run())

    assert {headers["x-opscli-user-email"] for headers in captured_headers} == {
        "first@example.com",
        "second@example.com",
    }
    assert {headers["authorization"] for headers in captured_headers} == {
        "Basic fixed-secret"
    }


def test_load_upstream_config_rejects_non_namespaced_tool(tmp_path):
    payload = _config_payload()
    payload["servers"][0]["tools"][0]["exposed_name"] = "search"

    with pytest.raises(UpstreamMcpConfigError, match="ext_vendor_"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_load_upstream_config_rejects_invalid_json_schema(tmp_path):
    payload = _config_payload()
    payload["servers"][0]["tools"][0]["input_schema"] = {
        "type": "object",
        "properties": {"keyword": {"type": "not-a-json-type"}},
    }

    with pytest.raises(UpstreamMcpConfigError, match="input_schema"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_load_upstream_config_rejects_non_boolean_private_network_flag(tmp_path):
    payload = _config_payload()
    payload["servers"][0]["allow_private_networks"] = "false"

    with pytest.raises(UpstreamMcpConfigError, match="allow_private_networks"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_load_upstream_config_keeps_side_effects_independent_from_idempotency(tmp_path):
    payload = _config_payload(idempotent=True)
    tool = payload["servers"][0]["tools"][0]
    tool["read_only"] = False
    tool["destructive"] = True

    config = load_upstream_config(_write_config(tmp_path, payload))

    assert config.tool("ext_vendor_search").read_only is False
    assert config.tool("ext_vendor_search").destructive is True


def test_load_upstream_config_rejects_read_only_destructive_tool(tmp_path):
    payload = _config_payload()
    tool = payload["servers"][0]["tools"][0]
    tool["read_only"] = True
    tool["destructive"] = True

    with pytest.raises(UpstreamMcpConfigError, match="只读工具"):
        load_upstream_config(_write_config(tmp_path, payload))


def test_gateway_retries_idempotent_connect_failure_once(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    request = httpx.Request("POST", "https://mcp.vendor.example/mcp")
    transport = FakeTransport(
        [
            httpx.ConnectError("connection refused", request=request),
            {"success": True, "data": {"attempt": 2}},
        ]
    )
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            return await gateway.call(
                "ext_vendor_search",
                {"keyword": "charger"},
                identity="user-1",
            )

    result = asyncio.run(run())

    assert result == {"success": True, "data": {"attempt": 2}}
    assert len(transport.calls) == 2
    assert transport.opened == 1
    assert transport.closed == 1


def test_gateway_does_not_retry_non_idempotent_tool(tmp_path):
    payload = _config_payload(idempotent=False)
    payload["servers"][0]["tools"][0]["max_attempts"] = 1
    config = load_upstream_config(_write_config(tmp_path, payload))
    request = httpx.Request("POST", "https://mcp.vendor.example/mcp")
    transport = FakeTransport([httpx.ConnectError("connection refused", request=request)])
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            await gateway.call(
                "ext_vendor_search",
                {"keyword": "charger"},
                identity="user-1",
            )

    with pytest.raises(UpstreamMcpUnavailableError):
        asyncio.run(run())

    assert len(transport.calls) == 1


def test_gateway_retries_idempotent_503(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    request = httpx.Request("POST", "https://mcp.vendor.example/mcp")
    response = httpx.Response(503, request=request, headers={"Retry-After": "0"})
    transport = FakeTransport(
        [
            httpx.HTTPStatusError("unavailable", request=request, response=response),
            {"success": True, "data": {"attempt": 2}},
        ]
    )
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            return await gateway.call(
                "ext_vendor_search", {"keyword": "charger"}, identity="user-1"
            )

    assert asyncio.run(run()) == {"success": True, "data": {"attempt": 2}}
    assert len(transport.calls) == 2


def test_gateway_validates_frozen_schema_before_remote_call(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    transport = FakeTransport()
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            await gateway.call(
                "ext_vendor_search",
                {"keyword": 123},
                identity="user-1",
            )

    with pytest.raises(UpstreamMcpCallError, match="参数不符合"):
        asyncio.run(run())

    assert transport.calls == []


def test_gateway_opens_circuit_after_configured_failures(tmp_path):
    payload = _config_payload()
    payload["servers"][0]["limits"]["failure_threshold"] = 1
    config = load_upstream_config(_write_config(tmp_path, payload))
    request = httpx.Request("POST", "https://mcp.vendor.example/mcp")
    transport = FakeTransport(
        [
            httpx.ConnectError("refused", request=request),
            httpx.ConnectError("refused", request=request),
        ]
    )
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            with pytest.raises(UpstreamMcpUnavailableError):
                await gateway.call(
                    "ext_vendor_search",
                    {"keyword": "charger"},
                    identity="user-1",
                )
            await gateway.call(
                "ext_vendor_search",
                {"keyword": "charger"},
                identity="user-1",
            )

    with pytest.raises(UpstreamMcpCircuitOpenError):
        asyncio.run(run())

    assert len(transport.calls) == 2


def test_gateway_total_deadline_interrupts_heartbeating_call(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))

    class HangingTransport(FakeTransport):
        cancelled = False

        async def call_tool(self, server, tool, arguments, *, email=None):
            self.calls.append((server.id, tool.remote_name, arguments))
            try:
                while True:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    transport = HangingTransport()
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            await gateway.call(
                "ext_vendor_search",
                {"keyword": "charger"},
                identity="user-1",
            )

    with pytest.raises(UpstreamMcpTimeoutError):
        asyncio.run(run())

    assert len(transport.calls) == 1
    assert transport.cancelled is True


def test_gateway_queue_timeout_isolated_per_server_and_user(tmp_path):
    payload = _config_payload()
    limits = payload["servers"][0]["limits"]
    limits["max_concurrent"] = 1
    limits["max_concurrent_per_user"] = 1
    limits["queue_timeout_seconds"] = 0.02
    payload["servers"][0]["tools"][0]["timeout_seconds"] = 0.2
    config = load_upstream_config(_write_config(tmp_path, payload))
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingTransport(FakeTransport):
        async def call_tool(self, server, tool, arguments, *, email=None):
            self.calls.append((server.id, tool.remote_name, arguments))
            started.set()
            await release.wait()
            return {"success": True}

    transport = BlockingTransport()
    gateway = UpstreamMcpGateway(config, transport=transport)

    async def run():
        async with gateway.lifespan():
            first = asyncio.create_task(
                gateway.call(
                    "ext_vendor_search",
                    {"keyword": "first"},
                    identity="user-1",
                )
            )
            await started.wait()
            with pytest.raises(UpstreamMcpBusyError):
                await gateway.call(
                    "ext_vendor_search",
                    {"keyword": "second"},
                    identity="user-1",
                )
            release.set()
            await first

    asyncio.run(run())

    assert transport.calls == [("vendor", "search", {"keyword": "first"})]


def test_runtime_registers_frozen_schema_and_routes_through_gateway(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    transport = FakeTransport([{"success": True, "data": {"items": ["A"]}}])
    gateway = UpstreamMcpGateway(config, transport=transport)
    runtime = UpstreamMcpRuntime(config=config, gateway=gateway)

    class FakeMcp:
        def __init__(self) -> None:
            self.tools = []

        def add_tool(self, tool):
            self.tools.append(tool)

    mcp = FakeMcp()
    runtime.register(mcp)

    assert [tool.name for tool in mcp.tools] == ["ext_vendor_search"]
    assert mcp.tools[0].parameters == config.tool("ext_vendor_search").input_schema

    async def run():
        async with runtime.lifespan():
            return await mcp.tools[0].run({"keyword": "charger"})

    result = asyncio.run(run())

    assert result.structured_content == {"success": True, "data": {"items": ["A"]}}
    assert transport.calls == [
        ("vendor", "search", {"keyword": "charger"})
    ]


def test_runtime_passes_verified_email_to_identity_aware_upstream(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))

    class IdentityTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.emails = []

        async def call_tool(self, server, tool, arguments, *, email):
            self.emails.append(email)
            return await super().call_tool(server, tool, arguments, email=email)

    transport = IdentityTransport()
    runtime = UpstreamMcpRuntime(
        config=config,
        gateway=UpstreamMcpGateway(config, transport=transport),
    )

    class FakeMcp:
        tool = None

        def add_tool(self, tool):
            self.tool = tool

    mcp = FakeMcp()
    runtime.register(mcp)

    async def run():
        token = mcp_request_ctx.set(
            {"user_id": "u-1", "email": " Verified.User@Example.com "}
        )
        try:
            async with runtime.lifespan():
                return await mcp.tool.run({"keyword": "charger"})
        finally:
            mcp_request_ctx.reset(token)

    result = asyncio.run(run())

    assert result.structured_content["success"] is True
    assert transport.emails == ["verified.user@example.com"]


def test_runtime_rejects_identity_aware_upstream_without_verified_email(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))
    transport = FakeTransport()
    runtime = UpstreamMcpRuntime(
        config=config,
        gateway=UpstreamMcpGateway(config, transport=transport),
    )

    class FakeMcp:
        tool = None

        def add_tool(self, tool):
            self.tool = tool

    mcp = FakeMcp()
    runtime.register(mcp)

    async def run():
        async with runtime.lifespan():
            return await mcp.tool.run({"keyword": "charger"})

    result = asyncio.run(run())

    assert result.structured_content["error"]["code"] == "UPSTREAM_MCP_IDENTITY_REQUIRED"
    assert transport.calls == []


def test_runtime_dynamic_tools_still_enter_instrumentation_catalog(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    runtime = UpstreamMcpRuntime(
        config=config,
        gateway=UpstreamMcpGateway(config, transport=FakeTransport()),
    )
    catalog = ToolCatalog()
    proxy = InstrumentedMcpProxy(FastMCP("upstream-test"), catalog=catalog)

    runtime.register(proxy)

    assert catalog.get_catalog() == [
        {
            "name": "ext_vendor_search",
            "module": "external_vendor",
            "description": "查询 Vendor 数据。",
        }
    ]


def test_runtime_uses_explicit_side_effect_annotations(tmp_path):
    payload = _config_payload(idempotent=True)
    payload["servers"][0]["tools"][0].update(
        {"read_only": False, "destructive": True}
    )
    config = load_upstream_config(_write_config(tmp_path, payload))
    runtime = UpstreamMcpRuntime(
        config=config,
        gateway=UpstreamMcpGateway(config, transport=FakeTransport()),
    )

    class FakeMcp:
        tool = None

        def add_tool(self, tool):
            self.tool = tool

    mcp = FakeMcp()
    runtime.register(mcp)

    assert mcp.tool.annotations.readOnlyHint is False
    assert mcp.tool.annotations.destructiveHint is True


def test_runtime_isolates_url_credentials_and_query_at_start(tmp_path, monkeypatch):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    monkeypatch.setenv(
        "OPSCLI_UPSTREAM_VENDOR_URL",
        "https://user:secret@mcp.vendor.example/mcp?api_key=secret",
    )
    runtime = UpstreamMcpRuntime(config=config)

    async def run():
        async with runtime.lifespan():
            with pytest.raises(UpstreamMcpUnavailableError):
                await runtime.gateway.call(
                    "ext_vendor_search",
                    {"keyword": "charger"},
                    identity="user-1",
                )

    asyncio.run(run())


def test_transport_startup_isolates_invalid_server(tmp_path, monkeypatch):
    payload = _config_payload()
    second = json.loads(json.dumps(payload["servers"][0]))
    second["id"] = "analytics"
    second["url_env"] = "OPSCLI_UPSTREAM_ANALYTICS_URL"
    second["allowed_hosts"] = ["mcp.analytics.example"]
    second["tools"][0]["exposed_name"] = "ext_analytics_search"
    payload["servers"].append(second)
    config = load_upstream_config(_write_config(tmp_path, payload))
    monkeypatch.setenv("OPSCLI_UPSTREAM_ANALYTICS_URL", "https://mcp.analytics.example/mcp")
    transport = StreamableHttpUpstreamTransport(config)

    async def run():
        await transport.open()
        try:
            assert set(transport._clients) == {"analytics"}
            with pytest.raises(UpstreamMcpUnavailableError):
                await transport.call_tool(
                    config.servers[0], config.servers[0].tools[0], {"keyword": "x"}
                )
        finally:
            await transport.close()

    asyncio.run(run())


def test_pinned_dns_rejects_link_local_even_for_private_server(tmp_path):
    payload = _config_payload()
    payload["servers"][0]["allow_private_networks"] = True
    config = load_upstream_config(_write_config(tmp_path, payload))

    class NeverCalledTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise AssertionError("受保护地址不应建立连接")

    resolver = lambda *args: [(None, None, None, None, ("169.254.169.254", 443))]
    transport = _PinnedDnsTransport(
        config.servers[0],
        resolver=resolver,
        limits=httpx.Limits(max_connections=1),
        transport=NeverCalledTransport(),
    )

    with pytest.raises(UpstreamMcpSecurityError):
        asyncio.run(
            transport.handle_async_request(
                httpx.Request("POST", "https://mcp.vendor.example/mcp")
            )
        )


def test_pinned_dns_uses_validated_ip_and_original_tls_name(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _config_payload()))
    captured = {}

    class RecordingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured["host"] = request.url.host
            captured["sni"] = request.extensions["sni_hostname"]
            captured["host_header"] = request.headers["host"]
            return httpx.Response(200, request=request, content=b"{}")

    resolver = lambda *args: [(None, None, None, None, ("93.184.216.34", 443))]
    transport = _PinnedDnsTransport(
        config.servers[0],
        resolver=resolver,
        limits=httpx.Limits(max_connections=1),
        transport=RecordingTransport(),
    )

    response = asyncio.run(
        transport.handle_async_request(httpx.Request("POST", "https://mcp.vendor.example/mcp"))
    )

    assert response.status_code == 200
    assert captured == {
        "host": "93.184.216.34",
        "sni": "mcp.vendor.example",
        "host_header": "mcp.vendor.example",
    }


def test_pinned_dns_allows_approved_private_http_without_tls_sni(tmp_path):
    config = load_upstream_config(_write_config(tmp_path, _inline_config_payload()))
    captured = {}

    class RecordingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured["host"] = request.url.host
            captured["sni"] = request.extensions.get("sni_hostname")
            captured["host_header"] = request.headers["host"]
            return httpx.Response(200, request=request, content=b"{}")

    resolver = lambda *args: [(None, None, None, None, ("10.1.6.13", 8008))]
    transport = _PinnedDnsTransport(
        config.server("vendor"),
        resolver=resolver,
        limits=httpx.Limits(max_connections=1),
        transport=RecordingTransport(),
    )

    response = asyncio.run(
        transport.handle_async_request(httpx.Request("POST", "http://10.1.6.13:8008/mcp"))
    )

    assert response.status_code == 200
    assert captured == {
        "host": "10.1.6.13",
        "sni": None,
        "host_header": "10.1.6.13:8008",
    }


def test_size_limited_stream_stops_before_protocol_parsing():
    class BytesStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"1234"
            yield b"5678"

        async def aclose(self):
            return None

    async def consume():
        return [chunk async for chunk in _SizeLimitedStream(BytesStream(), 6)]

    with pytest.raises(UpstreamMcpPayloadTooLargeError, match="大小上限"):
        asyncio.run(consume())
