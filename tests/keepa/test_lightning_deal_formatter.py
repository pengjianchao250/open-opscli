from opscli.keepa.lightning_deal_formatter import format_lightning_deal_export


def test_lightning_deal_formatter_derives_values_and_splits_variations():
    formatted = format_lightning_deal_export(
        [
            {
                "domainId": 1,
                "asin": "B000000001",
                "dealId": "deal-1",
                "dealPrice": 1299,
                "currentPrice": 1999,
                "lastUpdate": 7588958,
                "startTime": 7589018,
                "endTime": 7589078,
                "rating": 45,
                "image": "abc.jpg",
                "dealState": "ACTIVE",
                "percentClaimed": 42,
                "percentOff": 35,
                "variation": [
                    {"dimension": "Size", "value": "Large"},
                    {"dimension": "Color", "value": "Red"},
                ],
            }
        ],
        site="US",
    )

    deal = formatted.deals[0]
    assert deal["dealPriceAmount"] == 12.99
    assert deal["currentPriceAmount"] == 19.99
    assert deal["calculatedDiscountPercent"] == 35.02
    assert deal["durationMinutes"] == 60
    assert deal["durationHours"] == 1.0
    assert deal["percentOffDisplay"] == "35%"
    assert deal["ratingStars"] == 4.5
    assert deal["imageUrl"] == "https://m.media-amazon.com/images/I/abc.jpg"
    assert deal["variationCount"] == 2
    assert "variation" not in deal
    assert formatted.variations[1]["dimension"] == "Color"
