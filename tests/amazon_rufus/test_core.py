import json
import re
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
from opscli.amazon_rufus.services.replay import RufusReplayService


runner = CliRunner()


def _read_single_rufus_report(tmp_path: Path) -> tuple[Path, str]:
    """读取单次 CLI 测试生成的 Rufus 报告文件。"""
    report_files = list((tmp_path / "output" / "amazon-rufus").glob("*.md"))
    assert len(report_files) == 1
    return report_files[0], report_files[0].read_text(encoding="utf-8")


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


def test_question_bank_rejects_empty_items(tmp_path: Path):
    # 空题库会导致 get 静默输出 0 个问题，必须提前失败。
    data_dir = tmp_path / "ops-amazon-rufus" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "question_templates.json").write_text('{"items": []}', encoding="utf-8")

    bank = QuestionBankService(skills_dir=str(tmp_path))

    with pytest.raises(QuestionBankNotReadyError) as exc:
        bank.load_templates()

    assert "题库为空" in str(exc.value)


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


def test_parser_extracts_html_sections_and_top_level_thread_id():
    raw = '\n'.join([
        'event: conversation_metadata',
        'data: {"threadId":"thread-1"}',
        '',
        'event: message',
        'data: {"sections":[{"content":{"format":"HTML","data":"<div>Hello <b>Rufus</b></div>"}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "Hello Rufus"
    assert answer.html == '<div>Hello <b>Rufus</b></div>'
    assert answer.thread_id == "thread-1"
    assert answer.is_success is True


def test_parser_reconstructs_text_from_streaming_json_patches():
    raw = '\n'.join([
        'event: conversation_metadata',
        'data: {"threadId":"thread-1"}',
        '',
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"add","path":"/","groupId":"markdown_processor_1","value":{"type":"container","children":[]}}]}',
        '',
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"replace","path":"/","groupId":"markdown_processor_1","value":{"type":"container","children":[{"type":"text","children":[{"type":"text","children":"这是 "},{"type":"link","children":"Aiheal 电动鹅颈壶温度控制款","onPress":{"url":"https://www.amazon.com/dp/B0B1MLVMY5"}},{"type":"text","children":" — 高端电热水壶。"}]}]}}]}',
        '',
        'event: inference',
        'data: {"sections":[{"content":{"format":"HTML","data":"<div>容量和尺寸如何？</div>"}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "这是 Aiheal 电动鹅颈壶温度控制款 — 高端电热水壶。"
    assert answer.summary_text == answer.text
    assert answer.product_links == ["https://www.amazon.com/dp/B0B1MLVMY5"]
    assert answer.thread_id == "thread-1"
    assert answer.is_success is True


def test_parser_extracts_text_template_json_patches():
    raw = '\n'.join([
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"add","path":"/","groupId":"text_template_summary_1","value":{"type":"text","children":[{"type":"text","children":"总结 A"},{"type":"text","children":"，总结 B"}]}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "总结 A，总结 B"
    assert answer.summary_text == "总结 A，总结 B"
    assert answer.is_success is True


def test_parser_applies_json_patch_remove_operations():
    raw = '\n'.join([
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"add","path":"/","groupId":"markdown_processor_1","value":{"type":"container","children":[{"type":"text","children":"保留"},{"type":"text","children":"删除"}]}}]}',
        '',
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"remove","path":"/children/1","groupId":"markdown_processor_1"}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "保留"


