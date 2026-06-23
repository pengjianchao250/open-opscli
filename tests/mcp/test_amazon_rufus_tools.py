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
    assert "amazon_rufus_remote_consent_status" in names
    assert "amazon_rufus_remote_consent_set" in names
    assert "amazon_rufus_login_status" in names
    assert "amazon_rufus_watch_login" in names
    assert "amazon_rufus_logout" in names
    assert "amazon_rufus_platform_cookie_save" in names
    assert "amazon_rufus_platform_cookie_get" in names
    assert "amazon_rufus_curl_save" in names
    assert "amazon_rufus_init" not in names
    assert "amazon_rufus_get_remote" not in names


def test_amazon_rufus_get_writes_report_and_filters_sensitive(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, request):
            captured["request"] = request
            return {
                "report_path": "output/amazon-rufus/B0TEST1234-test.md",
                "asin": "B0TEST1234",
                "country": "US",
                "question_count": 1,
                "answer_count": 1,
                "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
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

    assert captured["request"].question == "这个商品适合送礼吗？"
    assert captured["request"].timeout_seconds == 180
    assert data == {
        "report_path": "output/amazon-rufus/B0TEST1234-test.md",
        "asin": "B0TEST1234",
        "country": "US",
        "question_count": 1,
        "answer_count": 1,
        "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
    }


def test_amazon_rufus_get_accepts_multiple_questions(monkeypatch, tmp_path: Path):
    captured = {}
    questions = ["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]

    class DummyManager:
        def get(self, request):
            captured["request"] = request
            return {
                "report_path": "output/amazon-rufus/B0TEST1234-test.md",
                "asin": "B0TEST1234",
                "country": "US",
                "question_count": len(request.questions),
                "answer_count": len(request.questions),
                "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(
        amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            questions=questions,
        )
    )

    assert result["success"] is True
    assert captured["request"].question is None
    assert captured["request"].questions == questions
    assert result["data"]["question_count"] == 2


def test_amazon_rufus_remote_consent_tools_use_isolated_store(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def remote_consent_status(self, **kwargs):
            country = kwargs["country"]
            captured["status_country"] = country
            return {
                "country": country,
                "status": "unknown",
                "use_remote_authorization": None,
                "updated_at": None,
                "source": None,
            }

        def remote_consent_set(self, **kwargs):
            request = kwargs["request"]
            captured["save"] = {
                "country": request.country,
                "allowed": request.allowed,
            }
            return {
                "country": request.country,
                "status": "allowed" if request.allowed else "denied",
                "use_remote_authorization": request.allowed,
                "updated_at": "2026-06-09T00:00:00Z",
                "source": "mcp",
            }

    monkeypatch.setattr(amazon_rufus_tools, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    status = _run(amazon_rufus_tools.amazon_rufus_remote_consent_status(country="US"))
    saved = _run(amazon_rufus_tools.amazon_rufus_remote_consent_set(country="US", allowed=True))

    assert status["success"] is True
    assert status["data"] == {
        "country": "US",
        "status": "unknown",
        "use_remote_authorization": None,
        "updated_at": None,
        "source": None,
    }
    assert saved["success"] is True
    assert saved["data"]["status"] == "allowed"
    assert captured["save"] == {"country": "US", "allowed": True}


def test_amazon_rufus_login_status_returns_safe_summary(monkeypatch):
    class DummyManager:
        def login_status(self, **kwargs):
            assert kwargs == {"country": "US"}
            return {
                "country": "US",
                "status": "ready",
                "has_login_state": True,
                "can_get_backend": True,
                "session_cookie_count": 3,
                "has_streaming_request": True,
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(amazon_rufus_tools.amazon_rufus_login_status(country="US"))

    assert result == {
        "success": True,
        "data": {
            "country": "US",
            "status": "ready",
            "has_login_state": True,
            "can_get_backend": True,
            "session_cookie_count": 3,
            "has_streaming_request": True,
        },
        "error": None,
    }


def test_amazon_rufus_watch_login_returns_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def watch_login(self, **kwargs):
            request = kwargs["request"]
            captured.update(request.to_manager_kwargs())
            return {
                "country": "US",
                "asin": "B0TEST1234",
                "saved": True,
                "login_detected": True,
                "cookie_count": 5,
                "origin_count": 1,
                "streaming_request_saved": True,
                "has_payload_template": True,
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_watch_login(
            asin="B0TEST1234",
            country="US",
            timeout_seconds=20,
            chrome_path="C:/Chrome/chrome.exe",
            close_browser=True,
        )
    )

    assert result["success"] is True
    assert result["data"] == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "login_detected": True,
        "cookie_count": 5,
        "origin_count": 1,
        "streaming_request_saved": True,
        "has_payload_template": True,
    }
    assert captured == {
        "asin": "B0TEST1234",
        "country": "US",
        "timeout_seconds": 20,
        "chrome_path": "C:/Chrome/chrome.exe",
        "launch_if_needed": True,
        "close_browser": True,
    }


def test_amazon_rufus_logout_returns_safe_summary(monkeypatch):
    class DummyManager:
        def logout(self, **kwargs):
            assert kwargs == {"country": "US", "include_browser_profile": False}
            return {
                "country": "US",
                "state_deleted": True,
                "browser_profile_deleted": False,
                "mcp_state_cleared": True,
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_logout(
            country="US",
            include_browser_profile=False,
        )
    )

    assert result == {
        "success": True,
        "data": {
            "country": "US",
            "state_deleted": True,
            "browser_profile_deleted": False,
            "mcp_state_cleared": True,
        },
        "error": None,
    }


def test_amazon_rufus_platform_cookie_save_returns_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def platform_cookie_save(self, **kwargs):
            captured.update(kwargs)
            return {
                "platform": kwargs["platform"],
                "country": kwargs["country"],
                "status": "saved",
                "message": "ok",
                "content_length": len(kwargs["content"]),
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_platform_cookie_save(
            platform="amazon",
            country="US",
            content='{"curl":"curl hidden","storage_state":"hidden"}',
        )
    )

    assert result == {
        "success": True,
        "data": {
            "platform": "amazon",
            "country": "US",
            "status": "saved",
            "message": "ok",
            "content_length": 47,
        },
        "error": None,
    }
    assert captured["content"].startswith("{")
    assert "hidden" not in json.dumps(result, ensure_ascii=False)


def test_amazon_rufus_platform_cookie_get_hides_content_by_default(monkeypatch):
    captured = {}

    class DummyManager:
        def platform_cookie_get(self, **kwargs):
            captured.update(kwargs)
            return {
                "platform": "amazon",
                "country": "US",
                "status": "exists",
                "message": "ok",
                "content_length": 31,
                "has_content": True,
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_platform_cookie_get(
            platform="amazon",
            country="US",
        )
    )

    assert result["success"] is True
    assert result["data"] == {
        "platform": "amazon",
        "country": "US",
        "status": "exists",
        "message": "ok",
        "content_length": 31,
        "has_content": True,
    }
    assert captured == {"platform": "amazon", "country": "US", "include_content": False}
    assert "content" not in result["data"]


def test_amazon_rufus_platform_cookie_get_can_include_content(monkeypatch):
    class DummyManager:
        def platform_cookie_get(self, **kwargs):
            assert kwargs == {"platform": "amazon", "country": "US", "include_content": True}
            return {
                "platform": "amazon",
                "country": "US",
                "status": "exists",
                "message": "ok",
                "content_length": 31,
                "has_content": True,
                "content": '{"curl":"curl hidden"}',
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_platform_cookie_get(
            platform="amazon",
            country="US",
            include_content=True,
        )
    )

    assert result["success"] is True
    assert result["data"]["content"] == '{"curl":"curl hidden"}'


def test_amazon_rufus_curl_save_returns_safe_summary(monkeypatch):
    captured = {}

    class DummyManager:
        def curl_save(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": kwargs["country"],
                "asin": kwargs["asin"],
                "saved": True,
                "cookie_count": 4,
                "header_count": 7,
                "has_curl": True,
                "has_payload_template": True,
            }

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    result = _run(
        amazon_rufus_tools.amazon_rufus_curl_save(
            asin="B0TEST1234",
            country="US",
            raw_curl="curl 'https://www.amazon.com/rufus/cl/streaming' -H 'cookie: session-id=hidden'",
        )
    )

    assert result["success"] is True
    assert result["data"] == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "cookie_count": 4,
        "header_count": 7,
        "has_curl": True,
        "has_payload_template": True,
    }
    assert captured["raw_curl"].startswith("curl ")
    assert "session-id=hidden" not in json.dumps(result, ensure_ascii=False)


def test_amazon_rufus_sensitive_tool_errors_do_not_echo_secret_inputs(monkeypatch):
    class DummyManager:
        def platform_cookie_save(self, **kwargs):
            raise ValueError("boom")

        def curl_save(self, **kwargs):
            raise ValueError("boom")

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())

    cookie_result = _run(
        amazon_rufus_tools.amazon_rufus_platform_cookie_save(
            platform="amazon",
            country="US",
            content="secret-content",
        )
    )
    curl_result = _run(
        amazon_rufus_tools.amazon_rufus_curl_save(
            asin="B0TEST1234",
            country="US",
            raw_curl="curl secret",
        )
    )

    combined = json.dumps([cookie_result, curl_result], ensure_ascii=False)
    assert "secret-content" not in combined
    assert "curl secret" not in combined
    cookie_call = cookie_result["feedback"]["execution_summary"]["failed_calls"][0]
    curl_call = curl_result["feedback"]["execution_summary"]["failed_calls"][0]
    assert cookie_call["call_params"]["content_provided"] is True
    assert cookie_call["call_params"]["content_length"] == 14
    assert curl_call["call_params"]["raw_curl_provided"] is True
    assert curl_call["call_params"]["raw_curl_length"] == 11


def test_amazon_rufus_get_returns_platform_cookie_auth_error(monkeypatch, tmp_path: Path):
    """平台 Cookie API 鉴权失败应原样返回，不误报 Rufus secret 缺失。"""
    from opscli.amazon_rufus.domain.exceptions import RufusPlatformCookieAuthError

    class DummyManager:
        def get(self, **kwargs):
            raise RufusPlatformCookieAuthError()

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(
        amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )
    )

    assert result["success"] is False
    assert result["error"]["code"] == "RUFUS_PLATFORM_COOKIE_AUTH_ERROR"
    assert result["error"]["status_code"] == 401
    assert result["error"]["code"] != "RUFUS_SECRET_NOT_READY"


