from opscli.keepa.api.scenarios import get_scenario, normalize_domain
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
    assert params["offers"] == 20


def test_product_params_rejects_too_many_items_with_offers():
    scenario = get_scenario("product")

    try:
        scenario.build_params(params={"asins": [f"B{i:09d}" for i in range(21)], "offers": 20}, site="US")
    except KeepaConfigError as exc:
        assert "最多 20" in str(exc)
    else:
        raise AssertionError("expected KeepaConfigError")


def test_product_finder_selection_is_json_encoded():
    scenario = get_scenario("product-finder")
    params = scenario.build_params(
        params={"selection": {"current_SALES_gte": 1, "perPage": 50}},
        site="DE",
    )

    assert params["domain"] == "3"
    assert params["selection"] == '{"current_SALES_gte":1,"perPage":50}'


def test_search_and_lookup_accept_documented_aliases():
    product_search = get_scenario("product-search").build_params(params={"keyword": "flashlight"}, site="US")
    category_lookup = get_scenario("category-lookup").build_params(params={"categories": [123, 456]}, site="US")
    seller = get_scenario("seller").build_params(params={"sellers": ["A2L77EE7U53NWQ"]}, site="US")
    bestsellers = get_scenario("bestsellers").build_params(params={"productGroup": "Home"}, site="US")

    assert product_search["term"] == "flashlight"
    assert category_lookup["category"] == "123,456"
    assert seller["seller"] == "A2L77EE7U53NWQ"
    assert bestsellers["category"] == "Home"
