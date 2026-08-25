from opscli.keepa.summary import summarize_rows


def test_product_summary_preserves_deal_and_price_contract():
    rows = [
        {
            "asin": "B0DP4L8HBB",
            "title": "Deal Product",
            "dealMetadataStatus": "available",
            "hasActiveDealMetadata": True,
            "dealTypesJoined": "LIMITED_TIME_DEAL",
            "dealBadgesJoined": "Limited time deal",
            "statsBuyBoxLandedPrice": 125.99,
            "statsBuyBoxSavingBasis": 139.99,
            "statsBuyBoxSavingBasisType": "WAS_PRICE",
            "statsBuyBoxSavingPercentage": 10,
            "dealAssociatedBuyBoxLandedPrice": 125.99,
            "dealAssociatedPriceStatus": "complete",
            "dealAssociatedPriceCurrency": "USD",
            "dealAssociatedPriceSource": "STATS_BUY_BOX_LANDED",
            "dealAssociatedPriceIsNativeDealPrice": False,
            "offersSuccessful": True,
            "currencyCode": "USD",
            "offers": [{"large": "nested data"}],
        }
    ]

    assert summarize_rows(rows, scenario="product") == [
        {
            "asin": "B0DP4L8HBB",
            "title": "Deal Product",
            "dealMetadataStatus": "available",
            "hasActiveDealMetadata": True,
            "dealTypesJoined": "LIMITED_TIME_DEAL",
            "dealBadgesJoined": "Limited time deal",
            "statsBuyBoxLandedPrice": 125.99,
            "statsBuyBoxSavingBasis": 139.99,
            "statsBuyBoxSavingBasisType": "WAS_PRICE",
            "statsBuyBoxSavingPercentage": 10,
            "dealAssociatedBuyBoxLandedPrice": 125.99,
            "dealAssociatedPriceStatus": "complete",
            "dealAssociatedPriceCurrency": "USD",
            "dealAssociatedPriceSource": "STATS_BUY_BOX_LANDED",
            "dealAssociatedPriceIsNativeDealPrice": False,
            "offersSuccessful": True,
            "currencyCode": "USD",
        }
    ]
