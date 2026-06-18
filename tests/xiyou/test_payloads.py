from datetime import date

import pytest

import opscli.xiyou.api.payloads as payloads_module
from opscli.xiyou.api.payloads import SUPPORTED_SITES, normalize_site
from opscli.xiyou.api.scenarios import get_resource_scenario, get_scenario
from opscli.xiyou.domain.exceptions import XiyouConfigError


def test_asin_ranking_payload_defaults_to_flow():
    scenario = get_scenario("asin")

    payload = scenario.build_payload(
        site="us",
        period="week",
        rank_pattern=None,
        query="",
        page=1,
        page_size=50,
    )

    assert payload == {
        "biz": {
            "country": "US",
            "filed": "week",
            "page": 1,
            "pageSize": 50,
            "query": "",
            "rankPattern": "flow",
        }
    }


def test_keyword_ranking_payload_uses_aba():
    scenario = get_scenario("keyword")

    payload = scenario.build_payload(
        site="DE",
        period="week",
        rank_pattern="aba",
        query="desk",
        page=2,
        page_size=20,
    )

    assert payload["biz"]["country"] == "DE"
    assert payload["biz"]["filed"] == "week"
    assert payload["biz"]["page"] == 2
    assert payload["biz"]["pageSize"] == 20
    assert payload["biz"]["query"] == "desk"
    assert payload["biz"]["rankPattern"] == "aba"


def test_keyword_ranking_period_rejects_month():
    scenario = get_scenario("keyword")

    with pytest.raises(XiyouConfigError):
        scenario.normalize_period("month")


def test_asin_ranking_period_allows_month():
    scenario = get_scenario("asin")

    assert scenario.normalize_period("month") == "month"


def test_invalid_rank_pattern_is_rejected():
    scenario = get_scenario("asin")

    with pytest.raises(XiyouConfigError):
        scenario.build_payload(
            site="US",
            period="week",
            rank_pattern="aba",
            query="",
            page=1,
            page_size=50,
        )


def test_unknown_target_is_rejected():
    with pytest.raises(XiyouConfigError):
        get_scenario("category")


def test_reverse_keyword_payload():
    scenario = get_resource_scenario("reverse-keyword")

    payload = scenario.build_payload(
        site="us",
        asin="b0g33fz8xs",
        asins=None,
        keyword=None,
        query="stand",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=2,
        page_size=25,
    )

    assert payload["resource"] == {"country": "US", "asin": "B0G33FZ8XS"}
    assert payload["biz"]["asin"] == "B0G33FZ8XS"
    assert payload["biz"]["query"] == "stand"
    assert payload["biz"]["page"] == 2
    assert payload["biz"]["pageSize"] == 25
    assert payload["biz"]["orders"] == [{"field": "follow", "order": "desc"}]
    assert payload["biz"]["filters"] == [{"field": "asinResearchType", "filter": ["all"]}]
    assert payload["biz"]["cycleFilter"] == {
        "cycle": "daily",
        "period": "last7days",
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }
    assert payload["biz"]["tableType"] == "asinResearchTotalList"


def test_reverse_keyword_supports_trends_view_and_organic_keywords(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("reverse-keyword")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        cycle_period="last3months",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=20,
        view_mode="trends",
        keyword_type="organic",
    )

    assert payload["biz"]["orders"] == [{"field": "organicTraffic", "order": "desc"}]
    assert payload["biz"]["filters"] == [{"field": "asinResearchType", "filter": ["organic"]}]
    assert payload["biz"]["tableType"] == "asinResearchTrendsViewOrganicSearchTerm"
    assert payload["biz"]["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-03-01", "endDate": "2026-03-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_reverse_keyword_data_view_uses_organic_table_for_organic_keywords():
    scenario = get_resource_scenario("reverse-keyword")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="home decor",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="data",
        keyword_type="organic",
    )

    assert payload["biz"]["orders"] == [{"field": "organicTraffic", "order": "desc"}]
    assert payload["biz"]["filters"] == [{"field": "asinResearchType", "filter": ["organic"]}]
    assert payload["biz"]["tableType"] == "asinResearchOrganicList"


