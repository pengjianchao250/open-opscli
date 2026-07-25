import json
from pathlib import Path

import pytest

from opscli.amazon_rufus.domain.mcp_models import (
    RufusGetRequest,
    RufusRemoteConsentRequest,
    RufusWatchLoginRequest,
)
from opscli.amazon_rufus.services.mcp_manager import RufusMcpManager


def _rufus_data() -> dict:
    """构造包含敏感字段的 Rufus 结果，验证 façade 返回前会过滤。"""
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


def _manager(rufus_manager, remote_consent_store=None) -> RufusMcpManager:
    """构造测试用 RufusMcpManager。"""

    class EmptyConsentStore:
        def status(self, country):
            return {"country": country, "status": "unknown"}

        def save(self, *, country, allowed, source):
            return {"country": country, "status": "allowed" if allowed else "denied", "source": source}

    return RufusMcpManager(
        rufus_manager=rufus_manager,
        remote_consent_store=remote_consent_store or EmptyConsentStore(),
    )


def test_mcp_manager_get_writes_report_and_filters_sensitive(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyRufusManager:
        def get_backend(self, **kwargs):
            captured.update(kwargs)
            return _rufus_data()

    monkeypatch.chdir(tmp_path)
    manager = _manager(DummyRufusManager())

    result = manager.get(
        RufusGetRequest(
            asin="B0TEST1234",
            country="US",
            question="这个商品适合送礼吗？",
        )
    )

    report_path = tmp_path / result["report_path"]
    report_text = report_path.read_text(encoding="utf-8")

    assert captured["include_upload_payload"] is False
    assert captured["timeout_seconds"] == 180
    assert result == {
        "report_path": result["report_path"],
        "asin": "B0TEST1234",
        "country": "US",
        "question_count": 1,
        "answer_count": 1,
        "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
    }
    assert result["report_path"].startswith("output/amazon-rufus/B0TEST1234-")
    assert "适合送礼" in report_text
    combined = json.dumps(result, ensure_ascii=False).lower() + report_text.lower()
    assert "cookie" not in combined
    assert "storage_state" not in combined
    assert "seed_request" not in combined


def test_mcp_manager_get_accepts_multiple_questions(monkeypatch, tmp_path: Path):
    captured = {}
    questions = ["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]

    class DummyRufusManager:
        def get_backend(self, **kwargs):
            captured.update(kwargs)
            data = _rufus_data()
            data["question_count"] = len(kwargs["questions"])
            data["questions"] = kwargs["questions"]
            data["answers"] = [
                {"text": f"答案：{question}", "isSuccess": True, "summaryText": ""}
                for question in kwargs["questions"]
            ]
            return data

    monkeypatch.chdir(tmp_path)
    manager = _manager(DummyRufusManager())

    result = manager.get(
        RufusGetRequest(
            asin="B0TEST1234",
            country="US",
            questions=questions,
        )
    )

    assert captured["question"] is None
    assert captured["questions"] == questions
    assert result["question_count"] == 2
    report_text = (tmp_path / result["report_path"]).read_text(encoding="utf-8")
    assert "## 第 1 题：这个商品适合送礼吗？" in report_text
    assert "## 第 2 题：差评主要集中在哪些方面？" in report_text


def test_mcp_manager_remote_consent_uses_safe_payload():
    captured = {}

    class DummyStore:
        def status(self, country):
            captured["status_country"] = country
            return {
                "country": country,
                "status": "unknown",
                "use_remote_authorization": None,
                "updated_at": None,
                "source": None,
                "content": "hidden",
            }

        def save(self, *, country, allowed, source):
            captured["save"] = {"country": country, "allowed": allowed, "source": source}
            return {
                "country": country,
                "status": "allowed" if allowed else "denied",
                "use_remote_authorization": allowed,
                "updated_at": "2026-06-09T00:00:00Z",
                "source": source,
                "storage_state": "hidden",
            }

    manager = _manager(object(), remote_consent_store=DummyStore())

    status = manager.remote_consent_status("US")
    saved = manager.remote_consent_set(RufusRemoteConsentRequest(country="US", allowed=True))

    assert status == {
        "country": "US",
        "status": "unknown",
        "use_remote_authorization": None,
        "updated_at": None,
        "source": None,
    }
    assert saved["status"] == "allowed"
    assert "storage_state" not in saved
    assert captured["save"] == {"country": "US", "allowed": True, "source": "mcp"}


def test_mcp_manager_login_status_returns_safe_summary():
    class DummyRufusManager:
        def login_status(self, **kwargs):
            assert kwargs == {"country": "US"}
            return {
                "country": "US",
                "status": "ready",
                "has_login_state": True,
                "can_get_backend": True,
                "session_cookie_count": 3,
                "has_streaming_request": True,
                "content": "hidden",
            }

    result = _manager(DummyRufusManager()).login_status("US")

    assert result == {
        "country": "US",
        "status": "ready",
        "has_login_state": True,
        "can_get_backend": True,
        "session_cookie_count": 3,
        "has_streaming_request": True,
    }


def test_mcp_manager_watch_login_returns_safe_summary():
    captured = {}

    class DummyRufusManager:
        def watch_login(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": "US",
                "asin": "B0TEST1234",
                "saved": True,
                "login_detected": True,
                "cookie_count": 5,
                "origin_count": 1,
                "streaming_request_saved": True,
                "has_payload_template": True,
                "storage_state": {"cookies": ["hidden"]},
                "seed_request": {"request_headers": {"cookie": "hidden"}},
            }

    result = _manager(DummyRufusManager()).watch_login(
        RufusWatchLoginRequest(
            asin="B0TEST1234",
            country="US",
            timeout_seconds=20,
            chrome_path="C:/Chrome/chrome.exe",
            close_browser=True,
        )
    )

    assert result == {
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


def test_mcp_manager_logout_returns_safe_summary():
    class DummyRufusManager:
        def logout(self, **kwargs):
            assert kwargs == {"country": "US", "include_browser_profile": False}
            return {
                "country": "US",
                "state_deleted": True,
                "browser_profile_deleted": False,
                "mcp_state_cleared": True,
                "content": "hidden",
            }

    result = _manager(DummyRufusManager()).logout(
        country="US",
        include_browser_profile=False,
    )

    assert result == {
        "country": "US",
        "state_deleted": True,
        "browser_profile_deleted": False,
        "mcp_state_cleared": True,
    }


def test_mcp_manager_platform_cookie_save_returns_safe_summary():
    captured = {}

    class DummyRufusManager:
        def save_platform_cookie(self, **kwargs):
            captured.update(kwargs)
            return {
                "platform": kwargs["platform"],
                "country": kwargs["country"],
                "status": "saved",
                "message": "ok",
                "content_length": len(kwargs["content"]),
                "content": kwargs["content"],
            }

    result = _manager(DummyRufusManager()).platform_cookie_save(
        platform="amazon",
        country="US",
        content='{"curl":"curl hidden"}',
    )

    assert result == {
        "platform": "amazon",
        "country": "US",
        "status": "saved",
        "message": "ok",
        "content_length": 22,
    }
    assert captured["content"] == '{"curl":"curl hidden"}'


def test_mcp_manager_platform_cookie_get_hides_content_by_default():
    class DummyRufusManager:
        def get_platform_cookie(self, **kwargs):
            return {
                "platform": kwargs["platform"],
                "country": kwargs["country"],
                "status": "exists",
                "message": "ok",
                "content": "secret-content",
                "content_length": 14,
            }

    result = _manager(DummyRufusManager()).platform_cookie_get(
        platform="amazon",
        country="US",
    )

    assert result == {
        "platform": "amazon",
        "country": "US",
        "status": "exists",
        "message": "ok",
        "content_length": 14,
        "has_content": True,
    }


def test_mcp_manager_platform_cookie_get_can_include_content():
    class DummyRufusManager:
        def get_platform_cookie(self, **kwargs):
            return {
                "platform": kwargs["platform"],
                "country": kwargs["country"],
                "status": "exists",
                "message": "ok",
                "content": "secret-content",
                "content_length": 14,
            }

    result = _manager(DummyRufusManager()).platform_cookie_get(
        platform="amazon",
        country="US",
        include_content=True,
    )

    assert result == {
        "platform": "amazon",
        "country": "US",
        "status": "exists",
        "message": "ok",
        "content_length": 14,
        "has_content": True,
        "content": "secret-content",
    }


def test_mcp_manager_curl_save_returns_safe_summary():
    captured = {}

    class DummyRufusManager:
        def save_curl(self, **kwargs):
            captured.update(kwargs)
            return {
                "country": kwargs["country"],
                "asin": kwargs["asin"],
                "saved": True,
                "cookie_count": 4,
                "header_count": 7,
                "has_curl": True,
                "has_payload_template": True,
                "curl": kwargs["raw_curl"],
            }

    result = _manager(DummyRufusManager()).curl_save(
        asin="B0TEST1234",
        country="US",
        raw_curl="curl secret",
    )

    assert result == {
        "country": "US",
        "asin": "B0TEST1234",
        "saved": True,
        "cookie_count": 4,
        "header_count": 7,
        "has_curl": True,
        "has_payload_template": True,
    }
    assert captured == {"asin": "B0TEST1234", "country": "US", "raw_curl": "curl secret"}


def test_mcp_manager_rejects_sensitive_response_keys():
    manager = _manager(object())

    with pytest.raises(ValueError, match="敏感字段"):
        manager._result({"cookie": "hidden"})

    with pytest.raises(ValueError, match="敏感字段"):
        manager._result({"curl": "curl hidden"})


def test_mcp_manager_factory_uses_current_request_credential_dir(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyAuthClient:
        def __init__(self, base_dir=None):
            captured["base_dir"] = base_dir

    class DummyTransport:
        def __init__(self, auth_client=None):
            captured["auth_client"] = auth_client

    class DummyRufusManager:
        def __init__(self, transport_client=None):
            captured["transport_client"] = transport_client

    class DummyConsentStore:
        def __init__(self, base_dir=None):
            captured["consent_base_dir"] = base_dir

    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.AuthClient", DummyAuthClient)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RufusTransportClient", DummyTransport)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RufusManager", DummyRufusManager)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RemoteConsentStore", DummyConsentStore)

    manager = RufusMcpManager.for_current_request(credential_dir=tmp_path)

    assert isinstance(manager.rufus_manager, DummyRufusManager)
    assert captured["base_dir"] == tmp_path
    assert isinstance(captured["auth_client"], DummyAuthClient)
    assert isinstance(captured["transport_client"], DummyTransport)
    assert captured["consent_base_dir"] == tmp_path / "amazon-rufus"


def test_mcp_manager_factory_keeps_default_credentials_for_stdio(monkeypatch):
    captured = {}

    class DummyAuthClient:
        def __init__(self, base_dir="default"):
            captured["base_dir"] = base_dir

    class DummyTransport:
        def __init__(self, auth_client=None):
            captured["auth_client"] = auth_client

    class DummyRufusManager:
        def __init__(self, transport_client=None):
            captured["transport_client"] = transport_client

    class DummyConsentStore:
        def __init__(self, base_dir="default"):
            captured["consent_base_dir"] = base_dir

    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.AuthClient", DummyAuthClient)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RufusTransportClient", DummyTransport)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RufusManager", DummyRufusManager)
    monkeypatch.setattr("opscli.amazon_rufus.services.mcp_manager.RemoteConsentStore", DummyConsentStore)

    manager = RufusMcpManager.for_current_request(credential_dir=None)

    assert isinstance(manager.rufus_manager, DummyRufusManager)
    assert captured["base_dir"] == "default"
    assert captured["consent_base_dir"] == "default"
