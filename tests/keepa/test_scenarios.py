import json

import pytest

from opscli.keepa.api.scenarios import (
    get_scenario,
    normalize_domain,
    telemetry_dimensions,
)
from opscli.keepa.domain.exceptions import KeepaConfigError


def test_normalize_domain_accepts_common_sites():
    assert normalize_domain("US") == "1"
    assert normalize_domain("uk") == "2"
    assert normalize_domain("JP") == "5"
    assert normalize_domain("11") == "11"


def test_product_params_validate_item_limits_with_offers():
    scenario = get_scenario("product")
    params = scenario.build_params(params={"asins": ["B000000001", "B000000002"], "offers": 20}, site="US")

    assert params["domain"] == "1"
    assert params["asin"] == "B000000001,B000000002"
    assert params["history"] is True
    assert params["offers"] == 20


def test_product_params_default_history_can_be_disabled():
    scenario = get_scenario("product")
    params = scenario.build_params(params={"asin": "B000000001", "history": False}, site="US")

    assert params["history"] is False


def test_product_params_allows_up_to_one_hundred_items_with_offers():
    scenario = get_scenario("product")
    params = scenario.build_params(
        params={"asins": [f"B{i:09d}" for i in range(100)], "offers": 20},
        site="US",
    )

    assert len(params["asin"].split(",")) == 100


def test_product_params_supports_new_documented_options():
    scenario = get_scenario("product")
    params = scenario.build_params(
        params={
            "codes": ["0123456789012"],
            "code_limit": 5,
            "historical_variations": True,
        },
        site="US",
    )

    assert params["code"] == "0123456789012"
    assert params["code-limit"] == 5
    assert params["historical-variations"] is True


def test_product_params_normalizes_string_flags_and_numbers():
    scenario = get_scenario("product")
    params = scenario.build_params(
        params={
            "asin": " B000000001 ",
            "history": "false",
            "offers": "20",
            "update": "0",
            "only_live_offers": "1",
            "code_limit": "5",
        },
        site="US",
    )

    assert params["asin"] == "B000000001"
    assert params["history"] is False
    assert params["offers"] == 20
    assert params["update"] == 0
    assert params["only-live-offers"] is True
    assert params["code-limit"] == 5


@pytest.mark.parametrize("offers", [1, 19, 101])
def test_product_params_rejects_offers_outside_official_range(offers):
    with pytest.raises(KeepaConfigError, match="offers.*20.*100"):
        get_scenario("product").build_params(
            params={"asin": "B000000001", "offers": offers}, site="US"
        )


def test_deals_requires_exactly_one_supported_price_type():
    scenario = get_scenario("deals")

    with pytest.raises(KeepaConfigError, match="priceTypes"):
        scenario.build_params(params={"selection": {"page": 0}}, site="US")
    with pytest.raises(KeepaConfigError, match="只能包含 1 个"):
        scenario.build_params(
            params={"selection": {"priceTypes": [0, 18]}}, site="US"
        )
    with pytest.raises(KeepaConfigError, match="不支持"):
        scenario.build_params(
            params={"selection": {"priceTypes": [99]}}, site="US"
        )

    params = scenario.build_params(
        params={"selection": {"priceTypes": [18], "page": 0}}, site="US"
    )
    assert json.loads(params["selection"])["priceTypes"] == [18]


def test_product_params_rejects_more_than_one_hundred_items():
    scenario = get_scenario("product")

    with pytest.raises(KeepaConfigError, match="最多 100"):
        scenario.build_params(
            params={"asins": [f"B{i:09d}" for i in range(101)], "offers": 20},
            site="US",
        )


def test_aliases_must_not_disagree():
    with pytest.raises(KeepaConfigError, match="asin/asins"):
        get_scenario("product").build_params(
            params={"asin": "A", "asins": "B"}, site="US"
        )
    with pytest.raises(KeepaConfigError, match="term/keyword"):
        get_scenario("product-search").build_params(
            params={"term": "flashlight", "keyword": "camera"}, site="US"
        )


def test_product_token_estimate_includes_known_add_on_costs():
    scenario = get_scenario("product")

    assert scenario.estimate_tokens({"asins": ["A", "B"]}) == 2
    assert scenario.estimate_tokens({"asins": ["A", "B"], "offers": 20}) >= 12
    assert scenario.estimate_tokens({"asin": "A", "buybox": True, "stock": True, "rating": True}) > 1


def test_product_finder_selection_is_json_encoded():
    scenario = get_scenario("product-finder")
    params = scenario.build_params(
        params={"selection": {"current_SALES_gte": 1, "perPage": 50}},
        site="DE",
    )

    assert params["domain"] == "3"
    assert params["selection"] == '{"current_SALES_gte":1,"perPage":50}'
    assert scenario.estimate_tokens({"selection": {"perPage": 250}}) == 13
    assert scenario.estimate_tokens({"selection": {"current_SALES_gte": 1}}) == 11


