import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastmcp import Client

from opscli.mcp.server import mcp
from opscli.mcp.tools import amazon_rufus as amazon_rufus_tools


def _run(coro):
    return asyncio.run(coro)


def _rufus_data() -> dict:
    """构造包含敏感字段的 Rufus 结果，验证 MCP 返回前会过滤。"""
    return {
        "asin": "B0TEST1234",
        "country": "US",
        "page_url": "https://www.amazon.com/dp/B0TEST1234",
        "question_count": 1,
        "questions": ["这个商品适合送礼吗？"],
        "answers": [
            {
                "text": "适合送礼。",
                "isSuccess": True,
                "summaryText": "",
            }
        ],
        "seed_request": {
            "request_headers": {"cookie": "session-id=hidden"},
            "request_body": '{"storage_state":"hidden"}',
        },
        "upload_payload": {
            "records": [
                {
                    "requestBody": json.dumps({"cookie": "hidden"}, ensure_ascii=False),
                    "questions": [{"question": "这个商品适合送礼吗？", "capturedAt": 1}],
                }
            ]
        },
    }


def _rufus_data_with_questions(questions: list[str]) -> dict:
    """构造多题 Rufus 结果，验证 MCP 可一次写出多题报告。"""
    return {
        "asin": "B0TEST1234",
        "country": "US",
        "page_url": "https://www.amazon.com/dp/B0TEST1234",
        "question_count": len(questions),
        "questions": questions,
        "answers": [
            {
                "text": f"答案：{question}",
                "isSuccess": True,
                "summaryText": "",
            }
            for question in questions
        ],
    }


def test_mcp_exposes_amazon_rufus_tools():
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    names = _run(scenario())

    assert "amazon_rufus_get" in names
    assert "amazon_rufus_init" not in names
    assert "amazon_rufus_get_remote" not in names


def test_amazon_rufus_get_writes_report_and_filters_sensitive(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            raise AssertionError("默认 MCP 获取不应调用 CDP get")

        def get_backend(self, **kwargs):
            captured.update(kwargs)
            return _rufus_data()

    monkeypatch.setattr(amazon_rufus_tools, "RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(
        amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )
    )

    assert result["success"] is True
    data = result["data"]
    report_path = tmp_path / data["report_path"]
    report_text = report_path.read_text(encoding="utf-8")

    assert captured["include_upload_payload"] is False
    assert captured["timeout_seconds"] == 180
    assert data == {
        "report_path": data["report_path"],
        "asin": "B0TEST1234",
        "country": "US",
        "question_count": 1,
        "answer_count": 1,
        "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
    }
    assert data["report_path"].startswith("output/amazon-rufus/B0TEST1234-")
    assert "适合送礼" in report_text
    combined = json.dumps(data, ensure_ascii=False).lower() + report_text.lower()
    assert "cookie" not in combined
    assert "storage_state" not in combined
    assert "seed_request" not in combined


def test_amazon_rufus_get_accepts_multiple_questions(monkeypatch, tmp_path: Path):
    captured = {}
    questions = ["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]

    class DummyManager:
        def get(self, **kwargs):
            raise AssertionError("默认 MCP 获取不应调用 CDP get")

        def get_backend(self, **kwargs):
            captured.update(kwargs)
            return _rufus_data_with_questions(kwargs["questions"])

    monkeypatch.setattr(amazon_rufus_tools, "RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(
        amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            questions=questions,
        )
    )

    assert result["success"] is True
    assert captured["question"] is None
    assert captured["questions"] == questions
    assert result["data"]["question_count"] == 2
    report_text = (tmp_path / result["data"]["report_path"]).read_text(encoding="utf-8")
    assert "## 第 1 题：这个商品适合送礼吗？" in report_text
    assert "## 第 2 题：差评主要集中在哪些方面？" in report_text


def test_amazon_rufus_get_rejects_removed_cdp_options(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            raise AssertionError("默认 MCP 获取不应调用 CDP get")

        def get_backend(self, **kwargs):
            captured.update(kwargs)
            return _rufus_data()

    monkeypatch.setattr(amazon_rufus_tools, "RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    with pytest.raises(TypeError):
        _run(
            amazon_rufus_tools.amazon_rufus_get(
                asin="B0TEST1234",
                country="US",
                question="这个商品适合送礼吗？",
                launch_if_needed=True,
            )
        )
    assert captured == {}


def test_amazon_rufus_tool_schema_excludes_cdp_options():
    async def scenario():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return next(tool for tool in tools if tool.name == "amazon_rufus_get")

    tool = _run(scenario())
    properties = (tool.inputSchema or {}).get("properties", {})

    for name in ["cdp_url", "new_chrome", "keep_chrome_open", "chrome_path", "launch_if_needed"]:
        assert name not in properties


def test_amazon_rufus_get_runs_manager_outside_event_loop(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, **kwargs):
            raise AssertionError("默认 MCP 获取不应调用 CDP get")

        def get_backend(self, **kwargs):
            captured["manager_thread"] = threading.get_ident()
            return _rufus_data()

    async def scenario():
        captured["event_loop_thread"] = threading.get_ident()
        return await amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )

    monkeypatch.setattr(amazon_rufus_tools, "RufusManager", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(scenario())

    assert result["success"] is True
    assert captured["manager_thread"] != captured["event_loop_thread"]
