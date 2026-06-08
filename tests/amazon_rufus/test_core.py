import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opscli.amazon_rufus.cli import app
from opscli.amazon_rufus.domain.models import SeedRequestRecord
from opscli.amazon_rufus.domain.exceptions import HeadlessRufusCaptureError, InvalidQuestionError, InvalidRufusCookieError, QuestionBankNotReadyError, UnsupportedMarketplaceError
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.headless_capture import HeadlessRufusCaptureService
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


def test_answer_report_formatter_falls_back_to_text_when_raw_blocks_are_unrenderable():
    from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter

    report = AnswerReportFormatter().format_data(
        {
            "answers": [
                {
                    "text": "正文文本",
                    "isSuccess": True,
                    # Rufus 原始 UI tree 不应阻止 text 回退渲染。
                    "blocks": [{"type": "container", "children": [{"type": "text", "children": "正文文本"}]}],
                    "summaryText": "总结文本",
                }
            ]
        }
    )

    assert "正文文本" in report
    assert "第 1 题未获取到答案" not in report
    assert "### 总结" in report
    assert "总结文本" in report


def test_answer_report_formatter_omits_missing_answer_when_summary_exists():
    from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter

    report = AnswerReportFormatter().format_data(
        {
            "answers": [
                {
                    "text": "",
                    "isSuccess": False,
                    # 已有总结时，报告不再额外输出空答案提示。
                    "summaryText": "总结文本",
                }
            ]
        }
    )

    assert report == "\n".join(
        [
            "## 第 1 题：第 1 题",
            "",
            "### 总结",
            "",
            "总结文本",
        ]
    )


def test_answer_report_writer_writes_relative_report_path(tmp_path: Path):
    writer = AnswerReportWriter()

    report_path = writer.write(
        {
            "asin": "b0test1234",
            "questions": ["这个商品适合送礼吗？"],
            "answers": [{"text": "适合送礼。", "isSuccess": True}],
        },
        output_dir=tmp_path / "output" / "amazon-rufus",
    )

    assert re.fullmatch(r"B0TEST1234-\d{8}-\d{6}\.md", report_path.name)
    assert report_path.parent == tmp_path / "output" / "amazon-rufus"
    assert "适合送礼" in report_path.read_text(encoding="utf-8")


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


def test_manager_submits_upload_payload_only_when_enabled():
    class DummyTransport:
        def __init__(self):
            self.payload = None

        def submit_upload_payload(self, payload):
            self.payload = payload
            return {"code": 200, "message": "ok"}

    transport = DummyTransport()
    manager = RufusManager(transport_client=transport)
    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        request_headers={},
        request_body='{"seed":true}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )

    data = manager._build_result(
        asin="B0TEST1234",
        country="US",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        questions=["问题0"],
        answers=[],
        seed=seed,
        include_upload_payload=True,
        submit_upload=True,
    )

    assert transport.payload == data["upload_payload"]
    assert data["upload_result"] == {"code": 200, "message": "ok"}


def test_headless_capture_installs_missing_playwright_browser_and_retries(monkeypatch):
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

    class FakeContext:
        def add_cookies(self, cookies):
            calls.append(("cookies", cookies))

        def new_page(self):
            return FakePage()

        def close(self):
            calls.append(("context-close", None))

    class FakeBrowser:
        def new_context(self, storage_state=None):
            return FakeContext()

        def close(self):
            calls.append(("browser-close", None))

    class FakeChromium:
        def __init__(self):
            self.launch_count = 0

        def launch(self, **kwargs):
            self.launch_count += 1
            calls.append(("launch", self.launch_count, kwargs))
            if self.launch_count == 1:
                raise Exception("BrowserType.launch: Executable doesn't exist. Please run playwright install")
            return FakeBrowser()

    fake_chromium = FakeChromium()

    class FakePlaywright:
        chromium = fake_chromium

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_run(command, check, capture_output, text):
        calls.append(("install", command, check, capture_output, text))
        return subprocess.CompletedProcess(command, 0)

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(subprocess, "run", fake_run)

    seed = HeadlessRufusCaptureService().capture_seed_request(
        asin="B0TEST1234",
        country="US",
        cookie="session-id=abc",
        timeout_seconds=1,
        page_url="https://www.amazon.com/dp/B0TEST1234",
    )

    install_calls = [item for item in calls if item[0] == "install"]
    assert seed.tab_id == "tab-1"
    assert fake_chromium.launch_count == 2
    assert len(install_calls) == 1
    assert install_calls[0][1] == [sys.executable, "-m", "playwright", "install", "chromium"]


def test_headless_capture_reopens_page_after_transient_miss(monkeypatch):
    """页面首次未触发 Rufus 请求时，应重开 Amazon 页面并继续捕获。"""
    calls = []

    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
        post_data = '{"tabId":"tab-1"}'
        headers = {"content-type": "application/json"}

    class FakePage:
        def __init__(self, index: int) -> None:
            self.index = index
            self.url = "about:blank"
            self.handler = None

        def on(self, event, handler):
            self.handler = handler

        def goto(self, url, wait_until, timeout):
            self.url = url
            calls.append(("goto", self.index, url, wait_until, timeout))
            if self.index == 4:
                self.handler(FakeRequest())

        def wait_for_timeout(self, timeout):
            calls.append(("wait", self.index, timeout))

        def close(self):
            calls.append(("page-close", self.index))

    class FakeContext:
        def __init__(self) -> None:
            self.page_count = 0

        def add_cookies(self, cookies):
            calls.append(("cookies", cookies))

        def new_page(self):
            self.page_count += 1
            calls.append(("new-page", self.page_count))
            return FakePage(self.page_count)

        def close(self):
            calls.append(("context-close", None))

    class FakeBrowser:
        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self, storage_state=None):
            calls.append(("context", storage_state))
            return self.context

        def close(self):
            calls.append(("browser-close", None))

    class FakeChromium:
        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
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

    seed = HeadlessRufusCaptureService().capture_seed_request(
        asin="B0TEST1234",
        country="US",
        cookie="session-id=abc",
        timeout_seconds=10,
        page_url="https://www.amazon.com/dp/B0TEST1234",
    )

    assert seed.tab_id == "tab-1"
    assert [item for item in calls if item[0] == "new-page"] == [
        ("new-page", 1),
        ("new-page", 2),
        ("new-page", 3),
        ("new-page", 4),
    ]
    assert len([item for item in calls if item[0] == "launch"]) == 1
    assert len([item for item in calls if item[0] == "context"]) == 1


