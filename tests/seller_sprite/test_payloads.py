from datetime import date

import pytest

from opscli.seller_sprite.api import payloads as payloads_module
from opscli.seller_sprite.api.payloads import (
    build_referer,
    make_aba_research_payload,
    make_aba_reverse_payload,
    make_association_traffic_payload,
    make_branddb_payload,
    make_competitor_payload,
    make_keyword_comparison_payload,
    make_keyword_conversion_rate_payload,
    make_keyword_miner_payload,
    make_keyword_research_payload,
    make_keyword_reverse_payload,
    make_listing_analysis_payload,
    make_product_research_payload,
    make_traffic_extend_payload,
)
from opscli.seller_sprite.api.scenarios import get_scenario
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


def test_traffic_extend_scenario_builds_first_page_all_variants_payload():
    scenario = get_scenario("traffic-extend")

    payload = scenario.build_payload(
        params={"asins": "B089K9L3VY B07F8S18D5"},
        site="US",
        period="30d",
        page_size=100,
    )

    assert scenario.endpoint == "/v3/api/traffic/extend/asin"
    assert scenario.browser_context_only is True
    assert payload == {
        "queryVariations": True,
        "asinList": ["B089K9L3VY", "B07F8S18D5"],
        "originAsinList": ["B089K9L3VY", "B07F8S18D5"],
        "market": 1,
        "page": 1,
        "month": "",
        "size": 100,
        "orderColumn": 12,
        "desc": True,
        "exactly": False,
        "ac": False,
    }
    referer = scenario.build_referer(payload)
    assert referer.startswith("https://www.sellersprite.com/v3/traffic/extend?")
    assert "q=" not in referer


def test_keyword_conversion_rate_scenario_builds_first_page_batch_payload():
    scenario = get_scenario("keyword-conversion-rate")

    payload = scenario.build_payload(
        params={
            "keywords": "wireless charger stand\nphone holder\twireless charger stand",
        },
        site="US",
        period="W",
        page_size=20,
    )

    assert scenario.endpoint == "/v3/api/keyword-conv"
    assert scenario.browser_context_only is True
    assert scenario.replay_safe is False
    assert payload == {
        "pageNum": 1,
        "pageSize": 100,
        "market": "US",
        "timeType": "W",
        "bidMatchType": "exact",
        "keywordMatchType": "all",
        "matchType": 1,
        "keyword": "wireless charger stand,phone holder",
    }
    assert (
        scenario.build_referer(payload)
        == "https://www.sellersprite.com/v3/keyword-conversion-rate"
    )


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("W", "W"),
        ("week", "W"),
        ("按周", "W"),
        ("30d", "W"),
        ("90D", "90D"),
        ("90d", "90D"),
        ("近90天", "90D"),
    ],
)
def test_keyword_conversion_rate_normalizes_page_period(period, expected):
    payload = make_keyword_conversion_rate_payload(
        {"keywords": ["phone stand"], "site": "US", "period": period}
    )

    assert payload["timeType"] == expected


def test_keyword_conversion_rate_rejects_more_than_one_thousand_keywords():
    with pytest.raises(SellerSpriteConfigError, match="最多支持 1000 个关键词"):
        make_keyword_conversion_rate_payload(
            {
                "keywords": [f"keyword {index}" for index in range(1001)],
                "site": "US",
                "period": "W",
            }
        )


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        (None, "all"),
        ("all", "all"),
        ("用全部变体拓词", "all"),
        ("sell_well", "sell_well"),
        ("用畅销变体拓词", "sell_well"),
        ("current", "current"),
        ("用当前变体拓词", "current"),
    ],
)
def test_traffic_extend_variant_selection_supports_page_options(variant, expected):
    params = {"asins": ["B089K9L3VY"]}
    if variant is not None:
        params["variantSelection"] = variant

    assert payloads_module.traffic_extend_variant_selection(params) == expected


def test_traffic_extend_rejects_more_than_twenty_asins():
    asins = [f"B0000000{index:02d}" for index in range(21)]

    with pytest.raises(SellerSpriteConfigError, match="最多支持 20 个 ASIN"):
        make_traffic_extend_payload({"asins": asins, "site": "US", "period": "30d"})


def test_branddb_scenario_builds_official_export_payload():
    scenario = get_scenario("branddb")

    payload = scenario.build_payload(
        params={"text": "ANKER"},
        site="US",
        period="30d",
        page_size=100,
    )

    assert scenario.endpoint == "/v3/api/branddb/export-syn"
    assert scenario.method == "POST_XLSX"
    assert scenario.browser_context_only is True
    assert scenario.replay_safe is False
    assert payload == {
        "text": "ANKER",
        "feature": "",
        "office": [],
        "brandName": [],
        "status": [],
        "applicant": [],
        "niceClass": [],
        "applicationYear": [],
        "expiryYear": [],
        "desc": True,
        "orderField": "",
        "pageNum": 1,
        "pageSize": 20,
        "ids": [],
    }
    assert scenario.build_referer(payload) == "https://www.sellersprite.com/v3/branddb"


