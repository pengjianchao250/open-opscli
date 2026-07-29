"""卖家精灵任务监督后端公共契约测试。"""

import asyncio
import json
from pathlib import Path

from opscli.seller_sprite import mcp_bundle
from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.models import (
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


class _SingleAccountProvider:
    """提供一个稳定公共账号。"""

    def __init__(self) -> None:
        self.account = SellerSpriteAccount(
            name="account-1",
            username="user@example.com",
            password="secret",
        )

    def list_accounts(self, *, refresh=False):
        """返回固定账号列表。"""
        return [self.account]

    def get_default(self, *, refresh=False):
        """返回固定默认账号。"""
        return self.account


class _PostClaimContextFailureStore(SellerSpriteTaskQueueStore):
    """仅在首条任务已领取后模拟上下文读取失败。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failed_once = False

    def get_task_context(self, job_id: str):
        """首条任务进入 running 后抛出一次设置异常。"""
        if (
            job_id == "setup-failure"
            and not self.failed_once
            and self.get_status(job_id)["state"] == "running"
        ):
            self.failed_once = True
            raise RuntimeError("post-claim context failure")
        return super().get_task_context(job_id)


class _PostClaimRequestFailureStore(SellerSpriteTaskQueueStore):
    """仅在首条任务已领取后模拟请求读取失败。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failed_once = False

    def get_request(self, job_id: str):
        """首条任务读取请求时抛出一次异常。"""
        if job_id == "request-failure" and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("post-claim request failure")
        return super().get_request(job_id)


class _FlakyHeartbeatStore(SellerSpriteTaskQueueStore):
    """首轮续租失败、后续恢复的心跳仓储。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.renew_calls = 0

    def renew_active_execution_leases(self, **kwargs):
        """首轮模拟瞬时 SQLite 故障。"""
        self.renew_calls += 1
        if self.renew_calls == 1:
            raise RuntimeError("transient heartbeat failure")
        return super().renew_active_execution_leases(**kwargs)


def _request(job_id: str) -> SellerSpriteScenarioRequest:
    """构造监督测试任务。"""
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="US",
        period="30d",
        params={"asin": "B0TEST1234"},
        job_id=job_id,
        export_format="json",
    )


def _manager_factory(**kwargs):
    """构造立即成功且兼容旧工厂协议的执行器。"""

    class Manager:
        async def run(self, request):
            root_dir = Path(kwargs["settings"].output_dir) / str(request.job_id)
            root_dir.mkdir(parents=True, exist_ok=True)
            return SellerSpriteScenarioResult.empty(
                job_id=str(request.job_id),
                scenario=request.scenario,
                site=request.site,
                period=request.period,
                root_dir=root_dir,
                params_path=root_dir / "params.json",
                raw_path=root_dir / "raw.json",
                result_path=root_dir / "result.json",
            )

    return Manager()


async def _wait_for_state(scheduler, job_id: str, expected: str) -> dict:
    """等待任务到达指定终态。"""
    for _ in range(100):
        status = scheduler.job_status(job_id)
        if status["state"] == expected:
            return status
        await asyncio.sleep(0.01)
    raise AssertionError(f"{job_id} 未到达 {expected}")


def test_scheduler_contains_post_claim_setup_failure_and_continues(tmp_path: Path):
    """领取后的设置失败应结束当前任务，且工作槽继续消费下一条。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        store = _PostClaimContextFailureStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=_SingleAccountProvider(),
            manager_factory=_manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("setup-failure"))
        await scheduler.enqueue(_request("after-setup-failure"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "setup-failure", "failed")
        succeeded = await _wait_for_state(
            scheduler,
            "after-setup-failure",
            "succeeded",
        )

        assert failed["error"] == {
            "code": "RuntimeError",
            "message": "post-claim context failure",
        }
        assert succeeded["state"] == "succeeded"
        assert scheduler.generic_worker_count == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_contains_post_claim_request_failure_and_continues(tmp_path: Path):
    """领取后的请求读取失败应结束当前任务，且工作槽继续消费下一条。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        store = _PostClaimRequestFailureStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=_SingleAccountProvider(),
            manager_factory=_manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("request-failure"))
        await scheduler.enqueue(_request("after-request-failure"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "request-failure", "failed")
        succeeded = await _wait_for_state(
            scheduler,
            "after-request-failure",
            "succeeded",
        )

        assert failed["error"] == {
            "code": "RuntimeError",
            "message": "post-claim request failure",
        }
        assert succeeded["state"] == "succeeded"
        assert scheduler.generic_worker_count == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_contains_manager_factory_failure_and_continues(tmp_path: Path):
    """领取后的执行器构造失败应结束当前任务，且工作槽继续消费下一条。"""
    factory_calls = 0

    def fail_once_manager_factory(**kwargs):
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            raise RuntimeError("post-claim manager factory failure")
        return _manager_factory(**kwargs)

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=_SingleAccountProvider(),
            manager_factory=fail_once_manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("manager-failure"))
        await scheduler.enqueue(_request("after-manager-failure"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "manager-failure", "failed")
        succeeded = await _wait_for_state(
            scheduler,
            "after-manager-failure",
            "succeeded",
        )

        assert failed["error"] == {
            "code": "RuntimeError",
            "message": "post-claim manager factory failure",
        }
        assert succeeded["state"] == "succeeded"
        assert scheduler.generic_worker_count == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_publishes_runtime_heartbeat_and_marks_stopped(tmp_path: Path):
    """调度器启动和关闭应发布可查询的真实生命周期与容量。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(
                output_dir=tmp_path,
                task_heartbeat_seconds=0.01,
            ),
            account_provider=_SingleAccountProvider(),
            manager_factory=_manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )

        await scheduler.start()
        await asyncio.sleep(0.03)
        running = scheduler.runtime_health()

        assert running["status"] == "ready"
        assert running["checks"]["scheduler"] == "running"
        assert running["runtime"]["lifecycle_state"] == "running"
        assert running["runtime"]["generic_workers_alive"] == 1
        assert running["runtime"]["listing_worker_alive"] == 1
        assert running["runtime"]["generic_available_capacity"] == 1
        assert running["runtime"]["listing_available_capacity"] == 1
        assert running["runtime"]["available_capacity"] == 2
        assert "execution_owner" not in running["runtime"]

        await scheduler.close()
        stopped = scheduler.runtime_health()
        assert stopped["status"] == "not_ready"
        assert stopped["checks"]["scheduler"] == "stopped"
        assert stopped["runtime"]["lifecycle_state"] == "stopped"
        assert stopped["runtime"]["generic_workers_alive"] == 0

    asyncio.run(scenario())


