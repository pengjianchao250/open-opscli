"""卖家精灵 SQLite 任务队列仓储测试。"""

import json
import sqlite3
from pathlib import Path

from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest


def _request(*, job_id: str, asin: str = "B07YRMT36L") -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": asin},
        job_id=job_id,
        export_format="json",
    )


def _mcp_request(*, job_id: str, asin: str = "B07YRMT36L") -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": asin},
        job_id=job_id,
        export_format="json",
        mode="mcp",
    )


def _listing_request(*, job_id: str) -> SellerSpriteScenarioRequest:
    return SellerSpriteScenarioRequest(
        scenario="listing-analysis",
        site="US",
        period="nearly",
        params={"asin": "B0LISTING"},
        job_id=job_id,
        export_format="json",
    )


def test_store_enqueue_returns_queue_position(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    first = store.enqueue(
        request=_request(job_id="job-1"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-1",
    )
    second = store.enqueue(
        request=_request(job_id="job-2", asin="B00TEST222"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-2",
    )

    assert first["job_id"] == "job-1"
    assert first["state"] == "queued"
    assert first["position"] == 1
    assert second["job_id"] == "job-2"
    assert second["state"] == "queued"
    assert second["position"] == 2


def test_store_claim_next_updates_waiting_position(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    store.enqueue(request=_request(job_id="job-2"), queue_scope="seller_sprite", root_dir=tmp_path / "job-2")

    claimed = store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")
    waiting = store.get_status("job-2")

    assert claimed is not None
    assert claimed["job_id"] == "job-1"
    assert claimed["state"] == "running"
    assert claimed["assigned_account"] == "default"
    assert waiting["job_id"] == "job-2"
    assert waiting["state"] == "queued"
    assert waiting["position"] == 1


def test_claim_returns_committed_attempt_without_reopening_status(tmp_path: Path, monkeypatch):
    """领取结果必须在领取事务内构造，提交后不得再经过可失败的状态读取。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-claim"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-claim",
    )
    monkeypatch.setattr(
        store,
        "get_status",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("unexpected status reopen")),
    )

    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
        execution_owner="owner-1",
    )

    assert claimed is not None
    assert claimed["job_id"] == "job-claim"
    assert claimed["state"] == "running"
    assert claimed["progress_stage"] == "claimed"
    assert claimed["assignment_generation"] == 1


def test_store_claim_next_enforces_one_running_task_per_queue_scope(tmp_path: Path):
    """同一 SQLite 队列范围已有 running 时，其他实例不得继续领取。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    first = SellerSpriteTaskQueueStore(db_path=db_path)
    second = SellerSpriteTaskQueueStore(db_path=db_path)
    first.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    first.enqueue(request=_request(job_id="job-2"), queue_scope="seller_sprite", root_dir=tmp_path / "job-2")

    claimed = first.claim_next(
        queue_scope="seller_sprite",
        worker_key="worker-1",
        assigned_account="default",
    )
    blocked = second.claim_next(
        queue_scope="seller_sprite",
        worker_key="worker-2",
        assigned_account="default",
    )

    assert claimed["job_id"] == "job-1"
    assert blocked is None
    first.finish_task(
        job_id="job-1",
        result_path=str(tmp_path / "job-1" / "result.json"),
        row_count=0,
        export_payload=None,
    )
    resumed = second.claim_next(
        queue_scope="seller_sprite",
        worker_key="worker-2",
        assigned_account="default",
    )
    assert resumed["job_id"] == "job-2"


def test_store_claims_generic_tasks_in_parallel_for_distinct_accounts(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    store.enqueue(request=_request(job_id="job-2"), queue_scope="seller_sprite", root_dir=tmp_path / "job-2")

    first = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )
    second = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-2",
        assigned_account="account-2",
        worker_key="slot-2",
    )
    blocked = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )

    assert first["job_id"] == "job-1"
    assert second["job_id"] == "job-2"
    assert first["assignment_generation"] == 1
    assert second["assignment_generation"] == 1
    assert blocked is None


def test_store_public_worker_does_not_claim_user_binding_task(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
        SellerSpriteTaskQueueStore,
    )

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="dedicated-job"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "dedicated-job",
        expected_user_email="user@example.com",
        account_route=ACCOUNT_ROUTE_USER_BINDING,
        requested_account_id="account-id",
        requested_account_key="account-key",
    )

    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="public-account-key",
        assigned_account="public-account",
        worker_key="public-worker",
    )

    assert claimed is None
    assert store.get_status("dedicated-job")["state"] == "queued"


def test_store_unbind_failure_only_ends_queued_user_binding_tasks(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
        SellerSpriteTaskQueueStore,
    )

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    for job_id in ("dedicated-running", "dedicated-queued"):
        store.enqueue_owned_mcp_run(
            request=_request(job_id=job_id),
            queue_scope="seller_sprite",
            root_dir=tmp_path / job_id,
            user_email="user@example.com",
            expected_user_email="user@example.com",
            account_route=ACCOUNT_ROUTE_USER_BINDING,
            requested_account_id="account-id",
            requested_account_key="account-key",
        )
    running = store.claim_user_binding_task(
        job_id="dedicated-running",
        account_id="account-id",
        account_key="account-key",
        assigned_account="dedicated-a",
        worker_key="dedicated-worker",
    )

    changed = store.fail_queued_user_binding_tasks(
        user_email="USER@example.com",
        reason="专属账号绑定已解除",
    )

    assert running["state"] == "running"
    assert changed == 1
    assert store.get_status("dedicated-running")["state"] == "running"
    queued = store.get_status("dedicated-queued")
    assert queued["state"] == "failed"
    assert queued["error"]["code"] == "SELLER_SPRITE_DEDICATED_ACCOUNT_UNAVAILABLE"
    assert store.get_mcp_run("dedicated-running")["result_state"] == "queued"
    assert store.get_mcp_run("dedicated-queued")["result_state"] == "failed"


