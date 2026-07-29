import httpx
import pytest

from opscli.mcp_client.config_client import (
    BadRemoteConfigError,
    McpConfigClient,
    RemoteConfigBusinessError,
)


class DummyAuthClient:
    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        assert alias == "ops"
        return (
            {"Authorization": "Bearer jwt-demo", "X-Opscli-Version": "0.0.97"},
            {
                "polarisUserToken": "sid-demo",
                "opscliDeviceCode": "dc-demo",
            },
        )


def test_fetch_remote_config_forwards_auth_headers_and_cookies(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, cookies=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["cookies"] = cookies
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "http": {
                        "mcpServers": {
                            "BI运营系统": {
                                "type": "http",
                                "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
                            }
                        }
                    }
                },
            },
        )

    monkeypatch.setattr("opscli.mcp_client.config_client.httpx.get", fake_get)
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    payload = client.fetch_remote_config()

    assert captured["url"] == "https://ops.example.com/api/v1/mcp-api-keys/config"
    assert captured["headers"]["Authorization"] == "Bearer jwt-demo"
    assert captured["headers"]["X-Opscli-Version"] == "0.0.97"
    assert captured["cookies"]["polarisUserToken"] == "sid-demo"
    assert captured["cookies"]["opscliDeviceCode"] == "dc-demo"
    assert captured["timeout"] == 20
    assert payload["data"]["http"]["mcpServers"]["BI运营系统"]["type"] == "http"


def test_fetch_remote_config_rejects_success_false_payload(monkeypatch):
    def fake_get(url, headers=None, cookies=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "success": False,
                "error": "配置生成失败",
                "data": {},
            },
        )

    monkeypatch.setattr("opscli.mcp_client.config_client.httpx.get", fake_get)
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    with pytest.raises(RemoteConfigBusinessError, match="配置生成失败"):
        client.fetch_remote_config()


def test_select_server_prefers_named_http_server():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "备用服务": {
                        "type": "http",
                        "url": "https://backup.example.com/mcp?api_key=backup",
                    },
                    "BI运营系统": {
                        "type": "http",
                        "url": "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo",
                    },
                }
            }
        }
    }

    server = client.select_server(payload, transport="http", preferred_name="BI运营系统")

    assert server.name == "BI运营系统"
    assert server.transport == "http"
    assert server.url == "https://ops.mcp.xenkee.com/mcp?api_key=mcp_demo"


def test_select_server_falls_back_to_first_http_server():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "默认服务": {
                        "type": "http",
                        "url": "https://default.example.com/mcp?api_key=default",
                    }
                }
            }
        }
    }

    server = client.select_server(payload, transport="http", preferred_name="不存在的服务")

    assert server.name == "默认服务"
    assert server.transport == "http"
    assert server.url == "https://default.example.com/mcp?api_key=default"


def test_select_server_strict_mode_rejects_missing_preferred_server():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "备用服务": {
                        "type": "http",
                        "url": "https://backup.example.com/mcp?api_key=default",
                    }
                }
            }
        }
    }

    with pytest.raises(BadRemoteConfigError, match="BI运营系统"):
        client.select_server(
            payload,
            transport="http",
            preferred_name="BI运营系统",
            require_preferred=True,
        )


def test_select_server_raises_when_http_servers_missing():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    with pytest.raises(BadRemoteConfigError, match="http\\.mcpServers"):
        client.select_server({"data": {}}, transport="http")


def test_select_server_raises_when_mcp_servers_shape_invalid():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")

    with pytest.raises(BadRemoteConfigError, match="http\\.mcpServers"):
        client.select_server({"data": {"http": {"mcpServers": []}}}, transport="http")


def test_select_server_raises_when_server_type_mismatch():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "BI运营系统": {
                        "type": "sse",
                        "url": "https://ops.mcp.xenkee.com/sse?api_key=mcp_demo",
                    }
                }
            }
        }
    }

    with pytest.raises(BadRemoteConfigError, match="type"):
        client.select_server(payload, transport="http", preferred_name="BI运营系统")


def test_select_server_raises_when_server_url_missing():
    client = McpConfigClient(auth_client=DummyAuthClient(), ops_url="https://ops.example.com/api")
    payload = {
        "data": {
            "http": {
                "mcpServers": {
                    "BI运营系统": {
                        "type": "http",
                    }
                }
            }
        }
    }

    with pytest.raises(BadRemoteConfigError, match="url"):
        client.select_server(payload, transport="http", preferred_name="BI运营系统")
