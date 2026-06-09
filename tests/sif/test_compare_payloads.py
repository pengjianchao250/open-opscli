from opscli.sif.compare.scenarios import compare_my_keywords_payload, compare_sales_payload, compare_summary_payload


ASINS = ["B075WPKK5P", "B07KVV8RFF", "B07QQ21GL2", "B07YJPFJ43", "B08PNQCKF7"]


def test_compare_sales_payload_matches_confirmed_contract():
    payload = compare_sales_payload(asins=ASINS, time_piece_type="latelyDay", time_piece_value="30")

    assert payload == {
        "pageNum": 1,
        "pageSize": 100,
        "sortBy": "",
        "desc": True,
        "asins": ASINS,
        "timePieceType": "latelyDay",
        "timePieceValue": "30",
    }


def test_compare_summary_show_type_values():
    assert compare_summary_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="7",
        show_type=1,
    )["showType"] == 1
    assert compare_summary_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="7",
        show_type=2,
    )["showType"] == 2


def test_compare_my_keywords_list_type_values():
    assert compare_my_keywords_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="7",
        list_type=1,
    )["listType"] == 1
    assert compare_my_keywords_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="7",
        list_type=2,
    )["listType"] == 2


def test_compare_payloads_accept_page_size():
    assert compare_sales_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="30",
        page_size=20,
    )["pageSize"] == 20
    assert compare_my_keywords_payload(
        asins=ASINS,
        time_piece_type="latelyDay",
        time_piece_value="7",
        list_type=1,
        page_size=20,
    )["myPageSize"] == 20