def test_scheduler_old_attempt_cannot_untrack_new_generation(tmp_path: Path):
    """旧 worker 收尾不得删除同任务新代际的租约跟踪。"""
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    scheduler = SellerSpriteTaskScheduler(
        store=SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3"),
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=_SingleAccountProvider(),
        manager_factory=_manager_factory,
        auto_start=False,
    )
    old_attempt_id = scheduler._track_attempt(
        {
            "job_id": "same-job",
            "task_kind": "generic",
            "assigned_account_key": "account-key-1",
            "assignment_generation": 1,
        }
    )
    new_attempt_id = scheduler._track_attempt(
        {
            "job_id": "same-job",
            "task_kind": "generic",
            "assigned_account_key": "account-key-2",
            "assignment_generation": 2,
        }
    )

    assert scheduler._refresh_tracked_attempt(
        {
            "job_id": "same-job",
            "task_kind": "generic",
            "assigned_account_key": "account-key-3",
            "assignment_generation": 3,
        },
        attempt_id=old_attempt_id,
    ) is False
    assert scheduler._untrack_attempt("same-job", attempt_id=old_attempt_id) is False
    assert scheduler._active_attempts["same-job"]["assignment_generation"] == 2
    assert scheduler._untrack_attempt("same-job", attempt_id=new_attempt_id) is True
    assert "same-job" not in scheduler._active_attempts


