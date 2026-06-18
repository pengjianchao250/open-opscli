import asyncio
import json
from pathlib import Path

from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest, SellerSpriteScenarioResult
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
