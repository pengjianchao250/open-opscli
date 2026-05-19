# tests/telemetry/test_collector.py
"""TelemetryCollector 单元测试。"""

import pytest


@pytest.fixture(autouse=True)
def clear_pending_error():
    """每个测试前清空全局错误状态。"""
    from opscli.telemetry import collector
    collector._pending_error.clear()
    yield
    collector._pending_error.clear()


def test_build_event_contains_required_fields():
    """build_event 应包含所有必要字段。"""
    from opscli.telemetry.collector import build_event

    event = build_event(
        event_type="cli_command",
        command="query run",
        module="query",
        status="success",
        duration_ms=1250,
    )

    assert event["event_type"] == "cli_command"
    assert event["command"] == "query run"
    assert event["module"] == "query"
    assert event["status"] == "success"
    assert event["duration_ms"] == 1250
    assert "device_id" in event
    assert "opscli_version" in event
    assert "os" in event
    assert "timestamp" in event


def test_build_event_timestamp_is_iso8601():
    """timestamp 字段应为 ISO 8601 格式。"""
    from datetime import datetime, timezone
    from opscli.telemetry.collector import build_event

    event = build_event(
        event_type="cli_command",
        command="auth login",
        module="auth",
        status="success",
    )

    # datetime.fromisoformat 解析失败会抛出 ValueError
    ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    assert ts.tzinfo is not None  # 必须有时区信息


def test_pop_status_returns_success_by_default():
    """未设置错误时 pop_status 应返回 success。"""
    from opscli.telemetry.collector import pop_status

    assert pop_status() == "success"


def test_set_error_makes_pop_status_return_error():
    """set_error 后 pop_status 应返回 error。"""
    from opscli.telemetry.collector import set_error, pop_status

    class FakeError(Exception):
        pass

    set_error(FakeError("test"))
    assert pop_status() == "error"


def test_pop_error_type_returns_class_name():
    """pop_error_type 应返回异常类名字符串。"""
    from opscli.telemetry.collector import set_error, pop_error_type

    class NetworkError(Exception):
        pass

    set_error(NetworkError())
    assert pop_error_type() == "NetworkError"


def test_pop_error_type_clears_state():
    """pop_error_type 调用后，状态应被清空（pop 语义）。"""
    from opscli.telemetry.collector import set_error, pop_status, pop_error_type

    class FakeError(Exception):
        pass

    set_error(FakeError())
    pop_error_type()  # 读取并清空
    assert pop_status() == "success"  # 已清空