def test_scheduler_shared_account_busy_removes_both_task_kind_capacities(tmp_path: Path):
    """Generic 与 Listing 共用账号时，任一任务运行都应让两个槽暂不可领取。"""
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    class AliveTask:
        def done(self):
            return False

    provider = _SingleAccountProvider()
    account_key = seller_sprite_account_key(provider.account)
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=provider,
        manager_factory=_manager_factory,
        auto_start=False,
    )
    scheduler._generic_worker_tasks["slot-1"] = AliveTask()
    scheduler._generic_worker_accounts["slot-1"] = provider.account
    scheduler._listing_worker_task = AliveTask()
    scheduler._listing_worker_account_key = account_key
    generic_attempt_id = scheduler._track_attempt(
        {
            "job_id": "generic-job",
            "task_kind": "generic",
            "assigned_account_key": account_key,
            "assignment_generation": 1,
        }
    )

    scheduler._publish_runtime_heartbeat(lifecycle_state="running")
    generic_busy = store.get_runtime_heartbeat(scheduler._session_owner_id)
    assert generic_busy["generic_available_capacity"] == 0
    assert generic_busy["listing_available_capacity"] == 0
    assert generic_busy["available_capacity"] == 0

    scheduler._untrack_attempt("generic-job", attempt_id=generic_attempt_id)
    scheduler._track_attempt(
        {
            "job_id": "dedicated-job",
            "task_kind": "generic",
            "assigned_account_key": account_key,
            "assignment_generation": 1,
        },
        capacity_kind=None,
    )
    scheduler._publish_runtime_heartbeat(lifecycle_state="running")
    dedicated_busy = store.get_runtime_heartbeat(scheduler._session_owner_id)
    assert dedicated_busy["generic_available_capacity"] == 0
    assert dedicated_busy["listing_available_capacity"] == 0


def test_scheduler_different_accounts_keep_other_task_kind_capacity(tmp_path: Path):
    """Generic 与 Listing 使用不同账号时，忙碌账号不得吞掉另一账号容量。"""
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    class AliveTask:
        def done(self):
            return False

    provider = _SingleAccountProvider()
    listing_account = SellerSpriteAccount(
        name="listing-account",
        username="listing@example.com",
        password="secret",
    )
    generic_key = seller_sprite_account_key(provider.account)
    listing_key = seller_sprite_account_key(listing_account)
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=provider,
        manager_factory=_manager_factory,
        auto_start=False,
    )
    scheduler._generic_worker_tasks["slot-1"] = AliveTask()
    scheduler._generic_worker_accounts["slot-1"] = provider.account
    scheduler._listing_worker_task = AliveTask()
    scheduler._listing_worker_account_key = listing_key
    scheduler._track_attempt(
        {
            "job_id": "generic-job",
            "task_kind": "generic",
            "assigned_account_key": generic_key,
            "assignment_generation": 1,
        }
    )

    scheduler._publish_runtime_heartbeat(lifecycle_state="running")
    generic_busy = store.get_runtime_heartbeat(scheduler._session_owner_id)
    assert generic_busy["generic_available_capacity"] == 0
    assert generic_busy["listing_available_capacity"] == 1
    assert generic_busy["available_capacity"] == 1


def test_scheduler_capacity_uses_global_running_account_occupancy(tmp_path: Path):
    """其他调度器占用同账号时，本调度器不得发布虚假可领取容量。"""
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    class AliveTask:
        def done(self):
            return False

    provider = _SingleAccountProvider()
    account_key = seller_sprite_account_key(provider.account)
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request("external-running"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "external-running",
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key=account_key,
        assigned_account=provider.account.name,
        worker_key="external-slot",
        execution_owner="external-scheduler",
    )
    assert claimed is not None

    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=provider,
        manager_factory=_manager_factory,
        auto_start=False,
    )
    scheduler._generic_worker_tasks["local-slot"] = AliveTask()
    scheduler._generic_worker_accounts["local-slot"] = provider.account
    scheduler._listing_worker_task = AliveTask()
    scheduler._listing_worker_account_key = account_key

    scheduler._publish_runtime_heartbeat(lifecycle_state="running")

    runtime = store.get_runtime_heartbeat(scheduler._session_owner_id)
    assert runtime["generic_available_capacity"] == 0
    assert runtime["listing_available_capacity"] == 0
    assert runtime["available_capacity"] == 0


def test_scheduler_heartbeat_recovers_after_single_round_failure(tmp_path: Path):
    """单轮续租失败不得结束长期心跳监督。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        store = _FlakyHeartbeatStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(
                output_dir=tmp_path,
                task_heartbeat_seconds=0.01,
            ),
            account_provider=_SingleAccountProvider(),
            manager_factory=_manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )

        await scheduler.start()
        for _ in range(30):
            if store.renew_calls >= 2:
                break
            await asyncio.sleep(0.01)

        assert store.renew_calls >= 2
        assert scheduler._heartbeat_task is not None
        assert not scheduler._heartbeat_task.done()
        assert scheduler.runtime_health()["status"] == "ready"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_reports_queue_error_when_runtime_store_cannot_be_read(tmp_path: Path):
    """运行态读取异常必须报告队列错误，不能伪装成尚未启动。"""
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=_SingleAccountProvider(),
        manager_factory=_manager_factory,
        auto_start=False,
    )

    def fail_runtime_read(_execution_owner):
        raise RuntimeError("database is locked")

    store.get_runtime_heartbeat = fail_runtime_read
    health = scheduler.runtime_health()

    assert health["status"] == "degraded"
    assert health["checks"] == {"queue": "error", "scheduler": "unknown"}
    assert health["runtime"] == {"lifecycle_state": "unknown"}


def test_scheduler_reports_degraded_when_heartbeat_task_dies(tmp_path: Path):
    """运行态仍为 running 但心跳任务终止时必须直接报告 degraded。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        scheduler = SellerSpriteTaskScheduler(
            store=SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3"),
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=_SingleAccountProvider(),
            manager_factory=_manager_factory,
            auto_start=False,
        )
        await scheduler.start()
        heartbeat_task = scheduler._heartbeat_task
        assert heartbeat_task is not None
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        health = scheduler.runtime_health()
        assert health["status"] == "degraded"
        assert health["checks"]["scheduler"] == "heartbeat_failed"
        await scheduler.close()

    asyncio.run(scenario())


