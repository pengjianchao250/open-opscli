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


def test_fetch_category_top_traffic_allows_omitted_category_and_returns_funnel_data() -> None:
    class DummyTrafficClient(DummyTopClient):
        def fetch_traffic(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "success",
                "row_count": 1,
                "rows": [
                    {
                        "category": "3D Wall Panels",
                        "category_product_count": 47,
                        "top_product_count": 10,
                        "funnel_average": {"sessions": 1961, "page_views": 2834.2},
                    }
                ],
                "metadata": {
                    "category_filter": None,
                    "category_total": 3289,
                    "category_names": ["3D Wall Panels"],
                    "ranking_metric": "page_views",
                    "top_n": 10,
                },
            }

    top_client = DummyTrafficClient()
    service = AsinDataQueryService(
        top_client=top_client,
        today_factory=lambda: date(2026, 7, 27),
    )

    result = service.fetch_category_top(
        category=None,
        data_type="traffic",
        date_from="2026-07-01",
        date_to="2026-07-27",
    )

    assert result == {
        "data_type": "traffic",
        "category": None,
        "date_from": "2026-07-01",
        "date_to": "2026-07-27",
        "row_count": 1,
        "category_total": 3289,
        "category_names": ["3D Wall Panels"],
        "ranking_metric": "page_views",
        "top_n": 10,
        "category_traffic": [
            {
                "category": "3D Wall Panels",
                "category_product_count": 47,
                "top_product_count": 10,
                "funnel_average": {"sessions": 1961, "page_views": 2834.2},
            }
        ],
    }
    assert top_client.calls == [
        {
            "category": None,
            "date_from": "2026-07-01",
            "date_to": "2026-07-27",
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
    with pytest.raises(ValueError, match="必须传入 category"):
        service.fetch_category_top(category=None)
    with pytest.raises(ValueError, match="仅支持 asin 或 traffic"):
        service.fetch_category_top(category="Bed Frames", data_type="unknown")


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
