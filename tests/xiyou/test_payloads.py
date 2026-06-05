import pytest

from opscli.xiyou.api.scenarios import get_scenario
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

