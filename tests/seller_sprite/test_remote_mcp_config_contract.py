import json
import re
from pathlib import Path


DOC_PATH = Path("docs/spec/卖家精灵远端MCP配置契约.md")


def test_remote_mcp_config_contract_success_example_freezes_response_shape():
    content = DOC_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"## Success Response\s+```json\s*(\{.*?\})\s*```",
        content,
        re.DOTALL,
    )
    assert match is not None

    payload = json.loads(match.group(1))
    servers = payload["data"]["http"]["mcpServers"]
    assert set(servers) == {"BI运营系统"}
    server = servers["BI运营系统"]

    assert payload["success"] is True
    assert "mcpServers" in payload["data"]["http"]
    assert server["type"] == "http"
    assert set(server) == {"type", "url"}
    assert "api_key=" in server["url"]


def test_remote_mcp_config_contract_doc_freezes_endpoint_and_transport():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "GET /api/v1/mcp-api-keys/config" in content
    assert "http.mcpServers" in content
    assert '"type": "http"' in content
    assert '"BI运营系统"' in content
    assert '"url": "https://<ops-mcp-host>/mcp?api_key=<issued_key>"' in content
    assert "this is the OPS general MCP, not Collector MCP" in content
    assert "the CLI neither discovers nor configures the Collector address" in content
    assert "data.http.mcpServers" in content
    assert "public `opscli seller-sprite` CLI path is frozen to `data.http.mcpServers`" in content
    assert "the public path only accepts HTTP transport entries from `data.http.mcpServers`" in content
    assert "Authorization: Bearer <ops_jwt>" in content
    assert "X-Opscli-Version: <version>" in content
    assert "polarisUserToken" in content
    assert "opscliDeviceCode" in content
    assert "AuthClient.build_request_auth(\"ops\")" in content
    assert "redact the `api_key` query value" in content
    assert "including the backend-issued user `api_key` query parameter" in content
    assert "does not introduce any dedicated auth-bridge endpoint" in content
    assert "POST /v1/mcp/auth/api-key" not in content
