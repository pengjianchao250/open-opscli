from opscli.keepa.seller_formatter import format_seller_export


def test_seller_formatter_splits_ratings_histories_and_storefront_details():
    formatted = format_seller_export(
        [
            {
                "domainId": 1,
                "sellerId": "A2L77EE7U53NWQ",
                "sellerName": "Example Store",
                "trackingSince": 7588958,
                "lastUpdate": 7589018,
                "lastRatingUpdate": 7589078,
                "address": ["123 Main Street", "New York", "US"],
                "customerServicesAddress": ["Support", "US"],
                "ratingCount": [3, 10, 98, 321],
                "positiveRating": [96, 98, 98, 95],
                "neutralRating": [1, 1, 1, 2],
                "negativeRating": [3, 1, 1, 3],
                "recentFeedback": [{"date": 7588958, "rating": 50, "isStriked": False}],
                "csv": [[7588958, 95], [7588958, 321]],
                "asinList": ["B000000001", "B000000002"],
                "asinListLastSeen": [7588958, 7589018],
                "totalStorefrontAsins": [7589018, 1200],
                "sellerCategoryStatistics": [{"catId": 281052, "productCount": 214}],
                "sellerBrandStatistics": [{"brand": "sony", "productCount": 45}],
                "competitors": [{"sellerId": "COMPETITOR1", "percent": 34}],
            }
        ],
        site="US",
    )

    seller = formatted.sellers[0]
    assert seller["addressText"] == "123 Main Street | New York | US"
    assert seller["totalStorefrontAsinCount"] == 1200
    assert seller["rating30DaysCount"] == 3
    assert "recentFeedback" not in seller
    assert "asinList" not in seller
    assert "address" not in seller
    assert "customerServicesAddress" not in seller
    assert not any(isinstance(value, (dict, list)) for value in seller.values())
    assert formatted.ratings[3]["window"] == "lifetime"
    assert formatted.rating_history[0]["ratingPercent"] == 95
    assert formatted.feedback[0]["ratingStars"] == 5.0
    assert formatted.storefront[1]["asin"] == "B000000002"
    assert formatted.categories[0]["catId"] == "281052"
    assert formatted.brands[0]["brand"] == "sony"
    assert formatted.competitors[0]["competitorSellerId"] == "COMPETITOR1"