def test_reverse_keyword_data_view_uses_advertising_table_for_ad_keywords():
    scenario = get_resource_scenario("reverse-keyword")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="home decor",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="data",
        keyword_type="advertising",
    )

    assert payload["biz"]["orders"] == [{"field": "adTraffic", "order": "desc"}]
    assert payload["biz"]["filters"] == [{"field": "asinResearchType", "filter": ["advertising"]}]
    assert payload["biz"]["tableType"] == "asinResearchAdvertisingList"


def test_reverse_keyword_supports_top10_and_custom_month_range():
    scenario = get_resource_scenario("reverse-keyword")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        cycle_period="custom_month_range",
        start_month="2026-05",
        end_month="2026-06",
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="自然TOP10",
        keyword_type="广告关键词",
    )

    assert payload["biz"]["orders"] == [{"field": "adTraffic", "order": "desc"}]
    assert payload["biz"]["filters"] == [{"field": "asinResearchType", "filter": ["advertising"]}]
    assert payload["biz"]["tableType"] == "asinResearchOrganicTop10"
    assert payload["biz"]["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-05-01", "endDate": "2026-05-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_asin_compare_payload_requires_two_asins():
    scenario = get_resource_scenario("asin-compare")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins="B0G33FZ8XS, B0G337Q47M, B0G33FZ8XS",
        keyword=None,
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["resource"]["asins"] == ["B0G33FZ8XS", "B0G337Q47M"]
    assert payload["tableType"] == "multiAsinsComparisonList"

    with pytest.raises(XiyouConfigError):
        scenario.build_payload(
            site="US",
            asin=None,
            asins="B0G33FZ8XS",
            keyword=None,
            query="",
            cycle_period=None,
            start_month=None,
            end_month=None,
            start_date=None,
            end_date=None,
            report_date=None,
            page=1,
            page_size=50,
        )


def test_asin_compare_ignores_view_mode_for_monthly_organic_download(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("asin-compare")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=["B08X4615SC", "B07BJN11KV"],
        keyword=None,
        query="",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="top10",
        keyword_type="organic",
    )

    assert payload["filters"] == [{"field": "asinResearchType", "filter": ["organic"]}]
    assert payload["tableType"] == "multiAsinsComparisonList"
    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-05-01", "endDate": "2026-05-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_asin_compare_supports_custom_month_range_and_advertising_keywords():
    scenario = get_resource_scenario("asin-compare")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=["B08X4615SC", "B07BJN11KV"],
        keyword=None,
        query="",
        cycle_period="custom_month_range",
        start_month="2026-05",
        end_month="2026-06",
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="自然TOP10",
        keyword_type="广告关键词",
    )

    assert payload["filters"] == [{"field": "asinResearchType", "filter": ["advertising"]}]
    assert payload["tableType"] == "multiAsinsComparisonList"
    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-05-01", "endDate": "2026-05-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_asin_compare_ignores_invalid_view_mode_for_download_shape():
    scenario = get_resource_scenario("asin-compare")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=["B08X4615SC", "B07BJN11KV"],
        keyword=None,
        query="tupperware",
        cycle_period="last7days",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
        view_mode="preview-only-style",
        keyword_type="all",
    )

    assert payload["tableType"] == "multiAsinsComparisonList"
    assert payload["filters"] == [{"field": "asinResearchType", "filter": ["all"]}]


def test_keyword_analysis_payload():
    scenario = get_resource_scenario("keyword-analysis")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="tv stands for living room",
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["resource"] == {"country": "US", "searchTerm": "tv stands for living room"}
    assert payload["searchTerm"] == "tv stands for living room"
    assert payload["orders"] == [{"field": "traffic", "order": "desc"}]


def test_keyword_analysis_supports_last3months(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("keyword-analysis")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period="last3months",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-03-01", "endDate": "2026-03-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_keyword_analysis_supports_custom_month_range():
    scenario = get_resource_scenario("keyword-analysis")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period="custom_month_range",
        start_month="2025-07",
        end_month="2025-08",
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=20,
    )

    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2025-07-01", "endDate": "2025-07-31"},
        "endCycle": {"startDate": "2025-08-01", "endDate": "2025-08-31"},
    }


