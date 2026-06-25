"""Canopy 远端 MCP 适配层测试。"""

from opscli.canopy.remote_adapter import CanopyRemoteAdapter
from opscli.mcp_client.config_client import RemoteMcpServerConfig


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


def test_remote_adapter_maps_run_to_beta_canopy_run():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = CanopyRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="product",
        domain="JP",
        params={"asin": "B0TEST123"},
        job_id=None,
        export_format="xls",
        timeout_seconds=45,
    )

    assert result["success"] is True
    assert result["data"]["tool"] == "beta_canopy_run"
    assert result["data"]["arguments"] == {
        "scenario": "product",
        "domain": "JP",
        "params": {"asin": "B0TEST123"},
        "export_format": "xls",
        "timeout_seconds": 45,
    }
    assert created_clients[0].calls == [
        (
            "beta_canopy_run",
            {
                "scenario": "product",
                "domain": "JP",
                "params": {"asin": "B0TEST123"},
                "export_format": "xls",
                "timeout_seconds": 45,
            },
        )
    ]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_remote_adapter_preserves_explicit_job_id():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = CanopyRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="search",
        domain="US",
        params={"searchTerm": "desk lamp"},
        job_id="canopy-job-1",
        export_format="xls",
        timeout_seconds=75,
    )

    assert result["data"]["arguments"]["job_id"] == "canopy-job-1"
    assert created_clients[0].calls == [
        (
            "beta_canopy_run",
            {
                "scenario": "search",
                "domain": "US",
                "params": {"searchTerm": "desk lamp"},
                "job_id": "canopy-job-1",
                "export_format": "xls",
                "timeout_seconds": 75,
            },
        )
    ]


def test_remote_adapter_maps_query_tools():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = CanopyRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    scenarios = adapter.scenarios()
    status = adapter.job_status("job-1")
    export = adapter.export("job-1")

    assert scenarios["data"]["tool"] == "beta_canopy_scenarios"
    assert scenarios["data"]["arguments"] == {}
    assert status["data"]["tool"] == "beta_canopy_job_status"
    assert status["data"]["arguments"] == {"job_id": "job-1"}
    assert export["data"]["tool"] == "beta_canopy_export"
    assert export["data"]["arguments"] == {"job_id": "job-1"}
