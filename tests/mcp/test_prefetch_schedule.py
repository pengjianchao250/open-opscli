"""预取计划 MCP 管理工具测试。"""

import asyncio
from types import SimpleNamespace

from opscli.mcp.prefetch import PrefetchMcpRuntime


class _FakeRepository:
    """记录管理工具写入内容的轻量仓储替身。"""

    def __init__(self):
        self.created = None
        self.enabled_change = None

    def create_schedule(self, **kwargs):
        self.created = kwargs
        return {
            "id": 1,
            "schedule_name": kwargs["schedule_name"],
            "source_system": kwargs["source_system"],
            "scenario": kwargs["scenario"],
            "request": kwargs["request"],
            "run_time": kwargs["run_time"],
            "timezone": kwargs["timezone_name"],
            "enabled": kwargs["enabled"],
        }

    def set_schedules_enabled(self, **kwargs):
        self.enabled_change = kwargs
        return {
            "changed_count": 2,
            "schedules": [
                {
                    "id": schedule_id,
                    "schedule_name": f"schedule-{schedule_id}",
                    "source_system": "seller_sprite",
                    "enabled": kwargs["enabled"],
                }
                for schedule_id in kwargs["schedule_ids"]
            ],
        }


def _runtime():
    storage = SimpleNamespace(settings=SimpleNamespace(enabled=False))
    runtime = PrefetchMcpRuntime(storage, SimpleNamespace(), SimpleNamespace())
    runtime.repository = _FakeRepository()
    runtime._require_owner = lambda: "owner@example.com"
    return runtime


def test_create_schedule_normalizes_request_without_credentials():
    """创建工具应规范化来源参数并写入当前用户审计字段。"""
    runtime = _runtime()

    result = asyncio.run(
        runtime.prefetch_schedule_create(
            name="每日商品",
            source_system="keepa",
            scenario="product",
            params={"asin": "B0TEST"},
            site="us",
            run_time="6:30",
        )
    )

    assert result["success"] is True
    assert result["data"]["execution_runtime"] == "mcp"
    assert runtime.repository.created["created_by"] == "owner@example.com"
    assert runtime.repository.created["request"] == {
        "params": {"asin": "B0TEST"},
        "site": "US",
        "export_format": "json",
    }
    assert runtime.repository.created["run_time"] == "06:30:00"


def test_create_schedule_rejects_secret_before_repository_write():
    """敏感字段错误属于用户输入，不生成自动反馈草案。"""
    runtime = _runtime()

    result = asyncio.run(
        runtime.prefetch_schedule_create(
            name="非法计划",
            source_system="google_trends",
            scenario="trends",
            params={"q": "charger", "refreshToken": "secret"},
        )
    )

    assert result["success"] is False
    assert "feedback" not in result
    assert runtime.repository.created is None


def test_enable_schedules_is_a_convenient_bulk_review_action():
    runtime = _runtime()

    result = asyncio.run(runtime.prefetch_schedule_enable([3, 7]))

    assert result["success"] is True
    assert result["data"]["enabled"] is True
    assert result["data"]["changed_count"] == 2
    assert result["data"]["active_runs_unchanged"] is True
    assert runtime.repository.enabled_change == {
        "schedule_ids": [3, 7],
        "created_by": "owner@example.com",
        "enabled": True,
    }
    assert all(
        schedule["execution_runtime"] == "collector"
        for schedule in result["data"]["schedules"]
    )


def test_disable_schedules_uses_same_bulk_action():
    runtime = _runtime()

    result = asyncio.run(runtime.prefetch_schedule_disable([3, 7]))

    assert result["success"] is True
    assert result["data"]["enabled"] is False
    assert runtime.repository.enabled_change["enabled"] is False