def test_keyword_analysis_accepts_chinese_cycle_alias(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("keyword-analysis")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period="半年",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["cycleFilter"]["startCycle"] == {
        "startDate": "2025-12-01",
        "endDate": "2025-12-31",
    }


def test_keyword_explorer_payload():
    scenario = get_resource_scenario("keyword-explorer")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="tv stand",
        query="modern",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["resource"] == {"country": "US", "searchTerm": "tv stand"}
    assert payload["query"] == "modern"
    assert payload["correlationTierAsins"] == []
    assert payload["customCorrelationTier"] == []


def test_keyword_explorer_supports_last3months(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("keyword-explorer")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period="last3months",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-03-01", "endDate": "2026-03-31"},
        "endCycle": {"startDate": "2026-06-01", "endDate": "2026-06-30"},
    }


def test_keyword_explorer_supports_custom_month_range():
    scenario = get_resource_scenario("keyword-explorer")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period="custom_month_range",
        start_month="2026-02",
        end_month="2026-05",
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["cycleFilter"] == {
        "cycle": "monthly",
        "period": "",
        "startCycle": {"startDate": "2026-02-01", "endDate": "2026-02-28"},
        "endCycle": {"startDate": "2026-05-01", "endDate": "2026-05-31"},
    }


def test_keyword_explorer_rejects_invalid_custom_month_range():
    scenario = get_resource_scenario("keyword-explorer")

    with pytest.raises(XiyouConfigError):
        scenario.build_payload(
            site="US",
            asin=None,
            asins=None,
            keyword="backpack",
            query="",
            cycle_period="custom_month_range",
            start_month="2026-06",
            end_month="2026-03",
            start_date=None,
            end_date=None,
            report_date=None,
            page=1,
            page_size=50,
        )


def test_keyword_historical_traffic_payload_defaults_to_last1month(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 9))
    scenario = get_resource_scenario("keyword-historical-traffic")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["biz"]["cycleFilter"] == {
        "cycle": "daily",
        "period": "",
        "startCycle": {"startDate": "2026-05-09", "endDate": "2026-05-09"},
        "endCycle": {"startDate": "2026-06-07", "endDate": "2026-06-07"},
    }
    assert payload["biz"]["trafficCampaignType"] == "organicCampaign"


def test_keyword_historical_traffic_payload_rejects_custom_date_range():
    scenario = get_resource_scenario("keyword-historical-traffic")

    with pytest.raises(XiyouConfigError) as exc:
        scenario.build_payload(
            site="US",
            asin=None,
            asins=None,
            keyword="backpack",
            query="",
            cycle_period=None,
            start_month=None,
            end_month=None,
            start_date="2026-05-09",
            end_date="2026-06-07",
            report_date=None,
            page=2,
            page_size=20,
        )

    assert "不支持用户自定义时间范围" in str(exc.value)


def test_keyword_historical_traffic_payload_rejects_cycle_period_override():
    scenario = get_resource_scenario("keyword-historical-traffic")

    with pytest.raises(XiyouConfigError) as exc:
        scenario.build_payload(
            site="US",
            asin=None,
            asins=None,
            keyword="backpack",
            query="",
            cycle_period="last1month",
            start_month=None,
            end_month=None,
            start_date=None,
            end_date=None,
            report_date=None,
            page=1,
            page_size=50,
        )

    assert "不支持用户自定义时间范围" in str(exc.value)


def test_keyword_ad_replay_payload_supports_report_date():
    scenario = get_resource_scenario("keyword-ad-replay")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date="2026-06-08",
        page=1,
        page_size=50,
    )

    assert payload == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "country": "US",
        "searchTerm": "backpack",
        "reportDate": "2026-06-08",
    }


def test_keyword_organic_replay_payload_supports_report_date():
    scenario = get_resource_scenario("keyword-organic-replay")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date="2026-06-08",
        page=1,
        page_size=50,
    )

    assert payload == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "biz": {
            "country": "US",
            "searchTerm": "backpack",
            "reportDate": "2026-06-08",
        },
    }


def test_keyword_ad_toppers_payload():
    scenario = get_resource_scenario("keyword-ad-toppers")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="backpack",
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "biz": {
            "country": "US",
            "searchTerm": "backpack",
        },
    }