def test_parser_renders_copy_template_text_and_recommended_asins():
    raw = '\n'.join([
        'event: inference',
        'data: {"type":"JSONPatches","patches":[{"op":"add","path":"/","groupId":"markdown_processor_1","value":{"type":"container","children":[{"type":"text","copyTemplate":{"prefix":"推荐：","suffix":"。"},"children":[{"type":"link","children":"竞品壶","onPress":{"url":"https://www.amazon.com/dp/B0ABC12345?th=1"}}]}]}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "推荐：竞品壶。"
    assert answer.product_links == ["https://www.amazon.com/dp/B0ABC12345?th=1"]
    assert answer.recommended_asins == ["B0ABC12345"]


def test_parser_extracts_review_aspect_flow_summary():
    raw = '\n'.join([
        'event: inference',
        'data: {"sections":[{"target":{"type":"ReviewAspectFlow","groupId":"review-1"},"content":{"format":"HTML","data":"<div data-section-class=\\"ReviewAspectFlow\\"><span data-testid=\\"overall-summary\\">买家普遍认为温控准确，外观高级。</span><span data-testid=\\"aspect-summary\\">手柄隔热表现好。</span></div>"}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.text == "买家普遍认为温控准确，外观高级。"
    assert answer.blocks == [{"type": "paragraph", "text": "买家普遍认为温控准确，外观高级。"}]
    assert answer.is_success is True


def test_parser_extracts_asin_faceout_list_and_footer_cards():
    raw = '\n'.join([
        'event: inference',
        'data: {"sections":[{"target":{"type":"AsinFaceoutList","groupId":"faceout-1"},"content":{"format":"HTML","data":"<div data-section-class=\\"AsinFaceoutList\\"><a href=\\"/dp/B0ABC12345\\"><h2 aria-label=\\"竞品电热水壶\\">ignored</h2></a></div>"}}]}',
        '',
        'event: inference',
        'data: {"sections":[{"target":{"type":"AsinFaceoutFooter","groupId":"faceout-1_asinFooter"},"content":{"format":"HTML","data":"<div data-section-class=\\"AsinFaceoutFooter\\">温控稳定，适合手冲咖啡。 More details B0ABC12345</div>"}}]}',
        '',
    ])

    answer = RufusParserService().parse(raw)

    assert answer.recommended_asins == [
        {
            "asin": "B0ABC12345",
            "title": "竞品电热水壶",
            "href": "https://www.amazon.com/dp/B0ABC12345",
            "source": "AsinFaceoutList",
            "description": "温控稳定，适合手冲咖啡。",
        }
    ]


def test_answer_report_formatter_prefers_structured_blocks_and_related_sections():
    from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter

    report = AnswerReportFormatter().format_data(
        {
            "asin": "B0TEST1234",
            "country": "US",
            "page_url": "https://www.amazon.com/dp/B0TEST1234",
            "answers": [
                {
                    "text": "fallback text should not appear",
                    "isSuccess": True,
                    "productLinks": [
                        {
                            "asin": "B0LINK1234",
                            "title": "相关商品",
                            "href": "https://www.amazon.com/dp/B0LINK1234",
                        }
                    ],
                    "blocks": [
                        {"type": "heading", "text": "标题", "level": 2},
                        {"type": "paragraph", "text": "段落"},
                        {"type": "list_item", "text": "要点 1"},
                        {"type": "list_item", "text": "要点 2"},
                        {"type": "table_row", "text": "A | B", "cells": ["A", "B"]},
                        {"type": "table_row", "text": "1 | 2", "cells": ["1", "2"]},
                    ],
                    "recommendedAsins": [
                        {
                            "asin": "B0REC12345",
                            "title": "推荐商品",
                            "href": "https://www.amazon.com/dp/B0REC12345",
                            "source": "AsinFaceoutList",
                            "description": "推荐原因",
                        }
                    ],
                    "summaryText": "总结文本",
                }
            ],
            "upload_payload": {
                "records": [
                    {
                        "questions": [
                            {
                                "question": "这个商品怎么样？",
                                "capturedAt": 1710000000000,
                            }
                        ]
                    }
                ]
            },
            "seed_request": {"request_url": "hidden"},
        }
    )

    assert report == "\n".join(
        [
            "## 第 1 题：这个商品怎么样？",
            "",
            "### 相关产品",
            "",
            "- B0LINK1234 - 相关商品",
            "  https://www.amazon.com/dp/B0LINK1234",
            "",
            "### 答案",
            "",
            "#### 标题",
            "",
            "段落",
            "",
            "- 要点 1",
            "- 要点 2",
            "",
            "| A | B |",
            "| --- | --- |",
            "| 1 | 2 |",
            "",
            "### 推荐 ASIN",
            "",
            "- B0REC12345 - 推荐商品 (AsinFaceoutList)",
            "  https://www.amazon.com/dp/B0REC12345",
            "  推荐原因",
            "",
            "### 总结",
            "",
            "总结文本",
        ]
    )
    assert "fallback text should not appear" not in report
    assert "seed_request" not in report


def test_answer_report_formatter_falls_back_to_markdown_text():
    from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter

    report = AnswerReportFormatter().format_data(
        {
            "answers": [
                {
                    "text": "\n".join(
                        [
                            "# 标题",
                            "段落一",
                            "- 要点 1",
                            "  续行",
                            "- 要点 2",
                            "",
                            "| A | B |",
                            "| --- | --- |",
                            "| 1 | 2 |",
                            "| 3 | 4 |",
                        ]
                    ),
                    "isSuccess": True,
                }
            ]
        }
    )

    assert "## 第 1 题：第 1 题" in report
    assert "# 标题" in report
    assert "- 要点 1 续行" in report
    assert "| A | B |" in report
    assert "| 3 | 4 |" in report


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


def test_browser_capture_closes_new_chrome_by_default(monkeypatch):
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

    class FakeCdpSession:
        def send(self, command):
            calls.append(("cdp", command))

    class FakeBrowser:
        contexts = [FakeContext()]

        def new_browser_cdp_session(self):
            return FakeCdpSession()

        def close(self):
            calls.append(("close", None))

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
    monkeypatch.setattr(service, "_start_new_chrome", lambda: calls.append(("start", None)))
    monkeypatch.setattr(service, "_wait_for_cdp", lambda cdp_url, timeout_seconds: None)

    service.capture_seed_request(
        asin="B0TEST1234",
        country="US",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        cdp_url="http://127.0.0.1:9222",
        timeout_seconds=1,
        new_chrome=True,
    )

    assert ("cdp", "Browser.close") in calls


def test_browser_capture_keeps_new_chrome_open_when_requested(monkeypatch):
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

        def close(self):
            calls.append(("close", None))

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
    monkeypatch.setattr(service, "_start_new_chrome", lambda: None)
    monkeypatch.setattr(service, "_wait_for_cdp", lambda cdp_url, timeout_seconds: None)

    service.capture_seed_request(
        asin="B0TEST1234",
        country="US",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        cdp_url="http://127.0.0.1:9222",
        timeout_seconds=1,
        new_chrome=True,
        keep_chrome_open=True,
    )

    assert ("close", None) not in calls


def test_new_chrome_arguments_open_devtools_for_tabs():
    assert "--auto-open-devtools-for-tabs" in BrowserAttachService.DEFAULT_NEW_CHROME_ARGUMENTS


def test_browser_open_marketplace_for_login_opens_site_and_keeps_browser(monkeypatch):
    calls = []

    class FakePage:
        def __init__(self) -> None:
            self.url = "about:blank"
            self.brought_to_front = False

        def goto(self, url, wait_until, timeout):
            self.url = url
            calls.append(("goto", url, wait_until, timeout))

        def bring_to_front(self):
            self.brought_to_front = True
            calls.append(("front", None))

    fake_page = FakePage()

    class FakeContext:
        def new_page(self):
            return fake_page

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            calls.append(("close", None))

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

    service.open_marketplace_for_login(
        marketplace_url="https://www.amazon.de",
        cdp_url="http://127.0.0.1:9222",
        timeout_seconds=30,
    )

    assert calls == [
        ("start", None),
        ("wait", "http://127.0.0.1:9222"),
        ("connect", "http://127.0.0.1:9222"),
        ("goto", "https://www.amazon.de", "domcontentloaded", 30000),
        ("front", None),
    ]
    assert service.current_page is fake_page


def test_cli_get_writes_manager_result_to_report_file(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "answers": [{"text": "默认答案", "isSuccess": True}],
                "seed_request": {"request_url": "hidden"},
                "upload_payload": {"records": []},
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])
    report_path, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert re.fullmatch(r"B0TEST1234-\d{8}-\d{6}\.md", report_path.name)
    assert report_path.parent == tmp_path / "output" / "amazon-rufus"
    assert report_text == "## 第 1 题：第 1 题\n\n### 答案\n\n默认答案"
    assert "Rufus 答案报告已保存：" in result.stdout
    assert (Path("output") / "amazon-rufus" / report_path.name).as_posix() in result.stdout
    assert "默认答案" not in result.stdout
    assert "seed_request" not in result.stdout
    assert "upload_payload" not in result.stdout
    assert captured["new_chrome"] is False


def test_cli_get_writes_frontend_like_answer_report(monkeypatch, tmp_path: Path):
    class DummyManager:
        def get(self, **kwargs):
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "answers": [
                    {
                        "text": "fallback",
                        "isSuccess": True,
                        "blocks": [
                            {"type": "heading", "text": "回答标题", "level": 2},
                            {"type": "paragraph", "text": "第一条答案"},
                        ],
                        "summaryText": "总结",
                    },
                    {"text": "第二条答案", "isSuccess": True},
                ],
                "seed_request": {"request_url": "hidden"},
                "upload_payload": {
                    "records": [
                        {
                            "questions": [
                                {"question": "问题一", "capturedAt": 1},
                                {"question": "问题二", "capturedAt": 2},
                            ]
                        }
                    ]
                },
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])
    _, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert "## 第 1 题：问题一" in report_text
    assert "#### 回答标题" in report_text
    assert "第一条答案" in report_text
    assert "### 总结" in report_text
    assert "## 第 2 题：问题二" in report_text
    assert "第二条答案" in report_text
    assert "fallback" not in report_text
    assert "第一条答案" not in result.stdout
    assert "seed_request" not in result.stdout
    assert "upload_payload" not in result.stdout


def test_cli_get_answer_report_reports_failed_empty_answer(monkeypatch, tmp_path: Path):
    class DummyManager:
        def get(self, **kwargs):
            return {"asin": kwargs["asin"], "country": kwargs["country"], "answers": [{"text": "", "isSuccess": False}]}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])
    _, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert "## 第 1 题：第 1 题" in report_text
    assert "第 1 题未获取到答案" in report_text
    assert "第 1 题未获取到答案" not in result.stdout


