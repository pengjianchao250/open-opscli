from datetime import datetime
from uuid import UUID

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


def test_build_payload_adds_standard_observation_v2(monkeypatch):
    """旧调用也应自动获得可关联、可聚合的标准观测字段。"""
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")

    payload = FeedbackManager().build_payload(
        feedback_type="bug",
        title="查询失败",
        content="远端返回字段错误",
        source="mcp",
        system_alias="ops",
        client_name="opscli-mcp",
        mcp_tool_name="query_simple",
        execution_summary={
            "failed_calls": [
                {
                    "tool": "query_simple",
                    "error_message": "FIELD_NOT_FOUND: original_price",
                }
            ]
        },
    )

    observation = payload["context"]["observation"]
    assert observation["schema_version"] == "2.0"
    assert UUID(observation["event_id"])
    assert datetime.fromisoformat(observation["occurred_at"].replace("Z", "+00:00")).tzinfo
    assert observation["source"] == "mcp"
    assert observation["system_alias"] == "ops"
    assert observation["operation"] == "query_simple"
    assert observation["outcome"] == "failure"
    assert observation["retry_count"] == 0
    assert observation["client_name"] == "opscli-mcp"
    assert observation["client_version"] == "9.9.9"
    assert observation["runtime"]["python_version"]
    assert observation["runtime"]["platform"]


def test_submit_payload_normalizes_existing_observation_fields(monkeypatch):
    """文件模式应保留调用链标识，并把数值观测字段规范为统一类型。"""
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")
    manager = FeedbackManager()

    payload = manager.normalize_payload(
        {
            "source": "cli",
            "feedback_type": "bug",
            "severity": "high",
            "title": "请求超时",
            "content": "查询执行超时",
            "command_name": "opscli query run",
            "context": {
                "correlation_id": "trace-123",
                "request_id": "request-456",
                "error_code": "QUERY_TIMEOUT",
                "duration_ms": "1250.5",
                "retry_count": "2",
            },
        }
    )

    observation = payload["context"]["observation"]
    assert observation["correlation_id"] == "trace-123"
    assert observation["request_id"] == "request-456"
    assert observation["error_code"] == "QUERY_TIMEOUT"
    assert observation["duration_ms"] == 1250.5
    assert observation["retry_count"] == 2
    assert observation["operation"] == "opscli query run"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("duration_ms", -1, "duration_ms 必须大于或等于 0"),
        ("duration_ms", float("nan"), "duration_ms 必须是有限的非负数字"),
        ("duration_ms", float("inf"), "duration_ms 必须是有限的非负数字"),
        ("retry_count", -1, "retry_count 必须是大于或等于 0 的整数"),
        ("retry_count", float("inf"), "retry_count 必须是大于或等于 0 的整数"),
    ],
)
def test_submit_payload_rejects_invalid_observation_numbers(
    monkeypatch,
    field,
    value,
    message,
):
    """非法耗时和重试次数不得进入标准观测数据。"""
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")

    with pytest.raises(InvalidPayloadError, match=message):
        FeedbackManager().normalize_payload(
            {
                "source": "cli",
                "feedback_type": "bug",
                "severity": "medium",
                "title": "非法观测字段",
                "content": "校验失败",
                "context": {field: value},
            }
        )


@pytest.mark.parametrize("occurred_at", ["yesterday", "2026-08-06T09:30:00"])
def test_submit_payload_rejects_non_utc_observation_time(
    monkeypatch,
    occurred_at: str,
):
    """Observation 时间必须是带时区且可规范为 UTC 的 ISO-8601。"""
    monkeypatch.setattr(manager_module, "get_version", lambda: "9.9.9")

    with pytest.raises(InvalidPayloadError, match="occurred_at"):
        FeedbackManager().normalize_payload(
            {
                "source": "mcp",
                "feedback_type": "bug",
                "severity": "high",
                "title": "查询失败",
                "content": "字段映射失败",
                "context": {"observation": {"occurred_at": occurred_at}},
            }
        )
