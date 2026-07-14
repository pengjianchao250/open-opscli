"""卖家精灵账号登录与故障事件记录测试。"""

import logging
from pathlib import Path

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore


def test_account_event_recorder_logs_and_persists_sanitized_login_failure(caplog, tmp_path: Path):
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    recorder = SellerSpriteAccountEventRecorder(store=store)
    account = SellerSpriteAccount(
        name="account-1",
        username="private-user@example.com",
        password="super-secret-password",
    )

    with caplog.at_level(logging.WARNING):
        recorder.record_login_failure(
            account=account,
            job_id="job-1",
            worker_key="slot-1",
            assignment_generation=2,
            execution_mode="browser-route",
            login_stage="failover",
            error=RuntimeError(
                "login failed username=private-user@example.com password=super-secret-password token=secret-token"
            ),
            duration_ms=120,
            failover_count=1,
            next_action="try_next_standby",
        )

    event = store.list_account_events(job_id="job-1")[0]
    log_event = next(
        record.seller_sprite_event
        for record in caplog.records
        if getattr(record, "seller_sprite_event", {}).get("event_type") == "account_login_failed"
    )
    serialized = f"{event!r}{log_event!r}"

    assert event["masked_username"] == "p***@example.com"
    assert event["login_stage"] == "failover"
    assert event["next_action"] == "try_next_standby"
    assert "private-user@example.com" not in serialized
    assert "super-secret-password" not in serialized
    assert "secret-token" not in serialized


def test_account_event_recorder_keeps_business_error_when_sqlite_audit_fails(caplog):
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    class FailingAuditStore:
        def record_account_event(self, **kwargs):
            raise RuntimeError("SQLite audit unavailable")

    recorder = SellerSpriteAccountEventRecorder(store=FailingAuditStore())
    account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")

    with caplog.at_level(logging.ERROR):
        recorder.record_login_failure(
            account=account,
            job_id="job-1",
            worker_key="slot-1",
            assignment_generation=1,
            execution_mode="api-direct",
            login_stage="initial",
            error=RuntimeError("original login failure"),
            duration_ms=10,
            failover_count=0,
            next_action="close_slot",
        )

    assert any(
        getattr(record, "seller_sprite_event", {}).get("event_type")
        == "account_audit_persistence_failed"
        for record in caplog.records
    )
