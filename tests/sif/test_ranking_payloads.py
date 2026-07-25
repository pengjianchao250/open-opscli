import pytest

from opscli.sif.ranking.scenarios import normalize_ranking_granularity, ranking_download_payload, ranking_list_payload


def test_ranking_payloads_match_sif_contract():
    assert ranking_list_payload(asin="B0BMW2985V", granularity="month", page_size=20) == {
        "filterAsin": "",
        "granularity": "month",
        "asin": "B0BMW2985V",
        "endDay": None,
        "pageNum": 1,
        "pageSize": 20,
        "interval": 7,
        "sortBy": "estSearchesNum",
        "desc": True,
        "isListingSearch": True,
        "isExample": True,
    }
    assert ranking_download_payload(asin="B0BMW2985V", granularity="week") == {
        "isListingSearch": True,
        "asin": "B0BMW2985V",
        "granularity": "week",
        "isExample": True,
    }


def test_ranking_granularity_validation():
    assert normalize_ranking_granularity(None) == "week"
    with pytest.raises(ValueError):
        normalize_ranking_granularity("day")
