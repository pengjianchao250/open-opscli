"""Collector Monitor Typer CLI 公开契约测试。"""

from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from opscli.collector_monitor.cli import app

runner = CliRunner()


def _response(payload, *, status_code: int = 200) -> httpx.Response:
    """构造带请求上下文的 HTTP 响应。"""
    request = httpx.Request("GET", "http://127.0.0.1:8767/api/v1/status")
    return httpx.Response(status_code, json=payload, request=request)


def test_status_outputs_json_and_exits_nonzero_when_unhealthy(monkeypatch) -> None:
    """status 应输出 JSON，存在活动事故时以非零码表示不健康。"""
    payload = {
        "source": {"ready": True, "error": None},
        "summary": {"active_incident_count": 1},
        "incidents": [{"rule": "stalled", "subject": "job-1", "status": "active"}],
    }
    monkeypatch.setattr(
        "opscli.collector_monitor.cli.httpx.get",
        lambda *args, **kwargs: _response(payload),
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 2
    assert json.loads(result.output) == payload


def test_tasks_show_and_incidents_call_read_only_endpoints(monkeypatch) -> None:
    """查询命令应映射到各只读 API，并保持 JSON 输出。"""
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/tasks"):
            return _response({"tasks": [{"job_id": "job-1", "health": "stalled"}]})
        if url.endswith("/tasks/job-1"):
            return _response({"job_id": "job-1", "timeline": []})
        return _response({"incidents": []})

    monkeypatch.setattr("opscli.collector_monitor.cli.httpx.get", fake_get)

    tasks = runner.invoke(app, ["tasks", "--health", "stalled"])
    show = runner.invoke(app, ["show", "job-1"])
    incidents = runner.invoke(app, ["incidents"])

    assert tasks.exit_code == show.exit_code == incidents.exit_code == 0
    assert json.loads(tasks.output)["tasks"][0]["health"] == "stalled"
    assert json.loads(show.output)["job_id"] == "job-1"
    assert json.loads(incidents.output) == {"incidents": []}
    assert calls[0][1]["params"] == {"health": "stalled"}
    assert all(call[1]["timeout"] == 10.0 for call in calls)


def test_unreachable_monitor_has_clear_json_error_and_nonzero_exit(monkeypatch) -> None:
    """监控服务不可达时应返回安全错误类和明确非零退出码。"""
    def unreachable(*args, **kwargs):
        raise httpx.ConnectError("secret-url", request=httpx.Request("GET", "http://secret"))

    monkeypatch.setattr("opscli.collector_monitor.cli.httpx.get", unreachable)

    result = runner.invoke(app, ["tasks"])
    payload = json.loads(result.output)

    assert result.exit_code == 1
    assert payload == {
        "success": False,
        "error": {"code": "monitor_unreachable", "message": "Collector Monitor 不可达（ConnectError）"},
    }
    assert "secret" not in result.output


def test_serve_delegates_to_server_entrypoint(monkeypatch) -> None:
    """serve 命令应使用环境配置启动独立 Uvicorn 服务。"""
    calls = []
    monkeypatch.setattr(
        "opscli.collector_monitor.server.run",
        lambda **kwargs: calls.append(kwargs),
    )

    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0
    assert calls == [{"host": "0.0.0.0", "port": 9000}]
