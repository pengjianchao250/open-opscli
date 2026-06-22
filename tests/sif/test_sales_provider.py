import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.domain.models import SifSalesApiResult
from opscli.sif.sales.models import SifSalesRunRequest
from opscli.sif.sales.provider import SifSalesProvider


class FakeSifClient:
    expected_site = "US"
    last_kwargs = None

    def fetch_sales(self, *, asin: str, site: str, range_value: str | None = None, **kwargs):
        assert asin == "B01NBNDC1T"
        assert site == self.expected_site
        self.last_kwargs = kwargs
        return SifSalesApiResult(
            listing_history={
                "data": {
                    "variantSales": [
                        {
                            "asin": "B01NBNDC1T",
                            "name": "main",
                            "points": [{"date": "2026-01", "sales": 10000}],
                        }
                    ],
                    "colorSales": [],
                    "sizeSales": [],
                }
            },
            group_variants={
                "data": {
                    "asin": [
                        {
                            "asin": "B01NBNDC1T",
                            "title": "Demo",
                            "recent30dSales": "10,000+",
                        }
                    ]
                }
            },
            listing_history_xlsx=b"listing-history-xlsx",
            bought_by_asin_xlsx=b"bought-by-asin-xlsx",
        )


def test_sif_provider_writes_expected_files():
    output_dir = Path("output") / "test-artifacts" / f"sif-provider-{uuid4().hex}"
    provider = SifSalesProvider(client=FakeSifClient())

    result = provider.run(
        SifSalesRunRequest(
            feature="查销量",
            provider="sif",
            asin="B01NBNDC1T",
            site="US",
            output_dir=str(output_dir),
            job_id="job-sif",
        ),
        default_output_dir=output_dir,
    )

    root = output_dir / "job-sif"
    assert result.job_id == "job-sif"
    assert (root / "params.json").exists()
    assert (root / "raw.json").exists()
    assert (root / "result.json").exists()
    assert len(list(root.glob("boughtListingHistory_B01NBNDC1T_*.xlsx"))) == 1
    assert len(list(root.glob("boughtByAsin_B01NBNDC1T_*.xlsx"))) == 1

    payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sif_sales.v1"
    assert payload["listing_history"]["variant_sales"][0]["asin"] == "B01NBNDC1T"
    assert payload["group_variants"][0]["recent_30d_sales_text"] == "10,000+"


def test_sif_provider_normalizes_sales_site_aliases():
    output_dir = Path("output") / "test-artifacts" / f"sif-provider-site-{uuid4().hex}"
    fake_client = FakeSifClient()
    fake_client.expected_site = "UK"
    provider = SifSalesProvider(client=fake_client)

    result = provider.run(
        SifSalesRunRequest(
            feature="查销量",
            provider="sif",
            asin="B01NBNDC1T",
            site="英国站",
            output_dir=str(output_dir),
            job_id="job-sif",
        ),
        default_output_dir=output_dir,
    )

    assert result.site == "UK"


def test_sif_provider_sections_download_only_listing_history():
    output_dir = Path("output") / "test-artifacts" / f"sif-provider-section-{uuid4().hex}"
    fake_client = FakeSifClient()
    provider = SifSalesProvider(client=fake_client)

    result = provider.run(
        SifSalesRunRequest(
            feature="查销量",
            provider="sif",
            asin="B01NBNDC1T",
            site="US",
            sections=["不同变体销量"],
            output_dir=str(output_dir),
            job_id="job-sif",
        ),
        default_output_dir=output_dir,
    )

    assert list(result.exports) == ["listing_history_xlsx"]
    assert fake_client.last_kwargs["download_listing_history"] is True
    assert fake_client.last_kwargs["download_bought_by_asin"] is False


def test_sif_provider_params_do_not_include_sensitive_cookie():
    output_dir = Path("output") / "test-artifacts" / f"sif-provider-sensitive-{uuid4().hex}"
    provider = SifSalesProvider(client=FakeSifClient())

    provider.run(
        SifSalesRunRequest(
            feature="查销量",
            provider="sif",
            asin="B01NBNDC1T",
            site="US",
            output_dir=str(output_dir),
            job_id="job-sif",
            params={"safe": "value"},
            sif_username="user",
            sif_password="secret",
        ),
        default_output_dir=output_dir,
    )

    params_text = (output_dir / "job-sif" / "params.json").read_text(encoding="utf-8")
    assert "cookie" not in params_text.lower()
    assert "password" not in params_text.lower()
    assert "secret" not in params_text
    assert "user" not in params_text
