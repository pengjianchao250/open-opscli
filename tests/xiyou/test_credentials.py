import base64
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import opscli.xiyou.config as xiyou_config
from opscli.xiyou.config import XiyouSettings, load_settings
from opscli.xiyou.credential_service import (
    XiyouCredentialServiceClient,
    get_cached_remote_credential,
    parse_latest_credential_response,
)
from opscli.xiyou.credentials import XiyouCredentialProvider, XiyouCredentialStore
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.mcp.context import mcp_request_ctx


@pytest.fixture
def local_tmp_path():
    path = Path("output") / "test-runs" / f"xiyou-credential-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _jwt(*, seconds: int = 3600) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=seconds)).timestamp())
    header = {"alg": "none", "typ": "JWT"}
    payload = {"exp": exp, "UserId": "u-1"}
    return f"{_b64(header)}.{_b64(payload)}.signature"


def _b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_credential_store_saves_and_loads_atomically(local_tmp_path: Path):
    path = local_tmp_path / "credential.json"
    token = _jwt()
    store = XiyouCredentialStore(path)

    saved = store.save(
        authorization=f"authorization: {token}",
        cookie="sid=abc",
        source="admin",
        operator="zhangsan",
    )
    loaded = store.load()

    assert saved.authorization == token
    assert loaded is not None
    assert loaded.authorization == token
    assert loaded.cookie == "sid=abc"
    assert loaded.source == "admin"
    assert loaded.operator == "zhangsan"
    assert loaded.expires_at is not None


def test_credential_provider_uses_env_when_latest_url_not_configured(local_tmp_path: Path):
    path = local_tmp_path / "credential.json"
    file_token = _jwt()
    env_token = _jwt(seconds=7200)
    XiyouCredentialStore(path).save(authorization=file_token, source="admin")
    provider = XiyouCredentialProvider(
        XiyouSettings(
            authorization=env_token,
            cookie="env-cookie",
            credential_path=path,
        )
    )

    credential = provider.get_default()

    assert credential.authorization == env_token
    assert credential.cookie == "env-cookie"
    assert credential.source == "env"


def test_credential_store_rejects_expired_token_without_writing(local_tmp_path: Path):
    path = local_tmp_path / "credential.json"
    store = XiyouCredentialStore(path)

    with pytest.raises(XiyouConfigError):
        store.save(authorization=_jwt(seconds=-60), source="admin")

    assert not path.exists()


def test_credential_provider_prefers_remote_latest_when_configured(local_tmp_path: Path):
    token = _jwt()
    calls = []

    class BlockingAuthClient:
        def build_request_auth(self, alias):
            raise AssertionError("CLI auth should not be used when explicit credential API key is configured")

        def get_token_by_session(self, session_id, alias):
            raise AssertionError("session token should not be fetched")

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "success": True,
                "data": {
                    "version": 7,
                    "expires_at": "2026-06-15T03:35:26Z",
                    "credential": {
                        "authorization": token,
                        "cookie": "sid=remote",
                        "headers": {"krs-ver": "2026-06-08 15:00:00"},
                    },
                },
            }

    def http_get(url, **kwargs):
        calls.append({"url": url, "headers": kwargs["headers"]})
        return Response()

    settings = XiyouSettings(
        authorization=_jwt(seconds=7200),
        cookie="env-cookie",
        credential_path=local_tmp_path / "credential.json",
        credential_latest_url="https://ops.example.com/api/internal/xiyou/credential/latest",
        credential_api_key="secret",
    )
    client = XiyouCredentialServiceClient(settings, auth_client=BlockingAuthClient(), http_get=http_get)
    credential = get_cached_remote_credential(settings, client=client, refresh=True)

    assert credential.authorization == token
    assert credential.cookie == "sid=remote"
    assert credential.source == "credential_service"
    assert credential.version == 7
    assert credential.headers == {"krs-ver": "2026-06-08 15:00:00"}
    assert calls[0]["headers"]["authorization"] == "Bearer secret"


def test_remote_credential_cache_can_be_forced_to_refresh(local_tmp_path: Path):
    tokens = [_jwt(seconds=3600), _jwt(seconds=7200)]
    calls = []

    class RecordingAuthClient:
        def build_request_auth(self, alias):
            return {"Authorization": "Bearer cli-jwt", "X-Opscli-Version": "test"}, {
                "polarisUserToken": "cli-session"
            }

        def get_token_by_session(self, session_id, alias):
            raise AssertionError("session token should not be fetched")

    class Response:
        status_code = 200
        text = "{}"

        def __init__(self, token: str) -> None:
            self.token = token

        def json(self):
            return {"success": True, "data": {"credential": {"authorization": self.token}}}

    def http_get(url, **kwargs):
        calls.append(url)
        return Response(tokens[len(calls) - 1])

    settings = XiyouSettings(
        credential_latest_url="https://ops.example.com/api/internal/xiyou/credential/latest",
        credential_cache_ttl_seconds=600,
    )
    client = XiyouCredentialServiceClient(settings, auth_client=RecordingAuthClient(), http_get=http_get)

    first = get_cached_remote_credential(settings, client=client, refresh=True)
    second = get_cached_remote_credential(settings, client=client)
    third = get_cached_remote_credential(settings, client=client, refresh=True)

    assert first.authorization == second.authorization
    assert third.authorization != first.authorization
    assert len(calls) == 2


