import pytest

from opscli.scrape_do.api.scenarios import get_scenario, list_scenarios
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError


def test_list_scenarios_contains_three_structured_amazon_endpoints():
    scenarios = list_scenarios()
    ids = {item["scenario_id"] for item in scenarios}

    assert ids == {"amazon-pdp", "amazon-offer-listing", "amazon-search"}
    assert all("raw-html" not in item["scenario_id"] for item in scenarios)


def test_amazon_pdp_builds_params_without_html():
    scenario = get_scenario("amazon-pdp")

    params = scenario.build_params(
        params={"asin": "B0C7BKZ883", "zipcode": "90210", "language": "EN"},
        site="US",
        token="secret-token",
    )

    assert params == {
        "token": "secret-token",
        "asin": "B0C7BKZ883",
        "geocode": "US",
        "zipcode": "90210",
        "language": "EN",
    }
    assert "include_html" not in params


def test_amazon_offer_listing_rejects_zipcode_and_country_name_together():
    scenario = get_scenario("amazon-offer-listing")

    with pytest.raises(ScrapeDoConfigError, match="zipcode 和 countryName 不能同时传"):
        scenario.build_params(
            params={"asin": "B0DGJ7HYG1", "zipcode": "90210", "countryName": "United States"},
            site="US",
            token="secret-token",
        )


def test_amazon_search_requires_keyword_and_defaults_page():
    scenario = get_scenario("amazon-search")

    params = scenario.build_params(
        params={"keyword": "laptop stands", "device": "mobile", "super": True},
        site="us",
        token="secret-token",
    )

    assert params == {
        "token": "secret-token",
        "keyword": "laptop stands",
        "geocode": "US",
        "page": 1,
        "device": "mobile",
        "super": "true",
    }


def test_amazon_search_rejects_empty_keyword():
    scenario = get_scenario("amazon-search")

    with pytest.raises(ScrapeDoConfigError, match="缺少参数：keyword"):
        scenario.build_params(params={}, site="US", token="secret-token")
