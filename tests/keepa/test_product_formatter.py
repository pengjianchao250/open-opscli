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


def test_product_formatter_splits_large_nested_fields_into_detail_sheets():
    formatted = format_product_export(
        [
            {
                "asin": "B000000001",
                "domainId": 1,
                "images": [
                    {"variant": "MAIN", "l": "main.jpg", "w": 1200, "h": 1200},
                    {"variant": "PT01", "l": "detail.jpg", "w": 1000, "h": 800},
                ],
                "categoryTree": [{"catId": 1, "name": "Root"}],
                "salesRanks": {"172282": [7588958, 123, 7589018, 100]},
                "offers": [
                    {
                        "offerId": 7,
                        "sellerId": "SELLER1",
                        "condition": 1,
                        "price": 1299,
                        "shipping": 200,
                        "coupon": -5,
                        "offerCSV": [7588958, 1299, 0],
                        "stockCSV": [7588958, 5],
                        "couponHistory": [7588958, -5],
                        "offerDuplicates": [{"price": 1299, "shipping": 0}],
                    }
                ],
                "variations": [
                    {
                        "asin": "B000000002",
                        "attributes": [
                            {"dimension": "Color", "value": "Black"},
                            {"dimension": "Size", "value": "Large"},
                        ],
                    }
                ],
                "csv": [[] for _ in range(36)],
                "stats": {"current": [-1] * 36},
                "features": ["Line one", "Line two"],
                "materials": ["Steel"],
                "monthlySoldHistory": [7588958, 100, 7589018, 200],
                "parentAsinHistory": [7588958, "B000000009"],
                "unitCount": {"unitValue": 2.0},
                "fbaFees": {"lastUpdate": 7588958, "pickAndPackFee": 343},
                "eanList": ["1234567890123"],
                "coupon": [100, -5],
                "couponHistory": [7588958, 100, -5],
                "videos": [{"title": "Demo", "url": "https://example.test/video"}],
                "promotions": [{"type": "SNS", "discountPercent": 5}],
                "historicalVariations": [
                    {"asin": "B000000003", "attributes": [{"dimension": "Color", "value": "Blue"}]}
                ],
                "reviews": {"reviewCount": 5, "images": ["review.jpg"]},
            }
        ],
        site="US",
    )

    product = formatted.products[0]
    for field in (
        "images",
        "categoryTree",
        "salesRanks",
        "offers",
        "variations",
        "csv",
        "stats",
        "features",
        "materials",
        "monthlySoldHistory",
        "parentAsinHistory",
        "unitCount",
        "fbaFees",
        "eanList",
        "coupon",
        "couponHistory",
        "videos",
        "promotions",
        "historicalVariations",
        "reviews",
    ):
        assert field not in product
    assert product["unitCountUnitValue"] == 2.0
    assert product["fbaPickAndPackFeeAmount"] == 3.43
    assert product["eanListJoined"] == "1234567890123"
    assert not any(isinstance(value, (dict, list)) for value in product.values())
    assert formatted.images[0]["variant"] == "MAIN"
    assert formatted.images[0]["imageUrl"].endswith("/main.jpg")
    assert formatted.category_tree[0]["catId"] == "1"
    assert formatted.sales_ranks[1]["salesRank"] == 100
    assert formatted.offers[0]["offerId"] == 7
    assert formatted.offers[0]["conditionText"] == "new"
    assert formatted.offers[0]["priceAmount"] == 12.99
    assert formatted.offers[0]["shippingAmount"] == 2.0
    assert formatted.offers[0]["couponPercent"] == 5
    assert "offer" not in formatted.offers[0]
    assert formatted.offer_history[0]["priceAmount"] == 12.99
    assert formatted.offer_history[1]["stock"] == 5
    offer_coupon = next(row for row in formatted.offer_history if row["historyType"] == "coupon")
    assert offer_coupon["couponPercent"] == 5
    assert formatted.offer_duplicates[0]["priceAmount"] == 12.99
    assert formatted.variation_attributes[0]["dimension"] == "Color"
    assert "variation" not in formatted.variations[0]
    feature_rows = [row for row in formatted.list_values if row["field"] == "features"]
    assert feature_rows[0]["value"] == "Line one"
    assert formatted.product_history[1]["value"] == 200
    assert formatted.product_history[2]["field"] == "parentAsinHistory"
    coupon_rows = [row for row in formatted.product_history if row["field"] == "couponHistory"]
    assert coupon_rows[0]["oneTimeCouponAmount"] == 1.0
    assert coupon_rows[0]["snsCouponPercent"] == 5
    nested_paths = {row["path"] for row in formatted.nested_values}
    assert "promotions[0].discountPercent" in nested_paths
    assert "videos[0].url" in nested_paths
    assert "historicalVariations[0].attributes[0].value" in nested_paths
    assert "reviews.images[0]" in nested_paths
