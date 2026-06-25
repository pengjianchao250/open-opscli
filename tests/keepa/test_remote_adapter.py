"""Keepa 远端 MCP 适配层测试。"""

from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.keepa.remote_adapter import KeepaRemoteAdapter


class FakeConfigClient:
    """模拟远端 MCP 配置客户端。"""

    def __init__(self) -> None:
        self.payload = {"data": {}}
        self.calls = []

    def fetch_remote_config(self):
        """返回测试用远端配置。"""
        self.calls.append(("fetch_remote_config",))
        return self.payload

    def select_server(self, payload, *, transport="http", preferred_name=None):
        """返回固定的 HTTP server。"""
        self.calls.append(("select_server", payload, transport, preferred_name))
        return RemoteMcpServerConfig(
            name="BI运营系统",
            transport="http",
            url="https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
        )


class FakeRemoteClient:
    """记录远端工具调用参数。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        """返回可断言的结构化结果。"""
        self.calls.append((tool_name, arguments))
        return {
            "success": True,
            "data": {
                "tool": tool_name,
                "arguments": arguments,
                "url": self.url,
            },
            "error": None,
        }


def test_remote_adapter_maps_run_to_keepa_run():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = KeepaRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="product",
        site="JP",
        params={"asin": "B0TEST123"},
        job_id=None,
        export_format="xlsx",
        reserve_tokens=8,
        force=True,
        wait=False,
    )

    assert result["success"] is True
    assert result["data"]["tool"] == "keepa_run"
    assert result["data"]["arguments"] == {
        "scenario": "product",
        "site": "JP",
        "params": {"asin": "B0TEST123"},
        "export_format": "xlsx",
        "reserve_tokens": 8,
        "force": True,
        "wait": False,
    }
    assert created_clients[0].calls == [
        (
            "keepa_run",
            {
                "scenario": "product",
                "site": "JP",
                "params": {"asin": "B0TEST123"},
                "export_format": "xlsx",
                "reserve_tokens": 8,
                "force": True,
                "wait": False,
            },
        )
    ]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_remote_adapter_maps_status_and_export_tools():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = KeepaRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    status = adapter.job_status("job-1")
    export = adapter.export("job-1")

    assert status["data"]["tool"] == "keepa_job_status"
    assert status["data"]["arguments"] == {"job_id": "job-1"}
    assert export["data"]["tool"] == "keepa_export"
    assert export["data"]["arguments"] == {"job_id": "job-1"}
    assert [client.calls[0][0] for client in created_clients] == [
        "keepa_job_status",
        "keepa_export",
    ]


def test_remote_adapter_preserves_explicit_job_id():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = KeepaRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="product",
        site="US",
        params={"asin": "B0TEST456"},
        job_id="keepa-job-1",
        export_format="xls",
        reserve_tokens=None,
        force=False,
        wait=True,
    )

    assert result["data"]["arguments"]["job_id"] == "keepa-job-1"
    assert result["data"]["arguments"]["wait"] is True
    assert created_clients[0].calls == [
        (
            "keepa_run",
            {
                "scenario": "product",
                "site": "US",
                "params": {"asin": "B0TEST456"},
                "job_id": "keepa-job-1",
                "export_format": "xls",
                "force": False,
                "wait": True,
            },
        )
    ]


def test_remote_adapter_maps_scenarios_tool():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = KeepaRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.scenarios()

    assert result["success"] is True
    assert result["data"]["tool"] == "keepa_scenarios"
    assert result["data"]["arguments"] == {}
    assert created_clients[0].calls == [("keepa_scenarios", {})]
