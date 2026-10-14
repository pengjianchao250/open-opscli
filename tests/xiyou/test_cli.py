"""西柚 CLI 在宿主未挂载 MCP 工具时仍可走正式远端链路。"""

import json

import pytest
from typer.testing import CliRunner

from opscli.cli import app
from opscli.mcp_client.config_client import RemoteMcpServerConfig
from opscli.shared import remote_mcp_adapter


runner = CliRunner()


def test_xiyou_entrypoint_is_available_without_host_tools():
    result = runner.invoke(app, ["xiyou", "--help"])
    assert result.exit_code == 0, result.output
    assert "operations" in result.output
    assert "call" in result.output


def test_xiyou_cli_reaches_remote_mcp_without_local_provider(monkeypatch, tmp_path):
    """顶级命令经共享配置与传输层透传，供应商凭据留在服务端。"""
    calls = []

    class ConfigClient:
        def fetch_remote_config(self):
            return {"data": {}}

        def select_server(self, payload, **kwargs):
            assert kwargs["preferred_name"] == "BI运营系统"
            return RemoteMcpServerConfig(
                name="BI运营系统", transport="http", url="https://example.test/mcp"
            )

    class RemoteClient:
        def __init__(self, url):
            assert url == "https://example.test/mcp"

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return {"success": True, "data": [], "source": "xydc_openapi"}

    monkeypatch.setattr(remote_mcp_adapter, "McpConfigClient", ConfigClient)
    monkeypatch.setattr(remote_mcp_adapter, "RemoteMcpClient", RemoteClient)
    request = {"entities": [{"asin": "B0GHVWPSMZ", "country": "US"}]}
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(request), encoding="utf-8-sig")
    output_file = tmp_path / "result.json"
    directory = runner.invoke(app, ["xiyou", "operations"])
    query = runner.invoke(app, [
        "xiyou", "call", "asin_info", "--payload-file", str(payload_file),
        "--output", str(output_file),
    ])
    assert directory.exit_code == 0, directory.output
    assert query.exit_code == 0, query.output
    assert calls == [
        ("ext_xydc_openapi_operations", {}),
        ("ext_xydc_openapi_call", {"operation": "asin_info", "payload": request}),
    ]
    assert json.loads(output_file.read_text(encoding="utf-8"))["success"] is True


@pytest.mark.parametrize("args", [
    [],
    ["--payload", "[]"],
    ["--payload", "null"],
    ["--payload", "invalid-json"],
    ["--payload", ""],
])
def test_invalid_payload_never_reaches_remote(monkeypatch, args):
    from opscli.xiyou import cli

    def forbidden():
        raise AssertionError("无效参数不应触发远端或收费请求")

    monkeypatch.setattr(cli, "XiyouRemoteAdapter", forbidden)
    result = runner.invoke(app, ["xiyou", "call", "asin_info", *args])
    assert result.exit_code == 2, result.output


def test_payload_sources_are_exclusive_and_internal_operation_is_blocked(monkeypatch, tmp_path):
    from opscli.xiyou import cli

    def forbidden():
        raise AssertionError("内部操作或冲突输入不应触发远端请求")

    monkeypatch.setattr(cli, "XiyouRemoteAdapter", forbidden)
    source = tmp_path / "payload.json"
    source.write_text("{}", encoding="utf-8")
    for args in [
        ["asin_info", "--payload", "{}", "--payload-file", str(source)],
        ["client_quota", "--payload", "{}"],
        ["unknown_operation", "--payload", "{}"],
        ["asin_info", "--payload", "{}", "--output", str(tmp_path / "missing" / "out.json")],
    ]:
        result = runner.invoke(app, ["xiyou", "call", *args])
        assert result.exit_code == 2, result.output


def test_failed_remote_query_is_preserved_and_not_replayed(monkeypatch, tmp_path):
    """供应商范围拒绝原样落盘，不能由代理修改日期或吞掉失败。"""
    from opscli.xiyou.remote_adapter import XiyouRemoteAdapter

    request = {
        "asin": "B0GHVWPSMZ", "country": "US", "page": 0,
        "startMonth": "2025-06", "endMonth": "2026-09",
        "sort": {"field": "traffic", "order": "desc"},
    }
    response = {
        "success": False, "data": None, "source": "xydc_openapi",
        "error": {"code": "InvalidTrendsRange", "trace_id": "trace-123"},
        "quota": {"remaining": 20},
    }
    calls = []

    async def remote_call(self, tool_name, arguments):
        calls.append((tool_name, arguments))
        return response

    monkeypatch.setattr(XiyouRemoteAdapter, "call_tool_async", remote_call)
    target = tmp_path / "error.json"
    result = runner.invoke(app, [
        "xiyou", "call", "asin_research_monthly", "--payload", json.dumps(request),
        "--output", str(target),
    ])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == response
    assert json.loads(target.read_text(encoding="utf-8")) == response
    assert calls == [("ext_xydc_openapi_call", {"operation": "asin_research_monthly", "payload": request})]