def test_selection_accepts_json_string_and_rejects_invalid_json():
    scenario = get_scenario("product-finder")
    params = scenario.build_params(
        params={"selection": '{"perPage":"250"}', "stats": "1"}, site="US"
    )

    assert json.loads(params["selection"]) == {"perPage": "250"}
    assert params["stats"] is True
    assert scenario.estimate_tokens({"selection": '{"perPage":250}'}) == 13

    with pytest.raises(KeepaConfigError, match="selection.*JSON"):
        scenario.build_params(params={"selection": "[]"}, site="US")


def test_product_search_supports_rating_but_not_obsolete_page():
    scenario = get_scenario("product-search")
    params = scenario.build_params(
        params={"term": "flashlight", "rating": True, "page": 3},
        site="US",
    )

    assert params["rating"] is True
    assert "page" not in params
    assert scenario.estimate_tokens({"term": "flashlight"}) == 10


def test_search_and_lookup_accept_documented_aliases():
    product_search = get_scenario("product-search").build_params(params={"keyword": "flashlight"}, site="US")
    category_lookup = get_scenario("category-lookup").build_params(params={"categories": [123, 456]}, site="US")
    seller = get_scenario("seller").build_params(params={"sellers": ["A2L77EE7U53NWQ"]}, site="US")
    bestsellers = get_scenario("bestsellers").build_params(params={"productGroup": "Home"}, site="US")

    assert product_search["term"] == "flashlight"
    assert category_lookup["category"] == "123,456"
    assert seller["seller"] == "A2L77EE7U53NWQ"
    assert seller["storefront"] is False
    assert bestsellers["category"] == "Home"


def test_telemetry_dimensions_resolve_keepa_endpoint_from_scenario():
    assert telemetry_dimensions({"scenario": "product-search"}) == {"endpoint": "search"}
    assert telemetry_dimensions({"scenario": "deals"}) == {"endpoint": "deal"}
    assert telemetry_dimensions({"scenario": "unknown"}) == {}

def test_numeric_and_boolean_boundaries_are_validated():
    with pytest.raises(KeepaConfigError, match="offers.*整数"):
        get_scenario("product").build_params(
            params={"asin": "A", "offers": "many"}, site="US"
        )
    with pytest.raises(KeepaConfigError, match="parents.*布尔"):
        get_scenario("category-lookup").build_params(
            params={"category": "123", "parents": "sometimes"}, site="US"
        )
    with pytest.raises(KeepaConfigError, match="state 不能为空"):
        get_scenario("lightning-deals").build_params(
            params={"state": "  "}, site="US"
        )


def test_category_scenarios_use_parents_only_for_lookup():
    lookup = get_scenario("category-lookup").build_params(
        params={"category": 123}, site="US"
    )
    search = get_scenario("category-search").build_params(
        params={"term": "electronics", "parents": True}, site="US"
    )

    assert lookup["parents"] is False
    assert "parents" not in search


def test_seller_storefront_is_single_seller_only_and_costs_extra_tokens():
    scenario = get_scenario("seller")

    with pytest.raises(KeepaConfigError, match="storefront.*单个"):
        scenario.build_params(
            params={"sellers": ["SELLER1", "SELLER2"], "storefront": True},
            site="US",
        )

    assert scenario.estimate_tokens({"seller": "SELLER1"}) == 1
    assert scenario.estimate_tokens({"seller": "SELLER1", "storefront": True}) == 10


def test_seller_finder_encodes_selection_and_estimates_page_size():
    scenario = get_scenario("seller-finder")
    params = scenario.build_params(
        params={"selection": {"perPage": 250, "sort": [["ratingCount_lifetime", "desc"]]}},
        site="DE",
    )

    assert params["domain"] == "3"
    assert json.loads(params["selection"])["perPage"] == 250
    assert scenario.estimate_tokens({"selection": {"perPage": 250}}) == 13


def test_bestsellers_supports_optional_filters_and_validates_date_pair():
    scenario = get_scenario("bestsellers")
    params = scenario.build_params(
        params={
            "category": "172282",
            "month": 7,
            "year": 2025,
            "variations": True,
        },
        site="US",
    )

    assert params["month"] == 7
    assert params["year"] == 2025
    assert params["variations"] is True
    assert scenario.estimate_tokens({"category": "172282"}) == 50

    current = scenario.build_params(
        params={"category": "172282", "range": 90, "variations": True},
        site="US",
    )
    assert current["range"] == 90

    normalized = scenario.build_params(
        params={"category": "172282", "range": "30", "variations": "0"}, site="US"
    )
    assert normalized["range"] == 30
    assert normalized["variations"] is False

    with pytest.raises(KeepaConfigError, match="month.*year"):
        scenario.build_params(params={"category": "172282", "month": 7}, site="US")


def test_fixed_cost_and_lightning_deal_token_estimates():
    assert get_scenario("deals").estimate_tokens({}) == 5
    assert get_scenario("top-seller").estimate_tokens({}) == 50
    lightning = get_scenario("lightning-deals")
    params = lightning.build_params(params={"state": "ACTIVE"}, site="US")
    assert params["state"] == "ACTIVE"
    assert lightning.estimate_tokens({"asin": "B000000001"}) == 1
    assert lightning.estimate_tokens({}) == 500
