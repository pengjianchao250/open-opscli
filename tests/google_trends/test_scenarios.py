from opscli.google_trends.api.scenarios import get_scenario
from opscli.google_trends.api.scenarios import list_scenarios
from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError


def test_interest_over_time_normalizes_keywords_and_gprop():
    scenario = get_scenario("interest-over-time")

    params = scenario.build_params(
        params={"keywords": ["flashlight", "lantern"], "timeframe": "today 12-m", "gprop": "shopping"},
        geo="US",
    )

    assert params["kw_list"] == ["flashlight", "lantern"]
    assert params["timeframe"] == "today 12-m"
    assert params["geo"] == "US"
    assert params["gprop"] == "froogle"


def test_interest_payload_allows_global_geo():
    scenario = get_scenario("interest-over-time")

    params = scenario.build_params(params={"keyword": "flashlight", "geo": ""}, geo="US")

    assert params["geo"] == ""


def test_interest_payload_rejects_more_than_five_keywords():
    scenario = get_scenario("interest-over-time")

    try:
        scenario.build_params(params={"kw_list": [f"kw-{index}" for index in range(6)]}, geo="US")
    except GoogleTrendsConfigError as exc:
        assert "最多支持 5" in str(exc)
    else:
        raise AssertionError("expected GoogleTrendsConfigError")


def test_interest_by_region_normalizes_bool_options():
    scenario = get_scenario("interest-by-region")

    params = scenario.build_params(
        params={"keyword": "flashlight", "resolution": "region", "inc_low_vol": "false", "inc_geo_code": "1"},
        geo="US",
    )

    assert params["resolution"] == "REGION"
    assert params["inc_low_vol"] is False
    assert params["inc_geo_code"] is True


def test_trending_searches_maps_country_code_to_pytrends_pn():
    scenario = get_scenario("trending-searches")

    params = scenario.build_params(params={"pn": "US"}, geo="US")

    assert params["pn"] == "united_states"


def test_trending_scenarios_are_marked_unavailable():
    scenarios = {item["scenario_id"]: item for item in list_scenarios()}

    assert scenarios["trending-searches"]["availability"] == "unavailable"
    assert "404" in scenarios["trending-searches"]["notes"]
    assert scenarios["realtime-trending"]["availability"] == "unavailable"
    assert "404" in scenarios["realtime-trending"]["notes"]
    assert scenarios["related-topics"]["availability"] == "unavailable"
    assert "list index out of range" in scenarios["related-topics"]["notes"]


def test_realtime_trending_maps_country_name_to_code():
    scenario = get_scenario("realtime-trending")

    params = scenario.build_params(params={"pn": "united_states"}, geo="US")

    assert params["pn"] == "US"


def test_suggestions_accepts_single_keyword_only():
    scenario = get_scenario("suggestions")

    params = scenario.build_params(params={"keyword": "flashlight"}, geo="US")
    assert params == {"keyword": "flashlight"}

    try:
        scenario.build_params(params={"keywords": ["flashlight", "lantern"]}, geo="US")
    except GoogleTrendsConfigError as exc:
        assert "最多支持 1" in str(exc)
    else:
        raise AssertionError("expected GoogleTrendsConfigError")
