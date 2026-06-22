from opscli.sif.traffic.scenarios import asin_keyword_list_payload, asin_multi_nf_payload, listing_score_chart_query


def test_traffic_payloads_match_sif_download_contract():
    assert listing_score_chart_query(
        asin="B01NBNDC1T",
        country="US",
        time_piece_type="latelyDay",
        time_piece_value="7",
    ) == {
        "country": "US",
        "timePieceType": "latelyDay",
        "timePieceValue": "7",
        "asin": "B01NBNDC1T",
        "dimension": "asin",
        "desc": True,
    }
    assert asin_keyword_list_payload(
        asin="B01NBNDC1T",
        time_piece_type="latelyDay",
        time_piece_value="7",
        page_size=20,
    )["sort"] == "scoreInfo.scoreRatio"
    assert asin_keyword_list_payload(
        asin="B01NBNDC1T",
        time_piece_type="latelyDay",
        time_piece_value="7",
        page_size=20,
    )["pageSize"] == 20
    assert asin_multi_nf_payload(
        asin="B01NBNDC1T",
        time_piece_type="latelyDay",
        time_piece_value="7",
        page_size=20,
    )["sortBy"] == "nfScore"
    assert asin_multi_nf_payload(
        asin="B01NBNDC1T",
        time_piece_type="latelyDay",
        time_piece_value="7",
        page_size=20,
    )["pageSize"] == 20
