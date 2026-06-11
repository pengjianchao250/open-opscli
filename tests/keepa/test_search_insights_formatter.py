from opscli.keepa.search_insights_formatter import format_search_insights_export


def test_search_insights_formatter_derives_amounts_percent_rating_and_detail_rows():
    formatted = format_search_insights_export(
        {
            "avgBuyBox": 1299,
            "avgBuyBox90": 1399,
            "avgBuyBox365": -1,
            "avgBuyBoxDeviation": 250,
            "avgDeltaPercent30BuyBox": -0.12,
            "isFBAPercent": 78.3,
            "avgReviewCount": 123,
            "avgRating": 45,
            "sellerCount": 8,
            "brandCount": 2,
            "highestRank": 9999,
            "lowestRank": 12,
            "relatedCategories": [172282, 541966],
            "topBrandsWithCounts": {"Brand A": 10, "Brand B": 5},
            "topSellersWithCounts": {"A2L77EE7U53NWQ": 7},
        },
        site="US",
        domain_id=1,
        query_name="portable charger",
    )

    assert formatted is not None
    row = formatted.main_rows[0]
    assert row["queryName"] == "portable charger"
    assert row["avgBuyBoxAmount"] == 12.99
    assert row["avgBuyBox365Amount"] is None
    assert row["avgBuyBoxDeviationAmount"] == 2.5
    assert row["avgDeltaPercent30BuyBoxDisplay"] == "-0.12%"
    assert row["isFBAPercentDisplay"] == "78.3%"
    assert row["avgRatingRaw"] == 45
    assert row["avgRatingStars"] == 4.5
    assert row["relatedCategoryCount"] == 2
    assert row["relatedCategoriesJoined"] == "172282, 541966"
    assert row["topBrandsJoined"] == "Brand A:10, Brand B:5"
    assert row["currencyCode"] == "USD"
    assert row["searchInsightsRaw"]["avgBuyBox"] == 1299

    assert formatted.brand_rows == [
        {"rank": 1, "brand": "Brand A", "productCount": 10, "queryName": "portable charger"},
        {"rank": 2, "brand": "Brand B", "productCount": 5, "queryName": "portable charger"},
    ]
    assert formatted.seller_rows == [
        {
            "rank": 1,
            "sellerId": "A2L77EE7U53NWQ",
            "buyBoxOccurrenceCount": 7,
            "queryName": "portable charger",
        }
    ]
    assert formatted.category_rows == [
        {"index": 1, "categoryId": "172282", "queryName": "portable charger"},
        {"index": 2, "categoryId": "541966", "queryName": "portable charger"},
    ]