def test_ad_analysis_payload_uses_parent_asin_related_asins_and_search_terms():
    scenario = get_resource_scenario("ad-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="",
        parent_asin="B0FDB5VR1V",
        cycle_period="last7days",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms="candle warmer",
        page=1,
        page_size=20,
    )

    assert payload["resource"] == {"country": "US", "asin": "B0DZFGTCLR"}
    assert payload["biz"]["parentAsin"] == "B0FDB5VR1V"
    assert payload["biz"]["asins"] == ["B0DZFGTCLR", "B0DZFW1QS1"]
    assert payload["biz"]["filters"]["searchTerms"] == ["candle warmer"]


def test_ad_analysis_payload_allows_empty_search_terms():
    scenario = get_resource_scenario("ad-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="",
        parent_asin="B0FDB5VR1V",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=20,
    )

    assert payload["biz"]["filters"]["searchTerms"] == []


def test_ad_analysis_payload_falls_back_to_query_as_search_terms():
    scenario = get_resource_scenario("ad-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="candle warmer",
        parent_asin="B0FDB5VR1V",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=20,
    )

    assert payload["biz"]["filters"]["searchTerms"] == ["candle warmer"]


def test_ad_analysis_payload_supports_last14days():
    scenario = get_resource_scenario("ad-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="",
        parent_asin="B0FDB5VR1V",
        cycle_period="last14days",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=20,
    )

    assert payload["biz"]["cycleFilter"] == {
        "cycle": "daily",
        "period": "last14days",
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }


def test_ad_analysis_payload_supports_last30days():
    scenario = get_resource_scenario("ad-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="",
        parent_asin="B0FDB5VR1V",
        cycle_period="last30days",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=20,
    )

    assert payload["biz"]["cycleFilter"] == {
        "cycle": "daily",
        "period": "last30days",
        "startCycle": {"startDate": "", "endDate": ""},
        "endCycle": {"startDate": "", "endDate": ""},
    }


def test_parent_analysis_payload_uses_variation_compare_shape():
    scenario = get_resource_scenario("parent-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=["B0DZFGTCLR", "B0DZFW1QS1"],
        keyword=None,
        query="candle warmer lamp",
        parent_asin="B0FDB5VR1V",
        cycle_period="last1month",
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=50,
        keyword_type="organic",
    )

    assert payload["resource"] == {"country": "US", "parentAsin": "B0FDB5VR1V"}
    assert payload["filters"] == [{"field": "asinResearchType", "filter": ["organic"]}]
    assert payload["tableType"] == "variationCompareList"
    assert payload["asins"] == ["B0DZFGTCLR", "B0DZFW1QS1"]


def test_sales_analysis_payload_uses_monthly_cycle_and_query_defaults_to_asin():
    scenario = get_resource_scenario("sales-analysis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        parent_asin="B0FDB5VR1V",
        cycle_period="custom_month_range",
        start_month="2024-02",
        end_month="2026-05",
        start_date=None,
        end_date=None,
        report_date=None,
        search_terms=None,
        page=1,
        page_size=50,
    )

    assert payload["biz"]["query"] == "B0DZFGTCLR"
    assert payload["biz"]["cycleFilter"]["cycle"] == "monthly"
    assert payload["biz"]["cycleFilter"]["startCycle"] == {
        "startDate": "2024-02-01",
        "endDate": "2024-02-29",
    }


def test_flow_insight_payload_uses_date_range():
    scenario = get_resource_scenario("flow-insight")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        parent_asin=None,
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date="2026-05-27",
        end_date="2026-06-09",
        report_date=None,
        search_terms=None,
        page=1,
        page_size=50,
    )

    assert payload["biz"] == {
        "asin": "B0DZFGTCLR",
        "country": "US",
        "startDate": "2026-05-27",
        "endDate": "2026-06-09",
    }


def test_flow_weekly_payload_uses_date_range_and_blank_end_of_week():
    scenario = get_resource_scenario("flow-weekly")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        parent_asin=None,
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date="2026-05-25",
        end_date="2026-05-31",
        report_date=None,
        search_terms=None,
        page=1,
        page_size=50,
    )

    assert payload["biz"]["startDate"] == "2026-05-25"
    assert payload["biz"]["endDate"] == "2026-05-31"
    assert payload["biz"]["endOfWeek"] == ""


