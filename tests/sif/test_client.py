import httpx
import pytest

from opscli.sif.client import GROUP_VARIANTS_PATH, LISTING_HISTORY_PATH, LOGIN_PATH, SifApiClient
from opscli.sif.config import BASE_URL, SifSettings
from opscli.sif.domain.exceptions import SifApiRequestError, SifDownloadError, SifLoginError, SifLoginRequiredError


def test_client_uses_post_for_json_endpoints(monkeypatch):
    calls = []

    class DummyHttpClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        cookies = {"SESSION": "demo"}

        def post(self, url, json, params=None):
            calls.append(("POST", url, json, params))
            if url.endswith("/download"):
                return httpx.Response(200, content=b"PK\x03\x04demo")
            return httpx.Response(200, json={"code": 0, "data": {"asin": []}})

        def get(self, url, params):
            calls.append(("GET", url, params))
            return httpx.Response(200, content=b"PK\x03\x04demo")

    monkeypatch.setattr(httpx, "Client", DummyHttpClient)
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    result = client.fetch_sales(asin="B01NBNDC1T", site="US")

    assert result.listing_history["code"] == 0
    post_calls = [call for call in calls if call[0] == "POST"]
    assert post_calls[0][1] == f"{BASE_URL}{LISTING_HISTORY_PATH}"
    assert post_calls[0][2] == {"pageSize": 5, "pageNum": 1, "asins": ["B01NBNDC1T"], "dimension": "asin"}
    assert post_calls[0][3]["country"] == "US"
    assert post_calls[0][3]["_m"].startswith("Sif_")
    assert post_calls[1][1] == f"{BASE_URL}{GROUP_VARIANTS_PATH}"
    assert post_calls[2][1] == f"{BASE_URL}/api/updown/boughtListingHistory/download"
    assert post_calls[2][2] == {"asins": ["B01NBNDC1T"]}
    assert post_calls[3][1] == f"{BASE_URL}/api/updown/boughtByAsin/download"
    assert post_calls[3][2] == {
        "pageNum": 1,
        "pageSize": 100,
        "sortBy": "",
        "desc": True,
        "asins": ["B01NBNDC1T"],
        "timePieceType": "latelyDay",
        "timePieceValue": "30",
    }


def test_client_logs_in_with_username_password(monkeypatch):
    calls = []

    class DummyCookies(dict):
        pass

    class DummyHttpClient:
        def __init__(self, **kwargs):
            self.cookies = DummyCookies()
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, params=None):
            calls.append(("POST", url, json, params))
            if url.endswith(LOGIN_PATH):
                self.cookies["SESSION"] = "demo"
                return httpx.Response(200, json={"code": 1, "data": {"ok": True}}, headers={"authorization": "Bearer demo"})
            assert self.headers["authorization"] == "Bearer demo"
            if "/api/updown/" in url:
                return httpx.Response(200, content=b"PK\x03\x04demo")
            return httpx.Response(200, json={"code": 0, "data": {"asin": []}})

        def get(self, url, params):
            calls.append(("GET", url, params))
            return httpx.Response(200, content=b"PK\x03\x04demo")

    monkeypatch.setattr(httpx, "Client", DummyHttpClient)
    client = SifApiClient(settings=SifSettings(username="user", password="secret"))

    client.fetch_sales(asin="B01NBNDC1T", site="US")

    assert ("POST", f"{BASE_URL}{LOGIN_PATH}", {"phone": "user", "password": "secret"}, None) in calls


def test_client_prefers_credentials_over_cookie(monkeypatch):
    calls = []

    class DummyCookies(dict):
        pass

    class DummyHttpClient:
        def __init__(self, **kwargs):
            self.cookies = DummyCookies()
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, params=None):
            calls.append(("POST", url, json, params))
            self.cookies["SESSION"] = "demo"
            return httpx.Response(200, json={"code": 1, "data": {"isSuccess": True}}, headers={"authorization": "Bearer demo"})

        def get(self, url, params):
            return httpx.Response(200, json={"code": 0, "data": {}})

    monkeypatch.setattr(httpx, "Client", DummyHttpClient)
    client = SifApiClient(settings=SifSettings(cookie="OLD=1", username="user", password="secret"))

    payload = client.login_diagnostics()

    assert ("POST", f"{BASE_URL}{LOGIN_PATH}", {"phone": "user", "password": "secret"}, None) in calls
    assert payload["auth_input_mode"] == "credentials"
    assert payload["will_attempt_password_login"] is True


def test_login_diagnostics_exposes_shape_without_secrets():
    client = SifApiClient(settings=SifSettings(username="user", password="secret"))

    class DummyCookie:
        name = "SESSION"

    class DummyJar:
        def __iter__(self):
            return iter([DummyCookie()])

    class DummyCookies:
        jar = DummyJar()

        def __bool__(self):
            return True

    class DummyClient:
        cookies = DummyCookies()

    response = httpx.Response(
        200,
        json={"code": 1, "data": {"isSuccess": True, "userId": 123}},
        headers={"authorization": "Bearer secret-token"},
    )

    payload = client._build_login_diagnostics(response, DummyClient())

    assert payload["login_code"] == 1
    assert payload["login_is_success"] is True
    assert payload["login_has_authorization"] is True
    assert "secret-token" not in str(payload)


def test_client_login_failure_raises_login_error(monkeypatch):
    class DummyHttpClient:
        cookies = {}

        def post(self, url, json):
            return httpx.Response(200, json={"code": -1, "message": "bad login"})

    client = SifApiClient(settings=SifSettings(username="user", password="bad"))

    with pytest.raises(SifLoginError):
        client._login(DummyHttpClient())


def test_client_rejects_unauthorized_json_business_error():
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    with pytest.raises(SifLoginRequiredError):
        client._raise_for_business_error({"code": -10, "message": "UNAUTHORIZED"}, path="/api/demo")


def test_client_accepts_code_one_business_success():
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    client._raise_for_business_error({"code": 1, "data": {"items": []}}, path="/api/demo")


def test_client_business_error_exposes_public_request_params():
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    with pytest.raises(SifApiRequestError) as exc_info:
        client._raise_for_business_error(
            {"code": -1, "message": "参数错误"},
            path="/api/demo",
            request_payload={"asin": "B01NBNDC1T", "country": "US", "password": "secret"},
            request_query={"country": "US", "_t": 123},
        )

    payload = exc_info.value.to_dict()
    assert payload["request_payload"]["asin"] == "B01NBNDC1T"
    assert payload["request_query"]["country"] == "US"
    assert "password" not in str(payload)


def test_client_rejects_unauthorized_download_body():
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    with pytest.raises(SifLoginRequiredError):
        client._validate_xlsx_response(b'{"code": -10, "message": "UNAUTHORIZED"}', path="/api/download")


def test_client_rejects_non_xlsx_download_body():
    client = SifApiClient(settings=SifSettings(cookie="SESSION=demo"))

    with pytest.raises(SifDownloadError):
        client._validate_xlsx_response(b"not xlsx", path="/api/download")
