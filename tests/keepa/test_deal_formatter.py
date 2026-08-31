from opscli.keepa.deal_formatter import format_deal_export


def test_deal_formatter_derives_main_fields_and_metric_rows():
    image_name = "abc.jpg"
    formatted = format_deal_export(
        [
            {
                "asin": "B0088PUEPK",
                "title": "<b>Deal Product</b>",
                "rootCat": 172282,
                "categories": [172282, 541966],
                "image": [ord(char) for char in image_name],
                "lastUpdate": 7588958,
                "creationDate": 7588958,
                "lightningEnd": 7588960,
                "warehouseCondition": 3,
                "current": [1299, 1399, -1, 12345]
                + [-1] * 4
                + [1099]
                + [-1] * 7
                + [45, 456, 1499]
                + [-1] * 14
                + [1199],
                "currentSince": [7588958, 7588959],
                "deltaLast": [-100, -200, -1, 500],
                "delta": [[-100, -200, -1, 500]],
                "deltaPercent": [[-8, -10, -2, 5]],
                "avg": [[1499, 1599, -1, 13000]],
            }
        ],
        site="US",
        domain_id=1,
    )

    deal = formatted.deals[0]
    assert deal["titleText"] == "Deal Product"
    assert deal["rootCatText"] == "172282"
    assert deal["categoryIds"] == "172282, 541966"
    assert deal["imageName"] == "abc.jpg"
    assert deal["imageUrl"] == "https://images-na.ssl-images-amazon.com/images/I/abc.jpg"
    assert deal["lastUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert deal["creationDateUtc"] == "2025-06-06T02:38:00Z"
    assert deal["lightningEndUtc"] == "2025-06-06T02:40:00Z"
    assert deal["isLightningDeal"] is True
    assert deal["warehouseConditionText"] == "used_very_good"
    assert deal["currentAmazonPrice"] == 12.99
    assert deal["currentNewPrice"] == 13.99
    assert deal["currentSalesRank"] == 12345
    assert deal["currentRating"] == 4.5
    assert deal["currentReviewCount"] == 456
    assert deal["currentBuyBoxPrice"] == 14.99
    assert deal["currentLightningDealPrice"] == 10.99
    assert deal["currentPrimeExclusivePrice"] == 11.99
    assert deal["dealRaw"]["asin"] == "B0088PUEPK"

    current_since = next(
        row
        for row in formatted.metric_rows
        if row["metric"] == "currentSince" and row["priceTypeIndex"] == 0
    )
    assert current_since["formattedValue"] == "2025-06-06T02:38:00Z"
    assert current_since["valueKind"] == "time"

    delta = next(
        row
        for row in formatted.metric_rows
        if row["metric"] == "delta" and row["dateRangeName"] == "day" and row["priceTypeIndex"] == 0
    )
    assert delta["formattedValue"] == -1
    assert delta["currency"] == "USD"

    percent = next(
        row
        for row in formatted.metric_rows
        if row["metric"] == "deltaPercent" and row["priceTypeIndex"] == 3
    )
    assert percent["formattedValue"] == 5
    assert percent["valueKind"] == "percent"
    missing_percent = next(
        row
        for row in formatted.metric_rows
        if row["metric"] == "deltaPercent" and row["priceTypeIndex"] == 2
    )
    assert missing_percent["formattedValue"] is None
