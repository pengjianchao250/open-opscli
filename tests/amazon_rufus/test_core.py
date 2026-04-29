import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opscli.amazon_rufus.cli import app
from opscli.amazon_rufus.domain.exceptions import QuestionBankNotReadyError, UnsupportedMarketplaceError
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace
from opscli.amazon_rufus.services.browser import BrowserAttachService
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.parser import RufusParserService
from opscli.amazon_rufus.services.question_bank import QuestionBankService


runner = CliRunner()


def test_country_map_resolves_us_product_url():
    marketplace = resolve_marketplace("US")

    assert marketplace.country == "US"
    assert marketplace.base_url == "https://www.amazon.com"
    assert build_product_url("B0TEST1234", "US") == "https://www.amazon.com/dp/B0TEST1234"


def test_country_map_rejects_unknown_country():
    with pytest.raises(UnsupportedMarketplaceError):
        resolve_marketplace("FR")


def test_question_bank_loads_merged_templates(tmp_path: Path):
    data_dir = tmp_path / "ops-amazon-rufus" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "question_templates.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": 56,
                        "description": "测试",
                        "preferred_version_index": 0,
                        "questions": [
                            {"id": 3172, "text": "问题1", "position": 2},
                            {"id": 3171, "text": "问题0", "position": 1},
                        ],
                        "created_at": "2026-04-28T09:25:05",
                        "updated_at": "2026-04-28T09:25:12",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bank = QuestionBankService(skills_dir=str(tmp_path))
    templates = bank.load_templates()

    assert templates[0].id == 56
    assert [item.text for item in templates[0].questions] == ["问题0", "问题1"]


def test_question_bank_missing_file_raises_actionable_error(tmp_path: Path):
    bank = QuestionBankService(skills_dir=str(tmp_path))

    with pytest.raises(QuestionBankNotReadyError) as exc:
        bank.load_templates()

    assert "opscli skills install ops-amazon-rufus" in str(exc.value)
    assert "opscli skills upgrade ops-amazon-rufus" in str(exc.value)


def test_parser_extracts_text_from_sse_inference_event():
    raw = '\n'.join([
        'event: inference',
        'data: {"answer":"hello","conversation_metadata":{"threadId":"thread-1"}}',
        '',
        'event: close',
        'data: {}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "hello"
    assert answer.thread_id == "thread-1"
    assert answer.is_success is True


def test_manager_builds_upload_payload_with_questions(tmp_path: Path):
    manager = RufusManager()
    questions = ["问题0", "问题1"]

    payload = manager.build_upload_payload(
        asin="b0test1234",
        country="US",
        request_url="https://www.amazon.com/rufus/cl/streaming",
        request_body={"seed": True},
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        questions=questions,
        captured_at=1710000000000,
    )

    record = payload["records"][0]
    assert record["asin"] == "B0TEST1234"
    assert record["country"] == "US"
    assert record["businessType"] == "asin_rufus_cli"
    assert [item["question"] for item in record["questions"]] == questions


def test_browser_capture_opens_dedicated_tab_and_brings_to_front(monkeypatch):
    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
        post_data = '{"tabId":"tab-1"}'
        headers = {"content-type": "application/json"}

    class FakePage:
        def __init__(self) -> None:
            self.url = "about:blank"
            self.handler = None
            self.brought_to_front = False

        def on(self, event, handler):
            self.handler = handler

        def goto(self, url, wait_until, timeout):
            self.url = url
            if self.handler:
                self.handler(FakeRequest())

        def wait_for_timeout(self, timeout):
            return None

        def bring_to_front(self):
            self.brought_to_front = True

    class FakeContext:
        def __init__(self) -> None:
            self.pages = [FakePage()]
            self.created_page = None

        def new_page(self):
            self.created_page = FakePage()
            return self.created_page

    fake_context = FakeContext()

    class FakeBrowser:
        contexts = [fake_context]

    class FakeChromium:
        def connect_over_cdp(self, cdp_url):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    service = BrowserAttachService()

    seed = service.capture_seed_request(
        asin="B0TEST1234",
        country="US",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        cdp_url="http://127.0.0.1:9222",
        timeout_seconds=1,
    )

    assert fake_context.created_page is not None
    assert fake_context.created_page.brought_to_front is True
    assert fake_context.created_page.url == "https://www.amazon.com/dp/B0TEST1234"
    assert service.current_page is fake_context.created_page
    assert seed.tab_id == "tab-1"


def test_browser_capture_starts_new_chrome_before_connecting(monkeypatch):
    calls = []

    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
        post_data = '{"tabId":"tab-1"}'
        headers = {"content-type": "application/json"}

    class FakePage:
        url = "about:blank"

        def on(self, event, handler):
            self.handler = handler

        def goto(self, url, wait_until, timeout):
            self.url = url
            self.handler(FakeRequest())

        def wait_for_timeout(self, timeout):
            return None

        def bring_to_front(self):
            return None

    class FakeContext:
        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, cdp_url):
            calls.append(("connect", cdp_url))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    service = BrowserAttachService()
    monkeypatch.setattr(service, "_start_new_chrome", lambda: calls.append(("start", None)))
    monkeypatch.setattr(service, "_wait_for_cdp", lambda cdp_url, timeout_seconds: calls.append(("wait", cdp_url)))

    service.capture_seed_request(
        asin="B0TEST1234",
        country="US",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        cdp_url="http://127.0.0.1:9222",
        timeout_seconds=1,
        new_chrome=True,
    )

    assert calls[:3] == [
        ("start", None),
        ("wait", "http://127.0.0.1:9222"),
        ("connect", "http://127.0.0.1:9222"),
    ]


def test_cli_get_outputs_manager_result(monkeypatch):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {"asin": kwargs["asin"], "country": kwargs["country"], "answers": []}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "amazon-rufus get"
    assert payload["data"] == {"asin": "B0TEST1234", "country": "US", "answers": []}
    assert captured["new_chrome"] is False


def test_cli_get_passes_new_chrome(monkeypatch):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {"asin": kwargs["asin"], "country": kwargs["country"], "answers": []}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(app, ["get", "B0TEST1234", "US", "--new-chrome"])

    assert result.exit_code == 0
    assert captured["new_chrome"] is True


def test_manager_get_uses_question_bank_browser_and_replay():
    from opscli.amazon_rufus.domain.models import AnswerData, Question, QuestionTemplate, SeedRequestRecord

    class FakeQuestionBank:
        def load_templates(self):
            return [QuestionTemplate(id=1, description="默认", preferred_version_index=0, questions=[Question(id=1, text="问题1", position=1)])]

    class FakeBrowser:
        def capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return SeedRequestRecord(
                request_url="https://www.amazon.com/rufus/cl/streaming",
                request_headers={},
                request_body='{"queryContext": {}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeReplay:
        def replay(self, seed, questions):
            return [AnswerData(text=f"answer:{questions[0]}", thread_id="thread-1")]

    fake_browser = FakeBrowser()
    manager = RufusManager(question_bank=FakeQuestionBank(), browser=fake_browser, replay=FakeReplay())

    result = manager.get(asin="b0test1234", country="US", new_chrome=True)

    assert result["answers"][0]["text"] == "answer:问题1"
    assert result["question_count"] == 1
    assert result["upload_payload"]["records"][0]["questions"][0]["question"] == "问题1"
    assert fake_browser.kwargs["new_chrome"] is True
