from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


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
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = []

    async def call_tool(self, tool_name, arguments):
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


def test_remote_adapter_maps_run_to_seller_sprite_run():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = SellerSpriteRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.run(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": "B07YRMT36L"},
        page_size=100,
        export_format="json",
        output_dir=None,
        job_id=None,
    )

    assert result["success"] is True
    assert result["data"]["tool"] == "seller_sprite_run"
    assert result["data"]["arguments"]["scenario"] == "keyword-reverse"
    assert result["data"]["arguments"]["site"] == "JP"
    assert result["data"]["arguments"]["period"] == "nearly"
    assert result["data"]["arguments"]["params"] == {"asin": "B07YRMT36L"}
    assert result["data"]["arguments"]["page_size"] == 100
    assert result["data"]["arguments"]["export_format"] == "json"
    assert result["data"]["arguments"]["output_dir"] is None
    assert result["data"]["arguments"]["job_id"] is None
    assert created_clients[0].calls == [
        (
            "seller_sprite_run",
            {
                "scenario": "keyword-reverse",
                "site": "JP",
                "period": "nearly",
                "params": {"asin": "B07YRMT36L"},
                "page_size": 100,
                "export_format": "json",
                "output_dir": None,
                "job_id": None,
            },
        )
    ]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_remote_adapter_maps_job_status_and_export_tools():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = SellerSpriteRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    status = adapter.job_status("job-1")
    export = adapter.export("job-1")

    assert status["data"]["tool"] == "seller_sprite_job_status"
    assert status["data"]["arguments"] == {"job_id": "job-1"}
    assert export["data"]["tool"] == "seller_sprite_export"
    assert export["data"]["arguments"] == {"job_id": "job-1"}
    assert [client.calls[0][0] for client in created_clients] == [
        "seller_sprite_job_status",
        "seller_sprite_export",
    ]


def test_remote_adapter_maps_quota_status_tool():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = SellerSpriteRemoteAdapter(
        config_client=config_client,
        remote_client_factory=make_remote_client,
    )

    result = adapter.quota_status()

    assert result["success"] is True
    assert result["data"]["tool"] == "seller_sprite_quota_status"
    assert result["data"]["arguments"] == {}
    assert created_clients[0].calls == [("seller_sprite_quota_status", {})]
