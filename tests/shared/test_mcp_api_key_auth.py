from opscli.mcp.context import mcp_request_ctx
from opscli.shared.file_uploads import FileUploadClient
from opscli.shared.integration_accounts import IntegrationAccountClient


class BlockingAuthClient:
    def build_request_auth(self, alias):
        raise AssertionError("CLI auth should not be used when MCP API key is present")

    def get_token_by_session(self, session_id, alias):
        raise AssertionError("session token should not be fetched")


class RecordingAuthClient:
    def __init__(self):
        self.called_with = None

    def build_request_auth(self, alias):
        self.called_with = alias
        return {"Authorization": "Bearer cli-jwt", "X-Opscli-Version": "test"}, {
            "polarisUserToken": "cli-session"
        }

    def get_token_by_session(self, session_id, alias):
        raise AssertionError("session token should not be fetched")


def test_integration_accounts_use_mcp_api_key_without_cli_auth():
    client = IntegrationAccountClient(auth_client=BlockingAuthClient())
    token = mcp_request_ctx.set({"api_key": "mcp-key-1"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers["X-MCP-API-Key"] == "mcp-key-1"
    assert headers["X-Opscli-Version"]
    assert cookies == {}


def test_file_upload_uses_mcp_api_key_without_cli_auth():
    client = FileUploadClient(auth_client=BlockingAuthClient())
    token = mcp_request_ctx.set({"api_key": "mcp-key-2"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers["X-MCP-API-Key"] == "mcp-key-2"
    assert headers["X-Opscli-Version"]
    assert cookies == {}


def test_file_upload_uses_cli_auth_without_mcp_api_key():
    auth_client = RecordingAuthClient()
    client = FileUploadClient(auth_client=auth_client)

    headers, cookies = client._get_auth("ops")

    assert auth_client.called_with == "ops"
    assert headers["Authorization"] == "Bearer cli-jwt"
    assert cookies == {"polarisUserToken": "cli-session"}


def test_integration_accounts_use_cli_auth_without_mcp_api_key():
    auth_client = RecordingAuthClient()
    client = IntegrationAccountClient(auth_client=auth_client)

    headers, cookies = client._get_auth("ops")

    assert auth_client.called_with == "ops"
    assert headers["Authorization"] == "Bearer cli-jwt"
    assert cookies == {"polarisUserToken": "cli-session"}


def test_explicit_jwt_does_not_mix_request_mcp_api_key():
    client = IntegrationAccountClient(auth_client=BlockingAuthClient(), jwt="jwt-1")
    token = mcp_request_ctx.set({"api_key": "mcp-key-3"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers["Authorization"] == "Bearer jwt-1"
    assert headers["X-Opscli-Version"]
    assert "X-MCP-API-Key" not in headers
    assert cookies == {}


def test_explicit_session_and_jwt_do_not_mix_request_mcp_api_key():
    client = IntegrationAccountClient(
        auth_client=BlockingAuthClient(),
        jwt="jwt-2",
        session_id="session-2",
    )
    token = mcp_request_ctx.set({"api_key": "mcp-key-from-another-user"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers["Authorization"] == "Bearer jwt-2"
    assert headers["X-Opscli-Version"]
    assert "X-MCP-API-Key" not in headers
    assert cookies == {"polarisUserToken": "session-2"}
