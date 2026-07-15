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


def test_scheduler_requeues_stale_running_tasks_on_start(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        store.enqueue(
            request=_request("job-stale", "B07YRMT36L"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "job-stale",
        )
        store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: ImmediateRunManager(**kwargs),
            auto_start=False,
        )

        await scheduler.start()
        succeeded = await _wait_for_state(scheduler, "job-stale", "succeeded")

        assert succeeded["state"] == "succeeded"
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
