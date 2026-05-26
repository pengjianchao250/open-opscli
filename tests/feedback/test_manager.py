import pytest

from opscli.feedback.domain.exceptions import InvalidPayloadError
from opscli.feedback.services import manager as manager_module
from opscli.feedback.services.manager import FeedbackManager


class DummyClient:
    def __init__(self):
        self.submitted = None

    def submit(self, payload):
        self.submitted = payload
        return {"data": {"feedback_uuid": "fb-1"}}


def test_build_payload_forces_running_opscli_versions(monkeypatch):
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")

    payload = FeedbackManager().build_payload(
        feedback_type="bug",
        title="版本记录",
        content="验证版本号来源",
        app_version="client-app",
        client_version="client-lib",
        context={"app_version": "context-app", "client_name": "custom-client"},
    )

    assert payload["app_version"] == "9.9.9"
    assert payload["client_version"] == "9.9.9"
    assert payload["context"]["app_version"] == "9.9.9"
    assert payload["context"]["client_name"] == "custom-client"


def test_submit_payload_file_mode_forces_running_opscli_versions(monkeypatch):
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")
    client = DummyClient()
    manager = FeedbackManager()
    manager.client = client

    result = manager.submit_payload(
        {
            "source": "cli",
            "feedback_type": "bug",
            "severity": "medium",
            "title": "文件模式版本记录",
            "content": "验证 --file 模式也强制覆盖版本号",
            "app_version": "from-file",
            "client_version": "from-file",
            "context": {"app_version": "from-file-context"},
        }
    )

    assert result["data"]["feedback_uuid"] == "fb-1"
    assert client.submitted["app_version"] == "9.9.9"
    assert client.submitted["client_version"] == "9.9.9"
    assert client.submitted["context"]["app_version"] == "9.9.9"


def test_submit_payload_rejects_non_object_context_before_submit(monkeypatch):
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")
    client = DummyClient()
    manager = FeedbackManager()
    manager.client = client

    with pytest.raises(InvalidPayloadError, match="context 必须是 JSON 对象"):
        manager.submit_payload(
            {
                "source": "cli",
                "feedback_type": "bug",
                "severity": "medium",
                "title": "非法 context",
                "content": "context 类型错误",
                "context": "bad",
            }
        )

    assert client.submitted is None
