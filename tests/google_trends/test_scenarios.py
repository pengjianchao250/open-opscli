"""SerpApi Google Trends 场景参数测试。"""

import pytest

from opscli.google_trends.api.scenarios import get_scenario, list_scenarios
from opscli.google_trends.domain.exceptions import GoogleTrendsConfigError


def test_only_three_serpapi_scenarios_are_enabled():
    """场景列表只应公开三个 SerpApi 原始接口。"""
    scenarios = {item["scenario_id"]: item for item in list_scenarios()}

    assert set(scenarios) == {"trends", "autocomplete", "trending-now"}
    assert scenarios["trends"]["method"] == "google_trends"
    assert scenarios["autocomplete"]["method"] == "google_trends_autocomplete"
    assert scenarios["trending-now"]["method"] == "google_trends_trending_now"


def test_trends_normalizes_query_and_supported_params():
    """Trends 场景应映射原始 SerpApi 参数并规范化多关键词。"""
    params = get_scenario("trends").build_params(
        params={
            "q": ["flashlight", "lantern"],
            "data_type": "timeseries",
            "date": "today 12-m",
            "gprop": "froogle",
            "no_cache": True,
        },
        geo="US",
    )

    assert params == {
        "q": "flashlight,lantern",
        "data_type": "TIMESERIES",
        "date": "today 12-m",
        "gprop": "froogle",
        "no_cache": "true",
        "geo": "US",
    }


def test_trends_enforces_data_type_keyword_limits():
    """地域和相关数据类型应执行 SerpApi 的关键词数量约束。"""
    with pytest.raises(GoogleTrendsConfigError, match="GEO_MAP 需要 2 到 5"):
        get_scenario("trends").build_params(
            params={"q": "flashlight", "data_type": "GEO_MAP"},
            geo="US",
        )

    with pytest.raises(GoogleTrendsConfigError, match="仅支持 1 个关键词"):
        get_scenario("trends").build_params(
            params={"q": ["flashlight", "lantern"], "data_type": "RELATED_QUERIES"},
            geo="US",
        )


def test_trends_rejects_client_control_and_secret_params():
    """调用方不能覆盖 engine、API Key、输出模式或异步模式。"""
    for field in ("engine", "api_key", "output", "async"):
        with pytest.raises(GoogleTrendsConfigError, match=field):
            get_scenario("trends").build_params(
                params={"q": "flashlight", field: "forbidden"},
                geo="US",
            )


def test_autocomplete_requires_query():
    """Autocomplete 必须提供查询文本。"""
    with pytest.raises(GoogleTrendsConfigError, match="q"):
        get_scenario("autocomplete").build_params(params={}, geo="US")

    params = get_scenario("autocomplete").build_params(
        params={"q": "Apple", "hl": "en", "no_cache": False},
        geo="US",
    )
    assert params == {"q": "Apple", "hl": "en", "no_cache": "false"}


def test_trending_now_uses_outer_geo_and_validates_hours():
    """Trending Now 应使用外层地区并限制官方时间档位。"""
    params = get_scenario("trending-now").build_params(
        params={"hours": 24, "only_active": True, "category_id": 18},
        geo="JP",
    )
    assert params == {
        "geo": "JP",
        "hours": "24",
        "only_active": "true",
        "category_id": "18",
    }

    with pytest.raises(GoogleTrendsConfigError, match="hours"):
        get_scenario("trending-now").build_params(params={"hours": 12}, geo="US")


def test_legacy_scenario_is_disabled():
    """旧 pytrends 场景不应继续执行。"""
    with pytest.raises(GoogleTrendsConfigError, match="未知 Google Trends 场景"):
        get_scenario("interest-over-time")