def test_store_limits_user_binding_tasks_to_three_running_accounts(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_USER_BINDING,
        SellerSpriteTaskQueueStore,
    )

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    for index in range(1, 5):
        store.enqueue(
            request=_request(job_id=f"dedicated-{index}"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / f"dedicated-{index}",
            expected_user_email=f"user-{index}@example.com",
            account_route=ACCOUNT_ROUTE_USER_BINDING,
            requested_account_id=f"account-{index}",
            requested_account_key=f"account-key-{index}",
        )

    claimed = [
        store.claim_user_binding_task(
            job_id=f"dedicated-{index}",
            account_id=f"account-{index}",
            account_key=f"account-key-{index}",
            assigned_account=f"dedicated-{index}",
            worker_key=f"worker-{index}",
        )
        for index in range(1, 5)
    ]

    assert [item is not None for item in claimed] == [True, True, True, False]
    assert store.get_status("dedicated-4")["state"] == "queued"


def test_store_migrates_v2_queue_to_shared_account_route(tmp_path: Path):
    """v2 历史任务升级后应保留数据并明确归入公共账号池。"""
    from opscli.seller_sprite.services.task_queue_store import (
        ACCOUNT_ROUTE_SHARED_POOL,
        QUEUE_SCHEMA_VERSION,
        SellerSpriteTaskQueueStore,
    )

    db_path = tmp_path / "queue.sqlite3"
    request = _request(job_id="legacy-v2-job")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE seller_sprite_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                queue_scope TEXT NOT NULL,
                task_kind TEXT NOT NULL DEFAULT 'generic',
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                root_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NULL,
                finished_at TEXT NULL,
                assigned_account TEXT NULL,
                assigned_account_key TEXT NULL,
                worker_key TEXT NULL,
                assignment_generation INTEGER NOT NULL DEFAULT 0,
                failover_count INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT NULL,
                last_failed_account_key TEXT NULL,
                retry_reason TEXT NULL,
                result_path TEXT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                export_json TEXT NULL,
                error_json TEXT NULL,
                credential_scope TEXT NULL,
                runtime_auth_required INTEGER NOT NULL DEFAULT 0,
                expected_user_email TEXT NULL,
                session_id TEXT NULL,
                jwt TEXT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO seller_sprite_task_queue (
                job_id, queue_scope, task_kind, status, request_json, root_dir,
                created_at, row_count, runtime_auth_required
            )
            VALUES (?, 'seller_sprite', 'generic', 'queued', ?, ?, ?, 0, 0)
            """,
            (
                request.job_id,
                json.dumps(request.to_dict(), ensure_ascii=False),
                str(tmp_path / "legacy-v2-job"),
                "2026-07-20T10:00:00+08:00",
            ),
        )
        conn.execute("PRAGMA user_version = 2")

    store = SellerSpriteTaskQueueStore(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT account_route, requested_account_id, requested_account_key, "
            "execution_owner, heartbeat_at, lease_expires_at, remote_task_id, "
            "progress_stage, progress_at, progress_sequence "
            "FROM seller_sprite_task_queue WHERE job_id = ?",
            ("legacy-v2-job",),
        ).fetchone()
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert dict(row) == {
        "account_route": ACCOUNT_ROUTE_SHARED_POOL,
        "requested_account_id": None,
        "requested_account_key": None,
        "execution_owner": None,
        "heartbeat_at": None,
        "lease_expires_at": None,
        "remote_task_id": None,
        "progress_stage": "queued",
        "progress_at": "2026-07-20T10:00:00+08:00",
        "progress_sequence": 0,
    }
    assert user_version == QUEUE_SCHEMA_VERSION
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="public-account-key",
        assigned_account="public-account",
        worker_key="public-worker",
    )
    assert claimed["job_id"] == "legacy-v2-job"


def test_store_migrates_v5_runtime_capacity_columns(tmp_path: Path):
    """v5 聚合容量升级后应保留原数据，并以零值等待精确容量心跳。"""
    from opscli.seller_sprite.services.task_queue_store import (
        QUEUE_SCHEMA_VERSION,
        SellerSpriteTaskQueueStore,
    )

    db_path = tmp_path / "queue.sqlite3"
    SellerSpriteTaskQueueStore(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            DROP TABLE seller_sprite_runtime_heartbeats;
            CREATE TABLE seller_sprite_runtime_heartbeats (
                execution_owner TEXT NOT NULL PRIMARY KEY,
                lifecycle_state TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                generic_workers_alive INTEGER NOT NULL DEFAULT 0,
                listing_worker_alive INTEGER NOT NULL DEFAULT 0,
                available_capacity INTEGER NOT NULL DEFAULT 0,
                standby_capacity INTEGER NOT NULL DEFAULT 0,
                last_claim_at TEXT NULL,
                last_progress_at TEXT NULL
            );
            PRAGMA user_version = 5;
            """
        )
        conn.execute(
            "INSERT INTO seller_sprite_runtime_heartbeats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "owner-v5",
                "running",
                "2026-07-29T10:00:02+08:00",
                2,
                1,
                2,
                3,
                "2026-07-29T10:00:00+08:00",
                "2026-07-29T10:00:01+08:00",
            ),
        )

    migrated = SellerSpriteTaskQueueStore(db_path=db_path)
    runtime = migrated.get_runtime_heartbeat("owner-v5")
    with sqlite3.connect(db_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(seller_sprite_runtime_heartbeats)"
            )
        }
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert user_version == QUEUE_SCHEMA_VERSION == 8
    assert {
        "generic_available_capacity",
        "listing_available_capacity",
    } <= columns
    assert runtime == {
        "execution_owner": "owner-v5",
        "lifecycle_state": "running",
        "heartbeat_at": "2026-07-29T10:00:02+08:00",
        "generic_workers_alive": 2,
        "listing_worker_alive": 1,
        "generic_available_capacity": 0,
        "listing_available_capacity": 0,
        "available_capacity": 2,
        "standby_capacity": 3,
        "last_claim_at": "2026-07-29T10:00:00+08:00",
        "last_progress_at": "2026-07-29T10:00:01+08:00",
    }


