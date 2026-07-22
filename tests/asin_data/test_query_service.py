from datetime import date

import pytest

from opscli.asin_data.services.bi_report_data import BI_QUERY_SOURCE_KEYS
from opscli.asin_data.services.query_service import AsinDataQueryService


class DummyDataClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "success",
            "sources": {
                key: {
                    "key": key,
                    "status": "success",
                    "row_count": 1,
                    "rows": [{"ASIN": kwargs["asins"][0], "source": key}],
                }
                for key in kwargs["source_keys"]
            },
        }


class DummyTopClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "success",
            "row_count": 1,
            "rows": [{"排名": 1, "ASIN": "B086M58PQ3"}],
        }


def test_fetch_basic_normalizes_asins_and_maps_requested_sources() -> None:
    data_client = DummyDataClient()
    service = AsinDataQueryService(data_client=data_client)

    result = service.fetch_basic(
        asins=[" b086m58pq3 ", "B086M58PQ3"],
        site="us",
        sources=["listing"],
    )

    assert result["asins"] == ["B086M58PQ3"]
    assert result["site"] == "US"
    assert list(result["sources"]) == ["listing_basic"]
    assert data_client.calls[0]["source_keys"] == ("listing_basic",)
    assert data_client.calls[0]["site_by_asin"] == {"B086M58PQ3": "US"}


def test_fetch_bi_defaults_to_recent_30_days_and_all_domains() -> None:
    data_client = DummyDataClient()
    service = AsinDataQueryService(
        data_client=data_client,
        today_factory=lambda: date(2026, 7, 16),
    )

    result = service.fetch_bi(asins=["B086M58PQ3"], site="US")

    assert result["date_from"] == "2026-06-17"
    assert result["date_to"] == "2026-07-16"
    assert result["domains"] == list(BI_QUERY_SOURCE_KEYS)
    assert data_client.calls[0]["start_date"] == "2026-06-17"
    assert data_client.calls[0]["end_date"] == "2026-07-16"
    assert data_client.calls[0]["source_keys"] == BI_QUERY_SOURCE_KEYS


def test_fetch_category_top_uses_current_month_defaults_and_returns_only_rows() -> None:
    top_client = DummyTopClient()
    service = AsinDataQueryService(
        top_client=top_client,
        today_factory=lambda: date(2026, 7, 16),
    )

    result = service.fetch_category_top(category=" Bed Frames ", site="de", limit=10)

    assert result == {
        "category": "Bed Frames",
        "site": "DE",
        "date_from": "2026-07-01",
        "date_to": "2026-07-16",
        "limit": 10,
        "row_count": 1,
        "category_top": [{"排名": 1, "ASIN": "B086M58PQ3"}],
    }
    assert top_client.calls == [
        {
            "category": "Bed Frames",
            "site": "DE",
            "date_from": "2026-07-01",
            "date_to": "2026-07-16",
            "limit": 10,
        }
    ]


def test_query_service_rejects_invalid_asin_and_future_date() -> None:
    service = AsinDataQueryService(today_factory=lambda: date(2026, 7, 16))

    with pytest.raises(ValueError, match="ASIN"):
        service.fetch_basic(asins=["bad"], site="US")
    with pytest.raises(ValueError, match="未来"):
        service.fetch_bi(
            asins=["B086M58PQ3"],
            site="US",
            date_from="2026-07-01",
            date_to="2026-07-17",
        )


def test_query_service_rejects_unknown_site_source_and_domain() -> None:
    service = AsinDataQueryService()

    with pytest.raises(ValueError, match="站点"):
        service.fetch_basic(asins=["B086M58PQ3"], site="XX")
    with pytest.raises(ValueError, match="source"):
        service.fetch_basic(asins=["B086M58PQ3"], site="US", sources=["unknown"])
    with pytest.raises(ValueError, match="domain"):
        service.fetch_bi(asins=["B086M58PQ3"], site="US", domains=["unknown"])


def test_fetch_bi_accepts_sqp_domain() -> None:
    data_client = DummyDataClient()
    service = AsinDataQueryService(data_client=data_client)

    result = service.fetch_bi(
        asins=["B086M58PQ3"],
        site="US",
        date_from="2026-07-01",
        date_to="2026-07-15",
        domains=["sqp"],
    )

    assert result["domains"] == ["sqp"]
    assert data_client.calls[0]["source_keys"] == ("sqp",)