def test_cli_get_passes_new_chrome(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {"asin": kwargs["asin"], "country": kwargs["country"], "answers": []}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US", "--new-chrome"])

    assert result.exit_code == 0
    assert captured["new_chrome"] is True
    assert captured["keep_chrome_open"] is False


def test_cli_get_passes_keep_chrome_open(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {"asin": kwargs["asin"], "country": kwargs["country"], "answers": []}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US", "--new-chrome", "--keep-chrome-open"])

    assert result.exit_code == 0
    assert captured["new_chrome"] is True
    assert captured["keep_chrome_open"] is True


def test_cli_init_outputs_login_prompt(monkeypatch):
    captured = {}

    class DummyManager:
        def init(self, **kwargs):
            captured.update(kwargs)
            return {"country": "US", "url": "https://www.amazon.com"}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(app, ["init", "US"])

    assert result.exit_code == 0
    assert result.stdout == "请在新窗口中登录亚马逊\n"
    assert captured == {
        "country": "US",
        "cdp_url": "http://127.0.0.1:9222",
        "timeout_seconds": 30,
    }


def test_manager_init_opens_country_marketplace():
    captured = {}

    class FakeBrowser:
        def open_marketplace_for_login(self, **kwargs):
            captured.update(kwargs)

    manager = RufusManager(browser=FakeBrowser())

    result = manager.init(country="DE", cdp_url="http://127.0.0.1:9333", timeout_seconds=12)

    assert result == {"country": "DE", "url": "https://www.amazon.de"}
    assert captured == {
        "marketplace_url": "https://www.amazon.de",
        "cdp_url": "http://127.0.0.1:9333",
        "timeout_seconds": 12,
    }


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
    assert result["questions"] == ["问题1"]
    assert result["upload_payload"]["records"][0]["questions"][0]["question"] == "问题1"
    assert fake_browser.kwargs["new_chrome"] is True
    assert fake_browser.kwargs["keep_chrome_open"] is False


def test_manager_get_replays_before_playwright_context_closes(monkeypatch):
    from opscli.amazon_rufus.domain.models import AnswerData, Question, QuestionTemplate, SeedRequestRecord

    class FakeQuestionBank:
        def load_templates(self):
            return [QuestionTemplate(id=1, description="默认", preferred_version_index=0, questions=[Question(id=1, text="问题1", position=1)])]

    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
        post_data = '{"queryContext": {"query": ""}}'
        headers = {"content-type": "application/json"}

    class FakePage:
        def __init__(self) -> None:
            self.url = "about:blank"
            self.closed_loop = False

        def on(self, event, handler):
            self.handler = handler

        def goto(self, url, wait_until, timeout):
            self.url = url
            self.handler(FakeRequest())

        def wait_for_timeout(self, timeout):
            return None

        def bring_to_front(self):
            return None

    fake_page = FakePage()

    class FakeContext:
        def new_page(self):
            return fake_page

    class FakeBrowser:
        contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, cdp_url):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            fake_page.closed_loop = True
            return False

    class FakeReplay:
        def replay_with_page(self, page, seed, questions):
            if page.closed_loop:
                raise RuntimeError("Event loop is closed! Is Playwright already stopped?")
            return [AnswerData(text="answer", thread_id="thread-1")]

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    manager = RufusManager(question_bank=FakeQuestionBank(), browser=BrowserAttachService(), replay=FakeReplay())

    result = manager.get(asin="B0TEST1234", country="US")

    assert result["answers"][0]["text"] == "answer"


def test_replay_with_page_reuses_required_seed_headers():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    captured = {}

    class FakePage:
        def evaluate(self, script, args):
            captured.update(args)
            return 'data: {"answer":"hello"}\n\n'

    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming",
        request_headers={
            "content-type": "application/json",
            "anti-csrftoken-a2z": "token-1",
            "x-amz-is-papyrus": "true",
            "user-agent": "forbidden",
            "sec-ch-ua": "browser-owned",
        },
        request_body='{"queryContext": {"query": ""}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )

    answers = RufusReplayService().replay_with_page(FakePage(), seed, ["hello?"])

    assert answers[0].text == "hello"
    assert captured["headers"] == {
        "content-type": "application/json",
        "anti-csrftoken-a2z": "token-1",
        "x-amz-is-papyrus": "true",
    }


def test_replay_build_payload_matches_extension_context_fields():
    seed_body = json.dumps(
        {
            "queryContext": {"query": "seed"},
            "pageContext": {
                "targetPageMetadata": [{"type": "ASIN", "value": "OLDASIN000"}],
                "originPageMetadata": [{"type": "OTHER", "value": "keep"}],
                "originUrl": "https://www.amazon.com/dp/OLDASIN000",
            },
            "requestCancellationTokens": ["token-1"],
        }
    )

    payload = RufusReplayService().build_payload(
        seed_body,
        "这是什么商品？",
        thread_id="thread-1",
        asin="B0TEST1234",
    )

    assert payload["queryContext"] == {
        "query": "这是什么商品？",
        "actionType": "SEARCH",
        "qis": "NileCLTextInput",
    }
    assert payload["pageContext"]["originPageType"] == "DETAIL_PAGE"
    assert {"type": "ASIN", "value": "B0TEST1234"} in payload["pageContext"]["targetPageMetadata"]
    assert {"type": "ASIN", "value": "B0TEST1234"} in payload["pageContext"]["originPageMetadata"]
    assert payload["pageContext"]["originUrl"] == "https://www.amazon.com/dp/OLDASIN000"
    assert payload["bottomSheetContext"]["previousTurnsBottomSheetSize"] == "expanded"
    assert payload["impressionsContext"]["FIRST_TIME_USER_MESSAGE_SEEN_STATUS"] == "SEEN"
    assert payload["requestCancellationTokens"] == ["token-1"]
    assert payload["historyThreadContext"] == {
        "threadId": "thread-1",
        "threadState": "THREAD_STATE_UNKNOWN",
    }


def test_replay_build_url_adds_extension_query_params():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    seed = SeedRequestRecord(
        request_url="https://www.amazon.co.uk/rufus/cl/streaming?tabId=old-tab&x=1",
        request_headers={},
        request_body='{"queryContext": {}}',
        page_url="https://www.amazon.co.uk/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="UK",
        captured_at=1710000000000,
    )

    replay_url = RufusReplayService().build_replay_url(seed)

    assert replay_url == (
        "https://www.amazon.co.uk/rufus/cl/streaming"
        "?tabId=tab-1&x=1&programId=NILE_CLASSIC%3Adesktop-cl&ref=nl_cl_dsk_csq"
    )


def test_replay_with_page_uses_extension_payload_and_url():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    captured = {}

    class FakePage:
        def evaluate(self, script, args):
            captured.update(args)
            return 'data: {"answer":"hello","conversation_metadata":{"threadId":"thread-1"}}\n\n'

    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming?tabId=old-tab",
        request_headers={"content-type": "application/json"},
        request_body='{"queryContext": {"query": "seed"}, "pageContext": {}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )

    answers = RufusReplayService().replay_with_page(FakePage(), seed, ["hello?", "next?"])

    assert answers[0].thread_id == "thread-1"
    assert captured["url"].endswith("tabId=tab-1&programId=NILE_CLASSIC%3Adesktop-cl&ref=nl_cl_dsk_csq")
    assert captured["body"]["queryContext"]["actionType"] == "SEARCH"
    assert captured["body"]["queryContext"]["qis"] == "NileCLTextInput"
    assert {"type": "ASIN", "value": "B0TEST1234"} in captured["body"]["pageContext"]["targetPageMetadata"]
    assert captured["body"]["historyThreadContext"] == {
        "threadId": "thread-1",
        "threadState": "THREAD_STATE_UNKNOWN",
    }
