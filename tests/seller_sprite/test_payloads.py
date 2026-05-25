import pytest

from opscli.seller_sprite.api.payloads import make_competitor_payload, make_keyword_miner_payload, make_keyword_reverse_payload
from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


def test_competitor_payload_uses_page_size_month_name_and_no_default_filters():
    scenario = get_scenario("competitor-lookup")

    payload = scenario.build_payload(
        params={},
        site="DE",
        period="2026-04",
        page_size=100,
    )

    assert payload["market"] == "DE"
    assert payload["monthName"] == "bsr_sales_monthly_202604"
    assert payload["size"] == 100
    assert payload["nodeIdPaths"] == []
    assert payload["asins"] == []
    assert "brand" not in payload
    assert "sellerName" not in payload


def test_competitor_payload_keeps_optional_filters_when_provided():
    scenario = get_scenario("competitor-lookup")

    payload = scenario.build_payload(
        params={
            "brand": "anker",
            "sellerName": "AnkerDirect",
            "asins": "B00FLYWNYQ",
            "node": "78191031",
        },
        site="DE",
        period="2026-04",
        page_size=100,
    )

    assert payload["brand"] == "anker"
    assert payload["sellerName"] == "AnkerDirect"
    assert payload["asins"] == ["B00FLYWNYQ"]
    assert payload["nodeIdPaths"] == ["78191031"]


def test_keyword_miner_payload_maps_root_word_and_amazon_choice():
    payload = make_keyword_miner_payload(
        {
            "keyword": "flashlight",
            "site": "JP",
            "month": "nearly",
            "pageSize": 100,
            "filterRootWord": 1,
            "amazonChoice": True,
        }
    )

    assert payload["keyword"] == "flashlight"
    assert payload["market"] == 6
    assert payload["historyDate"] == ""
    assert payload["pageSize"] == 100
    assert payload["filterRootWord"] == 1
    assert payload["amazonChoice"] is True


def test_keyword_reverse_payload_keeps_orchestration_fields_for_manager():
    payload = make_keyword_reverse_payload(
        {
            "asin": "B07YRMT36L",
            "site": "JP",
            "month": "2026-03",
            "pageSize": 100,
            "includeHighFrequency": True,
        }
    )

    assert payload["asin"] == "B07YRMT36L"
    assert payload["market"] == "JP"
    assert payload["month"] == "202603"
    assert payload["limit"] == 100
    assert payload["skip"] == 0
    assert payload["includeHighFrequency"] is True


def test_required_params_are_validated_before_request():
    scenario = get_scenario("keyword-reverse")

    with pytest.raises(SellerSpriteConfigError):
        scenario.build_payload(params={}, site="JP", period="nearly", page_size=100)
