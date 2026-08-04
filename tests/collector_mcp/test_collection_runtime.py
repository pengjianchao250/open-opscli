import asyncio

from opscli.collector_mcp.storage.config import (
    CollectorStorageSettings,
    MySqlSettings,
)
from opscli.collector_mcp.storage.models import (
    CollectionSubmission,
    ParsedCollection,
    ReconciliationBatch,
)
from opscli.collector_mcp.storage.registry import CollectionParserRegistry
from opscli.collector_mcp.storage.runtime import CollectionStorageRuntime


def test_disabled_collection_runtime_creates_no_state_file(tmp_path):
    async def scenario():
        runtime = CollectionStorageRuntime(
            CollectorStorageSettings(
                enabled=False,
                data_environment=None,
                outbox_db_path=tmp_path / "collection.sqlite3",
                mysql=MySqlSettings(),
            )
        )
        await runtime.start()
        assert runtime.health() == {
            "status": "disabled",
            "checks": {"outbox": "disabled", "mysql": "disabled", "worker": "disabled"},
        }
        await runtime.close()

    asyncio.run(scenario())
    assert not (tmp_path / "collection.sqlite3").exists()


def test_enabled_collection_runtime_processes_registered_source(tmp_path):
    async def scenario():
        result_path = tmp_path / "result.json"
        result_path.write_text("{}", encoding="utf-8")
        submission = CollectionSubmission(
            source_system="future_source",
            source_job_id="job-1",
            producer_service="collector_mcp",
            scenario="example",
            site="US",
            data_environment="debug",
            ingestion_mode="live",
            result_path=result_path,
        )
        document = ParsedCollection(submission, "future-v1", {}, (), ())

        class FakeParser:
            source_system = "future_source"

            def parse(self, value):
                return document

        class FakeRepository:
            def __init__(self):
                self.checked = False
                self.documents = []

            def check_schema(self):
                self.checked = True

            def persist(self, value):
                self.documents.append(value)

        registry = CollectionParserRegistry()
        registry.register(FakeParser())
        repository = FakeRepository()
        runtime = CollectionStorageRuntime(
            CollectorStorageSettings(
                enabled=True,
                data_environment="debug",
                outbox_db_path=tmp_path / "collection.sqlite3",
                mysql=MySqlSettings(
                    host="mysql.internal",
                    database="polaris_ops_mcp",
                    user="collector_writer",
                    password="secret",
                ),
                poll_interval_seconds=0.01,
            ),
            registry=registry,
            repository=repository,
        )
        await runtime.start()
        assert runtime.submit(submission) is True
        for _ in range(100):
            if repository.documents:
                break
            await asyncio.sleep(0.01)
        assert repository.checked is True
        assert repository.documents == [document]
        assert runtime.health()["status"] == "ready"
        await runtime.close()

    asyncio.run(scenario())


def test_runtime_reconciles_live_successes_and_advances_source_cursor(tmp_path):
    async def scenario():
        result_path = tmp_path / "result.json"
        result_path.write_text("{}", encoding="utf-8")
        submission = CollectionSubmission(
            source_system="future_source",
            source_job_id="job-reconciled",
            producer_service="collector_mcp",
            scenario="example",
            site="US",
            data_environment="debug",
            ingestion_mode="live",
            result_path=result_path,
        )

        class FakeParser:
            source_system = "future_source"

            def parse(self, value):
                return ParsedCollection(value, "future-v1", {}, (), ())

        class FakeRepository:
            def __init__(self):
                self.documents = []

            def check_schema(self):
                return None

            def persist(self, value):
                self.documents.append(value)

        class FakeReconciler:
            source_system = "future_source"

            def __init__(self):
                self.calls = []

            def reconcile(self, *, cutover_at, cursor, limit):
                self.calls.append((cutover_at, cursor, limit))
                if cursor == 0:
                    return ReconciliationBatch((submission,), 77)
                return ReconciliationBatch((), cursor)

        registry = CollectionParserRegistry()
        registry.register(FakeParser())
        repository = FakeRepository()
        reconciler = FakeReconciler()
        runtime = CollectionStorageRuntime(
            CollectorStorageSettings(
                enabled=True,
                data_environment="debug",
                outbox_db_path=tmp_path / "collection.sqlite3",
                mysql=MySqlSettings(
                    host="mysql.internal",
                    database="polaris_ops_mcp",
                    user="collector_writer",
                    password="secret",
                ),
                poll_interval_seconds=0.01,
                reconcile_interval_seconds=0.01,
            ),
            registry=registry,
            repository=repository,
        )
        runtime.register_reconciler(reconciler)
        await runtime.start()
        for _ in range(100):
            if repository.documents:
                break
            await asyncio.sleep(0.01)
        assert [item.submission.source_job_id for item in repository.documents] == [
            "job-reconciled"
        ]
        assert reconciler.calls[0][1:] == (0, 500)
        assert runtime.outbox.get_meta("reconcile_cursor:future_source") == "77"
        assert runtime.outbox.get_meta("live_cutover_at")
        await runtime.close()

    asyncio.run(scenario())


def test_runtime_loop_survives_transient_iteration_failure(tmp_path):
    async def scenario():
        second_iteration_started = asyncio.Event()
        release_second_iteration = asyncio.Event()

        class FlakyWorker:
            last_error_code = None

            def __init__(self):
                self.calls = 0

            async def process_once(self):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("temporary outbox error")
                second_iteration_started.set()
                await release_second_iteration.wait()
                return False

        runtime = CollectionStorageRuntime(
            CollectorStorageSettings(
                enabled=True,
                data_environment="debug",
                outbox_db_path=tmp_path / "collection.sqlite3",
                mysql=MySqlSettings(),
                poll_interval_seconds=0.01,
            )
        )
        worker = FlakyWorker()
        runtime.worker = worker
        runtime._mysql_ready = True
        runtime._worker_task = asyncio.create_task(runtime._run_loop())

        await asyncio.wait_for(second_iteration_started.wait(), timeout=1)
        assert runtime._worker_task.done() is False
        assert worker.calls == 2

        runtime._stop_requested = True
        release_second_iteration.set()
        runtime._wake_event.set()
        await asyncio.wait_for(runtime._worker_task, timeout=1)

    asyncio.run(scenario())
