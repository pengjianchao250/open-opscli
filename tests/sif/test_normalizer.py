from opscli.sif.sales.normalizer import SifSalesNormalizer


def test_normalizer_builds_stable_shape():
    result = SifSalesNormalizer().normalize(
        asin="b01nbndc1t",
        site="us",
        range_value=None,
        listing_history={
            "data": {
                "variantSales": [
                    {
                        "asin": "B01NBNDC1T",
                        "points": [{"x": "2026-01", "y": 100}],
                    }
                ]
            }
        },
        group_variants={"data": {"asin": [{"childAsin": "B07TEST123", "sales": 9000}]}},
        exports={},
    )

    assert result["schema_version"] == "sif_sales.v1"
    assert result["asin"] == "B01NBNDC1T"
    assert result["site"] == "US"
    assert result["listing_history"]["variant_sales"][0]["points"][0]["sales"] == 100
    assert result["group_variants"][0]["asin"] == "B07TEST123"

