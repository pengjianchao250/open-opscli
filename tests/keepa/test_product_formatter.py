from opscli.keepa.product_formatter import format_product_export


def test_product_formatter_derives_money_time_stats_and_csv_history():
    csv = [[] for _ in range(36)]
    csv[0] = [7588958, 1299]
    csv[7] = [7588958, 1099, 200]
    csv[16] = [7588958, 45]
    current = [-1] * 36
    current[0] = 1599
    current[16] = 46
    current[17] = 123

    formatted = format_product_export(
        [
            {
                "asin": "B0088PUEPK",
                "domainId": 1,
                "title": "Test Product",
                "lastUpdate": 7588958,
                "competitivePriceThreshold": 1299,
                "packageWeight": 500,
                "publicationDate": 20240131,
                "imagesCSV": "abc.jpg,def.jpg",
                "categoryTree": [{"catId": 1, "name": "Root"}, {"catId": 2, "name": "Leaf"}],
                "stats": {"current": current},
                "csv": csv,
            }
        ],
        site="US",
        domain_id=1,
    )

    product = formatted.products[0]
    assert product["lastUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert product["competitivePriceThresholdAmount"] == 12.99
    assert product["packageWeightKg"] == 0.5
    assert product["publicationDateFormatted"] == "2024-01-31"
    assert product["mainImageUrl"] == "https://m.media-amazon.com/images/I/abc.jpg"
    assert product["categoryPathName"] == "Root > Leaf"
    assert product["currentAmazonPrice"] == 15.99
    assert product["currentRating"] == 4.6
    assert product["currentReviewCount"] == 123

    amazon_rows = [row for row in formatted.csv_history if row["csvName"] == "AMAZON"]
    shipping_rows = [row for row in formatted.csv_history if row["csvName"] == "NEW_FBM_SHIPPING"]
    rating_rows = [row for row in formatted.csv_history if row["csvName"] == "RATING"]

    assert amazon_rows[0]["priceAmount"] == 12.99
    assert shipping_rows[0]["priceAmount"] == 10.99
    assert shipping_rows[0]["shippingAmount"] == 2.0
    assert rating_rows[0]["rating"] == 4.5