def test_mcp_health_uses_live_scheduler_runtime_and_redacts_payloads(monkeypatch):
    """MCP 健康检查应读取实时心跳，并拒绝透传敏感或任意运行态字段。"""

    class Scheduler:
        def __init__(self) -> None:
            self.running = False

        async def start(self):
            self.running = True

        async def close(self):
            self.running = False

        def runtime_health(self):
            if not self.running:
                return {
                    "status": "not_ready",
                    "checks": {"queue": "ok", "scheduler": "stopped"},
                    "runtime": {
                        "lifecycle_state": "stopped",
                        "secret": "credential-value",
                    },
                }
            return {
                "status": "ready",
                "checks": {"queue": "ok", "scheduler": "running"},
                "runtime": {
                    "lifecycle_state": "running",
                    "heartbeat_at": "2026-07-29T12:00:00+00:00",
                    "generic_workers_alive": 2,
                    "listing_worker_alive": 1,
                    "generic_available_capacity": 2,
                    "listing_available_capacity": 1,
                    "available_capacity": 3,
                    "standby_capacity": 4,
                    "last_claim_at": None,
                    "last_progress_at": None,
                    "heartbeat_fresh": True,
                    "execution_owner": "private-owner",
                    "request": {"asin": "B0PRIVATE123"},
                    "path": "C:/private/output",
                    "credential": "credential-value",
                },
            }

    scheduler = Scheduler()
    monkeypatch.setattr(
        "opscli.seller_sprite.services.get_task_scheduler",
        lambda: scheduler,
    )

    async def scenario():
        async with mcp_bundle.lifespan():
            running = await mcp_bundle.health_check()
            assert running == {
                "bundle_id": "seller_sprite",
                "status": "ready",
                "checks": {"queue": "ok", "scheduler": "running"},
                "runtime": {
                    "lifecycle_state": "running",
                    "heartbeat_at": "2026-07-29T12:00:00+00:00",
                    "generic_workers_alive": 2,
                    "listing_worker_alive": 1,
                    "generic_available_capacity": 2,
                    "listing_available_capacity": 1,
                    "available_capacity": 3,
                    "standby_capacity": 4,
                    "last_claim_at": None,
                    "last_progress_at": None,
                    "heartbeat_fresh": True,
                },
            }
            assert "B0PRIVATE123" not in json.dumps(running)
            scheduler.runtime_health = lambda: {
                "status": "degraded",
                "checks": {"queue": "ok", "scheduler": "heartbeat_failed"},
                "runtime": {
                    "lifecycle_state": "running",
                    "heartbeat_fresh": True,
                    "credential": "credential-value",
                },
            }
            degraded = await mcp_bundle.health_check()
            assert degraded == {
                "bundle_id": "seller_sprite",
                "status": "degraded",
                "checks": {"queue": "ok", "scheduler": "heartbeat_failed"},
                "runtime": {
                    "lifecycle_state": "running",
                    "heartbeat_fresh": True,
                },
            }
            scheduler.runtime_health = lambda: {
                "status": "not_ready",
                "checks": {"queue": "ok", "scheduler": "stopped"},
                "runtime": {
                    "lifecycle_state": "stopped",
                    "secret": "credential-value",
                },
            }
            stopped = await mcp_bundle.health_check()
            assert stopped["status"] == "not_ready"
            assert stopped["checks"]["scheduler"] == "stopped"
            assert stopped["runtime"] == {"lifecycle_state": "stopped"}

    asyncio.run(scenario())