def test_load_settings_builds_default_latest_url_from_ops_system_url(monkeypatch):
    monkeypatch.setattr(xiyou_config, "_read_dotenv", lambda: {})
    monkeypatch.setattr(xiyou_config, "get_ops_system_url", lambda: "https://ops.api.qa.aukeyit.com")
    monkeypatch.delenv("OPSCLI_OPS_SYSTEM_URL", raising=False)
    monkeypatch.delenv("OPSCLI_XIYOU_CREDENTIAL_LATEST_URL", raising=False)

    settings = load_settings()

    assert settings.credential_latest_url == "https://ops.api.qa.aukeyit.com/api/v1/mcp-accounts?platform=xiyou"


def test_load_settings_prefers_explicit_latest_url_override(monkeypatch):
    monkeypatch.setattr(
        xiyou_config,
        "_read_dotenv",
        lambda: {"OPSCLI_XIYOU_CREDENTIAL_LATEST_URL": "https://custom.example.com/xiyou/latest"},
    )
    monkeypatch.setattr(xiyou_config, "get_ops_system_url", lambda: "https://ops.api.qa.aukeyit.com")
    monkeypatch.delenv("OPSCLI_OPS_SYSTEM_URL", raising=False)
    monkeypatch.delenv("OPSCLI_XIYOU_CREDENTIAL_LATEST_URL", raising=False)

    settings = load_settings()

    assert settings.credential_latest_url == "https://custom.example.com/xiyou/latest"


def test_parse_latest_credential_response_supports_mcp_accounts_shape():
    token = _jwt()
    payload = {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "id": 3,
            "platform": "xiyou",
            "cookie_content": json.dumps(
                {
                    "OPSCLI_XIYOU_AUTHORIZATION": token,
                    "OPSCLI_XIYOU_COOKIE": "sid=remote",
                    "OPSCLI_XIYOU_KRS_VER": "1.0.0",
                }
            ),
            "remark": "西柚补登",
            "expires_at": None,
            "updated_at": "2026-06-09 16:55:36",
        },
    }

    credential = parse_latest_credential_response(payload)

    assert credential.authorization == token
    assert credential.cookie == "sid=remote"
    assert credential.source == "credential_service"
    assert credential.operator == "西柚补登"
    assert credential.version == 3
    assert credential.headers == {"krs-ver": "1.0.0"}


def test_credential_service_uses_mcp_api_key_without_cli_auth():
    class BlockingAuthClient:
        def build_request_auth(self, alias):
            raise AssertionError("CLI auth should not be used when MCP API key is present")

        def get_token_by_session(self, session_id, alias):
            raise AssertionError("session token should not be fetched")

    client = XiyouCredentialServiceClient(
        XiyouSettings(credential_latest_url="https://ops.api.qa.aukeyit.com/api/v1/mcp-accounts?platform=xiyou"),
        auth_client=BlockingAuthClient(),
        http_get=lambda *args, **kwargs: None,
    )
    token = mcp_request_ctx.set({"api_key": "mcp-key-xiyou"})
    try:
        headers, cookies = client._get_auth("ops")
    finally:
        mcp_request_ctx.reset(token)

    assert headers["X-MCP-API-Key"] == "mcp-key-xiyou"
    assert headers["X-Opscli-Version"] == "0.0.84"
    assert cookies == {}


def test_credential_service_debug_logs_request_and_response(monkeypatch, capsys):
    token = _jwt()
    monkeypatch.setenv("OPSCLI_XIYOU_DEBUG_CREDENTIAL_REQUEST", "1")

    class DummyAuthClient:
        def build_request_auth(self, alias):
            raise AssertionError("CLI auth should not be used when explicit credential API key is configured")

        def get_token_by_session(self, session_id, alias):
            raise AssertionError("session token should not be fetched")

    class Response:
        status_code = 200
        text = '{"code":200}'

        def json(self):
            return {
                "code": 200,
                "data": {
                    "credential": {
                        "authorization": token,
                        "cookie": "sid=remote",
                    }
                },
            }

    client = XiyouCredentialServiceClient(
        XiyouSettings(
            credential_latest_url="https://ops.api.qa.aukeyit.com/api/v1/mcp-accounts?platform=xiyou",
            credential_api_key="secret-debug-token",
        ),
        auth_client=DummyAuthClient(),
        http_get=lambda *args, **kwargs: Response(),
    )

    credential = client.get_latest()

    assert credential.authorization == token
    stderr = capsys.readouterr().err
    assert "[xiyou-debug]" in stderr
    assert "secret-debug-token" in stderr
    assert "https://ops.api.qa.aukeyit.com/api/v1/mcp-accounts?platform=xiyou" in stderr
    assert '"stage": "response_json"' in stderr
