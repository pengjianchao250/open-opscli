from opscli.sif.product_time_machine.scenarios import product_time_machine_download_payload, product_time_machine_list_payload


def test_product_time_machine_payloads_match_sif_contract():
    assert product_time_machine_list_payload(
        keyword="balloon pump",
        time_piece_type="latelyDay",
        time_piece_value="7",
        page_size=20,
    ) == {
        "pageNum": 1,
        "pageSize": 20,
        "sortBy": "",
        "desc": True,
        "keyword": "balloon pump",
        "timePieceType": "latelyDay",
        "timePieceValue": "7",
    }
    assert product_time_machine_download_payload(keyword="balloon pump", time_piece_type="month", time_piece_value="2026-02") == {
        "keyword": "balloon pump",
        "sortBy": "",
        "desc": True,
        "timePieceValue": "2026-02",
        "timePieceType": "month",
    }