def test_flow_diagnosis_scenario_is_registered():
    scenario = get_resource_scenario("flow-diagnosis")

    assert scenario.function == "flow-diagnosis"
    assert scenario.endpoint == "/v3/asins/traffic/diagnosis/list"
    assert scenario.status_endpoint == ""
    assert scenario.mode == "rows"


def test_flow_diagnosis_payload_supports_report_date_and_traffic_type():
    scenario = get_resource_scenario("flow-diagnosis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date="2026-06-02",
        page=1,
        page_size=50,
        keyword_type="advertising",
    )

    assert payload == {
        "resource": {"country": "US", "asin": "B0DZFGTCLR"},
        "biz": {
            "asin": "B0DZFGTCLR",
            "country": "US",
            "date": "2026-06-02",
            "trafficType": "advertising",
        },
    }


def test_flow_diagnosis_defaults_to_total_and_latest_allowed_date(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 11))
    scenario = get_resource_scenario("flow-diagnosis")

    payload = scenario.build_payload(
        site="US",
        asin="B0DZFGTCLR",
        asins=None,
        keyword=None,
        query="",
        cycle_period=None,
        start_month=None,
        end_month=None,
        start_date=None,
        end_date=None,
        report_date=None,
        page=1,
        page_size=50,
    )

    assert payload["biz"]["date"] == "2026-06-09"
    assert payload["biz"]["trafficType"] == "total"


def test_flow_diagnosis_rejects_yesterday_or_newer_report_date(monkeypatch):
    monkeypatch.setattr(payloads_module, "_today", lambda: date(2026, 6, 11))
    scenario = get_resource_scenario("flow-diagnosis")

    with pytest.raises(XiyouConfigError) as exc:
        scenario.build_payload(
            site="US",
            asin="B0DZFGTCLR",
            asins=None,
            keyword=None,
            query="",
            cycle_period=None,
            start_month=None,
            end_month=None,
            start_date=None,
            end_date=None,
            report_date="2026-06-10",
            page=1,
            page_size=50,
        )

    assert "昨天之前" in str(exc.value)


def test_supported_sites_contains_all_thirteen_xiyou_marketplaces():
    # 西柚官网当前披露的 13 个站点，任何后续删除都会被这条用例拦截
    assert SUPPORTED_SITES == frozenset({
        "US", "CA", "MX", "BR",
        "DE", "UK", "FR", "IT", "ES",
        "JP",
        "AE", "SA",
        "AU",
    })


def test_normalize_site_accepts_chinese_country_names():
    assert normalize_site("日本") == "JP"
    assert normalize_site("美国站") == "US"
    assert normalize_site("澳洲") == "AU"
    assert normalize_site("沙特阿拉伯") == "SA"


def test_normalize_site_accepts_iso2_code_case_insensitive():
    assert normalize_site("us") == "US"
    assert normalize_site("JP") == "JP"
    assert normalize_site("gb") == "UK"  # 英国 ISO2 是 GB，西柚 code 是 UK，靠别名兜底


def test_normalize_site_defaults_to_us_when_empty():
    assert normalize_site(None) == "US"
    assert normalize_site("") == "US"
    assert normalize_site("   ") == "US"


def test_normalize_site_rejects_unsupported_country():
    with pytest.raises(XiyouConfigError) as exc:
        normalize_site("柬埔寨")
    assert "柬埔寨" in str(exc.value)


def test_ranking_payload_normalizes_chinese_site_to_code():
    scenario = get_scenario("asin")
    payload = scenario.build_payload(
        site="日本",
        period="week",
        rank_pattern=None,
        query="",
        page=1,
        page_size=50,
    )
    assert payload["biz"]["country"] == "JP"


def test_resource_payload_rejects_unsupported_site():
    scenario = get_resource_scenario("reverse-keyword")
    with pytest.raises(XiyouConfigError):
        scenario.build_payload(
            site="柬埔寨",
            asin="b0g33fz8xs",
            asins=None,
            keyword=None,
            query="",
            cycle_period=None,
            start_month=None,
            end_month=None,
            start_date=None,
            end_date=None,
            report_date=None,
            page=1,
            page_size=50,
        )
