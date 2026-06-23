from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.seller_sprite.remote_adapter import SellerSpriteRemoteAdapter


def test_remote_adapter_refetches_config_once_on_unauthorized():
    calls = {"config": 0, "tool": 0}

    class FakeConfigClient:
        def fetch_remote_config(self):
            calls["config"] += 1
            key = "old" if calls["config"] == 1 else "new"
            return {
                "data": {
                    "http": {
                        "mcpServers": {
                            "BI运营系统": {
                                "type": "http",
                                "url": f"https://ops.mcp.xenkee.com/mcp?api_key={key}",
                            }
                        }
                    }
                }
            }

        def select_server(self, payload, *, transport="http", preferred_name=None):
            server = payload["data"]["http"]["mcpServers"]["BI运营系统"]
            return RemoteMcpServerConfig(
                name="BI运营系统",
                transport="http",
                url=server["url"],
            )

    class UnauthorizedRemoteClient:
        def __init__(self, url):
            self.url = url

        async def call_tool(self, tool_name, arguments):
            calls["tool"] += 1
            if "api_key=old" in self.url:
                raise PermissionError("401 unauthorized")
            return {"success": True, "data": {"job_id": "job-1"}, "error": None}

    adapter = SellerSpriteRemoteAdapter(
        config_client=FakeConfigClient(),
        remote_client_factory=UnauthorizedRemoteClient,
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

    assert result == {"success": True, "data": {"job_id": "job-1"}, "error": None}
    assert calls == {"config": 2, "tool": 2}
