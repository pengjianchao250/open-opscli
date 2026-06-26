"""远端 MCP 共享适配基座测试。"""

import httpx

from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class FakeConfigClient:
    def __init__(self) -> None:
        self.payload = {"data": {}}
        self.calls = []

    def fetch_remote_config(self):
        self.calls.append(("fetch_remote_config",))
        return self.payload

    def select_server(self, payload, *, transport="http", preferred_name=None):
        self.calls.append(("select_server", payload, transport, preferred_name))
        return RemoteMcpServerConfig(
            name="BI运营系统",
            transport="http",
            url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
        )


class FakeRemoteClient:
    def __init__(self, url: str, *, result=None, error: Exception | None = None) -> None:
        self.url = url
        self.result = result or {"success": True, "data": {"ok": True}, "error": None}
        self.error = error
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.error is not None:
            raise self.error
        return self.result


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://ops.mcp.xenkee.com/mcp")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code} error", request=request, response=response)


def test_call_tool_selects_bi_http_server_and_filters_none_values():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.call_tool(
        "demo_tool",
        {
            "scenario": "product",
            "output_dir": None,
            "job_id": None,
            "page_size": 100,
        },
    )

    assert result["success"] is True
    assert created_clients[0].calls == [
        ("demo_tool", {"scenario": "product", "page_size": 100})
    ]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_call_tool_retries_once_when_permission_error_contains_401():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        error = PermissionError("401 unauthorized") if not created_clients else None
        client = FakeRemoteClient(
            url,
            result={"success": True, "data": {"attempt": len(created_clients) + 1}, "error": None},
            error=error,
        )
        created_clients.append(client)
        return client

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.call_tool("demo_tool", {"job_id": "job-1", "output_dir": None})

    assert result == {"success": True, "data": {"attempt": 2}, "error": None}
    assert len(created_clients) == 2
    assert created_clients[0].calls == [("demo_tool", {"job_id": "job-1"})]
    assert created_clients[1].calls == [("demo_tool", {"job_id": "job-1"})]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_call_tool_retries_once_when_exception_group_contains_http_401():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        error = ExceptionGroup("remote unauthorized", [_make_http_status_error(401)]) if not created_clients else None
        client = FakeRemoteClient(
            url,
            result={"success": True, "data": {"attempt": len(created_clients) + 1}, "error": None},
            error=error,
        )
        created_clients.append(client)
        return client

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.call_tool("demo_tool", {"job_id": "job-1"})

    assert result == {"success": True, "data": {"attempt": 2}, "error": None}
    assert len(created_clients) == 2
    assert created_clients[0].calls == [("demo_tool", {"job_id": "job-1"})]
    assert created_clients[1].calls == [("demo_tool", {"job_id": "job-1"})]


def test_call_tool_reraises_non_401_permission_error_without_retry():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url, error=PermissionError("403 forbidden"))
        created_clients.append(client)
        return client

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    try:
        adapter.call_tool("demo_tool", {"job_id": "job-1"})
    except PermissionError as exc:
        assert str(exc) == "403 forbidden"
    else:
        raise AssertionError("expected PermissionError to be re-raised")

    assert len(created_clients) == 1
    assert created_clients[0].calls == [("demo_tool", {"job_id": "job-1"})]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_call_tool_reraises_exception_group_without_401():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url, error=ExceptionGroup("remote failure", [_make_http_status_error(403)]))
        created_clients.append(client)
        return client

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    try:
        adapter.call_tool("demo_tool", {"job_id": "job-1"})
    except ExceptionGroup as exc:
        assert "remote failure" in str(exc)
    else:
        raise AssertionError("expected ExceptionGroup to be re-raised")

    assert len(created_clients) == 1
    assert created_clients[0].calls == [("demo_tool", {"job_id": "job-1"})]


def test_call_tool_passes_preferred_name_override_to_select_server():
    config_client = FakeConfigClient()

    adapter = RemoteMcpAdapter(
        config_client=config_client,
        remote_client_factory=FakeRemoteClient,
        preferred_name="备用服务",
    )

    adapter.call_tool("demo_tool", {"page_size": 50})

    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "备用服务"),
    ]
