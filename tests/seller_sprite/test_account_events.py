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


def test_account_event_recorder_sanitizes_json_style_credential_fields(caplog, tmp_path: Path):
    """JSON 风格的凭证字段也不得进入运行日志或 SQLite 审计。"""
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    recorder = SellerSpriteAccountEventRecorder(store=store)
    account = SellerSpriteAccount(name="account-1", username="user@example.com", password="secret")

    with caplog.at_level(logging.WARNING):
        recorder.record_login_failure(
            account=account,
            job_id="job-json-secret",
            worker_key="slot-1",
            assignment_generation=1,
            execution_mode="api-direct",
            login_stage="initial",
            error=RuntimeError(
                '{"token":"token-value","access_token":"access-value",'
                '"cookie":"cookie-value","password":"password-value"}'
            ),
            duration_ms=10,
            failover_count=0,
            next_action="close_slot",
        )

    serialized = f"{store.list_account_events(job_id='job-json-secret')!r}{caplog.text}"
    for secret in ("token-value", "access-value", "cookie-value", "password-value"):
        assert secret not in serialized


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


def test_account_event_recorder_persists_account_fetch_failure(caplog, tmp_path: Path):
    """账号接口刷新异常应同时进入结构化日志和 SQLite 审计。"""
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    recorder = SellerSpriteAccountEventRecorder(store=store)

    with caplog.at_level(logging.WARNING):
        recorder.record_account_fetch_failure(
            error=RuntimeError('{"access_token":"private-token"} upstream unavailable'),
            next_action="keep_queued_until_next_ttl_refresh",
        )

    event = store.list_account_events()[0]
    assert event["event_type"] == "account_fetch_failed"
    assert event["next_action"] == "keep_queued_until_next_ttl_refresh"
    assert "private-token" not in repr(event)
    assert any(
        getattr(record, "seller_sprite_event", {}).get("event_type")
        == "account_fetch_failed"
        for record in caplog.records
    )
