"""卖家精灵账号登录与故障事件记录测试。"""

import logging
from pathlib import Path

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.config import SellerSpriteSettings
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


def test_account_event_recorder_persists_sanitized_session_state_change(caplog, tmp_path: Path):
    """会话状态变化应以固定白名单同时写日志和 SQLite。"""
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    recorder = SellerSpriteAccountEventRecorder(store=store)
    account = SellerSpriteAccount(name="account-1", username="private@example.com", password="secret")

    with caplog.at_level(logging.INFO):
        recorder.record_session_state_change(
            account=account,
            previous_state="idle",
            state="recycling",
            reason="idle_timeout",
            session_age_seconds=1900,
            idle_seconds=1800,
            task_count=12,
        )

    event = store.list_account_events()[0]
    assert event["event_type"] == "account_session_state_changed"
    assert event["next_action"] == "idle_timeout"
    assert event["masked_username"] == "p***@example.com"
    assert event["metadata"] == {
        "previous_state": "idle",
        "state": "recycling",
        "reason": "idle_timeout",
        "session_age_seconds": 1900,
        "idle_seconds": 1800,
        "task_count": 12,
    }
    assert "private@example.com" not in repr(event)
    assert any(
        getattr(record, "seller_sprite_event", {}).get("event_type")
        == "account_session_state_changed"
        for record in caplog.records
    )


def test_account_event_recorder_uses_dedicated_close_failed_event(caplog, tmp_path: Path):
    """会话关闭失败必须写独立事件，且只保留异常类型。"""
    from opscli.seller_sprite.services.account_events import SellerSpriteAccountEventRecorder

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    recorder = SellerSpriteAccountEventRecorder(store=store)
    account = SellerSpriteAccount(name="account-1", username="private@example.com", password="secret")

    with caplog.at_level(logging.WARNING):
        recorder.record_session_state_change(
            account=account,
            previous_state="closing",
            state="close_failed",
            reason="scheduler_close",
            session_age_seconds=1900,
            idle_seconds=1800,
            task_count=12,
            error_code="RuntimeError",
        )

    event = store.list_account_events()[0]
    assert event["event_type"] == "account_session_close_failed"
    assert event["error_code"] == "RuntimeError"
    assert event["error_summary"] is None
    assert "private@example.com" not in repr(event)


def test_default_browser_listener_persists_direct_call_states_in_custom_output(tmp_path: Path):
    """非 scheduler 直调监听器也应把状态写入自定义输出目录的 SQLite。"""
    from opscli.seller_sprite.browser_route.worker import build_default_session_state_listener

    settings = SellerSpriteSettings(output_dir=tmp_path)
    account = SellerSpriteAccount(name="account-1", username="private@example.com", password="secret")
    listener = build_default_session_state_listener(settings)
    listener(
        account,
        {
            "previous_state": "registered",
            "state": "ready",
            "reason": "browser_context_opened",
            "session_age_seconds": 0,
            "idle_seconds": 0,
            "task_count": 0,
        },
    )

    store = SellerSpriteTaskQueueStore(
        db_path=tmp_path / ".seller_sprite_session_events.sqlite3"
    )
    event = store.list_account_events()[0]
    assert event["event_type"] == "account_session_state_changed"
    assert event["metadata"]["state"] == "ready"
    assert event["masked_username"] == "p***@example.com"


def test_default_browser_listener_does_not_block_when_sqlite_init_fails(
    caplog,
    monkeypatch,
    tmp_path: Path,
):
    """直调审计库初始化失败只能降级记录，不能覆盖 browser 主流程。"""
    from opscli.seller_sprite.browser_route.worker import build_default_session_state_listener
    from opscli.seller_sprite.services import task_queue_store as store_module

    def fail_store(*args, **kwargs):
        raise OSError("private@example.com disk unavailable")

    monkeypatch.setattr(store_module, "SellerSpriteTaskQueueStore", fail_store)
    listener = build_default_session_state_listener(SellerSpriteSettings(output_dir=tmp_path))
    account = SellerSpriteAccount(name="account-1", username="private@example.com", password="secret")

    with caplog.at_level(logging.ERROR):
        listener(account, {"state": "registered"})
        listener(account, {"state": "ready"})

    assert sum("会话审计初始化失败" in record.message for record in caplog.records) == 1
    assert "private@example.com" not in caplog.text
