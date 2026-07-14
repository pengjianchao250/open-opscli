"""MCP 健康检查工具测试。"""

import asyncio

from opscli.mcp.tools import health as health_tools


def _run(coro):
    return asyncio.run(coro)


def test_ops_health_check_returns_runtime_status(monkeypatch, tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("OPSCLI_ASIN_DATA_METRICS_PATH", str(metrics_path))
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_MAX_CONCURRENT", "4")
    monkeypatch.setenv("OPSCLI_ASIN_DATA_MCP_QUEUE_TIMEOUT", "1.5")

    result = _run(health_tools.ops_health_check())

    assert result["success"] is True
    data = result["data"]
    assert data["service"] == "opscli-mcp"
    assert data["auth"] == {"checked": False}
    assert data["metrics"]["enabled"] is True
    assert data["metrics"]["path"] == str(metrics_path)
    assert data["asin_data_limiter"]["max_concurrent"] == 4
    assert data["asin_data_limiter"]["queue_timeout_seconds"] == 1.5


def test_ops_health_check_can_check_auth(monkeypatch):
    monkeypatch.setattr(health_tools, "_get_auth_pair", lambda system: ("sid", "jwt"))

    result = _run(health_tools.ops_health_check(check_auth=True))

    assert result["success"] is True
    assert result["data"]["auth"] == {
        "checked": True,
        "has_session_id": True,
        "has_jwt": True,
    }


def test_ops_health_check_registers_tool():
    registered = []

    class DummyMcp:
        def tool(self):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn

            return decorator

    health_tools.register(DummyMcp())

    assert registered == ["ops_health_check"]
