import pytest

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
        period="month",
        rank_pattern="aba",
        query="desk",
        page=2,
        page_size=20,
    )

    assert payload["biz"]["country"] == "DE"
    assert payload["biz"]["filed"] == "month"
    assert payload["biz"]["page"] == 2
    assert payload["biz"]["pageSize"] == 20
    assert payload["biz"]["query"] == "desk"
    assert payload["biz"]["rankPattern"] == "aba"


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
        page=2,
        page_size=25,
    )

    assert payload["resource"] == {"country": "US", "asin": "B0G33FZ8XS"}
    assert payload["biz"]["asin"] == "B0G33FZ8XS"
    assert payload["biz"]["query"] == "stand"
    assert payload["biz"]["page"] == 2
    assert payload["biz"]["pageSize"] == 25
    assert payload["biz"]["tableType"] == "asinResearchTotalList"


def test_asin_compare_payload_requires_two_asins():
    scenario = get_resource_scenario("asin-compare")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins="B0G33FZ8XS, B0G337Q47M, B0G33FZ8XS",
        keyword=None,
        query="",
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
            page=1,
            page_size=50,
        )


def test_keyword_analysis_payload():
    scenario = get_resource_scenario("keyword-analysis")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="tv stands for living room",
        query="",
        page=1,
        page_size=50,
    )

    assert payload["resource"] == {"country": "US", "searchTerm": "tv stands for living room"}
    assert payload["searchTerm"] == "tv stands for living room"
    assert payload["orders"] == [{"field": "traffic", "order": "desc"}]


def test_keyword_explorer_payload():
    scenario = get_resource_scenario("keyword-explorer")

    payload = scenario.build_payload(
        site="US",
        asin=None,
        asins=None,
        keyword="tv stand",
        query="modern",
        page=1,
        page_size=50,
    )

    assert payload["resource"] == {"country": "US", "searchTerm": "tv stand"}
    assert payload["query"] == "modern"
    assert payload["correlationTierAsins"] == []
    assert payload["customCorrelationTier"] == []



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
            page=1,
            page_size=50,
        )
