"""佰易产品信息业务编排测试。"""

from __future__ import annotations

import pytest

from opscli.baiyi.domain.exceptions import (
    BaiyiProductInfoBadJsonError,
    InvalidBaiyiCompanySkuError,
)
from opscli.baiyi.services.manager import BaiyiProductInfoManager


class FakeClient:
    """记录请求并返回固定响应的假客户端。"""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.payloads: list[dict] = []

    def fetch_product_info(self, payload: dict) -> dict:
        """记录请求体并返回预设响应。"""
        self.payloads.append(payload)
        return self.response


def test_manager_trims_sku_and_preserves_case() -> None:
    """公司 SKU 只去除首尾空白，不改变大小写。"""
    client = FakeClient({"code": 200, "data": {"binding_sku_info": None}})
    manager = BaiyiProductInfoManager(client=client)

    result = manager.fetch("  AuKey-Us-001  ")

    assert client.payloads == [{"company_sku": "AuKey-Us-001"}]
    assert result.request == {"company_sku": "AuKey-Us-001"}


@pytest.mark.parametrize("length", [1, 128])
def test_manager_accepts_company_sku_length_boundaries(length: int) -> None:
    """公司 SKU 长度 1 和 128 都必须允许。"""
    client = FakeClient({"code": 200, "data": {"binding_sku_info": None}})
    manager = BaiyiProductInfoManager(client=client)

    result = manager.fetch("A" * length)

    assert result.success is True
    assert client.payloads == [{"company_sku": "A" * length}]


@pytest.mark.parametrize("value", ["", "   ", "A" * 129])
def test_manager_rejects_invalid_company_sku_without_remote_call(value: str) -> None:
    """空值和超长值必须在本地拒绝，不能调用远端。"""
    client = FakeClient({"code": 200, "data": {"binding_sku_info": None}})
    manager = BaiyiProductInfoManager(client=client)

    with pytest.raises(InvalidBaiyiCompanySkuError):
        manager.fetch(value)

    assert client.payloads == []


@pytest.mark.parametrize(
    ("binding_sku_info", "expected_found"),
    [({"company_sku": "REAL-SKU"}, True), (None, False)],
)
def test_manager_derives_found_and_preserves_unknown_fields(
    binding_sku_info: dict | None,
    expected_found: bool,
) -> None:
    """found 只取决于映射对象，后端未知字段必须透传。"""
    data = {
        "binding_sku_info": binding_sku_info,
        "stcodes": [],
        "future_section": {"new_field": "kept"},
    }
    manager = BaiyiProductInfoManager(
        client=FakeClient({"code": 200, "msg": "操作成功", "data": data})
    )

    result = manager.fetch("INPUT-SKU")

    assert result.found is expected_found
    assert result.data is data
    assert result.data["future_section"] == {"new_field": "kept"}


@pytest.mark.parametrize("data", [None, [], "bad"])
def test_manager_rejects_non_object_data(data) -> None:
    """后端 data 不是对象时必须返回稳定响应结构错误。"""
    manager = BaiyiProductInfoManager(
        client=FakeClient({"code": 200, "data": data})
    )

    with pytest.raises(BaiyiProductInfoBadJsonError) as exc_info:
        manager.fetch("INPUT-SKU")

    assert exc_info.value.code == "BAIYI_PRODUCT_INFO_BAD_JSON"
