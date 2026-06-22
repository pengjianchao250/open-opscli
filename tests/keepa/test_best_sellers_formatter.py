from opscli.keepa.best_sellers_formatter import format_best_sellers_export


def test_best_sellers_formatter_derives_summary_and_ranked_asin_rows():
    formatted = format_best_sellers_export(
        {
            "domainId": 1,
            "categoryId": 172282,
            "lastUpdate": 7588958,
            "asinList": ["B000000001", "B000000002"],
        },
        site="US",
    )

    assert formatted is not None
    summary = formatted.list_rows[0]
    assert summary["domain"] == "US"
    assert summary["amazonHost"] == "www.amazon.com"
    assert summary["categoryId"] == "172282"
    assert summary["categoryUrl"] == "https://www.amazon.com/b?node=172282"
    assert summary["lastUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert summary["asinCount"] == 2
    assert summary["bestSellersListRaw"]["asinList"] == ["B000000001", "B000000002"]

    assert formatted.asin_rows == [
        {
            "domainId": 1,
            "domain": "US",
            "amazonHost": "www.amazon.com",
            "categoryId": "172282",
            "categoryUrl": "https://www.amazon.com/b?node=172282",
            "lastUpdate": 7588958,
            "lastUpdateUtc": "2025-06-06T02:38:00Z",
            "asinCount": 2,
            "bestSellerRank": 1,
            "asin": "B000000001",
            "rowSource": "bestSellersList",
        },
        {
            "domainId": 1,
            "domain": "US",
            "amazonHost": "www.amazon.com",
            "categoryId": "172282",
            "categoryUrl": "https://www.amazon.com/b?node=172282",
            "lastUpdate": 7588958,
            "lastUpdateUtc": "2025-06-06T02:38:00Z",
            "asinCount": 2,
            "bestSellerRank": 2,
            "asin": "B000000002",
            "rowSource": "bestSellersList",
        },
    ]
