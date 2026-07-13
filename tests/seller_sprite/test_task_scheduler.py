import asyncio
import json
import sqlite3
from pathlib import Path

from opscli.seller_sprite.config import SellerSpriteSettings
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
    def finish_mcp_run_success(self, job_id: str, row_count: int, export_payload: dict[str, str]) -> None:
        raise RuntimeError("MCP 成功态写回失败")


class ProbeErrorStore(SellerSpriteTaskQueueStore):
    def get_mcp_run(self, job_id: str) -> dict[str, str]:
        raise sqlite3.OperationalError("MCP 记录表读取失败")


class FailingMcpCleanupStore(SellerSpriteTaskQueueStore):
    def finish_mcp_run_success(self, job_id: str, row_count: int, export_payload: dict[str, str]) -> None:
        raise RuntimeError("MCP 成功态写回失败")

    def finish_mcp_run_failed(self, job_id: str, error_payload: dict[str, str]) -> None:
        raise RuntimeError("MCP 失败态写回失败")


def test_scheduler_runs_tasks_in_fifo_order(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        manager = ControlledRunManager(settings=settings, account_provider=DummyAccountProvider())
        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: manager,
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
        await scheduler.enqueue(request)
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
        await scheduler.enqueue(request)
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
        await scheduler.enqueue(request)
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
        await scheduler.enqueue(request)
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
        await scheduler.enqueue(request)
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
        await scheduler.enqueue(first_request)
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