def test_headless_capture_waits_for_delayed_rufus_request(monkeypatch):
    """商品页加载后延迟触发 Rufus 请求时，应等待 request 事件。"""
    calls = []

    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-delayed"
        post_data = '{"tabId":"tab-delayed"}'
        headers = {"content-type": "application/json"}

    class FakePage:
        url = "about:blank"

        def on(self, event, handler):
            self.handler = handler

        def goto(self, url, wait_until, timeout):
            self.url = url
            calls.append(("goto", timeout))

        def wait_for_event(self, event, predicate, timeout):
            calls.append(("wait-event", event, timeout))
            request = FakeRequest()
            assert event == "request"
            assert predicate(request) is True
            return request

        def wait_for_timeout(self, timeout):
            raise AssertionError("存在 wait_for_event 时不应退回固定等待")

        def close(self):
            calls.append(("page-close", None))

    class FakeContext:
        def add_cookies(self, cookies):
            calls.append(("cookies", cookies))

        def new_page(self):
            return FakePage()

        def close(self):
            calls.append(("context-close", None))

    class FakeBrowser:
        def new_context(self, storage_state=None):
            return FakeContext()

        def close(self):
            calls.append(("browser-close", None))

    class FakeChromium:
        def launch(self, **kwargs):
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

    seed = HeadlessRufusCaptureService().capture_seed_request(
        asin="B0TEST1234",
        country="US",
        cookie="session-id=abc",
        timeout_seconds=30,
        page_url="https://www.amazon.com/dp/B0TEST1234",
    )

    assert seed.tab_id == "tab-delayed"
    assert [item[0] for item in calls if item[0] == "wait-event"] == ["wait-event"]


def test_headless_capture_stops_after_three_page_retries(monkeypatch):
    """页面持续未触发 Rufus 请求时，最多只重开 3 次 Amazon 页面。"""
    calls = []

    class FakePage:
        url = "about:blank"

        def __init__(self, index: int) -> None:
            self.index = index

        def on(self, event, handler):
            return None

        def goto(self, url, wait_until, timeout):
            self.url = url
            calls.append(("goto", self.index, url, wait_until, timeout))

        def wait_for_timeout(self, timeout):
            calls.append(("wait", self.index, timeout))

        def close(self):
            calls.append(("page-close", self.index))

    class FakeContext:
        def __init__(self) -> None:
            self.page_count = 0

        def add_cookies(self, cookies):
            calls.append(("cookies", cookies))

        def new_page(self):
            self.page_count += 1
            calls.append(("new-page", self.page_count))
            return FakePage(self.page_count)

        def close(self):
            calls.append(("context-close", None))

    class FakeBrowser:
        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self, storage_state=None):
            calls.append(("context", storage_state))
            return self.context

        def close(self):
            calls.append(("browser-close", None))

    class FakeChromium:
        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
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

    with pytest.raises(HeadlessRufusCaptureError) as exc:
        HeadlessRufusCaptureService().capture_seed_request(
            asin="B0TEST1234",
            country="US",
            cookie="session-id=abc",
            timeout_seconds=10,
            page_url="https://www.amazon.com/dp/B0TEST1234",
        )

    assert "已重新打开 Amazon 商品页并重试 3 次" in str(exc.value)
    assert [item for item in calls if item[0] == "new-page"] == [
        ("new-page", 1),
        ("new-page", 2),
        ("new-page", 3),
        ("new-page", 4),
    ]
    assert len([item for item in calls if item[0] == "launch"]) == 1
    assert len([item for item in calls if item[0] == "context"]) == 1


def test_headless_capture_reports_install_failure_for_missing_playwright_browser(monkeypatch):
    calls = []

    class FakeChromium:
        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
            raise Exception("BrowserType.launch: Executable doesn't exist. Please run playwright install")

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_run(command, check, capture_output, text):
        calls.append(("install", command))
        raise subprocess.CalledProcessError(1, command, stderr="download failed")

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HeadlessRufusCaptureError) as exc:
        HeadlessRufusCaptureService().capture_seed_request(
            asin="B0TEST1234",
            country="US",
            cookie="session-id=abc",
            timeout_seconds=1,
            page_url="https://www.amazon.com/dp/B0TEST1234",
        )

    message = str(exc.value)
    assert [item[0] for item in calls] == ["launch", "install"]
    assert "已尝试自动安装 Playwright Chromium" in message
    assert "python -m playwright install chromium" in message
    assert "download failed" in message


def test_headless_capture_does_not_retry_more_than_once_after_browser_install(monkeypatch):
    calls = []

    class FakeChromium:
        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
            if len([item for item in calls if item[0] == "launch"]) == 1:
                raise Exception("BrowserType.launch: Executable doesn't exist. Please run playwright install")
            raise Exception("BrowserType.launch: blocked")

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_run(command, check, capture_output, text):
        calls.append(("install", command))
        return subprocess.CompletedProcess(command, 0)

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(HeadlessRufusCaptureError) as exc:
        HeadlessRufusCaptureService().capture_seed_request(
            asin="B0TEST1234",
            country="US",
            cookie="session-id=abc",
            timeout_seconds=1,
            page_url="https://www.amazon.com/dp/B0TEST1234",
        )

    assert [item[0] for item in calls] == ["launch", "install", "launch"]
    assert "已尝试自动安装 Playwright Chromium" in str(exc.value)


def test_cli_help_exposes_init_and_cdp_options():
    root_help = runner.invoke(app, ["--help"])
    get_help = runner.invoke(app, ["get", "--help"])
    init_help = runner.invoke(app, ["init", "--help"])

    assert root_help.exit_code == 0
    assert get_help.exit_code == 0
    assert init_help.exit_code == 0
    assert "init" in root_help.stdout
    assert "save-state" in root_help.stdout
    assert "watch-login" in root_help.stdout
    assert "--chrome-path" in init_help.stdout
    assert "launch-if-needed" in init_help.stdout
    for text in [
        "--cdp-url",
        "--new-chrome",
        "keep-chrome",
        "--chrome-path",
        "launch-if",
        "submit-upload",
    ]:
        assert text in get_help.stdout
    assert "--remote-rufus" not in get_help.stdout


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

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

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
    assert captured["cdp_url"] == "http://127.0.0.1:9222"
    assert captured["new_chrome"] is False
    assert captured["keep_chrome_open"] is False
    assert captured["chrome_path"] is None
    assert captured["launch_if_needed"] is False
    assert captured["timeout_seconds"] == 180
    assert captured["submit_upload"] is False


def test_cli_get_submit_upload_flag_forwards_to_manager(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "answers": [{"text": "默认答案", "isSuccess": True}],
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US", "--submit-upload"])

    assert result.exit_code == 0
    assert captured["submit_upload"] is True


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
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "answers": [{"text": "", "isSuccess": False}],
            }

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])
    _, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert "## 第 1 题：第 1 题" in report_text
    assert "第 1 题未获取到答案" in report_text
    assert "第 1 题未获取到答案" not in result.stdout


def test_cli_get_outputs_manager_error(monkeypatch, tmp_path: Path):
    class DummyManager:
        def get(self, **kwargs):
            from opscli.amazon_rufus.domain.exceptions import RufusSecretNotReadyError

            raise RufusSecretNotReadyError("Rufus 后端授权材料不可用")

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["success"] is False
    assert payload["error"]["code"] == "RUFUS_SECRET_NOT_READY"
    assert "后端授权材料不可用" in payload["error"]["message"]
    assert not (tmp_path / "output" / "amazon-rufus").exists()


def test_cli_get_passes_question_to_manager(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "questions": [kwargs["question"]],
                "answers": [{"text": "单题答案", "isSuccess": True}],
                "upload_payload": {"records": [{"questions": [{"question": kwargs["question"], "capturedAt": 1}]}]},
            }

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["get", "B0TEST1234", "US", "--question", "这个商品是做什么的"])
    _, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert captured["question"] == "这个商品是做什么的"
    assert "## 第 1 题：这个商品是做什么的" in report_text
    assert "单题答案" in report_text