def test_store_persists_active_account_quarantine_by_credential_version(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    first = SellerSpriteTaskQueueStore(db_path=db_path)
    first.quarantine_account(
        account_key="account-key",
        credential_version="credential-v1",
        reason="authentication_failed",
        error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
        ttl_seconds=86400,
    )

    restarted = SellerSpriteTaskQueueStore(db_path=db_path)

    assert restarted.is_account_quarantined(
        account_key="account-key",
        credential_version="credential-v1",
    )
    assert not restarted.is_account_quarantined(
        account_key="account-key",
        credential_version="credential-v2",
    )


def test_store_does_not_fail_task_claimed_during_account_source_shutdown(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = _request(job_id="claimed-during-source-shutdown")
    store.enqueue(
        request=request,
        queue_scope="seller_sprite",
        root_dir=tmp_path / request.job_id,
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key",
        assigned_account="account-1",
        worker_key="worker-1",
    )
    assert claimed is not None

    committed = store.fail_queued_task(
        job_id=request.job_id,
        error_payload={
            "code": "SELLER_SPRITE_ACCOUNT_SOURCE_UNAVAILABLE",
            "message": "account source unavailable",
        },
    )

    assert committed is False
    assert store.get_status(request.job_id)["state"] == "running"


def test_store_does_not_auto_consume_while_legacy_generic_task_is_running(tmp_path: Path):
    """升级前领取且没有账号键的 running 任务应阻断新版 generic 自动消费。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="legacy-running"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "legacy",
    )
    store.enqueue(
        request=_request(job_id="new-queued"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "new",
    )
    store.claim_next(
        queue_scope="seller_sprite",
        worker_key="legacy-worker",
        assigned_account="legacy-account",
    )

    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="new-account-key",
        assigned_account="new-account",
        worker_key="new-worker",
    )

    assert claimed is None
    assert store.get_status("new-queued")["state"] == "queued"


def test_store_generic_claim_skips_listing_analysis_tasks(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_listing_request(job_id="listing-job"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "listing-job",
    )
    store.enqueue(
        request=_request(job_id="generic-job"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "generic-job",
    )

    assert store.get_status("listing-job")["position"] == 1
    assert store.get_status("generic-job")["position"] == 1

    generic = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )
    listing = store.claim_next_listing_analysis(
        queue_scope="seller_sprite",
        worker_key="listing-slot",
        assigned_account="account-2",
        account_key="account-key-2",
    )

    assert generic["job_id"] == "generic-job"
    assert generic["task_kind"] == "generic"
    assert listing["job_id"] == "listing-job"
    assert listing["task_kind"] == "listing_analysis"
    assert store.get_task_account_binding("listing-job") == {
        "assigned_account": "account-2",
        "assigned_account_key": "account-key-2",
    }


def test_store_listing_claim_waits_for_same_account_generic_task(tmp_path: Path):
    """Listing Analysis 不得与同账号普通任务并发使用同一浏览器会话。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="generic-running"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "generic-running",
    )
    store.enqueue(
        request=_listing_request(job_id="listing-waiting"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "listing-waiting",
    )
    store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )

    claimed = store.claim_next_listing_analysis(
        queue_scope="seller_sprite",
        worker_key="listing-slot",
        assigned_account="account-1",
        account_key="account-key-1",
    )

    assert claimed is None
    assert store.get_status("listing-waiting")["state"] == "queued"


def test_store_rejects_late_finish_after_failover_generation_changes(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-failover"), queue_scope="seller_sprite", root_dir=tmp_path / "job-failover")
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )

    reassignment = store.reassign_task_for_failover(
        job_id="job-failover",
        current_account_key="account-key-1",
        current_generation=claimed["assignment_generation"],
        replacement_account_key="account-key-2",
        replacement_account="account-2",
        worker_key="slot-1",
        error_code="SELLER_SPRITE_ACCOUNT_LOGIN_FAILED",
        retry_reason="account_login_failed",
    )
    assert reassignment.outcome == "reassigned"
    replacement = reassignment.status
    assert replacement is not None
    late_finish = store.finish_task_if_current(
        job_id="job-failover",
        account_key="account-key-1",
        assignment_generation=claimed["assignment_generation"],
        result_path=str(tmp_path / "stale.json"),
        row_count=1,
        export_payload=None,
    )
    current_finish = store.finish_task_if_current(
        job_id="job-failover",
        account_key="account-key-2",
        assignment_generation=replacement["assignment_generation"],
        result_path=str(tmp_path / "current.json"),
        row_count=2,
        export_payload=None,
    )

    assert replacement["assignment_generation"] == 2
    assert replacement["failover_count"] == 1
    assert late_finish is False
    assert current_finish is True
    assert store.get_status("job-failover")["row_count"] == 2
    events = store.list_task_progress_events(job_id="job-failover")
    assert [(event["stage"], event["assignment_generation"]) for event in events] == [
        ("claimed", 1),
        ("reassigned", 2),
        ("succeeded", 2),
    ]
    assert events[-2]["metadata"] == {"outcome": "reassigned"}
    assert events[-1]["metadata"] == {"outcome": "succeeded"}


def test_store_failover_distinguishes_busy_and_stale_without_reopening_status(
    tmp_path: Path,
    monkeypatch,
):
    """改绑必须区分备用占用和旧代际，并在事务内返回成功快照。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-current"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-current",
    )
    store.enqueue(
        request=_request(job_id="job-occupied"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-occupied",
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )
    occupied = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-2",
        assigned_account="account-2",
        worker_key="external-slot",
    )
    assert claimed is not None
    assert occupied is not None

    busy = store.reassign_task_for_failover(
        job_id="job-current",
        current_account_key="account-key-1",
        current_generation=claimed["assignment_generation"],
        replacement_account_key="account-key-2",
        replacement_account="account-2",
        worker_key="slot-1",
        error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
        retry_reason="account_authentication_failed",
    )
    assert busy.outcome == "replacement_busy"
    assert busy.status is None

    monkeypatch.setattr(
        store,
        "get_status",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("unexpected status reopen")),
    )
    reassigned = store.reassign_task_for_failover(
        job_id="job-current",
        current_account_key="account-key-1",
        current_generation=claimed["assignment_generation"],
        replacement_account_key="account-key-3",
        replacement_account="account-3",
        worker_key="slot-1",
        error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
        retry_reason="account_authentication_failed",
    )
    assert reassigned.outcome == "reassigned"
    assert reassigned.status is not None
    assert reassigned.status["assigned_account_key"] == "account-key-3"
    assert reassigned.status["assignment_generation"] == 2

    stale = store.reassign_task_for_failover(
        job_id="job-current",
        current_account_key="account-key-1",
        current_generation=claimed["assignment_generation"],
        replacement_account_key="account-key-4",
        replacement_account="account-4",
        worker_key="slot-1",
        error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
        retry_reason="account_authentication_failed",
    )
    assert stale.outcome == "stale_attempt"
    assert stale.status is None


def test_store_rejects_stale_generation_without_updating_mcp_terminal_state(tmp_path: Path):
    """旧代际不得单独覆盖 MCP 终态，队列与 MCP 写回必须同成同败。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = _request(job_id="job-mcp-cas")
    store.enqueue_owned_mcp_run(
        request=request,
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-mcp-cas",
        user_email="user@example.com",
        credential_scope=str(tmp_path / "credentials-user"),
        expected_user_email="user@example.com",
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )
    reassignment = store.reassign_task_for_failover(
        job_id="job-mcp-cas",
        current_account_key="account-key-1",
        current_generation=claimed["assignment_generation"],
        replacement_account_key="account-key-2",
        replacement_account="account-2",
        worker_key="slot-1",
        error_code="SELLER_SPRITE_AUTHENTICATION_ERROR",
        retry_reason="account_authentication_failed",
    )
    assert reassignment.outcome == "reassigned"
    replacement = reassignment.status
    assert replacement is not None

    stale_committed = store.finish_task_and_mcp_run_if_current(
        job_id="job-mcp-cas",
        account_key="account-key-1",
        assignment_generation=claimed["assignment_generation"],
        result_path=str(tmp_path / "stale.json"),
        row_count=1,
        export_payload=None,
        mcp_export_payload={"format": "json", "filename": "stale.json"},
    )
    current_committed = store.finish_task_and_mcp_run_if_current(
        job_id="job-mcp-cas",
        account_key="account-key-2",
        assignment_generation=replacement["assignment_generation"],
        result_path=str(tmp_path / "current.json"),
        row_count=2,
        export_payload=None,
        mcp_export_payload={"format": "json", "filename": "current.json"},
    )

    assert stale_committed is False
    assert current_committed is True
    status = store.get_status("job-mcp-cas")
    assert status["execution_owner"] is None
    assert status["heartbeat_at"] is None
    assert status["lease_expires_at"] is None
    assert store.get_mcp_run("job-mcp-cas")["result_export_filename"] == "current.json"
    assert store.get_task_context("job-mcp-cas") == {
        "credential_scope": None,
        "runtime_auth_required": False,
        "expected_user_email": None,
        "session_id": None,
        "jwt": None,
    }


def test_store_clears_auth_when_current_generation_fails_atomically(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = _request(job_id="job-mcp-auth-failed")
    store.enqueue_owned_mcp_run(
        request=request,
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-mcp-auth-failed",
        user_email="user@example.com",
        credential_scope=str(tmp_path / "credentials-user"),
        expected_user_email="user@example.com",
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
    )

    committed = store.fail_task_and_mcp_run_if_current(
        job_id="job-mcp-auth-failed",
        account_key="account-key-1",
        assignment_generation=claimed["assignment_generation"],
        error_payload={"code": "TEST", "message": "failed"},
        update_mcp_run=True,
    )

    assert committed is True
    status = store.get_status("job-mcp-auth-failed")
    assert status["execution_owner"] is None
    assert status["heartbeat_at"] is None
    assert status["lease_expires_at"] is None
    assert status["progress_stage"] == "failed"
    events = store.list_task_progress_events(job_id="job-mcp-auth-failed")
    assert [(event["stage"], event["assignment_generation"]) for event in events] == [
        ("claimed", 1),
        ("failed", 1),
    ]
    assert events[-1]["metadata"] == {"outcome": "failed"}
    assert store.get_task_context("job-mcp-auth-failed") == {
        "credential_scope": None,
        "runtime_auth_required": False,
        "expected_user_email": None,
        "session_id": None,
        "jwt": None,
    }


def test_store_records_queryable_account_login_failure_event(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.record_account_event(
        event_type="account_login_failed",
        account_key="safe-account-key",
        account_name="account-1",
        masked_username="u***@example.com",
        job_id="job-1",
        worker_key="slot-1",
        assignment_generation=2,
        execution_mode="browser-route",
        login_stage="failover",
        error_code="SELLER_SPRITE_CONFIG_ERROR",
        error_summary="卖家精灵浏览器登录失败",
        replacement_account_key=None,
        duration_ms=123,
        failover_count=1,
        next_action="try_next_standby",
        metadata={"reason": "failover"},
    )

    events = store.list_account_events(job_id="job-1")

    assert len(events) == 1
    assert events[0]["event_type"] == "account_login_failed"
    assert events[0]["assignment_generation"] == 2
    assert events[0]["login_stage"] == "failover"
    assert events[0]["next_action"] == "try_next_standby"
    assert events[0]["metadata"] == {"reason": "failover"}


def test_store_resets_running_tasks_back_to_queue(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    first = SellerSpriteTaskQueueStore(db_path=db_path)
    first.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    first.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

    second = SellerSpriteTaskQueueStore(db_path=db_path)
    reset_count = second.reset_running_tasks()
    status = second.get_status("job-1")

    assert reset_count == 1
    assert status["job_id"] == "job-1"
    assert status["state"] == "queued"
    assert status["position"] == 1
    assert status["assigned_account"] is None


def test_store_lists_tasks_and_summarizes_queue_status(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-queued"), queue_scope="seller_sprite", root_dir=tmp_path / "job-queued")
    store.enqueue(request=_request(job_id="job-running"), queue_scope="seller_sprite", root_dir=tmp_path / "job-running")
    store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

    summary = store.queue_status(stale_running_seconds=0)
    queued_tasks = store.list_tasks(state="queued")
    running_tasks = store.list_tasks(state="running")

    assert summary["by_state"] == {"queued": 1, "running": 1}
    assert summary["oldest_queued_at"] is not None
    assert summary["stale_running_count"] == 1
    assert [task["job_id"] for task in queued_tasks] == ["job-running"]
    assert [task["job_id"] for task in running_tasks] == ["job-queued"]


def test_store_fails_queued_tasks_and_syncs_mcp_runs(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = _request(job_id="job-to-fail")
    store.enqueue(request=request, queue_scope="seller_sprite", root_dir=tmp_path / "job-to-fail")
    store.create_mcp_run(request, "user@example.com")

    changed = store.fail_tasks(
        state="queued",
        job_ids=["job-to-fail"],
        reason="人工终止排队任务",
    )
    task = store.get_status("job-to-fail")
    mcp_run = store.get_mcp_run("job-to-fail")

    assert changed == 1
    assert task["state"] == "failed"
    assert task["error"]["code"] == "SELLER_SPRITE_QUEUE_ABORTED"
    assert task["error"]["message"] == "人工终止排队任务"
    assert mcp_run["result_state"] == "failed"
    assert mcp_run["error_json"]["message"] == "人工终止排队任务"


def test_store_requeues_only_stale_running_tasks(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="old-running"), queue_scope="seller_sprite", root_dir=tmp_path / "old-running")
    store.enqueue(request=_request(job_id="new-running"), queue_scope="seller_sprite-secondary", root_dir=tmp_path / "new-running")
    store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")
    store.claim_next(queue_scope="seller_sprite-secondary", worker_key="default", assigned_account="default")

    with sqlite3.connect(tmp_path / "queue.sqlite3") as conn:
        conn.execute(
            "UPDATE seller_sprite_task_queue SET started_at = ? WHERE job_id = ?",
            ("2026-07-09T10:00:00+08:00", "old-running"),
        )
        conn.execute(
            "UPDATE seller_sprite_task_queue SET started_at = ? WHERE job_id = ?",
            ("2026-07-09T12:00:00+08:00", "new-running"),
        )

    changed = store.reset_running_tasks(before_started_at="2026-07-09T11:00:00+08:00")

    assert changed == 1
    assert store.get_status("old-running")["state"] == "queued"
    assert store.get_status("new-running")["state"] == "running"


def test_store_recovers_only_expired_execution_lease_and_syncs_mcp_run(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    active = _request(job_id="active-running")
    expired = _request(job_id="expired-running")
    store.enqueue_owned_mcp_run(
        request=active,
        queue_scope="seller_sprite-active",
        root_dir=tmp_path / "active-running",
        user_email="user@example.com",
    )
    store.enqueue_owned_mcp_run(
        request=expired,
        queue_scope="seller_sprite-expired",
        root_dir=tmp_path / "expired-running",
        user_email="user@example.com",
    )
    store.claim_next(
        queue_scope="seller_sprite-active",
        worker_key="active-worker",
        assigned_account="active",
        execution_owner="active-owner",
        lease_seconds=60,
    )
    store.claim_next(
        queue_scope="seller_sprite-expired",
        worker_key="expired-worker",
        assigned_account="expired",
        execution_owner="expired-owner",
        lease_seconds=60,
    )
    store.mark_mcp_run_running("active-running")
    store.mark_mcp_run_running("expired-running")
    with sqlite3.connect(tmp_path / "queue.sqlite3") as conn:
        conn.execute(
            "UPDATE seller_sprite_task_queue SET lease_expires_at = ? WHERE job_id = ?",
            ("2000-01-01T00:00:00+00:00", "expired-running"),
        )

    changed = store.recover_expired_running_tasks()

    assert changed == 1
    assert store.get_status("active-running")["state"] == "running"
    recovered = store.get_status("expired-running")
    assert recovered["state"] == "queued"
    assert recovered["retry_reason"] == "lease_expired"
    assert recovered["assignment_generation"] == 2
    assert recovered["execution_owner"] is None
    assert store.get_mcp_run("active-running")["result_state"] == "running"
    assert store.get_mcp_run("expired-running")["result_state"] == "queued"
    events = store.list_task_progress_events(job_id="expired-running")
    assert [(event["stage"], event["assignment_generation"]) for event in events] == [
        ("claimed", 1),
        ("queued", 2),
    ]
    assert events[-1]["metadata"] == {"outcome": "queued"}


def test_store_renews_and_releases_owner_lease(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-owned"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-owned",
    )
    claimed = store.claim_next(
        queue_scope="seller_sprite",
        worker_key="worker",
        assigned_account="default",
        execution_owner="owner-1",
        lease_seconds=1,
    )

    renewed = store.renew_execution_leases(
        execution_owner="owner-1",
        lease_seconds=60,
    )
    released = store.release_running_tasks(execution_owner="owner-1")
    status = store.get_status("job-owned")

    assert claimed["execution_owner"] == "owner-1"
    assert renewed == 1
    assert released == 1
    assert status["state"] == "queued"
    assert status["retry_reason"] == "service_restart"
    assert status["assignment_generation"] == 2


def test_store_renews_only_explicitly_active_attempts(tmp_path: Path):
    """活动尝试续租不得顺带续期同 owner 下未跟踪的运行行。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    for job_id, scope, account_key in (
        ("tracked-job", "tracked-scope", "tracked-account"),
        ("orphan-job", "orphan-scope", "orphan-account"),
    ):
        store.enqueue(
            request=_request(job_id=job_id),
            queue_scope=scope,
            root_dir=tmp_path / job_id,
        )
        store.claim_next(
            queue_scope=scope,
            worker_key=f"worker-{job_id}",
            assigned_account=account_key,
            account_key=account_key,
            execution_owner="owner-1",
            lease_seconds=60,
        )

    before_orphan = store.get_status("orphan-job")["heartbeat_at"]
    renewed = store.renew_active_execution_leases(
        execution_owner="owner-1",
        attempts=[
            {
                "job_id": "tracked-job",
                "account_key": "tracked-account",
                "assignment_generation": 1,
            }
        ],
        lease_seconds=120,
    )

    assert renewed == 1
    assert store.get_status("tracked-job")["heartbeat_at"] is not None
    assert store.get_status("orphan-job")["heartbeat_at"] == before_orphan


def test_store_persists_listing_task_id_only_for_current_generation(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_listing_request(job_id="listing-job"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "listing-job",
    )
    claimed = store.claim_next_listing_analysis(
        queue_scope="seller_sprite",
        worker_key="listing-worker",
        assigned_account="default",
        account_key="account-key",
        execution_owner="owner-1",
    )

    stale = store.save_listing_analysis_task_id(
        job_id="listing-job",
        task_id="remote-stale",
        execution_owner="owner-1",
        assignment_generation=0,
    )
    current = store.save_listing_analysis_task_id(
        job_id="listing-job",
        task_id="remote-current",
        execution_owner="owner-1",
        assignment_generation=claimed["assignment_generation"],
    )

    assert stale is False
    assert current is True
    assert store.get_listing_analysis_task_id("listing-job") == "remote-current"


def test_store_claim_initializes_progress_and_rejects_stale_progress_update(tmp_path: Path):
    """领取任务应写入 claimed 时间线，旧代际不得推进当前进度。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-progress"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-progress",
    )
    claimed = store.claim_next_generic_for_account(
        queue_scope="seller_sprite",
        account_key="account-key-1",
        assigned_account="account-1",
        worker_key="slot-1",
        execution_owner="owner-1",
    )

    stale = store.update_task_progress(
        job_id="job-progress",
        account_key="account-key-1",
        assignment_generation=0,
        execution_owner="owner-1",
        stage="requesting",
    )
    current = store.update_task_progress(
        job_id="job-progress",
        account_key="account-key-1",
        assignment_generation=claimed["assignment_generation"],
        execution_owner="owner-1",
        stage="requesting",
        metadata={
            "poll_attempt": 3,
            "poll_status": "RUNNING",
            "request_params": {"asin": "B0SECRET"},
            "credential": "secret-token",
            "path": str(tmp_path / "private.json"),
            "source": str(tmp_path / "private-source"),
            "outcome": str(tmp_path / "private-outcome"),
        },
    )

    assert stale is False
    assert current is True
    status = store.get_status("job-progress")
    assert status["stage"] == "requesting"
    assert status["progress_stage"] == "requesting"
    assert status["progress_at"] is not None
    assert status["progress_sequence"] == 2
    assert store.list_task_progress_events(job_id="job-progress") == [
        {
            "job_id": "job-progress",
            "stage": "claimed",
            "progress_at": claimed["progress_at"],
            "sequence": 1,
            "assignment_generation": 1,
            "metadata": {},
        },
        {
            "job_id": "job-progress",
            "stage": "requesting",
            "progress_at": status["progress_at"],
            "sequence": 2,
            "assignment_generation": 1,
            "metadata": {"poll_attempt": 3, "poll_status": "RUNNING"},
        },
    ]


def test_store_publishes_and_stops_runtime_heartbeat(tmp_path: Path):
    """运行态心跳应保留监控容量字段，并可明确进入 stopped 生命周期。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.publish_runtime_heartbeat(
        execution_owner="owner-1",
        lifecycle_state="running",
        generic_workers_alive=2,
        listing_worker_alive=1,
        generic_available_capacity=1,
        listing_available_capacity=0,
        available_capacity=1,
        standby_capacity=3,
        last_claim_at="2026-07-29T10:00:00+08:00",
        last_progress_at="2026-07-29T10:00:01+08:00",
    )

    running = store.get_runtime_heartbeat("owner-1")
    assert running["execution_owner"] == "owner-1"
    assert running["lifecycle_state"] == "running"
    assert running["generic_workers_alive"] == 2
    assert running["listing_worker_alive"] == 1
    assert running["generic_available_capacity"] == 1
    assert running["listing_available_capacity"] == 0
    assert running["available_capacity"] == 1
    assert running["standby_capacity"] == 3
    assert running["last_claim_at"] == "2026-07-29T10:00:00+08:00"
    assert running["last_progress_at"] == "2026-07-29T10:00:01+08:00"

    assert store.mark_runtime_stopped(execution_owner="owner-1") is True
    stopped = store.get_runtime_heartbeat("owner-1")
    assert stopped["lifecycle_state"] == "stopped"
    assert stopped["generic_workers_alive"] == 0
    assert stopped["listing_worker_alive"] == 0
    assert stopped["generic_available_capacity"] == 0
    assert stopped["listing_available_capacity"] == 0
    assert stopped["available_capacity"] == 0


def test_store_marks_task_finished_and_persists_result_metadata(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(request=_request(job_id="job-1"), queue_scope="seller_sprite", root_dir=tmp_path / "job-1")
    store.claim_next(queue_scope="seller_sprite", worker_key="default", assigned_account="default")

    store.finish_task(
        job_id="job-1",
        result_path=str(tmp_path / "job-1" / "result.json"),
        row_count=3,
        export_payload={"path": "/tmp/job-1.json", "filename": "job-1.json"},
    )

    status = store.get_status("job-1")

    assert status["state"] == "succeeded"
    assert status["stage"] == "finished"
    assert status["row_count"] == 3
    assert status["export"]["filename"] == "job-1.json"
    assert status["position"] is None


def test_store_persists_only_non_sensitive_credential_scope(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-auth"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-auth",
        credential_scope=str(tmp_path / "credentials-user-1"),
        expected_user_email="user-1@example.com",
    )

    context = store.get_task_context("job-auth")

    assert context == {
        "credential_scope": str(tmp_path / "credentials-user-1"),
        "runtime_auth_required": False,
        "expected_user_email": "user-1@example.com",
        "session_id": None,
        "jwt": None,
    }


def test_store_clears_task_auth_context_after_success(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-auth-success"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-auth-success",
        credential_scope=str(tmp_path / "credentials-success"),
    )

    store.finish_task(
        job_id="job-auth-success",
        result_path=str(tmp_path / "job-auth-success" / "result.json"),
        row_count=0,
        export_payload=None,
    )

    assert store.get_task_context("job-auth-success") == {
        "credential_scope": None,
        "runtime_auth_required": False,
        "expected_user_email": None,
        "session_id": None,
        "jwt": None,
    }


def test_store_clears_task_auth_context_after_failure(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.enqueue(
        request=_request(job_id="job-auth-failed"),
        queue_scope="seller_sprite",
        root_dir=tmp_path / "job-auth-failed",
        credential_scope=str(tmp_path / "credentials-failed"),
    )

    store.fail_task(
        job_id="job-auth-failed",
        error_payload={"code": "TEST", "message": "failed"},
    )

    assert store.get_task_context("job-auth-failed") == {
        "credential_scope": None,
        "runtime_auth_required": False,
        "expected_user_email": None,
        "session_id": None,
        "jwt": None,
    }


def test_store_atomic_owned_enqueue_persists_queue_and_mcp_run(tmp_path: Path):
    """原子 owned enqueue 成功后必须同时存在队列行和所有权行。"""
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = _mcp_request(job_id="atomic-job-1")

    queued = store.enqueue_owned_mcp_run(
        request=request,
        queue_scope="seller_sprite",
        root_dir=tmp_path / "atomic-job-1",
        user_email="user@example.com",
        credential_scope=str(tmp_path / "credentials-user"),
        expected_user_email="user@example.com",
    )

    assert queued["job_id"] == "atomic-job-1"
    assert queued["state"] == "queued"
    assert store.get_task_context("atomic-job-1") == {
        "credential_scope": str(tmp_path / "credentials-user"),
        "runtime_auth_required": False,
        "expected_user_email": "user@example.com",
        "session_id": None,
        "jwt": None,
    }
    assert store.get_mcp_run("atomic-job-1")["user_email"] == "user@example.com"


def test_store_atomic_owned_enqueue_rolls_back_owner_on_queue_collision(tmp_path: Path):
    """caller-controlled job_id 碰撞时不得遗留当前用户所有权。"""
    import pytest

    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    original = _request(job_id="collision-job", asin="B0ORIGINAL")
    store.enqueue(
        request=original,
        queue_scope="seller_sprite",
        root_dir=tmp_path / "original",
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.enqueue_owned_mcp_run(
            request=_mcp_request(job_id="collision-job", asin="B0INTRUDER"),
            queue_scope="seller_sprite",
            root_dir=tmp_path / "intruder",
            user_email="intruder@example.com",
        )

    with pytest.raises(ValueError, match="MCP 调用记录不存在"):
        store.get_mcp_run("collision-job")
    assert store.get_status("collision-job")["state"] == "queued"
    assert store.get_request("collision-job").params == {"asin": "B0ORIGINAL"}


def test_store_create_mcp_run_persists_initial_record(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    created = store.create_mcp_run(_mcp_request(job_id="mcp-job-1"), "user@example.com")

    assert created["job_id"] == "mcp-job-1"
    assert created["user_email"] == "user@example.com"
    assert created["scenario"] == "keyword-reverse"
    assert created["mode"] == "browser-route"
    assert created["params_json"] == {"asin": "B07YRMT36L"}
    assert created["result_state"] == "queued"
    assert created["result_row_count"] == 0
    assert created["result_export_format"] is None
    assert created["result_export_filename"] is None
    assert created["result_export_job_id"] is None
    assert created["error_json"] is None
    assert created["created_at"] is not None
    assert created["started_at"] is None
    assert created["finished_at"] is None
    assert created["updated_at"] is not None


def test_store_mcp_run_updates_from_running_to_succeeded(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.create_mcp_run(_mcp_request(job_id="mcp-job-2"), "user@example.com")

    store.mark_mcp_run_running("mcp-job-2")
    store.finish_mcp_run_success(
        "mcp-job-2",
        row_count=5,
        export_payload={
            "format": "json",
            "filename": "mcp-job-2.json",
        },
    )

    record = store.get_mcp_run("mcp-job-2")

    assert record["job_id"] == "mcp-job-2"
    assert record["result_state"] == "succeeded"
    assert record["result_row_count"] == 5
    assert record["result_export_format"] == "json"
    assert record["result_export_filename"] == "mcp-job-2.json"
    assert record["result_export_job_id"] == "mcp-job-2"
    assert record["error_json"] is None
    assert record["started_at"] is not None
    assert record["finished_at"] is not None
    assert record["updated_at"] is not None


def test_store_mcp_run_updates_to_failed(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    store.create_mcp_run(_mcp_request(job_id="mcp-job-3"), "user@example.com")

    store.finish_mcp_run_failed(
        "mcp-job-3",
        error_payload={"code": "SELLER_SPRITE_ERROR", "message": "任务失败"},
    )

    record = store.get_mcp_run("mcp-job-3")

    assert record["job_id"] == "mcp-job-3"
    assert record["result_state"] == "failed"
    assert record["result_row_count"] == 0
    assert record["result_export_format"] is None
    assert record["result_export_filename"] is None
    assert record["result_export_job_id"] is None
    assert record["error_json"] == {
        "code": "SELLER_SPRITE_ERROR",
        "message": "任务失败",
    }
    assert record["started_at"] is None
    assert record["finished_at"] is not None
    assert record["updated_at"] is not None


def test_store_initializes_mcp_runs_table_with_expected_columns(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    SellerSpriteTaskQueueStore(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]: {"type": row[2], "notnull": row[3], "pk": row[5]}
            for row in conn.execute("PRAGMA table_info(seller_sprite_mcp_runs)")
        }

    assert "job_id" in columns
    assert columns["job_id"]["type"] == "TEXT"
    assert columns["job_id"]["pk"] == 1
    assert "mode" in columns
    assert columns["mode"]["type"] == "TEXT"
    assert columns["mode"]["notnull"] == 1
    assert "result_state" in columns
    assert columns["result_state"]["type"] == "TEXT"
    assert columns["result_state"]["notnull"] == 1
    assert "params_json" in columns
    assert columns["params_json"]["type"] == "TEXT"
    assert columns["params_json"]["notnull"] == 1


def test_store_migrates_legacy_mcp_runs_table_and_supports_updates(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE seller_sprite_mcp_runs (
                job_id TEXT NOT NULL PRIMARY KEY,
                user_email TEXT NOT NULL,
                scenario TEXT NOT NULL,
                mode TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    store = SellerSpriteTaskQueueStore(db_path=db_path)
    store.create_mcp_run(_mcp_request(job_id="legacy-job-1"), "user@example.com")
    store.mark_mcp_run_running("legacy-job-1")
    store.finish_mcp_run_success(
        "legacy-job-1",
        row_count=2,
        export_payload={"format": "json", "filename": "legacy-job-1.json"},
    )

    record = store.get_mcp_run("legacy-job-1")

    assert record["job_id"] == "legacy-job-1"
    assert record["mode"] == "browser-route"
    assert record["result_state"] == "succeeded"
    assert record["result_row_count"] == 2
    assert record["result_export_format"] == "json"
    assert record["result_export_filename"] == "legacy-job-1.json"
    assert record["result_export_job_id"] == "legacy-job-1"
    assert record["error_json"] is None
    assert record["started_at"] is not None
    assert record["finished_at"] is not None


def test_store_mark_mcp_run_running_raises_when_job_missing(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    try:
        store.mark_mcp_run_running("missing-job")
    except ValueError as exc:
        assert "MCP 调用记录不存在" in str(exc)
    else:
        raise AssertionError("缺失 job_id 时应抛出异常")


def test_store_migrates_legacy_mcp_runs_table_without_updated_at(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    db_path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE seller_sprite_mcp_runs (
                job_id TEXT NOT NULL PRIMARY KEY,
                user_email TEXT NOT NULL,
                scenario TEXT NOT NULL,
                mode TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_state TEXT NOT NULL,
                result_row_count INTEGER NOT NULL DEFAULT 0,
                result_export_format TEXT NULL,
                result_export_filename TEXT NULL,
                result_export_job_id TEXT NULL,
                error_json TEXT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NULL,
                finished_at TEXT NULL
            )
            """
        )

    store = SellerSpriteTaskQueueStore(db_path=db_path)
    record = store.create_mcp_run(_mcp_request(job_id="legacy-job-2"), "user@example.com")

    assert record["job_id"] == "legacy-job-2"
    assert record["mode"] == "browser-route"
    assert record["result_state"] == "queued"
    assert record["updated_at"] is not None
