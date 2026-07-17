import respx
from httpx import Response

from opscli.calculator import client as calculator_client
from opscli.calculator.client import CalculatorClient


class FakeAuthClient:
    def build_request_auth(self, alias):
        assert alias == "polaris"
        return {"Authorization": "Bearer test-token"}, {"polarisUserToken": "session-id"}


def test_client_default_base_url_uses_polaris_system_url(monkeypatch):
    monkeypatch.setattr(
        calculator_client,
        "get_builtin_systems",
        lambda: [
            {"alias": "ops", "url": "https://ops.api.xenkee.com"},
            {"alias": "polaris", "url": "https://bi.api.xenkee.com"},
        ],
    )

    client = CalculatorClient(auth_client=FakeAuthClient())

    assert client.base_url == "https://bi.api.xenkee.com"


@respx.mock
def test_query_cost_posts_to_polaris_endpoint():
    route = respx.post("https://polaris.test/calculator/newProduct/queryCost").mock(
        return_value=Response(200, json={"code": 200, "data": {"tariff_rate": 12}})
    )
    client = CalculatorClient(base_url="https://polaris.test", auth_client=FakeAuthClient())

    payload = client.query_cost({"country_code": "US"})

    assert payload == {"code": 200, "data": {"tariff_rate": 12}}
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert "polarisUserToken=session-id" in request.headers["cookie"]


@respx.mock
def test_client_methods_call_expected_paths():
    paths = {
        "dropdown": ("GET", "/calculator/newProduct/dropdownList"),
        "zones": ("GET", "/calculator/newProduct/zonesWarehouseList"),
        "do_calc": ("POST", "/calculator/newProduct/doCalc"),
        "forecast": ("POST", "/calculator/newProduct/forecastList"),
        "details": ("POST", "/calculator/newProduct/taskDetails"),
        "copy": ("POST", "/calculator/newProduct/copyTask"),
    }
    for _, (method, path) in paths.items():
        getattr(respx, method.lower())("https://polaris.test" + path).mock(return_value=Response(200, json={"code": 200, "data": {}}))

    client = CalculatorClient(base_url="https://polaris.test", auth_client=FakeAuthClient())

    assert client.dropdown_list()["code"] == 200
    assert client.zones_warehouse_list("US")["code"] == 200
    assert client.do_calc({})["code"] == 200
    assert client.forecast_list({})["code"] == 200
    assert client.task_details({"task_code": "T1"})["code"] == 200
    assert client.copy_task({"task_code": "T1"})["code"] == 200


@respx.mock
def test_zones_warehouse_list_sends_country_query_param():
    route = respx.get("https://polaris.test/calculator/newProduct/zonesWarehouseList").mock(return_value=Response(200, json={"code": 200, "data": {}}))
    client = CalculatorClient(base_url="https://polaris.test", auth_client=FakeAuthClient())

    assert client.zones_warehouse_list("US")["code"] == 200

    request = route.calls[0].request
    assert request.url.params["country"] == "US"


@respx.mock
def test_task_details_uses_longer_timeout(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        request = calculator_client.httpx.Request(method, url)
        return Response(200, json={"code": 200, "data": {}}, request=request)

    monkeypatch.setattr(calculator_client.httpx, "request", fake_request)
    client = CalculatorClient(base_url="https://polaris.test", auth_client=FakeAuthClient())

    assert client.task_details({"task_code": "T1"})["code"] == 200
    assert captured == {
        "method": "POST",
        "url": "https://polaris.test/calculator/newProduct/taskDetails",
        "timeout": 30.0,
    }


@respx.mock
def test_client_raises_chinese_error_for_non_200_response():
    respx.post("https://polaris.test/calculator/newProduct/doCalc").mock(return_value=Response(500, json={"message": "server error"}))
    client = CalculatorClient(base_url="https://polaris.test", auth_client=FakeAuthClient())

    try:
        client.do_calc({})
    except RuntimeError as exc:
        assert "Polaris 接口请求失败" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
