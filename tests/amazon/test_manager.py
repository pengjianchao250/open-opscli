import json

from opscli.amazon.manager import AmazonManager
from opscli.amazon.models import AmazonProductSnapshot, AmazonSearchResult


class DummyScraper:
    def scrape_product(self, asin: str, zip_code: str = "10001") -> AmazonProductSnapshot:
        return AmazonProductSnapshot(
            asin=asin,
            zip_code=zip_code,
            marketplace="amazon.com",
            page_url=f"https://www.amazon.com/dp/{asin}",
            page_title="Sample",
            product_name="Sample Product",
            price_text="$19.99",
            price_amount=19.99,
            currency="USD",
            rating_text="4.6 out of 5 stars",
            rating_value=4.6,
            review_count_text="1,234 ratings",
            review_count_value=1234,
            location="New York 10001",
            collected_at="2026-04-23 10:00:00",
            valid=True,
            raw={"foo": "bar"},
        )

    def search_products(self, keyword: str, *, max_results: int = 10, zip_code: str = "10001") -> list[AmazonSearchResult]:
        return [
            AmazonSearchResult(
                asin="B0TEST1234",
                keyword=keyword,
                zip_code=zip_code,
                rank=1,
                title="Sample Product",
                price_text="$19.99",
                price_amount=19.99,
                rating_text="4.6 out of 5 stars",
                rating_value=4.6,
                review_count_text="1,234 ratings",
                review_count_value=1234,
                is_best_seller=True,
            )
        ][:max_results]


class DummyClient:
    def __init__(self):
        self.submitted = None
        self.endpoint = None

    def submit_snapshot(self, snapshot, *, endpoint=None):
        self.submitted = snapshot
        self.endpoint = endpoint
        return {"code": 200, "message": "ok"}


def test_scrape_product_appends_history(tmp_path):
    manager = AmazonManager(base_dir=tmp_path, scraper=DummyScraper(), client=DummyClient())

    result = manager.scrape_product(asin="B0TEST1234", zip_code="10001")

    assert result.history_path is not None
    lines = result.history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["asin"] == "B0TEST1234"


def test_scrape_and_submit_uses_client(tmp_path):
    client = DummyClient()
    manager = AmazonManager(base_dir=tmp_path, scraper=DummyScraper(), client=client)

    result = manager.scrape_and_submit(
        asin="B0TEST1234",
        zip_code="10001",
        endpoint="/v1/amazon/collect",
    )

    assert result.submit_result == {"code": 200, "message": "ok"}
    assert client.submitted.asin == "B0TEST1234"
    assert client.endpoint == "/v1/amazon/collect"


def test_load_history_reads_jsonl(tmp_path):
    manager = AmazonManager(base_dir=tmp_path, scraper=DummyScraper(), client=DummyClient())
    history_dir = tmp_path / "amazon" / "history"
    history_dir.mkdir(parents=True)
    history_file = history_dir / "B0TEST1234.jsonl"
    history_file.write_text(
        '{"asin":"B0TEST1234","price_text":"$19.99"}\n{"asin":"B0TEST1234","price_text":"$18.99"}\n',
        encoding="utf-8",
    )

    records = manager.load_history("B0TEST1234")

    assert len(records) == 2
    assert records[1]["price_text"] == "$18.99"


def test_search_products_forwards_limit_and_zip_code(tmp_path):
    scraper = DummyScraper()
    manager = AmazonManager(base_dir=tmp_path, scraper=scraper, client=DummyClient())

    results = manager.search_products(keyword="pool vacuum", zip_code="30301", limit=1)

    assert len(results) == 1
    assert results[0].zip_code == "30301"


def test_scrape_payload_returns_reserved_submit_shape(tmp_path):
    manager = AmazonManager(base_dir=tmp_path, scraper=DummyScraper(), client=DummyClient())

    result = manager.scrape_payload(asin="B0TEST1234", zip_code="10001")

    assert result["payload"]["source"] == "opscli.amazon"
    assert result["payload"]["snapshot"]["asin"] == "B0TEST1234"
    assert result["history_path"].endswith("B0TEST1234.jsonl")
