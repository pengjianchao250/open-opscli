import pytest
import respx
import httpx
from opscli.auth.core.device_flow import DeviceFlow
from opscli.auth.exceptions import DeviceFlowExpiredError, DeviceFlowDeniedError

OPS = "https://ops.example.com"


@pytest.fixture
def flow(tmp_path):
    from opscli.auth.storage.credential_store import CredentialStore
    return DeviceFlow(ops_url=OPS, store=CredentialStore(base_dir=tmp_path))


@respx.mock
def test_request_device_code(flow):
    respx.post(f"{OPS}/v1/cli/device/code").mock(return_value=httpx.Response(200, json={
        "device_code": "dc-abc",
        "user_code": "ABCD-1234",
        "verification_url": f"{OPS}/cli-auth",
        "expires_in": 300,
        "interval": 1,
    }))
    r = flow.request_device_code()
    assert r["user_code"] == "ABCD-1234"


@respx.mock
def test_poll_once_pending_does_not_save_session(flow):
    respx.get(f"{OPS}/v1/cli/device/poll").mock(
        return_value=httpx.Response(200, json={"status": "pending", "interval": 1})
    )

    r = flow.poll_once("dc-abc", timeout=1)

    assert r["status"] == "pending"
    assert flow._store.load() is None


@respx.mock
def test_poll_once_authorized_saves_session(flow):
    respx.get(f"{OPS}/v1/cli/device/poll").mock(return_value=httpx.Response(200, json={
        "status": "authorized",
        "session_id": "uuid-yyyy",
        "email": "user@example.com",
        "expires_at": "2099-01-01T00:00:00Z",
    }))

    r = flow.poll_once("dc-abc", timeout=1)

    assert r["status"] == "authorized"
    assert flow._store.load()["session_id"] == "uuid-yyyy"


@respx.mock
def test_poll_success(flow):
    respx.get(f"{OPS}/v1/cli/device/poll").mock(return_value=httpx.Response(200, json={
        "status": "authorized",
        "session_id": "uuid-yyyy",
        "email": "user@example.com",
        "expires_at": "2099-01-01T00:00:00Z",
    }))
    r = flow.poll("dc-abc", interval=0)
    assert r["session_id"] == "uuid-yyyy"
    assert flow._store.load()["device_code"] == "dc-abc"


@respx.mock
def test_poll_expired_raises(flow):
    respx.get(f"{OPS}/v1/cli/device/poll").mock(
        return_value=httpx.Response(200, json={"status": "expired"}))
    with pytest.raises(DeviceFlowExpiredError):
        flow.poll("dc-abc", interval=0)


@respx.mock
def test_poll_denied_raises(flow):
    respx.get(f"{OPS}/v1/cli/device/poll").mock(
        return_value=httpx.Response(200, json={"status": "denied"}))
    with pytest.raises(DeviceFlowDeniedError):
        flow.poll("dc-abc", interval=0)
