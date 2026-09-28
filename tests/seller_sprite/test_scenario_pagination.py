"""卖家精灵普通 JSON 场景分页合同测试。"""

import pytest

from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError
from opscli.seller_sprite.services.scenario_pagination import (
    get_pagination_contract,
)


def test_competitor_contract_uses_page_and_size() -> None:
    """选竞品使用官网的 page/size，并解析 data.items/data.total。"""
    contract = get_pagination_contract("competitor-lookup")
    assert contract.page_payload({"keyword": "loft bed", "page": 1, "size": 60}, page=2, page_size=100) == {
        "keyword": "loft bed",
        "page": 2,
        "size": 100,
    }
    assert contract.parse({"data": {"items": [{"asin": "B1"}], "total": 6928}}) == (
        [{"asin": "B1"}],
        6928,
    )
    assert contract.verified_access_limit == 2000


def test_keyword_miner_contract_uses_page_num_and_page_size() -> None:
    """关键词挖掘使用 pageNum/pageSize，不能继承产品的 2000 上限。"""
    contract = get_pagination_contract("keyword-miner")
    assert contract.page_payload({"keyword": "loft bed"}, page=21, page_size=100) == {
        "keyword": "loft bed",
        "pageNum": 21,
        "pageSize": 100,
    }
    assert contract.verified_access_limit is None


def test_keyword_reverse_translates_page_to_skip() -> None:
    """关键词反查通过 skip 翻页，并移除本地 page 字段。"""
    contract = get_pagination_contract("keyword-reverse")
    assert contract.page_payload({"asin": "B1", "page": 4}, page=4, page_size=50) == {
        "asin": "B1",
        "limit": 50,
        "skip": 150,
    }


def test_association_traffic_contract_uses_pager_dto() -> None:
    """关联流量使用 pageNum/pageSize 和 pagerDto.items/total。"""
    contract = get_pagination_contract("association-traffic")
    assert contract.page_payload({"asinList": ["B1"]}, page=7, page_size=50) == {
        "asinList": ["B1"],
        "pageNum": 7,
        "pageSize": 50,
    }
    assert contract.parse(
        {"data": {"pagerDto": {"items": [{"asin": "B2"}], "total": 375}}}
    ) == ([{"asin": "B2"}], 375)


def test_traffic_source_accepts_pager_total_without_page_validation() -> None:
    """流量来源允许历史响应的非标准 pager 页字段。"""
    contract = get_pagination_contract("traffic-source")
    rows, total = contract.parse(
        {"data": {"pager": {"page": 0, "size": None, "items": [{"keyword": "x"}], "total": 41}}}
    )
    assert rows == [{"keyword": "x"}]
    assert total == 41
    assert contract.response_page_validation is False


def test_unknown_scenario_is_rejected() -> None:
    """未核验场景不能静默套用普通 JSON 合同。"""
    with pytest.raises(SellerSpriteConfigError, match="尚未注册分页合同"):
        get_pagination_contract("market-research")


def test_invalid_rows_are_rejected() -> None:
    """缺少场景 rows 路径时必须失败。"""
    with pytest.raises(SellerSpriteConfigError, match="data.items"):
        get_pagination_contract("keyword-miner").parse({"data": {"items": None}})


@pytest.mark.parametrize(
    ("scenario", "contract"),
    [
        ("competitor-lookup", "competitor-lookup"),
        ("keyword-miner", "keyword-miner"),
        ("keyword-reverse", "keyword-reverse"),
        ("traffic-source", "traffic-source"),
        ("association-traffic", "association-traffic"),
    ],
)
def test_scenario_registry_points_to_independent_contracts(scenario: str, contract: str) -> None:
    """场景注册表明确引用自己的分页合同。"""
    assert get_scenario(scenario).pagination_contract == contract
