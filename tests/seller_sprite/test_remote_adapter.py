"""卖家精灵远端 MCP 适配层测试。"""

from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


class FakeAuthClient:
    def get_session(self, alias: str | None = None) -> str:
        assert alias == "ops"
        return "sid-cli-123"


class FakeConfigClient:
    def __init__(self) -> None:
        self.payload = {"data": {}}
        self.calls = []
        self.auth_client = FakeAuthClient()

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
    assert result["data"]["arguments"]["session_id"] == "sid-cli-123"
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
                "session_id": "sid-cli-123",
            },
        )
    ]
    assert config_client.calls == [
        ("fetch_remote_config",),
        ("select_server", {"data": {}}, "http", "BI运营系统"),
    ]


def test_remote_adapter_maps_listing_analysis_tools():
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

    submit = adapter.listing_analysis_submit(
        asin="B0TEST123",
        station="GLOBAL",
        site="US",
        export_format="json",
        job_id=None,
        output_dir=None,
    )
    status = adapter.listing_analysis_status("listing-job-1")
    result = adapter.listing_analysis_result("listing-job-1", export_format="json")

    assert submit["data"]["tool"] == "seller_sprite_listing_analysis_submit"
    assert submit["data"]["arguments"]["asin"] == "B0TEST123"
    assert submit["data"]["arguments"]["session_id"] == "sid-cli-123"
    assert status["data"]["tool"] == "seller_sprite_listing_analysis_status"
    assert result["data"]["tool"] == "seller_sprite_listing_analysis_result"



def test_remote_adapter_job_status_forwards_default_wait_seconds():
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

    assert status["data"]["tool"] == "seller_sprite_job_status"
    assert status["data"]["arguments"] == {"job_id": "job-1", "wait_seconds": 0}
    assert created_clients[0].calls == [
        ("seller_sprite_job_status", {"job_id": "job-1", "wait_seconds": 0})
    ]


def test_remote_adapter_job_status_forwards_explicit_wait_seconds():
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

    status = adapter.job_status("job-1", wait_seconds=12)

    assert status["data"]["arguments"] == {"job_id": "job-1", "wait_seconds": 12}


def test_remote_adapter_jobs_status_preserves_job_id_order_and_default_wait():
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

    status = adapter.jobs_status(["job-3", "job-1", "job-2"])

    assert status["data"]["tool"] == "seller_sprite_jobs_status"
    assert status["data"]["arguments"] == {
        "job_ids": ["job-3", "job-1", "job-2"],
        "wait_seconds": 0,
    }
    assert created_clients[0].calls == [
        (
            "seller_sprite_jobs_status",
            {
                "job_ids": ["job-3", "job-1", "job-2"],
                "wait_seconds": 0,
            },
        )
    ]


def test_remote_adapter_jobs_status_forwards_explicit_wait_seconds():
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

    status = adapter.jobs_status(["job-2", "job-1"], wait_seconds=30)

    assert status["data"]["arguments"] == {
        "job_ids": ["job-2", "job-1"],
        "wait_seconds": 30,
    }


def test_remote_adapter_maps_export_tool():
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

    export = adapter.export("job-1")

    assert export["data"]["tool"] == "seller_sprite_export"
    assert export["data"]["arguments"] == {"job_id": "job-1"}
    assert created_clients[0].calls == [("seller_sprite_export", {"job_id": "job-1"})]


def test_remote_adapter_preserves_explicit_output_dir_and_job_id():
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
        site="US",
        period="7d",
        params={"asin": "B0TEST123"},
        page_size=20,
        export_format="xlsx",
        output_dir="D:/exports",
        job_id="job-keep-1",
    )

    assert result["data"]["arguments"]["output_dir"] == "D:/exports"
    assert result["data"]["arguments"]["job_id"] == "job-keep-1"
    assert created_clients[0].calls == [
        (
            "seller_sprite_run",
            {
                "scenario": "keyword-reverse",
                "site": "US",
                "period": "7d",
                "params": {"asin": "B0TEST123"},
                "page_size": 20,
                "export_format": "xlsx",
                "output_dir": "D:/exports",
                "job_id": "job-keep-1",
                "session_id": "sid-cli-123",
            },
        )
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