def test_amazon_rufus_get_keeps_ops_auth_error_separate_from_secret_not_ready(monkeypatch, tmp_path: Path):
    """OPS/MCP 凭证缺失类错误不应被包装成 Rufus secret 缺失。"""

    class OpsAuthError(Exception):
        code = "AUTH_NOT_LOGGED_IN"

        def to_dict(self):
            return {"code": self.code, "message": "当前 MCP 会话没有可用 OPS 登录态"}

    class DummyManager:
        def get(self, **kwargs):
            raise OpsAuthError()

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(
        amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )
    )

    assert result["success"] is False
    assert result["error"]["code"] == "AUTH_NOT_LOGGED_IN"
    assert result["error"]["code"] != "RUFUS_SECRET_NOT_READY"


def test_amazon_rufus_get_rejects_removed_cdp_options(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, request):
            captured["request"] = request
            return {"report_path": "unused"}

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
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

    for name in [
        "cdp_url",
        "new_chrome",
        "keep_chrome_open",
        "chrome_path",
        "launch_if_needed",
        "cookie",
        "curl",
        "curl_data",
        "headers",
        "payload_template",
        "raw_curl",
        "storage_state",
        "allow_capture_browser_state",
    ]:
        assert name not in properties


def test_amazon_rufus_get_runs_manager_outside_event_loop(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyManager:
        def get(self, request):
            captured["manager_thread"] = threading.get_ident()
            return {
                "report_path": "output/amazon-rufus/B0TEST1234-test.md",
                "asin": request.asin,
                "country": request.country,
                "question_count": 1,
                "answer_count": 1,
                "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
            }

    async def scenario():
        captured["event_loop_thread"] = threading.get_ident()
        return await amazon_rufus_tools.amazon_rufus_get(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )

    monkeypatch.setattr(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda: DummyManager())
    monkeypatch.chdir(tmp_path)

    result = _run(scenario())

    assert result["success"] is True
    assert captured["manager_thread"] != captured["event_loop_thread"]


def test_rufus_mcp_manager_factory_passes_current_request_credential_dir(monkeypatch, tmp_path: Path):
    """Tool 工厂应把当前请求隔离目录传给 RufusMcpManager。"""
    captured = {}

    class DummyManager:
        @classmethod
        def for_current_request(cls, credential_dir=None):
            captured["credential_dir"] = credential_dir
            return "manager"

    monkeypatch.setattr(amazon_rufus_tools, "_get_credential_dir", lambda: tmp_path)
    monkeypatch.setattr(amazon_rufus_tools, "RufusMcpManager", DummyManager)

    manager = amazon_rufus_tools._rufus_mcp_manager_for_current_request()

    assert manager == "manager"
    assert captured["credential_dir"] == tmp_path


def test_rufus_mcp_manager_factory_passes_none_for_stdio(monkeypatch):
    """stdio 模式没有隔离目录时应把 None 传给 RufusMcpManager。"""
    captured = {}

    class DummyManager:
        @classmethod
        def for_current_request(cls, credential_dir=None):
            captured["credential_dir"] = credential_dir
            return "manager"

    monkeypatch.setattr(amazon_rufus_tools, "_get_credential_dir", lambda: None)
    monkeypatch.setattr(amazon_rufus_tools, "RufusMcpManager", DummyManager)

    manager = amazon_rufus_tools._rufus_mcp_manager_for_current_request()

    assert manager == "manager"
    assert captured["credential_dir"] is None
