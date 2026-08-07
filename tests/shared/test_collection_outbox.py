from datetime import datetime, timedelta, timezone

from opscli.shared.collection_storage.models import CollectionSubmission
from opscli.shared.collection_storage.outbox import CollectionOutbox


def _submission(tmp_path, job_id: str = "seller-job-1") -> CollectionSubmission:
    result_path = tmp_path / job_id / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}", encoding="utf-8")
    return CollectionSubmission(
        source_system="seller_sprite",
        source_job_id=job_id,
        producer_service="collector_mcp",
        scenario="keyword-reverse",
        site="US",
        data_environment="debug",
        ingestion_mode="live",
        result_path=result_path,
        started_at="2026-08-04T10:00:00+08:00",
        completed_at="2026-08-04T10:01:00+08:00",
    )


def test_outbox_submit_is_idempotent_and_expired_claim_can_be_recovered(tmp_path):
    outbox = CollectionOutbox(tmp_path / "collector-storage.sqlite3")
    submission = _submission(tmp_path)

    first_id = outbox.submit(submission)
    second_id = outbox.submit(submission)

    assert second_id == first_id
    claim_at = datetime(2030, 8, 4, 2, 2, tzinfo=timezone.utc)
    first_claim = outbox.claim_next(
        owner="worker-1",
        lease_seconds=30,
        now=claim_at,
    )
    assert first_claim is not None
    assert first_claim.submission == submission
    assert first_claim.attempt_count == 1
    assert (
        outbox.claim_next(
            owner="worker-2",
            lease_seconds=30,
            now=claim_at + timedelta(seconds=10),
        )
        is None
    )

    recovered = outbox.claim_next(
        owner="worker-2",
        lease_seconds=30,
        now=claim_at + timedelta(seconds=31),
    )

    assert recovered is not None
    assert recovered.id == first_id
    assert recovered.attempt_count == 2
    assert outbox.complete(recovered.id, owner="worker-2") is True
    assert outbox.get(first_id).status == "completed"
