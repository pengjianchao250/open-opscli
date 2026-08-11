import asyncio

from opscli.shared.collection_storage.models import (
    CollectionSubmission,
    ParsedCollection,
)
from opscli.shared.collection_storage.outbox import CollectionOutbox
from opscli.shared.collection_storage.parser_utils import CollectionParseError
from opscli.shared.collection_storage.registry import CollectionParserRegistry
from opscli.shared.collection_storage.worker import CollectionPersistenceWorker


def _run(coro):
    return asyncio.run(coro)


def test_worker_parses_persists_and_completes_one_outbox_record(tmp_path):
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
    document = ParsedCollection(
        submission=submission,
        parser_version="future-v1",
        request_params={},
        artifacts=(),
        datasets=(),
    )

    class FakeParser:
        source_system = "future_source"

        def parse(self, value):
            assert value == submission
            return document

    class FakeRepository:
        def __init__(self):
            self.documents = []

        def persist(self, value):
            self.documents.append(value)

    outbox = CollectionOutbox(tmp_path / "outbox.sqlite3")
    record_id = outbox.submit(submission)
    registry = CollectionParserRegistry()
    registry.register(FakeParser())
    repository = FakeRepository()
    worker = CollectionPersistenceWorker(
        outbox=outbox,
        registry=registry,
        repository=repository,
        lease_seconds=30,
    )

    processed = _run(worker.process_once())

    assert processed is True
    assert repository.documents == [document]
    assert outbox.get(record_id).status == "completed"
    assert _run(worker.process_once()) is False


def test_worker_retries_repository_failure_without_losing_successful_collection(
    tmp_path,
):
    result_path = tmp_path / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    submission = CollectionSubmission(
        source_system="future_source",
        source_job_id="job-retry",
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

    class UnavailableRepository:
        def persist(self, document):
            raise ConnectionError("mysql unavailable")

    outbox = CollectionOutbox(tmp_path / "outbox.sqlite3")
    record_id = outbox.submit(submission)
    registry = CollectionParserRegistry()
    registry.register(FakeParser())
    worker = CollectionPersistenceWorker(
        outbox=outbox,
        registry=registry,
        repository=UnavailableRepository(),
        lease_seconds=30,
    )

    processed = _run(worker.process_once())

    record = outbox.get(record_id)
    assert processed is True
    assert record.status == "retrying"
    assert record.last_error_code == "ConnectionError"


def test_worker_marks_invalid_source_files_as_permanent_failure(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    submission = CollectionSubmission(
        source_system="broken_source",
        source_job_id="job-broken",
        producer_service="collector_mcp",
        scenario="example",
        site="US",
        data_environment="debug",
        ingestion_mode="live",
        result_path=result_path,
    )

    class BrokenParser:
        source_system = "broken_source"

        def parse(self, value):
            raise CollectionParseError("result contract invalid")

    class UnusedRepository:
        def persist(self, document):
            raise AssertionError("invalid document must not reach repository")

    outbox = CollectionOutbox(tmp_path / "outbox.sqlite3")
    record_id = outbox.submit(submission)
    registry = CollectionParserRegistry()
    registry.register(BrokenParser())
    worker = CollectionPersistenceWorker(
        outbox=outbox,
        registry=registry,
        repository=UnusedRepository(),
        lease_seconds=30,
    )

    assert _run(worker.process_once()) is True
    assert outbox.get(record_id).status == "failed"
