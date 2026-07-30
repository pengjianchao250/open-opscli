"""佰易产品信息 HTTP 客户端测试。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from opscli.baiyi.domain.exceptions import (
    BaiyiProductInfoBadJsonError,
    BaiyiProductInfoBusinessError,
    BaiyiProductInfoHttpError,
    BaiyiProductInfoNetworkError,
)
from opscli.baiyi.transport.client import BaiyiProductInfoClient


PRODUCT_INFO_URL = "http://ops.example.com/dataMetrics/v1/binding-sku-product-info"


class FakeAuthClient:
    """提供固定 OPS 认证信息，避免读取真实凭证。"""

    def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        """返回测试 Header 与 Cookie。"""
        assert alias == "ops"
        return (
            {"Authorization": "Bearer fake-jwt", "X-Opscli-Version": "test"},
            {"polarisUserToken": "fake-session"},
        )


@pytest.fixture
def client(monkeypatch) -> BaiyiProductInfoClient:
    """构造指向测试地址的客户端。"""
    monkeypatch.setattr(
        "opscli.baiyi.transport.client.load_config",
        lambda: {"ops_system_url": "http://ops.example.com/"},
    )
    return BaiyiProductInfoClient(auth_client=FakeAuthClient())


@respx.mock
def test_client_sends_expected_request_contract(client: BaiyiProductInfoClient) -> None:
    """客户端必须使用固定 URL、请求体、认证和 10 秒超时。"""
    route = respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"code": 200, "msg": "操作成功", "data": {"binding_sku_info": None}},
        )
    )

    response = client.fetch_product_info({"company_sku": "AUKEY-US-EU-001"})

    assert response["code"] == 200
    request = route.calls.last.request
    assert json.loads(request.content) == {"company_sku": "AUKEY-US-EU-001"}
    assert request.headers["Authorization"] == "Bearer fake-jwt"
    assert request.headers["X-Opscli-Version"] == "test"
    assert "polarisUserToken=fake-session" in request.headers["Cookie"]
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


@pytest.mark.parametrize("status_code", [407, 422, 500])
@respx.mock
def test_client_maps_http_errors(
    client: BaiyiProductInfoClient,
    status_code: int,
) -> None:
    """HTTP 错误必须保留状态码。"""
    respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(
            status_code,
            json={"code": status_code, "msg": "远端失败"},
        )
    )

    with pytest.raises(BaiyiProductInfoHttpError) as exc_info:
        client.fetch_product_info({"company_sku": "SKU"})

    assert exc_info.value.status_code == status_code


@pytest.mark.parametrize("business_code", [407, 422, 500])
@respx.mock
def test_client_maps_business_errors(
    client: BaiyiProductInfoClient,
    business_code: int,
) -> None:
    """HTTP 成功但业务失败时必须保留业务码。"""
    respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"code": business_code, "msg": "业务失败"},
        )
    )

    with pytest.raises(BaiyiProductInfoBusinessError) as exc_info:
        client.fetch_product_info({"company_sku": "SKU"})

    assert exc_info.value.business_code == business_code


@respx.mock
def test_client_rejects_invalid_json(client: BaiyiProductInfoClient) -> None:
    """非 JSON 响应必须映射为稳定错误。"""
    respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(200, content=b"not-json")
    )

    with pytest.raises(BaiyiProductInfoBadJsonError):
        client.fetch_product_info({"company_sku": "SKU"})


@respx.mock
def test_client_keeps_http_status_for_non_json_error(
    client: BaiyiProductInfoClient,
) -> None:
    """非 JSON 的 HTTP 错误必须保留状态码，不能误报 JSON 结构错误。"""
    respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(
            404,
            text="<html>Not Found</html>",
            headers={"Content-Type": "text/html"},
        )
    )

    with pytest.raises(BaiyiProductInfoHttpError) as exc_info:
        client.fetch_product_info({"company_sku": "SKU"})

    assert exc_info.value.status_code == 404


@respx.mock
def test_client_rejects_non_object_json(client: BaiyiProductInfoClient) -> None:
    """合法 JSON 若不是对象，也必须映射为稳定结构错误。"""
    respx.post(PRODUCT_INFO_URL).mock(
        return_value=httpx.Response(200, json=[])
    )

    with pytest.raises(BaiyiProductInfoBadJsonError):
        client.fetch_product_info({"company_sku": "SKU"})


@pytest.mark.parametrize(
    "remote_error",
    [httpx.ReadTimeout("read timeout"), httpx.ConnectError("connect failed")],
)
@respx.mock
def test_client_maps_network_errors(
    client: BaiyiProductInfoClient,
    remote_error: httpx.RequestError,
) -> None:
    """超时和连接失败必须映射为不含凭证的模块错误。"""
    respx.post(PRODUCT_INFO_URL).mock(side_effect=remote_error)

    with pytest.raises(BaiyiProductInfoNetworkError) as exc_info:
        client.fetch_product_info({"company_sku": "SKU"})

    error = exc_info.value.to_dict()
    assert error["code"] == "BAIYI_PRODUCT_INFO_NETWORK_ERROR"
    assert "fake-jwt" not in error["message"]
    assert "fake-session" not in error["message"]
