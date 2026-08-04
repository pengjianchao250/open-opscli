"""卖家精灵持久队列与多账号任务调度器测试。"""

import asyncio
import json
import sqlite3
from pathlib import Path

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteAuthenticationError,
    SellerSpriteConfigError,
)
from opscli.seller_sprite.domain.models import (
    SellerSpriteExportResult,
    SellerSpriteScenarioRequest,
    SellerSpriteScenarioResult,
)
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


def _request(job_id: str, asin: str) -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": asin},
        job_id=job_id,
        export_format="json",
    )


def _branddb_request(job_id: str) -> SellerSpriteScenarioRequest:
    """构造全球商标库不可重放队列请求。"""
    return SellerSpriteScenarioRequest(
        scenario="branddb",
        site="US",
        period="30d",
        params={"text": "ANKER"},
        job_id=job_id,
        export_format="xlsx",
    )


def _listing_request(job_id: str, asin: str) -> SellerSpriteScenarioRequest:
    """构造 Listing Analysis 队列请求。"""
    return SellerSpriteScenarioRequest(
        scenario="listing-analysis",
        site="US",
        period="30d",
        params={"asin": asin, "station": "GLOBAL"},
        job_id=job_id,
        export_format="json",
    )


async def _wait_for_state(scheduler, job_id: str, expected_state: str, *, attempts: int = 50):
    for _ in range(attempts):
        status = scheduler.job_status(job_id)
        if status["state"] == expected_state:
            return status
        await asyncio.sleep(0.02)
    raise AssertionError(f"{job_id} did not reach {expected_state}")


class DummyAccountProvider:
    def get_default(self, *, refresh=False):
        from opscli.seller_sprite.accounts import SellerSpriteAccount

        return SellerSpriteAccount(name="default", username="user@example.com", password="secret")


class ControlledRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings
        self.account_provider = account_provider
        self.jwt = jwt
        self.session_id = session_id
        self.started = []
        self.allow_finish = asyncio.Event()
        self.first_started = asyncio.Event()

    async def run(self, request):
        self.started.append(request.job_id)
        if len(self.started) == 1:
            self.first_started.set()
            await self.allow_finish.wait()
        root_dir = Path(self.settings.output_dir) / str(request.job_id)
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


class TimeoutThenSuccessHarness:
    def __init__(self):
        self.started = []
        self.cancelled = asyncio.Event()

    def manager_factory(self, **kwargs):
        harness = self

        class Manager:
            async def run(self, request):
                harness.started.append(str(request.job_id))
                if str(request.job_id) == "job-timeout":
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        harness.cancelled.set()
                        raise
                return _empty_result(kwargs["settings"], request)

        return Manager()


class HangingRunManager:
    async def run(self, request):
        await asyncio.Event().wait()


class TargetClosedThenSuccessHarness:
    """模拟首条浏览器目标关闭、后续任务正常执行。"""

    def __init__(self):
        self.started = []

    def manager_factory(self, **kwargs):
        harness = self

        class TargetClosedError(Exception):
            """模拟 Playwright/Patchright 目标关闭异常。"""

        class Manager:
            async def run(self, request):
                harness.started.append(str(request.job_id))
                if str(request.job_id) == "job-target-closed":
                    raise TargetClosedError(
                        "Page.unroute: Target page, context or browser has been closed"
                    )
                return _empty_result(kwargs["settings"], request)

        return Manager()


class ImmediateRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings

    async def run(self, request):
        root_dir = Path(self.settings.output_dir) / str(request.job_id)
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


class AuthContextRecordingRunManager(ImmediateRunManager):
    records = []

    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        from opscli.mcp.context import get_current_api_key

        super().__init__(settings=settings, account_provider=account_provider, jwt=jwt, session_id=session_id)
        self.jwt = jwt
        self.session_id = session_id
        self.inherited_api_key = get_current_api_key()

    async def run(self, request):
        self.__class__.records.append(
            (request.job_id, self.jwt, self.session_id, self.inherited_api_key)
        )
        return await super().run(request)


class ResultFileRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings

    async def run(self, request):
        root_dir = Path(self.settings.output_dir) / str(request.job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        result_path = root_dir / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "job_id": str(request.job_id),
                    "row_count": 2,
                    "data": [{"keywords": "flashlight"}],
                    "export": {"path": str(root_dir / "job.json"), "filename": "job.json"},
                }
            ),
            encoding="utf-8",
        )
        return SellerSpriteScenarioResult(
            job_id=str(request.job_id),
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            row_count=2,
            root_dir=str(root_dir),
            params_path=str(root_dir / "params.json"),
            raw_path=str(root_dir / "raw.json"),
            result_path=str(result_path),
            export=None,
            data=[],
            warnings=[],
        )


class SuccessWithExportRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings

    async def run(self, request):
        root_dir = Path(self.settings.output_dir) / str(request.job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        result_path = root_dir / "result.json"
        result_path.write_text(json.dumps({"job_id": str(request.job_id)}), encoding="utf-8")
        export_path = root_dir / "job.xlsx"
        export_path.write_text("demo", encoding="utf-8")
        return SellerSpriteScenarioResult(
            job_id=str(request.job_id),
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            row_count=3,
            root_dir=str(root_dir),
            params_path=str(root_dir / "params.json"),
            raw_path=str(root_dir / "raw.json"),
            result_path=str(result_path),
            export=SellerSpriteExportResult(
                path=str(export_path),
                filename="job.xlsx",
                format="xlsx",
            ),
            data=[],
            warnings=[],
        )


class FailedRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings

    async def run(self, request):
        raise RuntimeError("卖家精灵执行失败")


class AccountErrorRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.account_provider = account_provider

    async def run(self, request):
        self.account_provider.get_default()


class BrokenAccountProvider:
    def get_default(self, *, refresh=False):
        raise RuntimeError("卖家精灵账号不可用")


class ControlledMcpRunManager:
    def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
        self.settings = settings
        self.first_started = asyncio.Event()
        self.allow_finish = asyncio.Event()

    async def run(self, request):
        self.first_started.set()
        await self.allow_finish.wait()
        root_dir = Path(self.settings.output_dir) / str(request.job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        result_path = root_dir / "result.json"
        result_path.write_text(json.dumps({"job_id": str(request.job_id)}), encoding="utf-8")
        export_path = root_dir / "job.json"
        export_path.write_text("demo", encoding="utf-8")
        return SellerSpriteScenarioResult(
            job_id=str(request.job_id),
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            row_count=1,
            root_dir=str(root_dir),
            params_path=str(root_dir / "params.json"),
            raw_path=str(root_dir / "raw.json"),
            result_path=str(result_path),
            export=SellerSpriteExportResult(
                path=str(export_path),
                filename="job.json",
                format="json",
            ),
            data=[],
            warnings=[],
        )


class FailingFinishMcpStore(SellerSpriteTaskQueueStore):
    def finish_task_and_mcp_run_if_current(self, **kwargs):
        raise RuntimeError("MCP 成功态写回失败")


class ProbeErrorStore(SellerSpriteTaskQueueStore):
    def get_mcp_run(self, job_id: str) -> dict[str, str]:
        raise sqlite3.OperationalError("MCP 记录表读取失败")


class FailingMcpCleanupStore(SellerSpriteTaskQueueStore):
    def finish_task_and_mcp_run_if_current(self, **kwargs):
        if kwargs.get("mcp_export_payload") is not None:
            raise RuntimeError("MCP 成功态写回失败")
        return super().finish_task_and_mcp_run_if_current(**kwargs)

    def fail_task_and_mcp_run_if_current(self, **kwargs):
        committed = super().fail_task_and_mcp_run_if_current(**kwargs)
        if kwargs["error_payload"].get("message") == "MCP 成功态写回失败":
            raise RuntimeError("MCP 失败态写回失败")
        return committed


class MultiAccountProvider:
    def __init__(self, count: int):
        self.accounts = [
            SellerSpriteAccount(
                name=f"account-{index}",
                username=f"user-{index}@example.com",
                password=f"secret-{index}",
            )
            for index in range(1, count + 1)
        ]
        self.refresh_calls = 0

    def list_accounts(self, *, refresh=False):
        self.refresh_calls += int(refresh)
        return list(self.accounts)

    def get_default(self, *, refresh=False):
        return self.accounts[0]


class RecoveringAccountProvider(MultiAccountProvider):
    def __init__(self):
        super().__init__(1)
        self.replacement = SellerSpriteAccount(
            name="account-2",
            username="user-2@example.com",
            password="secret-2",
        )

    def list_accounts(self, *, refresh=False):
        if not refresh:
            return list(self.accounts)
        self.refresh_calls += 1
        if self.refresh_calls == 1:
            return list(self.accounts)
        return [*self.accounts, self.replacement]


class ParallelRunHarness:
    def __init__(self, expected_started: int):
        self.expected_started = expected_started
        self.started_accounts = []
        self.all_started = asyncio.Event()
        self.allow_finish = asyncio.Event()

    def manager_factory(self, **kwargs):
        harness = self

        class Manager:
            async def run(self, request):
                account = kwargs["account_provider"].get_default()
                harness.started_accounts.append(account.name)
                if len(harness.started_accounts) >= harness.expected_started:
                    harness.all_started.set()
                await harness.allow_finish.wait()
                return _empty_result(kwargs["settings"], request)

        return Manager()


class FailoverRunHarness:
    def __init__(self, *, fail_all=False):
        self.fail_all = fail_all
        self.attempted_accounts = []

    def manager_factory(self, **kwargs):
        harness = self

        class Manager:
            async def run(self, request):
                account = kwargs["account_provider"].get_default()
                harness.attempted_accounts.append(account.name)
                if harness.fail_all or account.name == "account-1":
                    raise SellerSpriteAuthenticationError("卖家精灵账号登录失败")
                return _empty_result(kwargs["settings"], request)

        return Manager()


def _empty_result(settings, request):
    root_dir = (
        Path(request.attempt_output_dir)
        if request.attempt_output_dir
        else Path(settings.output_dir) / str(request.job_id)
    )
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


def test_scheduler_runs_tasks_in_fifo_order(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        manager = ControlledRunManager(settings=settings, account_provider=DummyAccountProvider())
        submissions = []

        def submit_collection(*, request, result, status):
            submissions.append((request, result, status))

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: manager,
            collection_submitter=submit_collection,
            auto_start=False,
        )

        first = await scheduler.enqueue(_request("job-1", "B07YRMT36L"))
        second = await scheduler.enqueue(_request("job-2", "B00TEST222"))
        assert first["position"] == 1
        assert second["position"] == 2

        await scheduler.start()
        await manager.first_started.wait()

        running = scheduler.job_status("job-1")
        waiting = scheduler.job_status("job-2")
        assert running["state"] == "running"
        assert waiting["state"] == "queued"
        assert waiting["position"] == 1

        manager.allow_finish.set()
        second_done = await _wait_for_state(scheduler, "job-2", "succeeded")

        assert second_done["state"] == "succeeded"
        assert manager.started == ["job-1", "job-2"]
        assert [result.job_id for _, result, _ in submissions] == ["job-1", "job-2"]
        assert all(status["state"] == "succeeded" for _, _, status in submissions)
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_recovers_expired_running_and_continues_queued(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(
            output_dir=tmp_path,
            task_lease_seconds=1,
            task_heartbeat_seconds=0.1,
        )
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        manager = ControlledRunManager(
            settings=settings,
            account_provider=DummyAccountProvider(),
        )
        store.enqueue(
            request=_request("job-interrupted", "B07YRMT36L"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-interrupted",
        )
        store.enqueue(
            request=_request("job-next", "B00TEST222"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-next",
        )
        store.claim_next(
            queue_scope="seller_sprite",
            worker_key="dead-worker",
            assigned_account="default",
            execution_owner="dead-owner",
            lease_seconds=60,
        )
        with sqlite3.connect(tmp_path / "queue.sqlite3") as conn:
            conn.execute(
                "UPDATE seller_sprite_task_queue SET lease_expires_at = ? WHERE job_id = ?",
                ("2000-01-01T00:00:00+00:00", "job-interrupted"),
            )

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: manager,
            auto_start=False,
        )
        await scheduler.start()
        await manager.first_started.wait()
        recovered_running = scheduler.job_status("job-interrupted")
        assert recovered_running["assignment_generation"] == 3
        assert recovered_running["execution_owner"] == scheduler._session_owner_id

        manager.allow_finish.set()
        await _wait_for_state(scheduler, "job-next", "succeeded")
        assert manager.started == ["job-interrupted", "job-next"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_close_requeues_current_running_task(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path, shutdown_timeout_seconds=0.2)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        manager = ControlledRunManager(
            settings=settings,
            account_provider=DummyAccountProvider(),
        )
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: manager,
            auto_start=False,
        )
        await scheduler.enqueue(_request("job-running", "B07YRMT36L"))
        await scheduler.start()
        await manager.first_started.wait()

        generation = scheduler.job_status("job-running")["assignment_generation"]
        await scheduler.close()
        recovered = scheduler.job_status("job-running")

        assert recovered["state"] == "queued"
        assert recovered["retry_reason"] == "service_restart"
        assert recovered["assignment_generation"] == generation + 1
        assert recovered["execution_owner"] is None

    asyncio.run(scenario())


def test_scheduler_times_out_generic_task_and_continues_queue(tmp_path: Path):
    """通用任务超时后应失败、回收账号会话并继续消费下一条任务。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path, task_timeout_seconds=0.02)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(2)
        harness = TimeoutThenSuccessHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        closed_sessions = []

        async def close_account_session(account, *, reason):
            closed_sessions.append((account.name, reason))

        scheduler._close_account_session = close_account_session
        timeout_request = _request("job-timeout", "B07YRMT36L")
        await scheduler.enqueue(timeout_request, session_id="test-session", jwt="test-jwt")
        store.create_mcp_run(timeout_request, "user@example.com")
        await scheduler.enqueue(_request("job-next", "B00TEST222"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-timeout", "failed")
        succeeded = await _wait_for_state(scheduler, "job-next", "succeeded")

        assert failed["error"] == {
            "code": "SELLER_SPRITE_TASK_TIMEOUT",
            "message": "卖家精灵任务执行超过 0.02 秒，已终止",
        }
        assert succeeded["state"] == "succeeded"
        assert harness.started == ["job-timeout", "job-next"]
        assert harness.cancelled.is_set()
        assert closed_sessions == [("account-1", "task_timeout")]
        mcp_run = store.get_mcp_run("job-timeout")
        assert mcp_run["result_state"] == "failed"
        assert mcp_run["error_json"] == failed["error"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_marks_target_closed_failed_and_continues_queue(tmp_path: Path):
    """真实目标关闭错误应形成失败终态，且不能阻断后续任务。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        harness = TargetClosedThenSuccessHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=MultiAccountProvider(1),
            manager_factory=harness.manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("job-target-closed", "B07YRMT36L"))
        await scheduler.enqueue(_request("job-after-target-closed", "B00TEST222"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-target-closed", "failed")
        succeeded = await _wait_for_state(
            scheduler,
            "job-after-target-closed",
            "succeeded",
        )

        assert failed["error"] == {
            "code": "TargetClosedError",
            "message": "Page.unroute: Target page, context or browser has been closed",
        }
        assert succeeded["state"] == "succeeded"
        assert harness.started == ["job-target-closed", "job-after-target-closed"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_times_out_listing_analysis_task(tmp_path: Path):
    """Listing Analysis 本地执行阶段也应受统一任务超时保护。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path, task_timeout_seconds=0.02)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(2)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=lambda **kwargs: HangingRunManager(),
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        closed_sessions = []

        async def close_account_session(account, *, reason):
            closed_sessions.append((account.name, reason))

        scheduler._close_account_session = close_account_session
        await scheduler.enqueue(_listing_request("listing-timeout", "B0LISTING"))

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "listing-timeout", "failed")

        assert failed["error"]["code"] == "SELLER_SPRITE_TASK_TIMEOUT"
        assert closed_sessions == [("account-1", "task_timeout")]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_binds_listing_analysis_to_default_account(tmp_path: Path):
    """Listing Analysis 执行器和队列记录必须绑定同一个默认账号。"""

    async def scenario():
        from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        provider = MultiAccountProvider(2)
        used_accounts = []

        def manager_factory(**kwargs):
            class Manager:
                async def run(self, request):
                    used_accounts.append(kwargs["account_provider"].get_default().name)
                    root_dir = tmp_path / str(request.job_id)
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

        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=provider,
            manager_factory=manager_factory,
            auto_start=False,
        )
        await scheduler.enqueue(_listing_request("listing-account", "B0LISTING"))
        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "listing-account", "succeeded")

        assert used_accounts == ["account-1"]
        assert succeeded["assigned_account"] == "account-1"
        assert store.get_task_account_binding("listing-account") == {
            "assigned_account": "account-1",
            "assigned_account_key": seller_sprite_account_key(provider.accounts[0]),
        }
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_runs_three_accounts_in_parallel_and_keeps_remaining_as_standby(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(5)
        harness = ParallelRunHarness(expected_started=3)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
        )
        for index in range(1, 5):
            await scheduler.enqueue(_request(f"parallel-{index}", f"B0PARALLEL{index}"))

        await scheduler.start()
        await asyncio.wait_for(harness.all_started.wait(), timeout=1)

        running_statuses = [scheduler.job_status(f"parallel-{index}") for index in range(1, 4)]
        assert {status["state"] for status in running_statuses} == {"running"}
        assert {status["assigned_account"] for status in running_statuses} == {
            "account-1",
            "account-2",
            "account-3",
        }
        assert scheduler.job_status("parallel-4")["state"] == "queued"
        assert scheduler.generic_worker_count == 3
        assert scheduler.standby_account_count == 2

        harness.allow_finish.set()
        for index in range(1, 5):
            await _wait_for_state(scheduler, f"parallel-{index}", "succeeded")
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_close_releases_healthy_browser_sessions_and_audits_states(tmp_path: Path):
    """调度器正常关闭应释放健康 browser 会话并记录 closing/closed。"""

    async def scenario():
        from opscli.seller_sprite.browser_route import worker as worker_module
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(1)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.start()
        account = provider.accounts[0]
        worker = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=scheduler._record_browser_session_state_change,
            owner_id=scheduler._session_owner_id,
        )

        class CloseProbe:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        context = CloseProbe()
        worker.mark_session_ready(context=context, page=object())

        await scheduler.close()

        assert context.closed is True
        assert worker_module.get_existing_browser_route_worker(
            settings=settings,
            account=account,
            owner_id=scheduler._session_owner_id,
        ) is None
        states = [
            event["metadata"]["state"]
            for event in store.list_account_events()
            if event["event_type"] == "account_session_state_changed"
        ]
        assert states == ["closed", "closing", "ready", "registered"]

    asyncio.run(scenario())


def test_scheduler_reaps_idle_browser_session_and_next_task_can_recreate_worker(tmp_path: Path):
    """supervisor 应周期回收空闲会话，registry 随后允许懒创建新 worker。"""

    async def scenario():
        from opscli.seller_sprite.browser_route import worker as worker_module
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        worker_module._WORKERS.clear()
        settings = SellerSpriteSettings(
            output_dir=tmp_path,
            browser_idle_ttl_seconds=1,
            browser_max_lifetime_seconds=21600,
        )
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(1)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            auto_start=False,
            poll_interval_seconds=0.01,
            session_reap_interval_seconds=0.01,
        )
        await scheduler.start()
        account = provider.accounts[0]
        original = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=scheduler._record_browser_session_state_change,
            owner_id=scheduler._session_owner_id,
        )

        class CloseProbe:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        context = CloseProbe()
        original.mark_session_ready(context=context, page=object())
        await asyncio.sleep(1.1)

        assert context.closed is True
        assert worker_module.get_existing_browser_route_worker(
            settings=settings,
            account=account,
            owner_id=scheduler._session_owner_id,
        ) is None
        replacement = worker_module.get_browser_route_worker(
            settings=settings,
            account=account,
            state_listener=scheduler._record_browser_session_state_change,
            owner_id=scheduler._session_owner_id,
        )
        assert replacement is not original
        reasons = [
            event["metadata"]["reason"]
            for event in store.list_account_events()
            if event["event_type"] == "account_session_state_changed"
        ]
        assert [reason for reason in reasons if reason == "idle_timeout"] == [
            "idle_timeout",
            "idle_timeout",
        ]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_replaces_failed_working_account_with_cold_standby(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(2)
        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-failover", "B0FAILOVER"))
        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "job-failover", "succeeded")

        assert harness.attempted_accounts == ["account-1", "account-2"]
        assert succeeded["assigned_account"] == "account-2"
        assert succeeded["failover_count"] == 1
        assert Path(succeeded["result_path"]).parent.name == "generation-2"
        assert store.list_account_events(job_id="job-failover")[0]["event_type"] == "account_login_failed"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_does_not_failover_non_replayable_branddb_request(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(2)
        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_branddb_request("job-branddb-no-replay"))
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-branddb-no-replay", "failed")

        assert harness.attempted_accounts == ["account-1"]
        assert failed["failover_count"] == 0
        assert failed["assigned_account"] == "account-1"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_skips_busy_standby_without_leaving_running_task(tmp_path: Path):
    """备用账号被其他调度器占用时，应继续接替且不得遗留无人续租任务。"""

    async def scenario():
        from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class ConflictThenFreeProvider:
            def __init__(self):
                self.accounts = [
                    SellerSpriteAccount(
                        name=f"account-{index}",
                        username=f"user-{index}@example.com",
                        password=f"secret-{index}",
                    )
                    for index in range(1, 4)
                ]

            def list_accounts(self, *, refresh=False):
                return list(self.accounts if refresh else self.accounts[:2])

            def get_default(self, *, refresh=False):
                return self.accounts[0]

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = ConflictThenFreeProvider()
        store.enqueue(
            request=_request("occupied-standby", "B0OCCUPIED"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "occupied-standby",
        )
        occupied = store.claim_next_generic_for_account(
            queue_scope="seller_sprite",
            account_key=seller_sprite_account_key(provider.accounts[1]),
            assigned_account=provider.accounts[1].name,
            worker_key="external-worker",
            execution_owner="external-scheduler",
        )
        assert occupied is not None

        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("job-failover-conflict", "B0FAILOVER"))
        await scheduler.start()
        succeeded = await _wait_for_state(
            scheduler,
            "job-failover-conflict",
            "succeeded",
            attempts=100,
        )

        assert harness.attempted_accounts == ["account-1", "account-3"]
        assert succeeded["assigned_account"] == "account-3"
        assert succeeded["failover_count"] == 1
        assert store.get_status("occupied-standby")["state"] == "running"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_stale_failover_keeps_new_generation_tracked(tmp_path: Path):
    """旧代际认证失败不得耗尽账号池、关新会话或删除新代际续租。"""

    async def scenario():
        from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(4)
        scheduler = None
        new_attempt_id = None

        def manager_factory(**_kwargs):
            class Manager:
                async def run(self, _request):
                    nonlocal new_attempt_id
                    assert scheduler is not None
                    assert store.reset_running_tasks() == 1
                    claimed_new = store.claim_next_generic_for_account(
                        queue_scope="seller_sprite",
                        account_key=seller_sprite_account_key(provider.accounts[1]),
                        assigned_account=provider.accounts[1].name,
                        worker_key="new-worker",
                        execution_owner=scheduler._session_owner_id,
                    )
                    assert claimed_new is not None
                    new_attempt_id = scheduler._track_attempt(claimed_new)
                    raise SellerSpriteAuthenticationError("旧代际登录失败")

            return Manager()

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=manager_factory,
            auto_start=False,
        )
        scheduler._account_pool.load(provider.accounts)
        store.enqueue(
            request=_request("job-stale-failover", "B0STALE"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-stale-failover",
        )
        claimed_old = store.claim_next_generic_for_account(
            queue_scope="seller_sprite",
            account_key=seller_sprite_account_key(provider.accounts[0]),
            assigned_account=provider.accounts[0].name,
            worker_key="old-worker",
            execution_owner=scheduler._session_owner_id,
        )
        assert claimed_old is not None
        old_attempt_id = scheduler._track_attempt(claimed_old)
        closed_accounts = []

        async def record_close(account, *, reason):
            closed_accounts.append((account.name, reason))

        scheduler._close_account_session = record_close
        replacement = await scheduler._run_generic_job(
            claimed=claimed_old,
            account=provider.accounts[0],
            worker_key="old-worker",
            attempt_id=old_attempt_id,
        )

        assert replacement is None
        assert new_attempt_id is not None
        assert provider.refresh_calls == 1
        assert closed_accounts == []
        assert [account.name for account in scheduler._account_pool.working_accounts] == [
            "account-1",
            "account-2",
            "account-3",
        ]
        assert [account.name for account in scheduler._account_pool.standby_accounts] == [
            "account-4"
        ]
        assert scheduler._untrack_attempt(
            "job-stale-failover",
            attempt_id=old_attempt_id,
        ) is False
        tracked = scheduler._active_attempts["job-stale-failover"]
        assert tracked["attempt_id"] == new_attempt_id
        assert tracked["assignment_generation"] == 3
        assert store.renew_active_execution_leases(
            execution_owner=scheduler._session_owner_id,
            attempts=list(scheduler._active_attempts.values()),
            lease_seconds=60,
        ) == 1
        status = store.get_status("job-stale-failover")
        assert status["state"] == "running"
        assert status["assignment_generation"] == 3
        assert status["assigned_account"] == "account-2"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_current_generation_when_all_standby_accounts_are_busy(
    tmp_path: Path,
):
    """所有备用账号均被占用时，应原子失败当前代际并清理租约。"""

    async def scenario():
        from opscli.seller_sprite.services.account_pool import seller_sprite_account_key
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class BusyStandbyProvider:
            def __init__(self):
                self.accounts = [
                    SellerSpriteAccount(
                        name=f"account-{index}",
                        username=f"user-{index}@example.com",
                        password=f"secret-{index}",
                    )
                    for index in range(1, 4)
                ]

            def list_accounts(self, *, refresh=False):
                return list(self.accounts if refresh else self.accounts[:2])

            def get_default(self, *, refresh=False):
                return self.accounts[0]

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = BusyStandbyProvider()
        for index, account in enumerate(provider.accounts[1:], start=2):
            job_id = f"occupied-standby-{index}"
            store.enqueue(
                request=_request(job_id, f"B0OCCUPIED{index}"),
                queue_scope="seller_sprite",
                root_dir=tmp_path / job_id,
            )
            occupied = store.claim_next_generic_for_account(
                queue_scope="seller_sprite",
                account_key=seller_sprite_account_key(account),
                assigned_account=account.name,
                worker_key=f"external-worker-{index}",
                execution_owner="external-scheduler",
            )
            assert occupied is not None

        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(_request("job-failover-exhausted", "B0FAILOVER"))
        await scheduler.start()
        failed = await _wait_for_state(
            scheduler,
            "job-failover-exhausted",
            "failed",
            attempts=100,
        )

        assert harness.attempted_accounts == ["account-1"]
        assert failed["error"]["code"] == "SELLER_SPRITE_ALL_STANDBY_BUSY"
        assert failed["failover_count"] == 0
        assert failed["execution_owner"] is None
        assert failed["heartbeat_at"] is None
        assert failed["lease_expires_at"] is None
        assert "job-failover-exhausted" not in scheduler._active_attempts
        assert [
            store.get_status(f"occupied-standby-{index}")["state"]
            for index in range(2, 4)
        ] == ["running", "running"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_does_not_failover_for_non_authentication_config_error(tmp_path: Path):
    """请求参数或导出配置错误不能误伤健康账号，也不能触发备用接替。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class ConfigErrorHarness:
            def __init__(self):
                self.accounts = []

            def manager_factory(self, **kwargs):
                harness = self

                class Manager:
                    async def run(self, request):
                        harness.accounts.append(kwargs["account_provider"].get_default().name)
                        raise SellerSpriteConfigError("不支持的导出格式")

                return Manager()

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(2)
        harness = ConfigErrorHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-config-error", "B0CONFIGERR"))
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-config-error", "failed")

        assert harness.accounts == ["account-1"]
        assert failed["error"]["code"] == "SELLER_SPRITE_CONFIG_ERROR"
        assert store.list_account_events(job_id="job-config-error") == []
        assert scheduler.generic_worker_count == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_retires_excess_idle_workers_after_account_refresh(tmp_path: Path):
    """账号接口从五个缩至三个时，空闲工作槽应收敛为两个。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path, account_cache_ttl_seconds=1)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(5)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            auto_start=False,
            poll_interval_seconds=0.01,
        )

        await scheduler.start()
        assert scheduler.generic_worker_count == 3
        provider.accounts = provider.accounts[:3]
        await asyncio.sleep(1.15)

        assert scheduler.generic_worker_count == 2
        assert scheduler.standby_account_count == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_closes_failed_slot_when_no_standby_account_exists(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = MultiAccountProvider(1)
        harness = FailoverRunHarness(fail_all=True)
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-no-standby", "B0NOSTANDBY1"))
        await scheduler.enqueue(_request("job-stays-queued", "B0NOSTANDBY2"))
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-no-standby", "failed")
        await asyncio.sleep(0.05)

        assert failed["error"]["code"] == "SELLER_SPRITE_ALL_ACCOUNTS_AUTH_FAILED"
        assert scheduler.job_status("job-stays-queued")["state"] == "queued"
        assert scheduler.generic_worker_count == 0
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_keeps_reassigned_task_running_when_quarantine_write_fails(
    tmp_path: Path,
):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class QuarantineFailingStore(SellerSpriteTaskQueueStore):
            def quarantine_account(self, **kwargs):
                raise OSError("quarantine store unavailable")

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = QuarantineFailingStore(db_path=tmp_path / "queue.sqlite3")
        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=MultiAccountProvider(2),
            manager_factory=harness.manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-quarantine-write-failed", "B0FAILOVER"))
        await scheduler.start()
        succeeded = await _wait_for_state(
            scheduler,
            "job-quarantine-write-failed",
            "succeeded",
        )

        assert harness.attempted_accounts == ["account-1", "account-2"]
        assert succeeded["assigned_account"] == "account-2"
        assert succeeded["failover_count"] == 1
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_reports_account_source_failure_when_failover_refresh_fails(
    tmp_path: Path,
):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class RefreshFailureProvider(MultiAccountProvider):
            def list_accounts(self, *, refresh=False):
                if refresh:
                    raise RuntimeError("remote account source unavailable")
                return super().list_accounts(refresh=refresh)

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=RefreshFailureProvider(1),
            manager_factory=FailoverRunHarness(fail_all=True).manager_factory,
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-source-failed", "B0SOURCEFAIL"))
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-source-failed", "failed")

        assert failed["error"]["code"] == "SELLER_SPRITE_ACCOUNT_SOURCE_UNAVAILABLE"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_queued_task_when_remote_source_has_no_eligible_account(
    tmp_path: Path,
):
    async def scenario():
        from opscli.seller_sprite.domain.exceptions import (
            SellerSpriteNoEligibleAccountError,
        )
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class EmptyRemoteProvider:
            def list_accounts(self, *, refresh=False):
                raise SellerSpriteNoEligibleAccountError(
                    "卖家精灵远程账号源没有可用账号"
                )

            def get_default(self, *, refresh=False):
                raise SellerSpriteNoEligibleAccountError(
                    "卖家精灵远程账号源没有可用账号"
                )

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=EmptyRemoteProvider(),
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-no-eligible", "B0NOELIGIBLE"))
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-no-eligible", "failed")

        assert failed["error"]["code"] == "SELLER_SPRITE_NO_ELIGIBLE_ACCOUNT"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_rebuilds_closed_slot_when_account_refresh_returns_new_account(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path, account_cache_ttl_seconds=1)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        provider = RecoveringAccountProvider()
        harness = FailoverRunHarness()
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=provider,
            manager_factory=harness.manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )

        await scheduler.enqueue(_request("job-closes-slot", "B0CLOSESLOT"))
        await scheduler.enqueue(_request("job-after-new-account", "B0NEWACCOUNT"))
        await scheduler.start()
        await _wait_for_state(scheduler, "job-closes-slot", "failed")
        succeeded = await _wait_for_state(
            scheduler,
            "job-after-new-account",
            "succeeded",
            attempts=100,
        )

        assert succeeded["assigned_account"] == "account-2"
        assert provider.refresh_calls >= 2
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_start_does_not_requeue_running_task_claimed_by_other_instance(tmp_path: Path):
    """普通 start 不得修改另一实例已经领取的 running 行。"""

    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        db_path = tmp_path / "queue.sqlite3"
        first_store = SellerSpriteTaskQueueStore(db_path=db_path)
        second_store = SellerSpriteTaskQueueStore(db_path=db_path)
        first_store.enqueue(
            request=_request("job-running", "B07YRMT36L"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-running",
        )
        first_store.enqueue(
            request=_request("job-queued", "B00TEST222"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-queued",
        )
        first_store.claim_next(
            queue_scope="seller_sprite",
            worker_key="other-worker",
            assigned_account="default",
        )

        scheduler = SellerSpriteTaskScheduler(
            store=second_store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("已有 running 时不得领取 queued")
            ),
            auto_start=False,
        )

        await scheduler.start()
        await asyncio.sleep(0.05)

        assert first_store.get_status("job-running")["state"] == "running"
        assert first_store.get_status("job-queued")["state"] == "queued"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_uses_each_tasks_auth_without_inheriting_first_request_context(tmp_path: Path):
    async def scenario():
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.context import mcp_request_ctx
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        AuthContextRecordingRunManager.records = []
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: AuthContextRecordingRunManager(**kwargs),
        )
        first_credential_dir = tmp_path / "credentials-user-a"
        second_credential_dir = tmp_path / "credentials-user-b"
        first_store = CredentialStore(base_dir=first_credential_dir)
        first_store.save_session("session-user-a", "a@example.com", "2099-01-01T00:00:00+00:00")
        first_store.save_token("ops", "jwt-user-a", 3600)
        second_store = CredentialStore(base_dir=second_credential_dir)
        second_store.save_session("session-user-b", "b@example.com", "2099-01-01T00:00:00+00:00")
        second_store.save_token("ops", "jwt-user-b", 3600)

        first_context = mcp_request_ctx.set({"api_key": "mcp-key-user-a"})
        try:
            await scheduler.enqueue(
                _request("job-user-a", "B07YRMT36L"),
                credential_scope=str(first_credential_dir),
            )
        finally:
            mcp_request_ctx.reset(first_context)

        second_context = mcp_request_ctx.set({"api_key": "mcp-key-user-b"})
        try:
            await scheduler.enqueue(
                _request("job-user-b", "B00TEST222"),
                credential_scope=str(second_credential_dir),
            )
        finally:
            mcp_request_ctx.reset(second_context)

        await _wait_for_state(scheduler, "job-user-b", "succeeded")

        assert AuthContextRecordingRunManager.records == [
            ("job-user-a", "jwt-user-a", "session-user-a", None),
            ("job-user-b", "jwt-user-b", "session-user-b", None),
        ]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_uses_explicit_task_auth_from_memory_without_persisting_secrets(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        AuthContextRecordingRunManager.records = []
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: AuthContextRecordingRunManager(**kwargs),
        )

        await scheduler.enqueue(
            _request("job-explicit-auth", "B07YRMT36L"),
            credential_scope=str(tmp_path / "empty-credential-scope"),
            session_id="explicit-session",
            jwt="explicit-jwt",
        )
        await _wait_for_state(scheduler, "job-explicit-auth", "succeeded")

        assert AuthContextRecordingRunManager.records == [
            ("job-explicit-auth", "explicit-jwt", "explicit-session", None),
        ]
        assert store.get_task_context("job-explicit-auth") == {
            "credential_scope": None,
            "runtime_auth_required": False,
            "expected_user_email": None,
            "session_id": None,
            "jwt": None,
        }
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_closed_when_credential_scope_has_no_session(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            manager_factory=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("缺凭证时不应创建 Manager")
            ),
        )
        request = _request("job-missing-auth", "B07YRMT36L")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.enqueue(
            request,
            credential_scope=str(tmp_path / "empty-credential-scope"),
        )
        failed = await _wait_for_state(scheduler, "job-missing-auth", "failed")

        assert failed["error"]["code"] == "SELLER_SPRITE_CONFIG_ERROR"
        assert "凭证作用域未登录" in failed["error"]["message"]
        assert store.get_mcp_run("job-missing-auth")["result_state"] == "failed"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_closed_after_restart_loses_explicit_runtime_auth(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        first_scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        request = _request("job-restart-explicit-auth", "B07YRMT36L")
        store.create_mcp_run(request, "user@example.com")
        await first_scheduler.enqueue(
            request,
            credential_scope=str(tmp_path / "credentials-user"),
            session_id="explicit-session",
            jwt="explicit-jwt",
        )

        restarted_scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        await restarted_scheduler.start()
        failed = await _wait_for_state(restarted_scheduler, "job-restart-explicit-auth", "failed")

        assert "显式任务凭证已随服务重启丢失" in failed["error"]["message"]
        first_scheduler._prune_runtime_auth()
        assert first_scheduler._runtime_auth == {}
        await restarted_scheduler.close()

    asyncio.run(scenario())


def test_scheduler_rejects_credential_scope_owned_by_another_user(tmp_path: Path):
    async def scenario():
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        credential_dir = tmp_path / "credentials-user-b"
        credential_store = CredentialStore(base_dir=credential_dir)
        credential_store.save_session(
            "session-user-b",
            "b@example.com",
            "2099-01-01T00:00:00+00:00",
        )
        credential_store.save_token("ops", "jwt-user-b", 3600)
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        request = _request("job-user-mismatch", "B07YRMT36L")
        await scheduler.enqueue(
            request,
            credential_scope=str(credential_dir),
            expected_user_email="a@example.com",
        )

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-user-mismatch", "failed")

        assert "凭证用户与提交用户不一致" in failed["error"]["message"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_uses_each_tasks_auth_without_inheriting_first_request_context(tmp_path: Path):
    async def scenario():
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.context import mcp_request_ctx
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        AuthContextRecordingRunManager.records = []
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: AuthContextRecordingRunManager(**kwargs),
        )
        first_credential_dir = tmp_path / "credentials-user-a"
        second_credential_dir = tmp_path / "credentials-user-b"
        first_store = CredentialStore(base_dir=first_credential_dir)
        first_store.save_session("session-user-a", "a@example.com", "2099-01-01T00:00:00+00:00")
        first_store.save_token("ops", "jwt-user-a", 3600)
        second_store = CredentialStore(base_dir=second_credential_dir)
        second_store.save_session("session-user-b", "b@example.com", "2099-01-01T00:00:00+00:00")
        second_store.save_token("ops", "jwt-user-b", 3600)

        first_context = mcp_request_ctx.set({"api_key": "mcp-key-user-a"})
        try:
            await scheduler.enqueue(
                _request("job-user-a", "B07YRMT36L"),
                credential_scope=str(first_credential_dir),
            )
        finally:
            mcp_request_ctx.reset(first_context)

        second_context = mcp_request_ctx.set({"api_key": "mcp-key-user-b"})
        try:
            await scheduler.enqueue(
                _request("job-user-b", "B00TEST222"),
                credential_scope=str(second_credential_dir),
            )
        finally:
            mcp_request_ctx.reset(second_context)

        await _wait_for_state(scheduler, "job-user-b", "succeeded")

        assert AuthContextRecordingRunManager.records == [
            ("job-user-a", "jwt-user-a", "session-user-a", None),
            ("job-user-b", "jwt-user-b", "session-user-b", None),
        ]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_uses_explicit_task_auth_from_memory_without_persisting_secrets(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        AuthContextRecordingRunManager.records = []
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: AuthContextRecordingRunManager(**kwargs),
        )

        await scheduler.enqueue(
            _request("job-explicit-auth", "B07YRMT36L"),
            credential_scope=str(tmp_path / "empty-credential-scope"),
            session_id="explicit-session",
            jwt="explicit-jwt",
        )
        await _wait_for_state(scheduler, "job-explicit-auth", "succeeded")

        assert AuthContextRecordingRunManager.records == [
            ("job-explicit-auth", "explicit-jwt", "explicit-session", None),
        ]
        assert store.get_task_context("job-explicit-auth") == {
            "credential_scope": None,
            "runtime_auth_required": False,
            "expected_user_email": None,
            "session_id": None,
            "jwt": None,
        }
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_closed_when_credential_scope_has_no_session(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            manager_factory=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("缺凭证时不应创建 Manager")
            ),
        )
        request = _request("job-missing-auth", "B07YRMT36L")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.enqueue(
            request,
            credential_scope=str(tmp_path / "empty-credential-scope"),
        )
        failed = await _wait_for_state(scheduler, "job-missing-auth", "failed")

        assert failed["error"]["code"] == "SELLER_SPRITE_CONFIG_ERROR"
        assert "凭证作用域未登录" in failed["error"]["message"]
        assert store.get_mcp_run("job-missing-auth")["result_state"] == "failed"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_closed_after_restart_loses_explicit_runtime_auth(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        first_scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        request = _request("job-restart-explicit-auth", "B07YRMT36L")
        store.create_mcp_run(request, "user@example.com")
        await first_scheduler.enqueue(
            request,
            credential_scope=str(tmp_path / "credentials-user"),
            session_id="explicit-session",
            jwt="explicit-jwt",
        )

        restarted_scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        await restarted_scheduler.start()
        failed = await _wait_for_state(restarted_scheduler, "job-restart-explicit-auth", "failed")

        assert "显式任务凭证已随服务重启丢失" in failed["error"]["message"]
        first_scheduler._prune_runtime_auth()
        assert first_scheduler._runtime_auth == {}
        await restarted_scheduler.close()

    asyncio.run(scenario())


def test_scheduler_rejects_credential_scope_owned_by_another_user(tmp_path: Path):
    async def scenario():
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        credential_dir = tmp_path / "credentials-user-b"
        credential_store = CredentialStore(base_dir=credential_dir)
        credential_store.save_session(
            "session-user-b",
            "b@example.com",
            "2099-01-01T00:00:00+00:00",
        )
        credential_store.save_token("ops", "jwt-user-b", 3600)
        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(store=store, settings=settings, auto_start=False)
        request = _request("job-user-mismatch", "B07YRMT36L")
        await scheduler.enqueue(
            request,
            credential_scope=str(credential_dir),
            expected_user_email="a@example.com",
        )

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-user-mismatch", "failed")

        assert "凭证用户与提交用户不一致" in failed["error"]["message"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_job_status_merges_result_file_after_success(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: ResultFileRunManager(**kwargs),
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-result", "B07YRMT36L"))
        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "job-result", "succeeded")

        assert succeeded["row_count"] == 2
        assert succeeded["data"][0]["keywords"] == "flashlight"
        assert succeeded["export"]["filename"] == "job.json"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_updates_existing_mcp_run_to_succeeded(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: SuccessWithExportRunManager(**kwargs),
            auto_start=False,
        )

        request = _request("job-mcp-success", "B07YRMT36L")
        await scheduler.enqueue(request, session_id="test-session", jwt="test-jwt")
        created = store.create_mcp_run(request, "user@example.com")

        assert created["result_state"] == "queued"
        assert created["started_at"] is None
        assert created["finished_at"] is None

        await scheduler.start()
        await _wait_for_state(scheduler, "job-mcp-success", "succeeded")

        mcp_run = store.get_mcp_run("job-mcp-success")
        assert mcp_run["result_state"] == "succeeded"
        assert mcp_run["result_row_count"] == 3
        assert mcp_run["result_export_format"] == "xlsx"
        assert mcp_run["result_export_filename"] == "job.xlsx"
        assert mcp_run["result_export_job_id"] == "job-mcp-success"
        assert mcp_run["started_at"] is not None
        assert mcp_run["finished_at"] is not None
        assert mcp_run["error_json"] is None
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_marks_existing_mcp_run_running_before_finish(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        manager = ControlledMcpRunManager(settings=settings, account_provider=DummyAccountProvider())
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: manager,
            auto_start=False,
        )

        request = _request("job-mcp-running", "B07YRMT36L")
        await scheduler.enqueue(request, session_id="test-session", jwt="test-jwt")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.start()
        await manager.first_started.wait()

        mcp_run = store.get_mcp_run("job-mcp-running")
        assert mcp_run["result_state"] == "running"
        assert mcp_run["started_at"] is not None
        assert mcp_run["finished_at"] is None

        manager.allow_finish.set()
        await _wait_for_state(scheduler, "job-mcp-running", "succeeded")
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_updates_existing_mcp_run_to_failed(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: FailedRunManager(**kwargs),
            auto_start=False,
        )

        request = _request("job-mcp-failed", "B07YRMT36L")
        await scheduler.enqueue(request, session_id="test-session", jwt="test-jwt")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.start()
        await _wait_for_state(scheduler, "job-mcp-failed", "failed")

        mcp_run = store.get_mcp_run("job-mcp-failed")
        assert mcp_run["result_state"] == "failed"
        assert mcp_run["started_at"] is not None
        assert mcp_run["finished_at"] is not None
        assert mcp_run["error_json"]["code"] == "RuntimeError"
        assert mcp_run["error_json"]["message"] == "卖家精灵执行失败"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_marks_task_failed_when_account_unavailable(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=BrokenAccountProvider(),
            manager_factory=lambda **kwargs: AccountErrorRunManager(**kwargs),
            auto_start=False,
        )

        request = _request("job-account-error", "B07YRMT36L")
        await scheduler.enqueue(request, session_id="test-session", jwt="test-jwt")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-account-error", "failed")

        assert failed["error"]["code"] == "RuntimeError"
        assert failed["error"]["message"] == "卖家精灵账号不可用"
        mcp_run = store.get_mcp_run("job-account-error")
        assert mcp_run["result_state"] == "failed"
        assert mcp_run["error_json"]["message"] == "卖家精灵账号不可用"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_job_when_existing_mcp_run_success_update_fails(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = FailingFinishMcpStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: SuccessWithExportRunManager(**kwargs),
            auto_start=False,
        )

        request = _request("job-mcp-finish-error", "B07YRMT36L")
        await scheduler.enqueue(request, session_id="test-session", jwt="test-jwt")
        store.create_mcp_run(request, "user@example.com")

        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-mcp-finish-error", "failed")

        assert failed["error"]["code"] == "RuntimeError"
        assert failed["error"]["message"] == "MCP 成功态写回失败"
        mcp_run = store.get_mcp_run("job-mcp-finish-error")
        assert mcp_run["result_state"] == "failed"
        assert mcp_run["error_json"]["code"] == "RuntimeError"
        assert mcp_run["error_json"]["message"] == "MCP 成功态写回失败"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_keeps_running_when_probe_mcp_run_errors_for_normal_job(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = ProbeErrorStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: ImmediateRunManager(**kwargs),
            auto_start=False,
        )

        await scheduler.enqueue(_request("job-probe-error", "B07YRMT36L"))
        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "job-probe-error", "succeeded")

        assert succeeded["state"] == "succeeded"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_closed_when_probe_mcp_run_errors_for_mcp_job(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = ProbeErrorStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            manager_factory=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("MCP 审计探测失败时不应创建 Manager")
            ),
            auto_start=False,
        )

        await scheduler.enqueue(
            _request("job-mcp-probe-error", "B07YRMT36L"),
            credential_scope=str(tmp_path / "credentials-user"),
            expected_user_email="user@example.com",
        )
        await scheduler.start()
        failed = await _wait_for_state(scheduler, "job-mcp-probe-error", "failed")

        assert failed["state"] == "failed"
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_continues_consuming_after_mcp_cleanup_error(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = FailingMcpCleanupStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: SuccessWithExportRunManager(**kwargs),
            auto_start=False,
        )

        first_request = _request("job-mcp-cleanup-error", "B07YRMT36L")
        second_request = _request("job-after-cleanup-error", "B00TEST222")
        await scheduler.enqueue(first_request, session_id="test-session", jwt="test-jwt")
        await scheduler.enqueue(second_request)
        store.create_mcp_run(first_request, "user@example.com")

        await scheduler.start()
        first_failed = await _wait_for_state(scheduler, "job-mcp-cleanup-error", "failed")
        second_succeeded = await _wait_for_state(scheduler, "job-after-cleanup-error", "succeeded")

        assert first_failed["error"]["message"] == "MCP 成功态写回失败"
        assert second_succeeded["state"] == "succeeded"
        await scheduler.close()

    asyncio.run(scenario())


def test_get_task_scheduler_supports_sync_cli_context():
    from opscli.seller_sprite.services import task_scheduler as module

    module._SCHEDULERS.clear()

    first = module.get_task_scheduler()
    second = module.get_task_scheduler()

    assert first is second


def test_scheduler_runs_user_binding_task_with_dedicated_account(tmp_path: Path):
    """专属账号任务应固定使用绑定账号，不进入公共账号池。"""

    async def scenario():
        from opscli.seller_sprite.services.account_bindings import (
            SellerSpriteAccountBindingStore,
        )
        from opscli.seller_sprite.services.task_queue_store import (
            ACCOUNT_ROUTE_USER_BINDING,
        )
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        binding_store = SellerSpriteAccountBindingStore(
            db_path=tmp_path / "bindings.sqlite3",
            key_path=tmp_path / "bindings.key",
        )
        binding = binding_store.bind(
            user_email="User@Example.com",
            account_name="dedicated-a",
            username="dedicated@example.com",
            password="dedicated-secret",
        )
        used_accounts = []

        def manager_factory(**kwargs):
            class Manager:
                async def run(self, request):
                    account = kwargs["account_provider"].get_default()
                    used_accounts.append((account.name, account.username))
                    return _empty_result(kwargs["settings"], request)

            return Manager()

        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=MultiAccountProvider(1),
            account_binding_store=binding_store,
            manager_factory=manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        await scheduler.enqueue(
            _request("dedicated-job", "B07YRMT36L"),
            mcp_user_email=binding.user_email,
            expected_user_email=binding.user_email,
            session_id="test-session",
            jwt="test-jwt",
            account_route=ACCOUNT_ROUTE_USER_BINDING,
            requested_account_id=binding.account.account_id,
            requested_account_key=binding.account_key,
        )

        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "dedicated-job", "succeeded")

        assert used_accounts == [("dedicated-a", "dedicated@example.com")]
        assert succeeded["assigned_account"] == "dedicated-a"
        assert succeeded["failover_count"] == 0
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_serializes_users_sharing_one_dedicated_account(tmp_path: Path):
    """多个用户复用同一专属账号时必须串行执行。"""

    async def scenario():
        from opscli.seller_sprite.services.account_bindings import (
            SellerSpriteAccountBindingStore,
        )
        from opscli.seller_sprite.services.task_queue_store import (
            ACCOUNT_ROUTE_USER_BINDING,
        )
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        binding_store = SellerSpriteAccountBindingStore(
            db_path=tmp_path / "bindings.sqlite3",
            key_path=tmp_path / "bindings.key",
        )
        first = binding_store.bind(
            user_email="first@example.com",
            account_name="dedicated-a",
            username="dedicated@example.com",
            password="secret",
        )
        second = binding_store.bind(
            user_email="second@example.com",
            account_name="dedicated-a",
            username="dedicated@example.com",
            password="secret",
        )
        manager = ControlledRunManager(
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=DummyAccountProvider(),
        )
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=MultiAccountProvider(1),
            account_binding_store=binding_store,
            manager_factory=lambda **kwargs: manager,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        for job_id, binding in (("first-job", first), ("second-job", second)):
            await scheduler.enqueue(
                _request(job_id, "B07YRMT36L"),
                mcp_user_email=binding.user_email,
                expected_user_email=binding.user_email,
                session_id="test-session",
                jwt="test-jwt",
                account_route=ACCOUNT_ROUTE_USER_BINDING,
                requested_account_id=binding.account.account_id,
                requested_account_key=binding.account_key,
            )

        await scheduler.start()
        await manager.first_started.wait()

        assert scheduler.job_status("first-job")["state"] == "running"
        assert scheduler.job_status("second-job")["state"] == "queued"
        manager.allow_finish.set()
        await _wait_for_state(scheduler, "second-job", "succeeded")
        assert manager.started == ["first-job", "second-job"]
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_fails_malformed_user_binding_task_without_public_fallback(
    tmp_path: Path,
):
    """缺少账号引用的专属任务必须失败，不能永久排队或进入公共池。"""
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
    )
    from opscli.seller_sprite.services.task_scheduler import (
        SellerSpriteTaskScheduler,
    )

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request("malformed-dedicated", "B07YRMT36L"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "malformed-dedicated",
        expected_user_email="user@example.com",
        account_route=ACCOUNT_ROUTE_USER_BINDING,
    )
    scheduler = SellerSpriteTaskScheduler(
        store=store,
        settings=SellerSpriteSettings(output_dir=tmp_path),
        account_provider=MultiAccountProvider(1),
        auto_start=False,
    )

    scheduler._start_user_binding_tasks()

    failed = store.get_status("malformed-dedicated")
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == (
        "SELLER_SPRITE_DEDICATED_ACCOUNT_UNAVAILABLE"
    )


def test_scheduler_dedicated_stale_generation_does_not_overwrite_requeued_task(
    tmp_path: Path,
):
    """专属任务被运维重排后，旧执行代际不得提交终态。"""

    async def scenario():
        from opscli.seller_sprite.services.account_bindings import (
            SellerSpriteAccountBindingStore,
        )
        from opscli.seller_sprite.services.task_queue_store import (
            ACCOUNT_ROUTE_USER_BINDING,
        )
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        binding_store = SellerSpriteAccountBindingStore(
            db_path=tmp_path / "bindings.sqlite3",
            key_path=tmp_path / "bindings.key",
        )
        binding = binding_store.bind(
            user_email="user@example.com",
            account_name="dedicated-a",
            username="dedicated@example.com",
            password="secret",
        )
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

        def manager_factory(**kwargs):
            class Manager:
                async def run(self, request):
                    assert store.reset_running_tasks() == 1
                    return _empty_result(kwargs["settings"], request)

            return Manager()

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=MultiAccountProvider(1),
            account_binding_store=binding_store,
            manager_factory=manager_factory,
            auto_start=False,
        )
        await scheduler.enqueue(
            _request("dedicated-stale", "B07YRMT36L"),
            mcp_user_email=binding.user_email,
            expected_user_email=binding.user_email,
            session_id="test-session",
            jwt="test-jwt",
            account_route=ACCOUNT_ROUTE_USER_BINDING,
            requested_account_id=binding.account.account_id,
            requested_account_key=binding.account_key,
        )
        claimed = store.claim_user_binding_task(
            job_id="dedicated-stale",
            account_id=binding.account.account_id,
            account_key=binding.account_key,
            assigned_account=binding.account.name,
            worker_key="dedicated-worker",
        )

        async def skip_reap():
            return None

        scheduler._reap_browser_sessions = skip_reap
        attempt_id = scheduler._track_attempt(claimed, capacity_kind=None)
        await scheduler._run_user_binding_task(
            claimed=claimed,
            account=binding.account.to_account(),
            attempt_id=attempt_id,
        )

        status = store.get_status("dedicated-stale")
        assert status["state"] == "queued"
        assert status["assignment_generation"] == 2
        assert status["result_path"] is None
        await scheduler.close()

    asyncio.run(scenario())


def test_scheduler_dedicated_authentication_failure_does_not_use_public_standby(
    tmp_path: Path,
):
    """专属账号认证失败后应直接失败，禁止公共账号接替。"""

    async def scenario():
        from opscli.seller_sprite.services.account_bindings import (
            SellerSpriteAccountBindingStore,
        )
        from opscli.seller_sprite.services.task_queue_store import (
            ACCOUNT_ROUTE_USER_BINDING,
        )
        from opscli.seller_sprite.services.task_scheduler import (
            SellerSpriteTaskScheduler,
        )

        binding_store = SellerSpriteAccountBindingStore(
            db_path=tmp_path / "bindings.sqlite3",
            key_path=tmp_path / "bindings.key",
        )
        binding = binding_store.bind(
            user_email="user@example.com",
            account_name="dedicated-a",
            username="dedicated@example.com",
            password="bad-secret",
        )
        attempted_accounts = []

        def manager_factory(**kwargs):
            class Manager:
                async def run(self, request):
                    account = kwargs["account_provider"].get_default()
                    attempted_accounts.append(account.name)
                    raise SellerSpriteAuthenticationError("专属账号登录失败")

            return Manager()

        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=SellerSpriteSettings(output_dir=tmp_path),
            account_provider=MultiAccountProvider(3),
            account_binding_store=binding_store,
            manager_factory=manager_factory,
            auto_start=False,
            poll_interval_seconds=0.01,
        )
        closed_sessions = []

        async def close_account_session(account, *, reason):
            closed_sessions.append((account.name, reason))

        scheduler._close_account_session = close_account_session
        await scheduler.enqueue(
            _request("dedicated-auth-failure", "B07YRMT36L"),
            mcp_user_email=binding.user_email,
            expected_user_email=binding.user_email,
            session_id="test-session",
            jwt="test-jwt",
            account_route=ACCOUNT_ROUTE_USER_BINDING,
            requested_account_id=binding.account.account_id,
            requested_account_key=binding.account_key,
        )

        await scheduler.start()
        failed = await _wait_for_state(
            scheduler,
            "dedicated-auth-failure",
            "failed",
        )

        assert attempted_accounts == ["dedicated-a"]
        assert failed["failover_count"] == 0
        assert failed["error"]["code"] == "SELLER_SPRITE_AUTHENTICATION_ERROR"
        assert closed_sessions == [("dedicated-a", "authentication_failed")]
        await scheduler.close()

    asyncio.run(scenario())
