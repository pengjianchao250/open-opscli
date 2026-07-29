from types import SimpleNamespace

from typer.testing import CliRunner

from opscli.cli import app
from opscli.seller_sprite import cli as seller_sprite_cli

runner = CliRunner()


def test_public_seller_sprite_scenarios_uses_remote_adapter(monkeypatch):
    class FakeAdapter:
        def scenarios(self):
            return {
                "success": True,
                "data": [{"id": "keyword-reverse"}],
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(app, ["seller-sprite", "scenarios"])

    assert result.exit_code == 0
    assert '"keyword-reverse"' in result.stdout


def test_public_seller_sprite_quota_status_uses_remote_adapter(monkeypatch):
    class FakeAdapter:
        def quota_status(self):
            return {
                "success": True,
                "data": {"service": "seller_sprite", "remaining": 4},
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(app, ["seller-sprite", "quota-status"])

    assert result.exit_code == 0
    assert '"remaining": 4' in result.stdout


def test_public_seller_sprite_queue_commands_use_local_store(monkeypatch):
    calls = {}

    class FakeStore:
        db_path = "queue.sqlite3"

        def queue_status(self, *, stale_running_seconds=1800):
            calls["status"] = stale_running_seconds
            return {
                "db_path": str(self.db_path),
                "by_state": {"queued": 2},
                "stale_running_count": 0,
            }

        def list_tasks(self, *, state=None, limit=50):
            calls["list"] = {"state": state, "limit": limit}
            return [{"job_id": "job-1", "state": state or "queued"}]

        def fail_tasks(self, *, state="queued", job_ids=None, before=None, reason="人工终止队列任务"):
            calls["fail"] = {
                "state": state,
                "job_ids": job_ids,
                "before": before,
                "reason": reason,
            }
            return 1

        def reset_running_tasks(self, *, before_started_at=None):
            calls["requeue"] = before_started_at
            return 3

    monkeypatch.setattr(seller_sprite_cli, "_get_queue_store", lambda: FakeStore())

    status = runner.invoke(app, ["seller-sprite", "queue", "status"])
    listed = runner.invoke(app, ["seller-sprite", "queue", "list", "--state", "queued", "--limit", "5"])
    failed = runner.invoke(
        app,
        [
            "seller-sprite",
            "queue",
            "fail",
            "--job-id",
            "job-1",
            "--reason",
            "人工终止排队任务",
        ],
    )
    requeued = runner.invoke(app, ["seller-sprite", "queue", "requeue-running", "--older-than-minutes", "30"])
    health = runner.invoke(app, ["seller-sprite", "queue", "worker-health"])

    assert status.exit_code == 0
    assert listed.exit_code == 0
    assert failed.exit_code == 0
    assert requeued.exit_code == 0
    assert health.exit_code == 0
    assert calls["status"] == 1800
    assert calls["list"] == {"state": "queued", "limit": 5}
    assert calls["fail"]["job_ids"] == ["job-1"]
    assert calls["fail"]["reason"] == "人工终止排队任务"
    assert calls["requeue"] is not None
    assert '"changed": 1' in failed.stdout
    assert '"changed": 3' in requeued.stdout
    assert '"worker_state": "no_heartbeat"' in health.stdout


def test_account_binding_cli_hides_password_and_outputs_masked_binding(monkeypatch):
    calls = {}

    class FakeStore:
        def bind(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                to_public_dict=lambda: {
                    "user_email": "user@example.com",
                    "account_name": "team-a",
                    "username": "s***@example.com",
                }
            )

    monkeypatch.setattr(
        seller_sprite_cli,
        "_get_account_binding_store",
        lambda: FakeStore(),
    )

    result = runner.invoke(
        app,
        [
            "seller-sprite",
            "account-binding",
            "bind",
            "--user-email",
            "User@Example.com",
            "--account-name",
            "team-a",
            "--username",
            "seller@example.com",
        ],
        input="dedicated-secret\n",
    )

    assert result.exit_code == 0
    assert calls["password"] == "dedicated-secret"
    assert "dedicated-secret" not in result.stdout
    assert '"username": "s***@example.com"' in result.stdout


def test_account_binding_cli_lists_masked_bindings(monkeypatch):
    monkeypatch.setattr(
        seller_sprite_cli,
        "_get_account_binding_store",
        lambda: SimpleNamespace(
            list_bindings=lambda: [
                {
                    "user_email": "user@example.com",
                    "account_name": "team-a",
                    "username": "s***@example.com",
                }
            ]
        ),
    )

    result = runner.invoke(app, ["seller-sprite", "account-binding", "list"])

    assert result.exit_code == 0
    assert '"username": "s***@example.com"' in result.stdout
    assert "password" not in result.stdout


def test_account_binding_cli_unbinds_after_failing_queued_tasks(monkeypatch):
    calls = []

    class FakeBindingStore:
        def get_binding_reference(self, user_email):
            calls.append(("reference", user_email))
            return SimpleNamespace(user_email="user@example.com")

        def unbind(self, user_email):
            calls.append(("unbind", user_email))
            return True

    class FakeQueueStore:
        def fail_queued_user_binding_tasks(self, *, user_email, reason):
            calls.append(("fail_queued", user_email, reason))
            return 2

    monkeypatch.setattr(
        seller_sprite_cli,
        "_get_account_binding_store",
        lambda: FakeBindingStore(),
    )
    monkeypatch.setattr(
        seller_sprite_cli,
        "_get_queue_store",
        lambda: FakeQueueStore(),
    )

    result = runner.invoke(
        app,
        [
            "seller-sprite",
            "account-binding",
            "unbind",
            "--user-email",
            "User@Example.com",
        ],
    )

    assert result.exit_code == 0
    assert [call[0] for call in calls] == ["reference", "fail_queued", "unbind"]
    assert '"deleted": true' in result.stdout
    assert '"failed_queued_tasks": 2' in result.stdout
