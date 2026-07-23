import pytest

from opscli.seller_sprite.api.payloads import (
    build_referer,
    make_competitor_payload,
    make_keyword_miner_payload,
    make_keyword_research_payload,
    make_keyword_reverse_payload,
    make_listing_analysis_payload,
    make_product_research_payload,
)
from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


def test_competitor_payload_requires_primary_filter_before_request():
    scenario = get_scenario("competitor-lookup")

    with pytest.raises(SellerSpriteConfigError, match="至少需要一个主筛选条件"):
        scenario.build_payload(
            params={},
            site="DE",
            period="2026-04",
            page_size=100,
        )


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


def test_competitor_payload_maps_singular_asin_to_asins_list():
    payload = make_competitor_payload(
        {
            "site": "US",
            "period": "2026-04",
            "asin": "B00FLYWNYQ",
        }
    )

    assert payload["asins"] == ["B00FLYWNYQ"]


def test_competitor_payload_accepts_singular_node_id_path():
    payload = make_competitor_payload(
        {
            "site": "US",
            "period": "2026-04",
            "nodeIdPath": "3375251:3386071:375519011:375540011",
        }
    )

    assert payload["nodeIdPaths"] == ["3375251:3386071:375519011:375540011"]


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


def test_keyword_research_payload_maps_public_filters_to_web_query():
    scenario = get_scenario("keyword-research")

    payload = scenario.build_payload(
        params={
            "departments": ["kitchen", "tools"],
            "keywords": "bed frame",
            "minSearchesCr": 20,
            "maxSearchesCr": 30,
            "minWordCount": 1,
            "maxWordCount": 9,
            "minRating": 0,
            "maxRating": 5,
            "marketPeriod": "S4,S5,S6",
            "orderDesc": False,
        },
        site="US",
        period="2026-06",
        page_size=100,
    )

    assert scenario.endpoint == "/v2/keyword-research"
    assert scenario.method == "GET_PAGE"
    assert payload["station"] == "US"
    assert payload["month"] == "202606"
    assert payload["page"] == "1"
    assert payload["size"] == "50"
    assert payload["departments[0]"] == "kitchen"
    assert payload["departments[1]"] == "tools"
    assert payload["includeKeywords"] == "bed frame"
    assert payload["minGrowth"] == "20"
    assert payload["maxGrowth"] == "30"
    assert payload["minAvgRating"] == "0"
    assert payload["maxAvgRating"] == "5"
    assert payload["marketPeriod"] == "S4,S5,S6"
    assert payload["order.desc"] == "false"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"minWordCount": 0}, "minWordCount"),
        ({"minWordCount": 6}, "minWordCount"),
        ({"maxWordCount": 10}, "maxWordCount"),
        ({"minRating": -0.1}, "minRating"),
        ({"maxRating": 5.1}, "maxRating"),
        ({"minSearches": 20, "maxSearches": 10}, "minSearches"),
        ({"marketPeriod": "S13"}, "marketPeriod"),
    ],
)
def test_keyword_research_payload_rejects_invalid_ranges(params, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_keyword_research_payload({"site": "US", "period": "2026-06", **params})


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
    assert "includeHighFrequency" not in payload


def test_listing_analysis_payload_defaults_to_global_station():
    scenario = get_scenario("listing-analysis")

    payload = scenario.build_payload(
        params={"asin": "b0d3845mwd"},
        site="US",
        period="30d",
        page_size=100,
    )

    assert payload == {"asin": "B0D3845MWD", "station": "GLOBAL"}
    assert scenario.endpoint == "/v3/api/ai-analysis/get-submitted"
    assert scenario.method == "PAGE_CAPTURE"
    assert scenario.task_result_endpoint is None
    assert build_referer(payload, "listing-analysis") == "https://www.sellersprite.com/v3/ai-history?module=LA"
    assert make_listing_analysis_payload({"asin": "b0d3845mwd", "station": "us"}) == {
        "asin": "B0D3845MWD",
        "station": "US",
    }


def test_product_research_accepts_recommendation_mode():
    payload = make_product_research_payload(
        {
            "site": "US",
            "period": "30d",
            "recommendationMode": "低价商品",
        }
    )

    assert payload["market"] == "US"
    assert payload["monthName"] == "bsr_sales_nearly"
    assert payload["eligibility"] == ["Y"]
    assert payload["maxPrice"] == "10"
    assert payload["smallAndLight"] == "lowPrice"
    assert payload["lowPrice"] == "Y"


def test_product_research_accepts_singular_node_id_path():
    payload = make_product_research_payload(
        {
            "site": "US",
            "period": "2026-04",
            "nodeIdPath": "165793011:166508011:3244725011",
            "minPrice": 100,
            "maxPrice": 500,
        }
    )

    assert payload["nodeIdPaths"] == ["165793011:166508011:3244725011"]
    assert payload["minPrice"] == "100"
    assert payload["maxPrice"] == "500"


def test_product_research_accepts_official_field_aliases():
    payload = make_product_research_payload(
        {
            "site": "US",
            "period": "30d",
            "minUnits": 300,
            "maxRatings": 50,
            "availableMonth": 6,
            "fulfillment": ["FBA"],
            "badgeNR": True,
            "variation": 1,
        }
    )

    assert payload["minSales"] == "300"
    assert payload["maxReviews"] == "50"
    assert payload["putawayMonth"] == 6
    assert payload["sellerTypes"] == ["FBA"]
    assert payload["productTags"] == ["NewRelease"]
    assert payload["maxVariations"] == "1"


def test_required_params_are_validated_before_request():
    scenario = get_scenario("keyword-reverse")

    with pytest.raises(SellerSpriteConfigError):
        scenario.build_payload(params={}, site="JP", period="nearly", page_size=100)
