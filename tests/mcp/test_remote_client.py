import asyncio
import json

import anyio
import pytest

from opscli.mcp_client.remote_client import (
    RemoteMcpClient,
    RemoteMcpSessionTimeoutError,
    RemoteMcpToolError,
)


class DummyTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


class DummyResult:
    def __init__(self, content, *, is_error: bool = False) -> None:
        self.content = content
        self.isError = is_error


class DummySession:
    def __init__(self, read_stream, write_stream, result: DummyResult, calls: dict) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.result = result
        self.calls = calls

    async def __aenter__(self):
        self.calls["session_entered"] = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.calls["session_exited"] = True
        return False

    async def initialize(self):
        self.calls["initialized"] = True
        return None

    async def call_tool(self, tool_name, arguments):
        self.calls["tool_name"] = tool_name
        self.calls["arguments"] = arguments
        return self.result


class DummyHttpTransport:
    def __init__(self, calls: dict) -> None:
        self.calls = calls

    async def __aenter__(self):
        self.calls["transport_entered"] = True
        return ("read-stream", "write-stream", lambda: "session-id")

    async def __aexit__(self, exc_type, exc, tb):
        self.calls["transport_exited"] = True
        return False


class TaskGroupHttpTransport(DummyHttpTransport):
    """模拟真实 MCP transport 在上下文内持有 AnyIO TaskGroup。"""

    async def __aenter__(self):
        self.calls["transport_entered"] = True
        self.task_group = anyio.create_task_group()
        await self.task_group.__aenter__()
        return ("read-stream", "write-stream", lambda: "session-id")

    async def __aexit__(self, exc_type, exc, tb):
        self.calls["transport_exited"] = True
        return await self.task_group.__aexit__(exc_type, exc, tb)


class DummyManagedHttpClient:
    def __init__(self, calls: dict) -> None:
        self.calls = calls

    async def __aenter__(self):
        self.calls["http_client_entered"] = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.calls["http_client_exited"] = True
        return False


def install_remote_client_mocks(monkeypatch, calls: dict, result: DummyResult) -> None:
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.create_mcp_http_client",
        lambda headers=None: (
            calls.update({"headers": headers}) or DummyManagedHttpClient(calls)
        ),
    )
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.streamable_http_client",
        lambda url, *, http_client: DummyHttpTransport(calls),
    )
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.ClientSession",
        lambda read_stream, write_stream: DummySession(read_stream, write_stream, result, calls),
    )


def test_remote_mcp_client_requires_url():
    with pytest.raises(ValueError, match="url"):
        RemoteMcpClient(url="")


def test_call_tool_returns_first_text_json(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True, "data": {"value": 1}}))])

    def fake_create_mcp_http_client(headers=None):
        calls["http_client_created"] = True
        calls["headers"] = headers
        return DummyManagedHttpClient(calls)

    def fake_streamable_http_client(url, *, http_client):
        calls["url"] = url
        calls["http_client"] = http_client
        return DummyHttpTransport(calls)

    def fake_client_session(read_stream, write_stream):
        return DummySession(read_stream, write_stream, result, calls)

    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.create_mcp_http_client",
        fake_create_mcp_http_client,
    )
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.streamable_http_client",
        fake_streamable_http_client,
    )
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.ClientSession",
        fake_client_session,
    )

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")
    payload = asyncio.run(client.call_tool("seller_sprite_scenarios", {"site": "JP"}))

    assert payload == {"success": True, "data": {"value": 1}}
    assert calls["http_client_created"] is True
    assert calls["headers"] is None
    assert calls["http_client_entered"] is True
    assert calls["http_client_exited"] is True
    assert calls["url"] == "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo"
    assert calls["initialized"] is True
    assert calls["tool_name"] == "seller_sprite_scenarios"
    assert calls["arguments"] == {"site": "JP"}
    assert calls["transport_entered"] is True
    assert calls["transport_exited"] is True
    assert calls["session_entered"] is True
    assert calls["session_exited"] is True


def test_call_tool_passes_http_headers(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(
        url="https://collector.example.com/mcp",
        headers={"Authorization": "Bearer mcp-user-key"},
    )
    payload = asyncio.run(client.call_tool("seller_sprite_scenarios", {}))

    assert payload == {"success": True}
    assert calls["headers"] == {"Authorization": "Bearer mcp-user-key"}


def test_call_tool_can_disable_http_redirects(monkeypatch):
    """带自定义密钥的调用方应能禁止自动跟随重定向。"""
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    install_remote_client_mocks(monkeypatch, calls, result)

    def transport(url, *, http_client):
        calls["follow_redirects"] = http_client.follow_redirects
        return DummyHttpTransport(calls)

    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.streamable_http_client",
        transport,
    )
    client = RemoteMcpClient(
        url="https://collector.example.com/mcp",
        headers={"X-MCP-API-Key": "mcp-user-key"},
        follow_redirects=False,
    )

    assert asyncio.run(client.call_tool("collector_modules_health", {})) == {
        "success": True
    }
    assert calls["follow_redirects"] is False


