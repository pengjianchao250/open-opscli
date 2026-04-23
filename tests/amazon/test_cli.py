import json

from typer.testing import CliRunner

from opscli.amazon.cli import app


runner = CliRunner()


def test_scrape_outputs_doc_aligned_json(monkeypatch):
    class DummyCollectResult:
        def to_dict(self, *, include_raw=False):
            return {
                "snapshot": {"asin": "B0TEST1234", "product_name": "Sample Product"},
                "history_path": "/tmp/history.jsonl",
                "submit_result": None,
            }

    class DummyManager:
        def scrape_product(self, **kwargs):
            return DummyCollectResult()

    monkeypatch.setattr("opscli.amazon.commands.cli.AmazonManager", lambda: DummyManager())

    result = runner.invoke(app, ["scrape", "--asin", "B0TEST1234"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "amazon scrape"
    assert payload["data"]["snapshot"]["asin"] == "B0TEST1234"


def test_search_outputs_doc_aligned_json(monkeypatch):
    class DummyResult:
        def to_dict(self):
            return {"asin": "B0TEST1234", "title": "Sample Product"}

    class DummyManager:
        def search_products(self, **kwargs):
            return [DummyResult()]

    monkeypatch.setattr("opscli.amazon.commands.cli.AmazonManager", lambda: DummyManager())

    result = runner.invoke(app, ["search", "--keyword", "pool vacuum"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "amazon search"
    assert payload["data"]["count"] == 1


def test_history_outputs_doc_aligned_json(monkeypatch):
    class DummyManager:
        def load_history(self, asin):
            return [{"asin": asin, "price_text": "$19.99"}]

    monkeypatch.setattr("opscli.amazon.commands.cli.AmazonManager", lambda: DummyManager())

    result = runner.invoke(app, ["history", "--asin", "B0TEST1234"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"]["count"] == 1


def test_payload_outputs_reserved_submit_shape(monkeypatch):
    class DummyManager:
        def scrape_payload(self, **kwargs):
            return {
                "payload": {
                    "source": "opscli.amazon",
                    "snapshot": {"asin": "B0TEST1234"},
                },
                "history_path": "/tmp/history.jsonl",
            }

    monkeypatch.setattr("opscli.amazon.commands.cli.AmazonManager", lambda: DummyManager())

    result = runner.invoke(app, ["payload", "--asin", "B0TEST1234"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "amazon payload"
    assert payload["data"]["payload"]["snapshot"]["asin"] == "B0TEST1234"


def test_schema_outputs_field_contract():
    result = runner.invoke(app, ["schema"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "amazon schema"
    assert payload["data"]["snapshot_fields"]["asin"] == "string"


def test_scrape_outputs_error_payload(monkeypatch):
    class DummyManager:
        def scrape_product(self, **kwargs):
            raise ValueError("boom")

    monkeypatch.setattr("opscli.amazon.commands.cli.AmazonManager", lambda: DummyManager())

    result = runner.invoke(app, ["scrape", "--asin", "B0TEST1234"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["error"]["message"] == "boom"
