from opscli.keepa.stats_formatter import format_stats_for_product


def test_stats_formatter_derives_main_fields_and_detail_rows():
    current = [-1] * 36
    current[0] = 1299
    current[1] = 1399
    current[3] = 12345
    current[16] = 45
    current[17] = 456
    avg30 = [-1] * 36
    avg30[1] = 1499
    avg30[3] = 23456
    avg90 = [-1] * 36
    avg90[1] = 1599

    formatted = format_stats_for_product(
        {
            "asin": "B0088PUEPK",
            "domainId": 1,
            "stats": {
                "current": current,
                "avg30": avg30,
                "avg90": avg90,
                "min": [[7588958, 999], None, None, [7588958, 1000]],
                "outOfStockPercentage30": [25, 0],
                "lastOffersUpdate": 7588958,
                "buyBoxSellerId": "A2L77EE7U53NWQ",
                "buyBoxPrice": 1299,
                "buyBoxShipping": 200,
                "buyBoxSavingPercentage": 15,
                "buyBoxShippingTime": [24, 48],
                "lightningDealInfo": [7588958, -1],
                "buyBoxStats": {
                    "A2L77EE7U53NWQ": {
                        "avgPrice": 1299,
                        "avgNewOfferCount": 2.5,
                        "isFBA": True,
                        "lastSeen": 7588958,
                        "percentageWon": 80,
                    }
                },
                "retrievedOfferCount": 10,
                "totalOfferCount": 12,
                "sellerIdsLowestFBA": ["A2L77EE7U53NWQ"],
                "offerCountFBA": -2,
                "isLowest": [1, 0, -1],
                "isLowest90": [0, 1, -2],
                "stockPerCondition3rdFBA": [5, -1, 2],
                "stockPerConditionFBM": [10, 4, -2],
            },
        },
        site="US",
        domain_id=1,
    )

    assert formatted is not None
    main = formatted.main_fields
    assert main["statsCurrentAmazonPriceRaw"] == 1299
    assert main["statsCurrentAmazonPrice"] == 12.99
    assert main["statsCurrentNewPrice"] == 13.99
    assert main["statsCurrentSalesRank"] == 12345
    assert main["statsCurrentRating"] == 4.5
    assert main["statsCurrentReviewCount"] == 456
    assert main["statsAvg30NewPrice"] == 14.99
    assert main["statsAvg90NewPrice"] == 15.99
    assert main["statsOutOfStockPercentage30Amazon"] == 25
    assert main["statsOutOfStockPercentage30AmazonDisplay"] == "25%"
    assert main["statsLastOffersUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert main["statsBuyBoxPrice"] == 12.99
    assert main["statsBuyBoxLandedPrice"] == 14.99
    assert main["statsBuyBoxSellerStatus"] == "seller"
    assert main["statsHasBuyBox"] is True
    assert main["statsBuyBoxShippingTimeText"] == "1-2 days"
    assert main["statsLightningDealStatus"] == "upcoming"
    assert main["statsSellerIdsLowestFBAJoined"] == "A2L77EE7U53NWQ"
    assert main["statsOfferCountFBA"] is None

    price_rows = [row for row in formatted.price_type_rows if row["statField"] == "current" and row["priceTypeIndex"] == 0]
    assert price_rows[0]["formattedValue"] == 12.99

    extreme_rows = [row for row in formatted.extreme_rows if row["statField"] == "min" and row["priceTypeIndex"] == 0]
    assert extreme_rows[0]["utc"] == "2025-06-06T02:38:00Z"
    assert extreme_rows[0]["formattedValue"] == 9.99

    assert formatted.buy_box_seller_rows[0]["avgPrice"] == 12.99
    assert formatted.buy_box_seller_rows[0]["lastSeenUtc"] == "2025-06-06T02:38:00Z"
    assert formatted.buy_box_seller_rows[0]["percentageWonDisplay"] == "80%"

    assert formatted.offer_snapshot_rows[0]["sellerIdsLowestFBAJoined"] == "A2L77EE7U53NWQ"
    assert "sellerIdsLowestFBA" not in formatted.offer_snapshot_rows[0]
    assert formatted.offer_snapshot_rows[0]["sellerIdsLowestFBACount"] == 1
    lowest_rows = [row for row in formatted.price_type_rows if row["statField"] == "isLowest"]
    assert [row["formattedValue"] for row in lowest_rows] == [True, False, None]
    assert formatted.stock_by_condition_rows[0]["fulfillmentType"] == "FBA"
    assert formatted.stock_by_condition_rows[0]["stock"] == 5
    assert formatted.stock_by_condition_rows[1]["stock"] is None


def test_stats_formatter_exposes_native_deal_price_types_and_buy_box_basis_type():
    current = [-1] * 36
    current[8] = 9999
    current[33] = 10999

    formatted = format_stats_for_product(
        {
            "asin": "B000000001",
            "domainId": 1,
            "stats": {
                "current": current,
                "buyBoxSavingBasisType": "LIST_PRICE",
                "buyBoxSavingPercentage": 25,
                "buyBoxIsPrimeExclusive": True,
                "buyBoxIsPrimeEligible": True,
            },
        },
        site="US",
        domain_id=1,
    )

    assert formatted is not None
    assert formatted.main_fields["statsCurrentLightningDealPrice"] == 99.99
    assert (
        formatted.main_fields["statsCurrentLightningDealPriceSource"]
        == "STATS_CURRENT_8"
    )
    assert formatted.main_fields["statsCurrentPrimeExclusivePrice"] == 109.99
    assert (
        formatted.main_fields["statsCurrentPrimeExclusivePriceSource"]
        == "STATS_CURRENT_33"
    )
    assert formatted.main_fields["statsBuyBoxSavingBasisType"] == "LIST_PRICE"
    assert formatted.main_fields["statsBuyBoxSavingPercentage"] == 25
    assert formatted.main_fields["statsBuyBoxIsPrimeExclusive"] is True
    assert formatted.main_fields["statsBuyBoxIsPrimeEligible"] is True
    prime_row = next(
        row
        for row in formatted.price_type_rows
        if row["statField"] == "current" and row["priceTypeIndex"] == 33
    )
    assert prime_row["priceTypeName"] == "PRIME_EXCL"
    assert prime_row["formattedValue"] == 109.99


def test_stats_formatter_distinguishes_missing_and_never_lightning_info():
    missing = format_stats_for_product({"asin": "MISSING", "stats": {}}, site="US")
    never = format_stats_for_product(
        {"asin": "NEVER", "stats": {"lightningDealInfo": None}}, site="US"
    )

    assert missing is not None
    assert never is not None
    assert missing.main_fields["statsLightningDealStatus"] == "not_returned"
    assert missing.main_fields["statsHasLightningDealHistory"] is None
    assert never.main_fields["statsLightningDealStatus"] == "never"
    assert never.main_fields["statsHasLightningDealHistory"] is False