def test_cli_get_passes_multiple_questions_to_manager(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            captured.update(kwargs)
            return {
                "asin": kwargs["asin"],
                "country": kwargs["country"],
                "questions": kwargs["questions"],
                "answers": [
                    {"text": f"答案：{question}", "isSuccess": True}
                    for question in kwargs["questions"]
                ],
                "upload_payload": {
                    "records": [
                        {
                            "questions": [
                                {"question": question, "capturedAt": index}
                                for index, question in enumerate(kwargs["questions"], start=1)
                            ]
                        }
                    ]
                },
            }

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

        def get_backend(self, **kwargs):
            raise AssertionError("CLI CDP 入口不应调用后端 headless get_backend")

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "get",
            "B0TEST1234",
            "US",
            "-q",
            "这个商品适合送礼吗？",
            "--question",
            "差评主要集中在哪些方面？",
        ],
    )
    _, report_text = _read_single_rufus_report(tmp_path)

    assert result.exit_code == 0
    assert captured["questions"] == ["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]
    assert captured["question"] is None
    assert "## 第 1 题：这个商品适合送礼吗？" in report_text
    assert "## 第 2 题：差评主要集中在哪些方面？" in report_text


def test_cli_init_calls_manager(monkeypatch):
    captured = {}

    class DummyManager:
        def init(self, **kwargs):
            captured.update(kwargs)
            return {"country": kwargs["country"], "url": "https://www.amazon.com"}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(app, ["init", "US"])

    assert result.exit_code == 0
    assert captured == {
        "country": "US",
        "cdp_url": "http://127.0.0.1:9222",
        "timeout_seconds": 30,
        "chrome_path": None,
        "launch_if_needed": True,
    }
    assert "请在新窗口中登录亚马逊" in result.stdout


def test_cli_init_passes_chrome_path_to_manager(monkeypatch):
    captured = {}

    class DummyManager:
        def init(self, **kwargs):
            captured.update(kwargs)
            return {"country": kwargs["country"], "url": "https://www.amazon.com"}

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(
        app,
        [
            "init",
            "US",
            "--chrome-path",
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "--no-launch-if-needed",
        ],
    )

    assert result.exit_code == 0
    assert captured["chrome_path"] == "C:/Program Files/Google/Chrome/Application/chrome.exe"
    assert captured["launch_if_needed"] is False


def test_cli_save_state_outputs_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def save_state(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": kwargs["country"],
                "saved": True,
                "cookie_count": 2,
                "origin_count": 1,
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(app, ["save-state", "US", "--pretty"])
    payload = json.loads(result.stdout)
    output_text = json.dumps(payload, ensure_ascii=False)

    assert result.exit_code == 0
    assert payload["success"] is True
    assert payload["command"] == "amazon-rufus save-state"
    assert payload["data"] == {
        "country": "US",
        "saved": True,
        "cookie_count": 2,
        "origin_count": 1,
    }
    assert captured == {
        "country": "US",
        "cdp_url": "http://127.0.0.1:9222",
        "timeout_seconds": 30,
        "chrome_path": None,
        "launch_if_needed": False,
    }
    assert "session-id" not in output_text
    assert "localStorage" not in output_text
    assert "storage_state" not in output_text


def test_manager_get_rejects_blank_question():
    manager = RufusManager()

    with pytest.raises(InvalidQuestionError) as exc:
        manager.get_backend(asin="B0TEST1234", country="US", question="   ")

    assert "question" in str(exc.value)


def test_manager_get_headless_rejects_blank_cookie():
    manager = RufusManager()

    with pytest.raises(InvalidRufusCookieError) as exc:
        manager.get_headless(
            asin="B0TEST1234",
            country="US",
            question="这个商品是做什么的",
            streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
            headers={},
            cookie="   ",
            payload_template={},
        )

    assert "cookie" in str(exc.value)


def test_manager_get_headless_uses_cookie_for_capture_and_streaming():
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord

    class FakeHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return SeedRequestRecord(
                request_url=kwargs["streaming_url"],
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeHeadlessClient:
        def query(self, **kwargs):
            self.kwargs = kwargs
            return [AnswerData(text=f"answer:{kwargs['questions'][0]}", thread_id="thread-1")]

    capture = FakeHeadlessCapture()
    client = FakeHeadlessClient()
    manager = RufusManager(headless_capture=capture, headless_client=client)

    result = manager.get_headless(
        asin="b0test1234",
        country="US",
        question="这个商品是做什么的",
        streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        headers={"anti-csrftoken-a2z": "token"},
        cookie="session-id=abc; ubid-main=def",
        payload_template={"queryContext": {"query": "old"}},
        timeout_seconds=12,
    )

    assert capture.kwargs["cookie"] == "session-id=abc; ubid-main=def"
    assert client.kwargs["cookie"] == "session-id=abc; ubid-main=def"
    assert client.kwargs["payload_template"] == {"queryContext": {"query": "old"}}
    assert result["asin"] == "B0TEST1234"
    assert result["question_count"] == 1
    assert result["answers"][0]["text"] == "answer:这个商品是做什么的"
    assert "cookie" not in json.dumps(result, ensure_ascii=False).lower()


def test_manager_get_headless_returns_reportable_result_when_answers_are_empty():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    class FakeHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            return SeedRequestRecord(
                request_url=kwargs["streaming_url"],
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeHeadlessClient:
        def query(self, **kwargs):
            return []

    manager = RufusManager(
        headless_capture=FakeHeadlessCapture(),
        headless_client=FakeHeadlessClient(),
    )

    result = manager.get_headless(
        asin="b0test1234",
        country="US",
        question="这个商品是做什么的",
        streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        headers={},
        cookie="session-id=abc",
        payload_template={},
    )

    assert result["asin"] == "B0TEST1234"
    assert result["question_count"] == 1
    assert result["answers"] == []


def test_manager_get_backend_uses_secret_provider_and_headless_services():
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord

    class FakeSecretProvider:
        def load(self, **kwargs):
            self.kwargs = kwargs
            return types.SimpleNamespace(
                url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
                headers={"anti-csrftoken-a2z": "token"},
                cookies="session-id=abc; ubid-main=def",
                payload_template={"queryContext": {"query": "old"}},
                storage_state=None,
            )

    class FakeHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return SeedRequestRecord(
                request_url=kwargs["streaming_url"],
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeHeadlessClient:
        def query(self, **kwargs):
            self.kwargs = kwargs
            return [AnswerData(text=f"backend:{kwargs['questions'][0]}", thread_id="thread-1")]

    secret_provider = FakeSecretProvider()
    capture = FakeHeadlessCapture()
    client = FakeHeadlessClient()
    manager = RufusManager(
        headless_capture=capture,
        headless_client=client,
        backend_secret_provider=secret_provider,
    )

    result = manager.get_backend(
        asin="b0test1234",
        country="US",
        question="这个商品是做什么的",
        timeout_seconds=12,
    )

    assert secret_provider.kwargs == {"country": "US"}
    assert capture.kwargs["cookie"] == "session-id=abc; ubid-main=def"
    assert capture.kwargs["streaming_url"] == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert client.kwargs["cookie"] == "session-id=abc; ubid-main=def"
    assert client.kwargs["headers"] == {"anti-csrftoken-a2z": "token"}
    assert client.kwargs["payload_template"] == {"queryContext": {"query": "old"}}
    assert result["asin"] == "B0TEST1234"
    assert result["answers"][0]["text"] == "backend:这个商品是做什么的"
    assert "session-id" not in json.dumps(result, ensure_ascii=False)


def test_manager_get_backend_returns_reportable_result_when_answers_are_empty():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    class FakeSecretProvider:
        def load(self, **kwargs):
            return types.SimpleNamespace(
                url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
                headers={},
                cookies="session-id=abc",
                payload_template=None,
                storage_state=None,
            )

    class FakeHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            return SeedRequestRecord(
                request_url=kwargs["streaming_url"],
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeHeadlessClient:
        def query(self, **kwargs):
            return []

    manager = RufusManager(
        headless_capture=FakeHeadlessCapture(),
        headless_client=FakeHeadlessClient(),
        backend_secret_provider=FakeSecretProvider(),
    )

    result = manager.get_backend(
        asin="b0test1234",
        country="US",
        question="这个商品是做什么的",
    )

    assert result["asin"] == "B0TEST1234"
    assert result["question_count"] == 1
    assert result["answers"] == []


def test_manager_get_backend_defaults_to_three_minutes_for_capture_and_streaming():
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord

    class FakeSecretProvider:
        def load(self, **kwargs):
            return types.SimpleNamespace(
                url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
                headers={"anti-csrftoken-a2z": "token"},
                cookies="session-id=abc; ubid-main=def",
                payload_template={"queryContext": {"query": "old"}},
                storage_state=None,
            )

    class FakeHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return SeedRequestRecord(
                request_url=kwargs["streaming_url"],
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeHeadlessClient:
        def query(self, **kwargs):
            self.kwargs = kwargs
            return [AnswerData(text=f"backend:{question}", thread_id="thread-1") for question in kwargs["questions"]]

    capture = FakeHeadlessCapture()
    client = FakeHeadlessClient()
    manager = RufusManager(
        headless_capture=capture,
        headless_client=client,
        backend_secret_provider=FakeSecretProvider(),
    )

    result = manager.get_backend(
        asin="b0test1234",
        country="US",
        questions=["问题1", "问题2"],
    )

    assert capture.kwargs["timeout_seconds"] == 180
    assert client.kwargs["timeout_seconds"] == 180
    assert result["question_count"] == 2


def test_manager_save_state_persists_browser_storage_state(tmp_path: Path):
    storage_state = {
        "cookies": [{"name": "session-id", "value": "abc", "domain": ".amazon.com", "path": "/"}],
        "origins": [{"origin": "https://www.amazon.com", "localStorage": [{"name": "k", "value": "v"}]}],
    }

    class FakeBrowser:
        def capture_storage_state(self, **kwargs):
            self.kwargs = kwargs
            return storage_state

    class FakeStore:
        def save(self, **kwargs):
            self.kwargs = kwargs
            return tmp_path / "browser-state-US.json"

    browser = FakeBrowser()
    store = FakeStore()
    manager = RufusManager(browser=browser, browser_state_store=store)

    result = manager.save_state(
        country="us",
        cdp_url="http://127.0.0.1:9333",
        timeout_seconds=12,
        chrome_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
        launch_if_needed=True,
    )

    assert browser.kwargs == {
        "marketplace_url": "https://www.amazon.com",
        "cdp_url": "http://127.0.0.1:9333",
        "timeout_seconds": 12,
        "chrome_path": "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "launch_if_needed": True,
    }
    assert store.kwargs == {
        "country": "US",
        "marketplace_origin": "https://www.amazon.com",
        "storage_state": storage_state,
    }
    assert result == {
        "country": "US",
        "saved": True,
        "cookie_count": 1,
        "origin_count": 1,
    }
    assert "session-id" not in json.dumps(result, ensure_ascii=False)


def test_browser_watch_login_detects_login_and_captures_streaming_request(monkeypatch):
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    calls = []

    class FakeRequest:
        url = "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
        headers = {"content-type": "application/json", "cookie": "session-id=abc"}
        post_data = '{"queryContext": {"query": "seed"}}'

    class FakePage:
        def __init__(self, name):
            self.name = name
            self.url = ""
            self.handler = None

        def on(self, event, handler):
            if event == "request":
                self.handler = handler

        def goto(self, url, wait_until=None, timeout=None):
            self.url = url
            calls.append((self.name, "goto", url))
            if "/dp/" in url and self.handler:
                self.handler(FakeRequest())

        def bring_to_front(self):
            calls.append((self.name, "front"))

        def wait_for_timeout(self, timeout_ms):
            calls.append((self.name, "wait", timeout_ms))

        def evaluate(self, script):
            return "Hello, Alice"

    class FakeContext:
        def __init__(self):
            self.pages = []
            self.page_handler = None

        def new_page(self):
            page = FakePage(f"page-{len(self.pages) + 1}")
            self.pages.append(page)
            if self.page_handler:
                self.page_handler(page)
            return page

        def on(self, event, handler):
            if event == "page":
                self.page_handler = handler

        def storage_state(self):
            return {
                "cookies": [{"name": "session-id", "value": "abc", "domain": ".amazon.com", "path": "/"}],
                "origins": [],
            }

    class FakeBrowser:
        def __init__(self):
            self.contexts = [FakeContext()]

    class FakeChromium:
        def connect_over_cdp(self, cdp_url):
            calls.append(("connect", cdp_url))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: FakePlaywright())
    monkeypatch.setitem(sys.modules, "playwright", types.SimpleNamespace(sync_api=fake_sync_api))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(BrowserAttachService, "_ensure_cdp_ready", lambda self, **kwargs: False)

    result = BrowserAttachService().watch_login_and_capture_seed_request(
        asin="B0TEST1234",
        country="US",
        marketplace_url="https://www.amazon.com",
        page_url="https://www.amazon.com/dp/B0TEST1234",
        cdp_url="http://127.0.0.1:9333",
        timeout_seconds=30,
        chrome_path=None,
        launch_if_needed=True,
    )

    assert ("connect", "http://127.0.0.1:9333") in calls
    assert ("page-1", "goto", "https://www.amazon.com") in calls
    assert ("page-2", "goto", "https://www.amazon.com/dp/B0TEST1234") in calls
    assert result["login_detected"] is True
    assert result["seed_request"].request_url == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert result["storage_state"]["cookies"][0]["name"] == "session-id"


def test_browser_login_detection_uses_nav_tools_text_without_account_list_selector():
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    class FakeContext:
        def storage_state(self):
            return {"cookies": [], "origins": []}

    class FakePage:
        def evaluate(self, script):
            assert "#nav-tools" in script
            return "Hola, Pepito, Cuenta y Listas"

    assert BrowserAttachService()._is_marketplace_logged_in(
        context=FakeContext(),
        pages=[FakePage()],
        marketplace_url="https://www.amazon.com",
    ) is True


def test_browser_login_detection_uses_amazon_login_cookie_names_without_values():
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    class FakeContext:
        def storage_state(self):
            return {
                "cookies": [
                    {"name": "at-main", "value": "secret-value", "domain": ".amazon.com", "path": "/"},
                ],
                "origins": [],
            }

    class FakePage:
        def evaluate(self, script):
            return "Hola, Identifícate, Cuenta y Listas"

    assert BrowserAttachService()._is_marketplace_logged_in(
        context=FakeContext(),
        pages=[FakePage()],
        marketplace_url="https://www.amazon.com",
    ) is True


def test_browser_signed_out_markers_cover_i18n_without_matching_greetings():
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    service = BrowserAttachService()

    for text in [
        "Hello, sign in",
        "Hola, Identifícate, Cuenta y Listas",
        "Hallo, Anmelden, Konto und Listen",
        "こんにちは, ログイン",
        "Bonjour, se connecter",
        "你好，请登录",
    ]:
        assert service._looks_like_signed_out_text(text.lower()) is True

    for text in [
        "Hola, Pepito, Cuenta y Listas",
        "Hello, Alice, Account & Lists",
        "Hallo, Max, Konto und Listen",
    ]:
        assert service._looks_like_signed_out_text(text.lower()) is False


def test_browser_resolves_edge_when_chrome_is_unavailable(monkeypatch, tmp_path: Path):
    """Chrome 不存在时回退到系统 Edge，保证 CDP 登录窗口仍可启动。"""
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    program_files = tmp_path / "Program Files"
    program_files_x86 = tmp_path / "Program Files (x86)"
    local_app_data = tmp_path / "LocalAppData"
    edge_path = program_files_x86 / "Microsoft/Edge/Application/msedge.exe"
    edge_path.parent.mkdir(parents=True)
    edge_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("opscli.amazon_rufus.services.browser.shutil.which", lambda command: None)
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("ProgramFiles(x86)", str(program_files_x86))
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    assert BrowserAttachService()._resolve_chrome_path(None) == str(edge_path)


def test_manager_get_uses_browser_cdp_and_replay():
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord

    class FakeBrowser:
        def capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return SeedRequestRecord(
                request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeReplay:
        def replay(self, seed, questions):
            self.seed = seed
            self.questions = questions
            return [AnswerData(text=f"cdp:{question}", thread_id="thread-1") for question in questions]

    browser = FakeBrowser()
    replay = FakeReplay()
    manager = RufusManager(browser=browser, replay=replay)

    result = manager.get(
        asin="b0test1234",
        country="US",
        questions=["问题1", "问题2"],
        cdp_url="http://127.0.0.1:9333",
        new_chrome=True,
        keep_chrome_open=True,
        chrome_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
        launch_if_needed=True,
        timeout_seconds=180,
    )

    assert browser.kwargs["page_url"] == "https://www.amazon.com/dp/B0TEST1234"
    assert browser.kwargs["cdp_url"] == "http://127.0.0.1:9333"
    assert browser.kwargs["new_chrome"] is True
    assert browser.kwargs["keep_chrome_open"] is True
    assert browser.kwargs["chrome_path"] == "C:/Program Files/Google/Chrome/Application/chrome.exe"
    assert browser.kwargs["launch_if_needed"] is True
    assert browser.kwargs["timeout_seconds"] == 180
    assert callable(browser.kwargs["on_captured"])
    assert replay.questions == ["问题1", "问题2"]
    assert result["asin"] == "B0TEST1234"
    assert result["question_count"] == 2
    assert result["answers"][0]["text"] == "cdp:问题1"


def test_manager_get_returns_reportable_result_when_answers_are_empty():
    from opscli.amazon_rufus.domain.models import SeedRequestRecord

    class FakeBrowser:
        def capture_seed_request(self, **kwargs):
            return SeedRequestRecord(
                request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
                request_headers={"content-type": "application/json"},
                request_body='{"queryContext": {"query": "seed"}}',
                page_url=kwargs["page_url"],
                tab_id="tab-1",
                asin=kwargs["asin"],
                country=kwargs["country"],
                captured_at=1710000000000,
            )

    class FakeReplay:
        def replay(self, seed, questions):
            return []

    manager = RufusManager(browser=FakeBrowser(), replay=FakeReplay())

    result = manager.get(
        asin="b0test1234",
        country="US",
        question="这个商品是做什么的",
    )

    assert result["asin"] == "B0TEST1234"
    assert result["question_count"] == 1
    assert result["answers"] == []


def test_headless_client_uses_timeout_for_each_question(monkeypatch):
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
    from opscli.amazon_rufus.services.headless_client import HeadlessRufusClient

    calls = []

    class FakeReplay:
        def build_payload(self, seed_body_text, question, thread_id, asin, origin_url=None):
            return {"queryContext": {"query": question}, "historyThreadContext": {"threadId": thread_id}}

    class FakeParser:
        def parse(self, raw_text):
            return AnswerData(text=raw_text, thread_id=f"thread-{len(calls)}")

    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming",
        request_headers={"content-type": "application/json"},
        request_body='{"queryContext": {"query": "seed"}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )
    client = HeadlessRufusClient(parser=FakeParser(), replay=FakeReplay())

    def fake_post_rufus(self, *, url, headers, payload, timeout_seconds):
        calls.append({"question": payload["queryContext"]["query"], "timeout_seconds": timeout_seconds})
        return payload["queryContext"]["query"]

    monkeypatch.setattr(HeadlessRufusClient, "_post_rufus", fake_post_rufus)

    answers = client.query(
        streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        seed=seed,
        questions=["问题1", "问题2", "问题3"],
        cookie="session-id=abc",
        headers={},
        payload_template=None,
        timeout_seconds=180,
    )

    assert calls == [
        {"question": "问题1", "timeout_seconds": 180},
        {"question": "问题2", "timeout_seconds": 180},
        {"question": "问题3", "timeout_seconds": 180},
    ]
    assert [answer.text for answer in answers] == ["问题1", "问题2", "问题3"]


def test_browser_state_store_saves_storage_state_plaintext_json_and_builds_cookie_header(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    storage_state = {
        "cookies": [
            {"name": "session-id", "value": "abc", "domain": ".amazon.com", "path": "/"},
            {"name": "ubid-main", "value": "def", "domain": "www.amazon.com", "path": "/"},
            {"name": "de-only", "value": "skip", "domain": ".amazon.de", "path": "/"},
        ],
        "origins": [
            {
                "origin": "https://www.amazon.com",
                "localStorage": [{"name": "rufus-key", "value": "rufus-value"}],
            }
        ],
    }
    store = RufusBrowserStateStore(base_dir=tmp_path)

    state_path = store.save(
        country="US",
        marketplace_origin="https://www.amazon.com",
        storage_state=storage_state,
    )
    loaded = store.load("US")

    assert state_path.parent == tmp_path
    assert state_path.name == "browser-state-US.json"
    assert not (tmp_path / ".browser-state-key").exists()
    raw_state = state_path.read_text(encoding="utf-8")
    assert "session-id" in raw_state
    assert "rufus-value" in raw_state
    assert json.loads(raw_state)["storage_state"] == storage_state
    assert loaded["storage_state"] == storage_state
    assert store.build_cookie_header(storage_state, "https://www.amazon.com") == "session-id=abc; ubid-main=def"


def test_browser_state_store_saves_streaming_seed_material_plaintext_json(tmp_path: Path):
    from opscli.amazon_rufus.domain.models import SeedRequestRecord
    from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    storage_state = {
        "cookies": [{"name": "session-id", "value": "from-storage", "domain": ".amazon.com", "path": "/"}],
        "origins": [],
    }
    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        request_headers={
            "content-type": "application/json",
            "cookie": "session-id=from-curl; ubid-main=from-curl",
            "content-length": "123",
            "anti-csrftoken-a2z": "csrf-token",
        },
        request_body='{"queryContext": {"query": "seed"}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )
    store = RufusBrowserStateStore(base_dir=tmp_path)

    state_path = store.save(
        country="US",
        marketplace_origin="https://www.amazon.com",
        storage_state=storage_state,
        seed_request=seed,
    )
    loaded = store.load("US")
    secret = RufusBackendSecretProvider(browser_state_store=store).load(country="US")

    raw_state = state_path.read_text(encoding="utf-8")
    assert state_path.name == "browser-state-US.json"
    assert "session-id=from-curl" in raw_state
    assert "csrf-token" in raw_state
    assert not (tmp_path / ".browser-state-key").exists()
    assert loaded["curl_data"] == {
        "url": "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        "headers": {"content-type": "application/json", "anti-csrftoken-a2z": "csrf-token"},
        "cookies": "session-id=from-curl; ubid-main=from-curl",
        "payload_template": {"queryContext": {"query": "seed"}},
    }
    assert loaded["streaming_url"] == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert loaded["headers"] == {"content-type": "application/json", "anti-csrftoken-a2z": "csrf-token"}
    assert loaded["payload_template"] == {"queryContext": {"query": "seed"}}
    assert loaded["seed_request"]["asin"] == "B0TEST1234"
    assert "request_body" not in loaded["seed_request"]
    assert secret.url == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert secret.headers == {"content-type": "application/json", "anti-csrftoken-a2z": "csrf-token"}
    assert secret.cookies == "session-id=from-curl; ubid-main=from-curl"
    assert secret.curl_data == loaded["curl_data"]
    assert secret.payload_template == {"queryContext": {"query": "seed"}}
    assert secret.seed_request is not None
    assert secret.seed_request.asin == "B0TEST1234"


def test_browser_state_store_ignores_legacy_bin_without_plaintext_json(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    (tmp_path / "browser-state-US.bin").write_bytes(b"legacy encrypted state")
    (tmp_path / ".browser-state-key").write_bytes(b"legacy key")
    store = RufusBrowserStateStore(base_dir=tmp_path)

    assert store.load("US") is None
    assert (tmp_path / "browser-state-US.bin").exists()
    assert (tmp_path / ".browser-state-key").exists()


def test_cookie_parser_builds_minimal_storage_state_for_marketplace():
    from opscli.amazon_rufus.services.cookie_parser import RufusCookieParser

    storage_state = RufusCookieParser().parse_cookie_header(
        'session-id=abc; session-token="token=with+plus/slash"; ubid-main=def',
        marketplace_origin="https://www.amazon.com",
    )

    cookies = storage_state["cookies"]
    assert storage_state["origins"] == []
    assert [item["name"] for item in cookies] == ["session-id", "session-token", "ubid-main"]
    assert cookies[0]["domain"] == ".amazon.com"
    assert cookies[0]["path"] == "/"
    assert cookies[0]["secure"] is True
    assert cookies[0]["sameSite"] == "Lax"
    assert cookies[1]["value"] == "token=with+plus/slash"


def _sample_rufus_curl() -> str:
    """构造脱敏的 Rufus Copy-as-cURL 样例。"""
    return r"""curl 'https://www.amazon.com/rufus/cl/streaming?tabId=tab-1&programId=NILE_CLASSIC%3Adesktop-cl' \
  -H 'accept: */*' \
  -H 'anti-csrftoken-a2z: csrf-token' \
  -H 'content-type: application/json' \
  -H 'content-length: 123' \
  -H 'authorization: bearer should-not-save' \
  -H 'Cookie: session-id=from-header' \
  -b 'session-id=abc; ubid-main=def; session-token=secret-token' \
  --data-raw '{"queryContext":{"query":"","actionType":"ASIN_CLICK"},"pageContext":{"targetUrl":"https://www.amazon.com/dp/B0TEST1234?th=1","targetPageMetadata":[{"type":"ASIN","value":"B0TEST1234"}],"pageMetadata":[{"type":"ASIN","value":"B0TEST1234"}]}}'"""


def test_curl_parser_extracts_streaming_request_and_sanitizes_headers():
    from opscli.amazon_rufus.services.curl_parser import RufusCurlParser

    parsed = RufusCurlParser().parse(_sample_rufus_curl())

    assert parsed.url == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1&programId=NILE_CLASSIC%3Adesktop-cl"
    assert parsed.cookies == "session-id=abc; ubid-main=def; session-token=secret-token"
    assert parsed.headers == {
        "accept": "*/*",
        "anti-csrftoken-a2z": "csrf-token",
        "content-type": "application/json",
    }
    assert parsed.payload_template["queryContext"]["actionType"] == "ASIN_CLICK"
    assert parsed.payload_template["pageContext"]["targetUrl"] == "https://www.amazon.com/dp/B0TEST1234?th=1"


def test_manager_save_curl_persists_plaintext_curl_data_and_masks_result(tmp_path: Path):
    from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser_state_store=store)

    result = manager.save_curl(
        asin="b0test1234",
        country="us",
        raw_curl=_sample_rufus_curl(),
    )
    loaded = store.load("US")
    secret = RufusBackendSecretProvider(browser_state_store=store).load(country="US")
    state_text = (tmp_path / "browser-state-US.json").read_text(encoding="utf-8")
    serialized_result = json.dumps(result, ensure_ascii=False)

    assert result == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "cookie_count": 3,
        "header_count": 3,
        "has_curl_data": True,
        "has_payload_template": True,
    }
    assert "secret-token" not in serialized_result
    assert "csrf-token" not in serialized_result
    assert "secret-token" in state_text
    assert "csrf-token" in state_text
    assert loaded["curl_data"]["url"].endswith("programId=NILE_CLASSIC%3Adesktop-cl")
    assert loaded["curl_data"]["cookies"] == "session-id=abc; ubid-main=def; session-token=secret-token"
    assert loaded["curl_data"]["headers"] == {
        "accept": "*/*",
        "anti-csrftoken-a2z": "csrf-token",
        "content-type": "application/json",
    }
    assert loaded["seed_request"]["asin"] == "B0TEST1234"
    assert loaded["seed_request"]["tab_id"] == "tab-1"
    assert secret.seed_request is not None
    assert secret.seed_request.page_url == "https://www.amazon.com/dp/B0TEST1234?th=1"
    assert secret.curl_data == loaded["curl_data"]


def test_manager_save_cookie_persists_plaintext_state_and_masks_result(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser_state_store=store)

    result = manager.save_cookie(
        country="us",
        cookie_header="session-id=abc; session-token=secret-token",
    )

    state_path = tmp_path / "browser-state-US.json"
    loaded = store.load("US")
    serialized_result = json.dumps(result, ensure_ascii=False)
    assert result == {"country": "US", "saved": True, "cookie_count": 2}
    assert "abc" not in serialized_result
    assert "secret-token" not in serialized_result
    assert "secret-token" in state_path.read_text(encoding="utf-8")
    assert store.build_cookie_header(loaded["storage_state"], "https://www.amazon.com") == (
        "session-id=abc; session-token=secret-token"
    )


def test_manager_cookie_status_returns_masked_summary(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser_state_store=store)
    manager.save_cookie(country="US", cookie_header="session-id=abc; ubid-main=def")

    result = manager.cookie_status(country="US")

    assert result == {
        "country": "US",
        "has_state": True,
        "cookie_count": 2,
        "can_build_cookie_header": True,
    }
    assert "abc" not in json.dumps(result, ensure_ascii=False)


def test_browser_state_store_delete_is_idempotent(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)
    store.save(
        country="US",
        marketplace_origin="https://www.amazon.com",
        storage_state={"cookies": [], "origins": []},
    )
    (tmp_path / "browser-state-US.bin").write_bytes(b"legacy encrypted state")
    (tmp_path / ".browser-state-key").write_bytes(b"legacy key")

    assert (tmp_path / "browser-state-US.json").exists()
    assert store.delete("US") is True
    assert store.load("US") is None
    assert (tmp_path / "browser-state-US.bin").exists()
    assert (tmp_path / ".browser-state-key").exists()
    assert store.delete("US") is False


def test_backend_secret_provider_reads_cookie_saved_state(tmp_path: Path):
    from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser_state_store=store)
    manager.save_cookie(country="US", cookie_header="session-id=abc; ubid-main=def")

    secret = RufusBackendSecretProvider(browser_state_store=store).load(country="US")

    assert secret.cookies == "session-id=abc; ubid-main=def"
    assert secret.storage_state is not None


def test_manager_logout_clears_mcp_readable_state_and_profile(tmp_path: Path):
    from opscli.amazon_rufus.domain.exceptions import RufusSecretNotReadyError
    from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    calls = []

    class FakeBrowser:
        def clear_owned_profile(self, *, cdp_url: str):
            calls.append(cdp_url)
            return True

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser=FakeBrowser(), browser_state_store=store)
    manager.save_cookie(country="US", cookie_header="session-id=abc; ubid-main=def")

    assert RufusBackendSecretProvider(browser_state_store=store).load(country="US").cookies

    result = manager.logout(country="US", cdp_url="http://127.0.0.1:9333")

    assert result == {
        "country": "US",
        "state_deleted": True,
        "browser_profile_deleted": True,
        "mcp_state_cleared": True,
    }
    assert calls == ["http://127.0.0.1:9333"]
    assert manager.cookie_status(country="US")["has_state"] is False
    with pytest.raises(RufusSecretNotReadyError):
        RufusBackendSecretProvider(browser_state_store=store).load(country="US")


def test_manager_logout_can_skip_browser_profile(tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    class FakeBrowser:
        def clear_owned_profile(self, *, cdp_url: str):
            raise AssertionError("不应清理浏览器 profile")

    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser=FakeBrowser(), browser_state_store=store)
    manager.save_cookie(country="US", cookie_header="session-id=abc")

    result = manager.logout(country="US", include_browser_profile=False)

    assert result == {
        "country": "US",
        "state_deleted": True,
        "browser_profile_deleted": False,
        "mcp_state_cleared": True,
    }


def test_manager_watch_login_saves_state_and_streaming_seed(tmp_path: Path):
    from opscli.amazon_rufus.domain.models import SeedRequestRecord
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    storage_state = {
        "cookies": [
            {"name": "session-id", "value": "abc", "domain": ".amazon.com", "path": "/"},
            {"name": "ubid-main", "value": "def", "domain": ".amazon.com", "path": "/"},
        ],
        "origins": [],
    }
    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        request_headers={"content-type": "application/json", "cookie": "session-id=abc"},
        request_body='{"queryContext": {"query": "seed"}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )

    class FakeBrowser:
        def watch_login_and_capture_seed_request(self, **kwargs):
            self.kwargs = kwargs
            return {"storage_state": storage_state, "seed_request": seed, "login_detected": True}

    browser = FakeBrowser()
    store = RufusBrowserStateStore(base_dir=tmp_path)
    manager = RufusManager(browser=browser, browser_state_store=store)

    result = manager.watch_login(
        asin="b0test1234",
        country="us",
        cdp_url="http://127.0.0.1:9333",
        timeout_seconds=120,
        chrome_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
        launch_if_needed=True,
    )
    loaded = store.load("US")

    assert browser.kwargs == {
        "asin": "B0TEST1234",
        "country": "US",
        "marketplace_url": "https://www.amazon.com",
        "page_url": "https://www.amazon.com/dp/B0TEST1234",
        "cdp_url": "http://127.0.0.1:9333",
        "timeout_seconds": 120,
        "chrome_path": "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "launch_if_needed": True,
    }
    assert result == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "login_detected": True,
        "cookie_count": 2,
        "origin_count": 0,
        "streaming_request_saved": True,
        "has_payload_template": True,
    }
    assert loaded["streaming_url"] == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert "abc" not in json.dumps(result, ensure_ascii=False)


def test_manager_get_backend_uses_matching_saved_streaming_seed(tmp_path: Path):
    from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    storage_state = {
        "cookies": [{"name": "session-id", "value": "from-storage", "domain": ".amazon.com", "path": "/"}],
        "origins": [],
    }
    seed = SeedRequestRecord(
        request_url="https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
        request_headers={
            "content-type": "application/json",
            "cookie": "session-id=from-curl; ubid-main=from-curl",
            "anti-csrftoken-a2z": "csrf-token",
        },
        request_body='{"queryContext": {"query": "seed"}, "pageContext": {"originPageType": "DETAIL_PAGE"}}',
        page_url="https://www.amazon.com/dp/B0TEST1234",
        tab_id="tab-1",
        asin="B0TEST1234",
        country="US",
        captured_at=1710000000000,
    )
    store = RufusBrowserStateStore(base_dir=tmp_path)
    store.save(
        country="US",
        marketplace_origin="https://www.amazon.com",
        storage_state=storage_state,
        seed_request=seed,
    )

    class FailingHeadlessCapture:
        def capture_seed_request(self, **kwargs):
            raise AssertionError("同 ASIN 已保存 streaming seed 时不应重新 headless 捕获")

    class FakeHeadlessClient:
        def query(self, **kwargs):
            self.kwargs = kwargs
            return [AnswerData(text="saved-seed answer")]

    client = FakeHeadlessClient()
    manager = RufusManager(
        browser_state_store=store,
        headless_capture=FailingHeadlessCapture(),
        headless_client=client,
    )

    result = manager.get_backend(
        asin="b0test1234",
        country="US",
        question="这是什么商品？",
    )

    assert client.kwargs["streaming_url"] == "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1"
    assert client.kwargs["seed"].asin == "B0TEST1234"
    assert client.kwargs["cookie"] == "session-id=from-curl; ubid-main=from-curl"
    assert client.kwargs["headers"] == {"content-type": "application/json", "anti-csrftoken-a2z": "csrf-token"}
    assert client.kwargs["payload_template"] == {
        "queryContext": {"query": "seed"},
        "pageContext": {"originPageType": "DETAIL_PAGE"},
    }
    assert result["answers"][0]["text"] == "saved-seed answer"


def test_cli_cookie_save_from_stdin_and_status_are_masked(monkeypatch, tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)

    class TestManager(RufusManager):
        def __init__(self):
            super().__init__(browser_state_store=store)

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", TestManager)

    save_result = runner.invoke(app, ["cookie", "save", "US", "--from-stdin", "--pretty"], input="session-id=abc; ubid-main=def")
    status_result = runner.invoke(app, ["cookie", "status", "US", "--pretty"])

    assert save_result.exit_code == 0
    assert status_result.exit_code == 0
    save_payload = json.loads(save_result.stdout)
    status_payload = json.loads(status_result.stdout)
    assert save_payload["command"] == "amazon-rufus cookie save"
    assert save_payload["data"] == {"country": "US", "saved": True, "cookie_count": 2}
    assert status_payload["command"] == "amazon-rufus cookie status"
    assert status_payload["data"]["can_build_cookie_header"] is True
    combined = save_result.stdout + status_result.stdout
    assert "abc" not in combined
    assert "def" not in combined


def test_cli_curl_save_from_stdin_outputs_safe_summary(monkeypatch, tmp_path: Path):
    from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore

    store = RufusBrowserStateStore(base_dir=tmp_path)

    class TestManager(RufusManager):
        def __init__(self):
            super().__init__(browser_state_store=store)

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", TestManager)

    result = runner.invoke(
        app,
        ["curl", "save", "B0TEST1234", "US", "--from-stdin", "--pretty"],
        input=_sample_rufus_curl(),
    )
    payload = json.loads(result.stdout)
    output_text = json.dumps(payload, ensure_ascii=False).lower()

    assert result.exit_code == 0
    assert payload["command"] == "amazon-rufus curl save"
    assert payload["data"] == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "cookie_count": 3,
        "header_count": 3,
        "has_curl_data": True,
        "has_payload_template": True,
    }
    for forbidden in [
        "secret-token",
        "csrf-token",
        "from-header",
        "\"payload_template\"",
        "\"headers\"",
        "cookie:",
        "storage_state",
    ]:
        assert forbidden not in output_text


def test_cli_watch_login_outputs_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def watch_login(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": kwargs["country"],
                "asin": kwargs["asin"],
                "saved": True,
                "login_detected": True,
                "cookie_count": 2,
                "origin_count": 1,
                "streaming_request_saved": True,
                "has_payload_template": True,
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(
        app,
        [
            "watch-login",
            "B0TEST1234",
            "US",
            "--cdp-url",
            "http://127.0.0.1:9333",
            "--timeout",
            "120",
            "--chrome-path",
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "--pretty",
        ],
    )
    payload = json.loads(result.stdout)
    output_text = json.dumps(payload, ensure_ascii=False).lower()

    assert result.exit_code == 0
    assert captured == {
        "asin": "B0TEST1234",
        "country": "US",
        "cdp_url": "http://127.0.0.1:9333",
        "timeout_seconds": 120,
        "chrome_path": "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "launch_if_needed": True,
    }
    assert payload["success"] is True
    assert payload["command"] == "amazon-rufus watch-login"
    assert payload["data"]["streaming_request_saved"] is True
    for forbidden in ["session-id", "session-token", "\"headers\"", "\"payload_template\"", "storage_state"]:
        assert forbidden not in output_text


def test_cli_logout_outputs_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def logout(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": kwargs["country"],
                "state_deleted": True,
                "browser_profile_deleted": False,
                "mcp_state_cleared": True,
            }

    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager())

    result = runner.invoke(
        app,
        [
            "logout",
            "US",
            "--cdp-url",
            "http://127.0.0.1:9333",
            "--no-browser-profile",
            "--pretty",
        ],
    )
    payload = json.loads(result.stdout)
    output_text = json.dumps(payload, ensure_ascii=False).lower()

    assert result.exit_code == 0
    assert captured == {
        "country": "US",
        "cdp_url": "http://127.0.0.1:9333",
        "include_browser_profile": False,
    }
    assert payload == {
        "success": True,
        "command": "amazon-rufus logout",
        "data": {
            "country": "US",
            "state_deleted": True,
            "browser_profile_deleted": False,
            "mcp_state_cleared": True,
        },
        "error": None,
    }
    for forbidden in ["session-id", "session-token", "\"headers\"", "\"payload_template\"", "storage_state", "seed_request"]:
        assert forbidden not in output_text


def test_browser_clear_owned_profile_deletes_only_opscli_profile(monkeypatch, tmp_path: Path):
    from opscli.amazon_rufus.services import browser as browser_module
    from opscli.amazon_rufus.services.browser import BrowserAttachService

    monkeypatch.setattr(browser_module.Path, "home", lambda: tmp_path)
    root = tmp_path / ".opscli" / "chrome-profiles"
    profile_dir = root / "amazon-rufus-9333"
    sibling_dir = root / "do-not-delete"
    profile_dir.mkdir(parents=True)
    sibling_dir.mkdir(parents=True)
    (profile_dir / "Cookies").write_text("secret", encoding="utf-8")
    (sibling_dir / "keep.txt").write_text("keep", encoding="utf-8")

    service = BrowserAttachService()

    assert service.clear_owned_profile(cdp_url="http://127.0.0.1:9333") is True
    assert not profile_dir.exists()
    assert sibling_dir.exists()
    assert service.clear_owned_profile(cdp_url="http://127.0.0.1:9333") is False


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
        origin_url="https://www.amazon.com/dp/B0TEST1234",
    )

    assert payload["queryContext"] == {
        "query": "这是什么商品？",
        "actionType": "SEARCH",
        "qis": "NileCLTextInput",
    }
    assert payload["pageContext"]["originPageType"] == "DETAIL_PAGE"
    assert payload["pageContext"]["pageType"] == "DETAIL_PAGE"
    assert payload["pageContext"]["targetPageType"] == "DETAIL_PAGE"
    assert payload["pageContext"]["targetUrl"] == "https://www.amazon.com/dp/B0TEST1234"
    assert payload["pageContext"]["originUrl"] == "https://www.amazon.com/dp/B0TEST1234"
    assert {"type": "ASIN", "value": "B0TEST1234"} in payload["pageContext"]["targetPageMetadata"]
    assert {"type": "ASIN", "value": "B0TEST1234"} in payload["pageContext"]["pageMetadata"]
    assert {"type": "ASIN", "value": "B0TEST1234"} in payload["pageContext"]["originPageMetadata"]
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