def test_call_tool_does_not_close_shared_http_client(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    shared_client = DummyManagedHttpClient(calls)
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.streamable_http_client",
        lambda url, *, http_client: DummyHttpTransport(calls),
    )
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.ClientSession",
        lambda read_stream, write_stream: DummySession(
            read_stream,
            write_stream,
            result,
            calls,
        ),
    )
    client = RemoteMcpClient(
        url="https://collector.example.com/mcp",
        http_client=shared_client,
        follow_redirects=False,
    )

    assert asyncio.run(client.call_tool("collector_modules_health", {})) == {
        "success": True
    }
    assert "http_client_exited" not in calls


def test_call_tool_preserves_real_transport_cancel_scope_order(monkeypatch):
    """Transport 的 TaskGroup 必须在创建它的父级 cancel scope 内退出。"""
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    install_remote_client_mocks(monkeypatch, calls, result)
    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.streamable_http_client",
        lambda url, *, http_client: TaskGroupHttpTransport(calls),
    )
    client = RemoteMcpClient(url="https://collector.example.com/mcp")

    assert asyncio.run(client.call_tool("collector_modules_health", {})) == {
        "success": True
    }
    assert calls["transport_exited"] is True


def test_call_tool_bounds_session_initialization(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    install_remote_client_mocks(monkeypatch, calls, result)

    class HangingInitializeSession(DummySession):
        async def initialize(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.ClientSession",
        lambda read_stream, write_stream: HangingInitializeSession(
            read_stream, write_stream, result, calls
        ),
    )
    client = RemoteMcpClient(
        url="https://collector.example.com/mcp",
        initialize_timeout_seconds=0.01,
    )

    with pytest.raises(RemoteMcpSessionTimeoutError):
        asyncio.run(client.call_tool("collector_modules_health", {}))

    assert calls["session_exited"] is True
    assert calls["transport_exited"] is True


def test_call_tool_bounds_hanging_session_cleanup(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True}))])
    install_remote_client_mocks(monkeypatch, calls, result)

    class HangingCleanupSession(DummySession):
        async def __aexit__(self, exc_type, exc, tb):
            calls["cleanup_started"] = True
            await asyncio.Event().wait()

    monkeypatch.setattr(
        "opscli.mcp_client.remote_client.ClientSession",
        lambda read_stream, write_stream: HangingCleanupSession(
            read_stream, write_stream, result, calls
        ),
    )
    client = RemoteMcpClient(
        url="https://collector.example.com/mcp",
        cleanup_timeout_seconds=0.01,
    )

    async def run():
        return await asyncio.wait_for(
            client.call_tool("collector_modules_health", {}),
            timeout=0.1,
        )

    assert asyncio.run(run()) == {"success": True}
    assert calls["cleanup_started"] is True


def test_call_tool_raises_remote_tool_error_with_remote_text(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent("remote tool failed")], is_error=True)

    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(RemoteMcpToolError, match="remote tool failed") as exc_info:
        asyncio.run(client.call_tool("seller_sprite_run", {"site": "JP"}))

    assert exc_info.value.raw_text == "remote tool failed"
    assert exc_info.value.result is result
    assert calls["http_client_exited"] is True


@pytest.mark.parametrize(
    ("content", "expected_raw_text"),
    [
        (None, None),
        ([], None),
        ([object()], None),
        ([DummyTextContent("   ")], None),
    ],
)
def test_call_tool_error_result_with_malformed_content_still_raises_remote_tool_error(
    monkeypatch,
    content,
    expected_raw_text,
):
    calls = {}
    result = DummyResult(content, is_error=True)
    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(RemoteMcpToolError, match="remote MCP tool returned error result") as exc_info:
        asyncio.run(client.call_tool("seller_sprite_run", {}))

    assert exc_info.value.raw_text == expected_raw_text
    assert exc_info.value.result is result
    assert calls["http_client_exited"] is True


def test_call_tool_rejects_non_text_first_content(monkeypatch):
    calls = {}
    result = DummyResult([object()])

    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(ValueError, match="text"):
        asyncio.run(client.call_tool("seller_sprite_scenarios", {}))


@pytest.mark.parametrize(
    "content",
    [
        None,
        [],
        [DummyTextContent("   ")],
    ],
)
def test_call_tool_rejects_missing_or_blank_text_on_success(monkeypatch, content):
    calls = {}
    result = DummyResult(content)
    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(ValueError, match="text content|non-empty text"):
        asyncio.run(client.call_tool("seller_sprite_scenarios", {}))


def test_call_tool_rejects_invalid_json_text(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent("{")])

    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(client.call_tool("seller_sprite_scenarios", {}))


def test_call_tool_rejects_success_text_over_configured_size(monkeypatch):
    calls = {}
    result = DummyResult([DummyTextContent(json.dumps({"success": True, "data": "large"}))])
    install_remote_client_mocks(monkeypatch, calls, result)
    client = RemoteMcpClient(
        url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
        max_response_bytes=8,
    )

    with pytest.raises(ValueError, match="size limit"):
        asyncio.run(client.call_tool("seller_sprite_scenarios", {}))


@pytest.mark.parametrize("text", ['"bad"', "[1, 2, 3]"])
def test_call_tool_rejects_non_object_json_on_success(monkeypatch, text):
    calls = {}
    result = DummyResult([DummyTextContent(text)])
    install_remote_client_mocks(monkeypatch, calls, result)

    client = RemoteMcpClient(url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo")

    with pytest.raises(ValueError, match="JSON object"):
        asyncio.run(client.call_tool("seller_sprite_scenarios", {}))
