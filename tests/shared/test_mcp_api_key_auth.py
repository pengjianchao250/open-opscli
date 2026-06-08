from opscli.mcp.context import mcp_request_ctx
from opscli.shared.file_uploads import FileUploadClient
from opscli.shared.integration_accounts import IntegrationAccountClient


class BlockingAuthClient:
    def build_request_auth(self, alias):
        raise AssertionError("CLI auth should not be used when MCP API key is present")

    def get_token_by_session(self, session_id, alias):
        raise AssertionError("session token should not be fetched")


def test_integration_accounts_use_mcp_api_key_without_cli_auth():
    client = IntegrationAccountClient(auth_client=BlockingAuthClient())
    token = mcp_request_ctx.set({"api_key": "mcp-key-1"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers == {"X-MCP-API-Key": "mcp-key-1"}
    assert cookies == {}


def test_file_upload_uses_mcp_api_key_without_cli_auth():
    client = FileUploadClient(auth_client=BlockingAuthClient())
    token = mcp_request_ctx.set({"api_key": "mcp-key-2"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers == {"X-MCP-API-Key": "mcp-key-2"}
    assert cookies == {}


def test_explicit_jwt_keeps_authorization_and_mcp_header():
    client = IntegrationAccountClient(auth_client=BlockingAuthClient(), jwt="jwt-1")
    token = mcp_request_ctx.set({"api_key": "mcp-key-3"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers == {"Authorization": "Bearer jwt-1", "X-MCP-API-Key": "mcp-key-3"}
    assert cookies == {}