def test_branddb_payload_normalizes_all_filters_and_keeps_false_desc():
    payload = make_branddb_payload(
        {
            "text": "Anker",
            "feature": "word",
            "office": ["US", "US", " CN "],
            "brandName": "ANKER, Soundcore",
            "status": ["已注册", "Expired", "已结束", "待审核", "未知"],
            "applicant": ["Anker Innovations Limited", ""],
            "niceClass": ["9", 35, 9],
            "applicationYear": [2022, "2022", "2023"],
            "expiryYear": "2032,2033",
            "desc": False,
            "orderField": "applicationDate",
            "pageNum": 2,
            "pageSize": 50,
            "ids": [123, "123", "456"],
        }
    )

    assert payload == {
        "text": "Anker",
        "feature": "word",
        "office": ["US", "CN"],
        "brandName": ["ANKER", "Soundcore"],
        "status": ["Registered", "Expired", "Ended", "Pending", "Unknown"],
        "applicant": ["Anker Innovations Limited"],
        "niceClass": [9, 35],
        "applicationYear": ["2022", "2023"],
        "expiryYear": ["2032", "2033"],
        "desc": False,
        "orderField": "applicationDate",
        "pageNum": 2,
        "pageSize": 50,
        "ids": [123, 456],
    }


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"text": "ANKER", "status": ["无效状态"]}, "status"),
        ({"text": "ANKER", "niceClass": [0]}, "niceClass"),
        ({"text": "ANKER", "applicationYear": ["20x2"]}, "applicationYear"),
        ({"text": "ANKER", "pageNum": 0}, "pageNum"),
        ({"text": "ANKER", "office": {"code": "US"}}, "office"),
        ({"text": "ANKER", "brandName": [["ANKER"]]}, "brandName"),
        ({"text": {"brand": "ANKER"}}, "text"),
        ({"text": "ANKER", "feature": ["word"]}, "feature"),
        ({"text": "ANKER", "orderField": {"name": "applicationDate"}}, "orderField"),
        ({"text": "ANKER", "desc": [False]}, "desc"),
    ],
)
def test_branddb_payload_rejects_invalid_filters(params, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_branddb_payload(params)


@pytest.mark.parametrize("text", [None, "", "   "])
def test_branddb_scenario_requires_non_blank_text(text):
    scenario = get_scenario("branddb")
    params = {} if text is None else {"text": text}

    with pytest.raises(SellerSpriteConfigError, match="text"):
        scenario.build_payload(params=params, site="US", period="30d", page_size=100)


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


def test_keyword_comparison_payload_normalizes_inputs_and_forces_first_page():
    scenario = get_scenario("keyword-comparison")

    payload = scenario.build_payload(
        params={
            "asin": "b0949dwjcv",
            "competitorAsins": "b0744dm3y3， B0BRN58CXR\nB0744DM3Y3",
            "page": 8,
            "size": 20,
        },
        site="US",
        period="30d",
        page_size=20,
    )

    assert scenario.endpoint == "/v3/api/keyword-comparison/asin"
    assert scenario.method == "POST"
    assert scenario.browser_context_only is True
    assert payload == {
        "page": 1,
        "size": 100,
        "exactly": False,
        "orderColumn": 22,
        "desc": True,
        "asin": "B0949DWJCV",
        "asinList": ["B0744DM3Y3", "B0BRN58CXR"],
        "station": "US",
        "sortAsin": "",
    }
    assert scenario.build_referer(payload) == (
        "https://www.sellersprite.com/v3/keyword-comparison"
    )


@pytest.mark.parametrize(
    ("variant_selection", "expected"),
    [
        (None, "sell_well"),
        ("sell_well", "sell_well"),
        ("用畅销变体拓词", "sell_well"),
        ("current", "current"),
        ("用当前变体拓词", "current"),
    ],
)
def test_keyword_comparison_variant_selection_is_validated_but_not_sent(
    variant_selection, expected
):
    params = {
        "asin": "B0949DWJCV",
        "competitorAsins": "B0744DM3Y3",
    }
    if variant_selection is not None:
        params["variantSelection"] = variant_selection

    payload = make_keyword_comparison_payload(params)

    assert (
        payloads_module.keyword_comparison_variant_selection(params) == expected
    )
    assert "variantSelection" not in payload


def test_keyword_comparison_rejects_unknown_variant_selection():
    with pytest.raises(SellerSpriteConfigError, match="variantSelection"):
        make_keyword_comparison_payload(
            {
                "asin": "B0949DWJCV",
                "competitorAsins": "B0744DM3Y3",
                "variantSelection": "unknown",
            }
        )


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"asin": "", "competitorAsins": "B0744DM3Y3"}, "自己的 ASIN"),
        (
            {"asin": "B0949DWJCV B0744DM3Y3", "competitorAsins": "B0BRN58CXR"},
            "自己的 ASIN 只能输入 1 个",
        ),
        ({"asin": "B0949DWJCV", "competitorAsins": ""}, "至少需要 1 个竞品 ASIN"),
        (
            {
                "asin": "B0949DWJCV",
                "competitorAsins": [f"B0000000{i:02d}" for i in range(11)],
            },
            "最多支持 10 个竞品 ASIN",
        ),
        (
            {"asin": "B0949DWJCV", "competitorAsins": "B0949DWJCV"},
            "不得包含自己的 ASIN",
        ),
        (
            {"asin": "INVALID", "competitorAsins": "B0744DM3Y3"},
            "自己的 ASIN 格式无效",
        ),
        (
            {"asin": "B0949DWJCV", "competitorAsins": "INVALID"},
            "竞品 ASIN 格式无效",
        ),
    ],
)
def test_keyword_comparison_payload_rejects_invalid_asins(params, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_keyword_comparison_payload({"site": "US", **params})


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
    assert payload["size"] == "100"
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


def test_association_traffic_payload_uses_all_variants_and_normalizes_pasted_asins():
    scenario = get_scenario("association-traffic")

    payload = scenario.build_payload(
        params={
            "asins": "b098t9zfb5\r\nB09JW5FNVX\tB0B71DH45N",
            "relations": ["VAV", "SP"],
            "pageNum": 3,
        },
        site="US",
        period="30d",
        page_size=100,
    )

    assert scenario.endpoint == "/v3/api/relation/traffic"
    assert scenario.method == "POST"
    assert payload == {
        "market": 1,
        "pageNum": 1,
        "pageSize": 100,
        "desc": True,
        "orderField": "createdTime",
        "relations": ["VAV", "SP"],
        "queryVariations": True,
        "asinList": ["B098T9ZFB5", "B09JW5FNVX", "B0B71DH45N"],
    }
    assert build_referer(payload, "association-traffic").startswith(
        "https://www.sellersprite.com/v3/relation-keyword?"
    )


@pytest.mark.parametrize(
    ("asins", "message"),
    [
        ("", "至少需要 1 个 ASIN"),
        ("B098T9ZFB5,INVALID", "INVALID"),
        (",".join(f"B0000000{i:02d}" for i in range(21)), "最多支持 20 个 ASIN"),
    ],
)
def test_association_traffic_payload_rejects_invalid_asin_input(asins, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_association_traffic_payload({"site": "US", "asins": asins})


def test_association_traffic_payload_rejects_unknown_relation_type():
    with pytest.raises(SellerSpriteConfigError, match="UNKNOWN"):
        make_association_traffic_payload(
            {"site": "US", "asins": ["B098T9ZFB5"], "relations": ["UNKNOWN"]}
        )


def test_aba_research_payload_maps_week_filters_and_forces_first_page():
    scenario = get_scenario("aba-research")

    payload = scenario.build_payload(
        params={
            "q": "B06XZTZ7GB",
            "departments": ["electronics", "kitchen"],
            "rankGrowthType": "W2",
            "page": 3,
            "size": 20,
            "minSearches": 1000,
            "maxSearches": 2000,
            "minConversionRate": 12.5,
            "maxConversionRate": 20,
            "orderField": "searches",
            "orderDesc": True,
        },
        site="US",
        period="2026第29周(07/12~07/18)",
        page_size=20,
    )

    assert scenario.endpoint == "/v3/api/aba-research"
    assert scenario.method == "POST"
    assert payload == {
        "rankGrowthType": "W2",
        "size": 100,
        "page": 1,
        "market": "COM",
        "q": "B06XZTZ7GB",
        "table": "ara_20260718",
        "reverseType": "W",
        "departments": ["electronics", "kitchen"],
        "keywordBidMatchType": "exact",
        "order": {"field": "searches", "desc": True},
        "minSearches": 1000,
        "maxSearches": 2000,
        "minConversionRate": 12.5,
        "maxConversionRate": 20,
    }
    assert build_referer(payload, "aba-research") == "https://www.sellersprite.com/v3/aba-research"


def test_aba_research_payload_maps_month_and_defaults_to_latest_week(monkeypatch):
    monthly = make_aba_research_payload(
        {
            "q": "iphone charger",
            "site": "JP",
            "period": "2026-06",
            "reverseType": "M",
        }
    )
    assert monthly["market"] == "JP"
    assert monthly["table"] == "ara_202606"
    assert monthly["reverseType"] == "M"

    monthly_table = make_aba_research_payload(
        {
            "q": "iphone charger",
            "site": "US",
            "table": "ara_202606",
            "includeKeywords": ["usb c", "fast charger"],
            "excludeKeywords": "case,stand",
        }
    )
    assert monthly_table["reverseType"] == "M"
    assert monthly_table["includeKeywords"] == "usb c,fast charger"
    assert monthly_table["excludeKeywords"] == "case,stand"

    monkeypatch.setattr(payloads_module, "_latest_completed_aba_week", lambda: "20260718")
    weekly = make_aba_research_payload({"q": "iphone charger", "site": "US", "period": "30d"})
    assert weekly["table"] == "ara_20260718"
    assert weekly["reverseType"] == "W"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"q": "x", "site": "MX", "period": "2026-07-18"}, "暂不支持站点"),
        ({"q": "x", "period": "2026-07", "reverseType": "W"}, "每周周期"),
        ({"q": "x", "period": "2026-07", "rankGrowthType": "W5"}, "rankGrowthType"),
        ({"q": "x", "period": "2026-07", "orderField": "unknown"}, "order.field"),
        ({"q": "x", "period": "2026-07", "minSearches": 2, "maxSearches": 1}, "minSearches"),
        ({"q": "x", "period": "2026-07", "minClicks": 1.5}, "minClicks"),
    ],
)
def test_aba_research_payload_rejects_invalid_input(params, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_aba_research_payload({"site": "US", **params})


def test_aba_reverse_week_payload_accepts_asins_and_amazon_links():
    scenario = get_scenario("aba-reverse")

    payload = scenario.build_payload(
        params={
            "asins": (
                "b00000jbnx，https://www.amazon.com/dp/B08DRS8MNF "
                "https://amazon.com/gp/product/B00000JBNX?th=1"
            ),
            "reverseType": "每周",
        },
        site="US",
        period="2026第29周(07/12~07/18)",
        page_size=100,
    )

    assert scenario.endpoint == "/v2/aba/reverse/export"
    assert scenario.method == "GET_XLSX"
    assert payload == {
        "station": "US",
        "table": "ara_20260718",
        "asin": "B00000JBNX",
        "order.field": "searchRank",
        "order.desc": "false",
        "conversionType": "",
        "loadVariations": "false",
        "reverseType": "W",
        "monthlyTable": "ara_202606",
        "textareaValue": "B00000JBNX,B08DRS8MNF",
    }
    referer = build_referer(payload, "aba-reverse")
    assert referer.startswith("https://www.sellersprite.com/v2/aba/reverse/search?")
    assert "asin=&" in referer
    assert "textareaValue=B00000JBNX%2CB08DRS8MNF" in referer


def test_aba_reverse_month_payload_uses_month_table_for_both_fields():
    payload = make_aba_reverse_payload(
        {
            "asin": "B00000JBNX",
            "site": "JP",
            "period": "2026-06",
            "periodType": "monthly",
        }
    )

    assert payload["reverseType"] == "M"
    assert payload["table"] == "ara_202606"
    assert payload["monthlyTable"] == "ara_202606"


def test_aba_reverse_defaults_to_latest_completed_week(monkeypatch):
    monkeypatch.setattr(
        payloads_module,
        "_latest_completed_aba_week",
        lambda: "20260718",
    )

    payload = make_aba_reverse_payload(
        {
            "asin": "B00000JBNX",
            "site": "US",
            "period": "30d",
        }
    )

    assert payload["reverseType"] == "W"
    assert payload["table"] == "ara_20260718"
    assert payload["monthlyTable"] == "ara_202606"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 7, 23), "20260718"),
        (date(2026, 7, 18), "20260711"),
        (date(2026, 7, 19), "20260718"),
    ],
)
def test_latest_completed_aba_week_excludes_current_saturday(today, expected):
    assert payloads_module._latest_completed_aba_week(today) == expected


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"asins": ""}, "至少需要"),
        ({"asins": "not-an-asin"}, "格式无效"),
        (
            {"asins": ",".join(f"B0000000{i:02d}" for i in range(21))},
            "最多支持 20 个",
        ),
        ({"asin": "B00000JBNX", "period": "2026-06", "reverseType": "W"}, "每周周期"),
        ({"asin": "B00000JBNX", "period": "20260718", "reverseType": "quarter"}, "周期类型"),
    ],
)
def test_aba_reverse_payload_rejects_invalid_input(params, message):
    with pytest.raises(SellerSpriteConfigError, match=message):
        make_aba_reverse_payload({"site": "US", **params})


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
