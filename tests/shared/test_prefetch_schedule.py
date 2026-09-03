"""共享预取计划校验、仓储领取和运行时测试。"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from opscli.shared.collection_storage.config import MySqlSettings
from opscli.shared.prefetch_schedule.config import PrefetchScheduleSettings
from opscli.shared.prefetch_schedule.models import PrefetchRunClaim
from opscli.shared.prefetch_schedule.repository import PrefetchScheduleRepository
from opscli.shared.prefetch_schedule.runtime import PrefetchSchedulerRuntime
from opscli.shared.prefetch_schedule.validation import (
    next_daily_run,
    normalize_schedule_request,
)


def test_next_daily_run_uses_schedule_timezone():
    """上海当天时间已过时，应返回次日对应的 UTC 时间。"""
    result = next_daily_run(
        "06:00",
        "Asia/Shanghai",
        after=datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 9, 3, 22, 0)


def test_schedule_request_rejects_nested_credentials():
    """任意层级的凭证字段都不得进入共享计划定义。"""
    with pytest.raises(ValueError, match="禁止保存凭证字段"):
        normalize_schedule_request(
            source_system="keepa",
            scenario="product",
            params={"asin": "B0TEST", "auth": {"api_key": "secret"}},
            site="US",
            period="30d",
            page_size=100,
            export_format="json",
        )


def test_schedule_request_rejects_listing_analysis():
    """Listing Analysis 必须保留用户显式触发边界。"""
    with pytest.raises(ValueError, match="禁止加入预取计划"):
        normalize_schedule_request(
            source_system="seller_sprite",
            scenario="listing-analysis",
            params={"asin": "B0TEST"},
            site="US",
            period="30d",
            page_size=100,
            export_format="json",
        )


def test_seller_sprite_pilot_schedule_fixture_is_valid():
    """试点名单必须保持禁用，并能通过当前计划请求校验。"""
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "prefetch"
        / "seller_sprite_pilot_schedules.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert payload["run_time"] == "06:00"
    assert payload["timezone_name"] == "Asia/Shanghai"
    assert payload["schedules"]
    for schedule in payload["schedules"]:
        source, scenario, request = normalize_schedule_request(
            source_system=schedule["source_system"],
            scenario=schedule["scenario"],
            params=schedule["params"],
            site=schedule["site"],
            period=schedule["period"],
            page_size=schedule["page_size"],
            export_format=schedule["export_format"],
        )
        assert schedule["enabled"] is False
        assert schedule["export_format"] == "xls"
        assert schedule["evidence"]["active_days"] == 14
        assert (
            schedule["evidence"]["account_route"]
            == "requires_shared_pool_verification"
        )
        assert source == "seller_sprite"
        assert scenario == schedule["scenario"]
        assert request["params"] == schedule["params"]


def test_legacy_candidate_export_does_not_require_cache_identity_columns():
    """历史补导 SQL 必须兼容尚未升级缓存指纹列的 v1 数据库。"""
    sql_path = (
        Path(__file__).parents[2]
        / "output"
        / "mcp-usage-analysis"
        / "seller-sprite-prefetch-candidate-export.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")

    assert "request_fingerprint" not in sql
    assert "cache_scope" not in sql
    assert "JSON_EXTRACT(request_params" in sql


def test_repository_claims_only_owned_sources_with_lease():
    """领取 SQL 必须限制来源并同时写入执行 owner 和租约。"""

    class Cursor:
        def __init__(self):
            self.calls = []
            self.lastrowid = 0
            self.phase = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.phase += 1
            self.calls.append((" ".join(sql.split()), params))
            return 1

        def fetchone(self):
            return {
                "run_id": 7,
                "schedule_id": 3,
                "trigger_type": "manual",
                "scheduled_for": datetime(2026, 9, 3, 1, 0),
                "source_system": "keepa",
                "scenario": "product",
                "request_json": '{"params":{"asin":"B0TEST"},"site":"US"}',
            }

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("不应回滚")

        def close(self):
            pass

    connection = Connection()
    repository = PrefetchScheduleRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    claim = repository.claim_next(
        source_systems=("keepa", "google_trends"),
        execution_owner="mcp-owner",
        lease_seconds=60,
        now=datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc),
    )

    assert claim is not None
    assert claim.job_id == "Prefetch-keepa-7"
    select_sql, select_params = connection.cursor_instance.calls[0]
    update_sql, update_params = connection.cursor_instance.calls[1]
    assert "runs.source_system IN (%s, %s)" in select_sql
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert select_params[:2] == ("google_trends", "keepa")
    assert "execution_owner = %s" in update_sql
    assert update_params[0] == "mcp-owner"
    assert connection.committed is True


def test_queue_run_now_copies_schedule_request_snapshot():
    """手动运行必须复制计划请求，后续编辑计划不能改写已排队任务。"""

    class Cursor:
        def __init__(self):
            self.calls = []
            self.lastrowid = 12

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.calls.append((" ".join(sql.split()), params))
            return 1

        def fetchone(self):
            return {
                "id": 3,
                "source_system": "keepa",
                "scenario": "product",
                "request_json": '{"params":{"asin":"B0SNAPSHOT"},"site":"US"}',
            }

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("不应回滚")

        def close(self):
            pass

    connection = Connection()
    repository = PrefetchScheduleRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    run = repository.queue_run_now(
        schedule_id=3,
        created_by="owner@example.com",
        now=datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc),
    )

    insert_sql, insert_params = connection.cursor_instance.calls[1]
    assert "source_system, scenario, request_json" in insert_sql
    assert insert_params[:4] == (
        3,
        "keepa",
        "product",
        '{"params":{"asin":"B0SNAPSHOT"},"site":"US"}',
    )
    assert run["run_id"] == 12
    assert connection.committed is True


def test_enqueue_due_copies_schedule_request_snapshot():
    """到期运行必须把来源、场景和请求快照写入独立运行记录。"""

    class Cursor:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.calls.append((" ".join(sql.split()), params))
            return 1

        def fetchall(self):
            return [
                {
                    "id": 4,
                    "source_system": "google_trends",
                    "scenario": "trends",
                    "request_json": '{"geo":"US","params":{"q":"charger"}}',
                    "run_time": "06:00:00",
                    "timezone": "Asia/Shanghai",
                    "next_run_at": datetime(2026, 9, 3, 1, 0),
                }
            ]

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("不应回滚")

        def close(self):
            pass

    connection = Connection()
    repository = PrefetchScheduleRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    queued = repository.enqueue_due(
        source_systems=("google_trends",),
        now=datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc),
    )

    insert_sql, insert_params = connection.cursor_instance.calls[1]
    assert "source_system, scenario, request_json" in insert_sql
    assert insert_params[:4] == (
        4,
        "google_trends",
        "trends",
        '{"geo":"US","params":{"q":"charger"}}',
    )
    assert queued == 1
    assert connection.committed is True


def test_delete_schedule_rejects_active_runs():
    """存在排队或运行任务时不得级联删除计划及执行记录。"""

    class Cursor:
        def __init__(self):
            self.calls = []
            self.rows = iter(({"id": 5}, {"total": 1}))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.calls.append((" ".join(sql.split()), params))
            return 1

        def fetchone(self):
            return next(self.rows)

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.rolled_back = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            raise AssertionError("活动任务存在时不应提交删除")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    connection = Connection()
    repository = PrefetchScheduleRepository(
        settings=MySqlSettings(),
        connect_factory=lambda: connection,
    )

    with pytest.raises(ValueError, match="仍有排队或运行中的任务"):
        repository.delete_schedule(
            schedule_id=5,
            created_by="owner@example.com",
        )

    assert len(connection.cursor_instance.calls) == 2
    assert connection.rolled_back is True


def test_runtime_executes_claim_and_records_success():
    """运行时只把自己拥有的来源交给对应执行器。"""
    claim = PrefetchRunClaim(
        run_id=9,
        schedule_id=4,
        source_system="keepa",
        scenario="product",
        request={"params": {"asin": "B0TEST"}, "site": "US"},
        trigger_type="scheduled",
        scheduled_for=datetime(2026, 9, 3, 1, 0),
    )

    class Repository:
        def __init__(self):
            self.claim = claim
            self.finished = []
            self.sources = []

        def enqueue_due(self, *, source_systems):
            self.sources.append(tuple(source_systems))
            return 1

        def claim_next(self, **kwargs):
            value, self.claim = self.claim, None
            return value

        def finish_run(self, **kwargs):
            self.finished.append(kwargs)

        def extend_lease(self, **kwargs):
            return True

    repository = Repository()

    async def executor(current):
        assert current.job_id == "Prefetch-keepa-9"
        return {"success": True, "data": {"job_id": current.job_id}, "error": None}

    runtime = PrefetchSchedulerRuntime(
        runtime_id="mcp",
        settings=PrefetchScheduleSettings(enabled=True, lease_seconds=60),
        repository=repository,
        executors={"keepa": executor},
    )

    processed = asyncio.run(runtime.process_once())

    assert processed is True
    assert repository.sources == [("keepa",)]
    assert repository.finished[0]["status"] == "succeeded"
    assert repository.finished[0]["source_job_id"] == "Prefetch-keepa-9"
