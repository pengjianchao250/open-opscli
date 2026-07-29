"""Google Trends 远端 MCP 适配层测试。"""

from opscli.google_trends.remote_adapter import GoogleTrendsRemoteAdapter
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


def test_remote_adapter_maps_run_to_google_trends_run():
    """正式 CLI 的 run 应映射到远端 google_trends_run。"""
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = GoogleTrendsRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="trends",
        geo="JP",
        params={"q": "flashlight", "data_type": "TIMESERIES"},
        job_id=None,
        export_format="json",
        hl="ja-JP",
        tz=540,
    )

    assert result["success"] is True
    assert result["data"]["tool"] == "google_trends_run"
    assert result["data"]["arguments"] == {
        "scenario": "trends",
        "geo": "JP",
        "params": {"q": "flashlight", "data_type": "TIMESERIES"},
        "export_format": "json",
        "hl": "ja-JP",
        "tz": 540,
    }
    assert created_clients[0].calls == [
        (
            "google_trends_run",
            {
                "scenario": "trends",
                "geo": "JP",
                "params": {"q": "flashlight", "data_type": "TIMESERIES"},
                "export_format": "json",
                "hl": "ja-JP",
                "tz": 540,
            },
        )
    ]


def test_remote_adapter_preserves_explicit_job_id():
    """显式传入的 job_id 不应被过滤。"""
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = GoogleTrendsRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="trends",
        geo="US",
        params={"q": "aukey", "data_type": "RELATED_QUERIES"},
        job_id="gt-job-1",
        export_format="xlsx",
        hl=None,
        tz=None,
    )

    assert result["data"]["arguments"]["job_id"] == "gt-job-1"
    assert created_clients[0].calls == [
        (
            "google_trends_run",
            {
                "scenario": "trends",
                "geo": "US",
                "params": {"q": "aukey", "data_type": "RELATED_QUERIES"},
                "job_id": "gt-job-1",
                "export_format": "xlsx",
            },
        )
    ]


def test_remote_adapter_maps_query_tools():
    """查询类命令应映射到对应远端工具。"""
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = GoogleTrendsRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    scenarios = adapter.scenarios()
    status = adapter.job_status("job-1")
    export = adapter.export("job-1")

    assert scenarios["data"]["tool"] == "google_trends_scenarios"
    assert scenarios["data"]["arguments"] == {}
    assert status["data"]["tool"] == "google_trends_job_status"
    assert status["data"]["arguments"] == {"job_id": "job-1"}
    assert export["data"]["tool"] == "google_trends_export"
    assert export["data"]["arguments"] == {"job_id": "job-1"}
