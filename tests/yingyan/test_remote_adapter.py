"""鹰眼 PND 远端 MCP 适配层测试。"""

from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.yingyan.remote_adapter import YingyanRemoteAdapter


class FakeConfigClient:
    def __init__(self) -> None:
        self.calls = []

    def fetch_remote_config(self):
        self.calls.append(("fetch_remote_config",))
        return {"data": {}}

    def select_server(
        self,
        payload,
        *,
        transport="http",
        preferred_name=None,
        require_preferred=False,
    ):
        self.calls.append(
            ("select_server", payload, transport, preferred_name, require_preferred)
        )
        return RemoteMcpServerConfig(
            name="BI运营系统",
            transport="http",
            url="https://example.test/mcp",
        )


class FakeRemoteClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return {"success": True, "data": {"tool": tool_name, "arguments": arguments}}


def make_adapter():
    config_client = FakeConfigClient()
    clients = []

    def factory(url: str):
        client = FakeRemoteClient(url)
        clients.append(client)
        return client

    return YingyanRemoteAdapter(
        config_client=config_client,
        remote_client_factory=factory,
    ), config_client, clients


def test_maps_all_yingyan_tools_to_remote_mcp():
    adapter, config_client, clients = make_adapter()

    datasets = adapter.list_available_datasets()
    sql = adapter.execute_readonly_sql("SELECT category_id FROM t LIMIT 1")
    terms = adapter.search_similar_terms(
        search_term="stereo amplifier",
        site="US",
        top=10,
    )
    status = adapter.report_task_status("task-1")

    assert [item[0] for client in clients for item in client.calls] == [
        "ext_pnd_list_available_datasets",
        "ext_pnd_execute_readonly_sql",
        "ext_pnd_search_similar_terms",
        "ext_pnd_get_report_task_status",
    ]
    assert sql["data"]["arguments"] == {"sql": "SELECT category_id FROM t LIMIT 1"}
    assert terms["data"]["arguments"] == {
        "search_term": "stereo amplifier",
        "site": "US",
        "top": 10,
    }
    assert status["data"]["arguments"] == {"task_id": "task-1"}
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统", True),
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统", True),
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统", True),
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统", True),
    ]
