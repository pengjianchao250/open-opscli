import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opscli.mcp import ops_credentials
from opscli.mcp.tools import seller_sprite as seller_sprite_tools
from opscli.mcp.server import _quota_wrap


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _route_credential_test_seams(monkeypatch):
    """让既有工具测试替身经统一凭证模块生效，且不读取真实本机凭证。"""
    original_auth_pair = ops_credentials._get_auth_pair
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_auth_pair",
        original_auth_pair,
        raising=False,
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_auth_pair",
        lambda system, session_id, jwt: seller_sprite_tools._get_auth_pair(
            system,
            session_id,
            jwt,
        ),
    )
    monkeypatch.setattr(
        ops_credentials,
        "_get_authenticated_user_email",
        lambda: seller_sprite_tools._get_current_mcp_user_email(),
    )


class DummyManager:
    def scenarios(self):
        return [{"scenario_id": "keyword-reverse", "title": "关键词反查"}]


class DummyScheduler:
    last_request = None
    last_enqueue_kwargs = None
    enqueue_calls = 0

    async def enqueue(self, request, **kwargs):
        self.__class__.last_request = request
        self.__class__.last_enqueue_kwargs = kwargs
        self.__class__.enqueue_calls += 1
        return {
            "job_id": request.job_id or "job-async-1",
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
        }

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "state": "queued",
            "stage": "queued",
            "position": 2,
            "row_count": 1,
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx"},
        }


class SuccessPollingScheduler:
    def __init__(self):
        now = datetime.now(timezone.utc).astimezone()
        self.created_at = (now - timedelta(seconds=12)).isoformat(timespec="seconds")
        self.started_at = (now - timedelta(seconds=4)).isoformat(timespec="seconds")
        self.job_status_calls = 0

    async def enqueue(self, request, **kwargs):
        return {
            "job_id": request.job_id or "job-success-1",
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
            "created_at": self.created_at,
            "started_at": None,
            "finished_at": None,
        }

    def job_status(self, job_id):
        self.job_status_calls += 1
        if self.job_status_calls == 1:
            return {
                "job_id": job_id,
                "state": "queued",
                "stage": "queued",
                "position": 1,
                "created_at": self.created_at,
                "started_at": None,
                "finished_at": None,
            }
        if self.job_status_calls == 2:
            return {
                "job_id": job_id,
                "state": "running",
                "stage": "running",
                "position": None,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": None,
            }
        return {
            "job_id": job_id,
            "state": "succeeded",
            "stage": "finished",
            "position": None,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "row_count": 3,
            "export": {"path": f"/tmp/{job_id}.json", "filename": f"{job_id}.json"},
        }


class RunningTimeoutScheduler:
    def __init__(self):
        now = datetime.now(timezone.utc).astimezone()
        self.created_at = (now - timedelta(minutes=9)).isoformat(timespec="seconds")
        self.started_at = (now - timedelta(minutes=8, seconds=5)).isoformat(timespec="seconds")

    async def enqueue(self, request, **kwargs):
        return {
            "job_id": request.job_id or "job-timeout-1",
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
            "created_at": self.created_at,
            "started_at": None,
            "finished_at": None,
        }

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "state": "running",
            "stage": "running",
            "position": None,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": None,
        }


class FailingScheduler:
    async def enqueue(self, request, **kwargs):
        raise RuntimeError("enqueue boom")


class NoNormalizeScheduler:
    last_request = None
    enqueue_calls = 0

    async def enqueue(self, request, **kwargs):
        self.__class__.last_request = request
        self.__class__.enqueue_calls += 1
        return {
            "job_id": request.job_id,
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "queued",
            "position": 1,
        }


class RecordingStore:
    def __init__(self):
        self.create_calls = 0
        self.finish_failed_calls = 0

    def create_mcp_run(self, request, user_email):
        self.create_calls += 1
        raise RuntimeError("create run boom")

    def finish_mcp_run_failed(self, job_id, error_payload):
        self.finish_failed_calls += 1


def _make_store(tmp_path: Path):
    from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

    return SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")


def _skip_wait_for_run(monkeypatch):
    async def _fake_wait(*, scheduler, job_id, initial_status):
        return initial_status

    monkeypatch.setattr(seller_sprite_tools, "_wait_for_seller_sprite_run_result", _fake_wait)


def test_seller_sprite_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "keyword-reverse"


def test_seller_sprite_spec_must_read_includes_scenario_param_manual():
    result = _run(seller_sprite_tools.seller_sprite_spec_must_read())

    assert result["success"] is True
    assert "# 卖家精灵场景参数手册" in result["data"]["spec"]
    assert "seller_sprite_listing_analysis_submit" in result["data"]["spec"]
    assert "不要让 `seller_sprite_run` 同步阻塞等待 `listing-analysis`" in result["data"]["spec"]


def test_seller_sprite_quota_status_returns_snapshot(monkeypatch):
    class FakeLimiter:
        def quota_snapshot(self, tool_name, identity):
            assert tool_name == "seller_sprite_run"
            assert identity == "email:mcp-user@example.com"
            return {
                "service": "seller_sprite",
                "limit": 5,
                "used": 2,
                "remaining": 3,
                "failures": 0,
                "reset_at": "2026-06-24T00:00:00+08:00",
            }

    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr("opscli.mcp.tools.seller_sprite.get_quota_limiter", lambda: FakeLimiter())

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is True
    assert result["data"]["remaining"] == 3


def test_seller_sprite_quota_status_returns_error_when_user_email_missing(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: None)

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]


def test_seller_sprite_run_accepts_params_json_string(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    _skip_wait_for_run(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params='{"asin":"B07YRMT36L"}',
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert result["data"]["position"] == 1
    assert DummyScheduler.last_request.params == {"asin": "B07YRMT36L"}
    assert DummyScheduler.last_request.page_size == 100
    assert DummyScheduler.last_request.export_format == "json"
    assert DummyScheduler.last_request.mode == "browser-route"
    assert DummyScheduler.enqueue_calls == 1
    assert store.get_mcp_run("job-async-1")["mode"] == "browser-route"


def test_listing_analysis_submit_enqueues_without_run_wait(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "listing-job-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_listing_analysis_submit(
            asin="b0test123",
            station="global",
            site="US",
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "listing-job-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.last_request.scenario == "listing-analysis"
    assert DummyScheduler.last_request.params == {"asin": "B0TEST123", "station": "GLOBAL"}
    assert DummyScheduler.last_request.mode == "browser-route"
    assert DummyScheduler.enqueue_calls == 1



def test_listing_analysis_status_returns_local_queue_state(monkeypatch):
    class LocalOnlyScheduler:
        def job_status(self, job_id):
            return {"job_id": job_id, "scenario": "listing-analysis", "state": "running", "stage": "running"}

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: LocalOnlyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["state"] == "running"
    assert result["data"]["ready"] is False



def test_listing_analysis_history_status_uses_history_get_endpoint(monkeypatch):
    class FakeManager:
        def __init__(self, **kwargs):
            self.account_provider = type("AccountProvider", (), {"get_default": lambda self: object()})()

    class FakeClient:
        calls = []

        def __init__(self, *, account):
            self.account = account

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def has_login_cookies(self):
            return True

        async def login(self):
            raise AssertionError("cached browser cookies should be used for history status")

        async def get_json(self, url, params, *, referer=None):
            self.__class__.calls.append({"url": url, "params": params, "referer": referer})
            return {
                "code": "OK",
                "success": True,
                "data": {
                    "items": [
                        {
                            "taskId": "f1f297d499620bd41177fa5455ff8001",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B0FQJR6RTS) | 全景分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            }

        async def post_json(self, *args, **kwargs):
            raise AssertionError("task/history must follow the page GET request shape")

    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", FakeManager)
    monkeypatch.setattr("opscli.seller_sprite.api.client.SellerSpriteApiClient", FakeClient)

    result = _run(
        seller_sprite_tools._fetch_listing_analysis_history_status(
            asin="B0FQJR6RTS",
            session_id="sid",
            jwt="jwt",
        )
    )

    assert result["task_id"] == "f1f297d499620bd41177fa5455ff8001"
    assert FakeClient.calls == [
        {
            "url": "/v3/api/ai-analysis/task/history",
            "params": {"page": 1, "pageSize": 20, "keywords": "", "modules": ""},
            "referer": "https://www.sellersprite.com/v3/ai-history?module=LA",
        }
    ]


def test_listing_analysis_status_relogs_and_retries_expired_history_session(monkeypatch):
    from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError

    class SubmittedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"asin": "B08Z6X4NK3", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B08Z6X4NK3", "station": "GLOBAL"},
            }

    class FakeManager:
        def __init__(self, **kwargs):
            self.account_provider = type(
                "AccountProvider",
                (),
                {"get_default": lambda self: object()},
            )()

    class ExpiredThenReadyClient:
        history_calls = 0
        login_calls = 0

        def __init__(self, *, account):
            self.account = account

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def has_login_cookies(self):
            return True

        async def login(self):
            self.__class__.login_calls += 1
            return {"logged_in": True}

        async def get_json(self, url, params, *, referer=None):
            self.__class__.history_calls += 1
            if self.__class__.history_calls == 1:
                raise SellerSpriteApiError(
                    "卖家精灵登录态失效",
                    api_code="ERR_GLOBAL_SESSION_EXPIRED",
                )
            return {
                "code": "OK",
                "data": {
                    "items": [
                        {
                            "taskId": "task-ready-after-relogin",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B08Z6X4NK3) | 全景分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            }

    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", FakeManager)
    monkeypatch.setattr(
        "opscli.seller_sprite.api.client.SellerSpriteApiClient",
        ExpiredThenReadyClient,
    )
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_task_scheduler",
        lambda **kwargs: SubmittedScheduler(),
    )
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-expired"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["task_id"] == "task-ready-after-relogin"
    assert ExpiredThenReadyClient.login_calls == 1
    assert ExpiredThenReadyClient.history_calls == 2



def test_listing_analysis_status_reads_history_by_asin(monkeypatch):
    class SubmittedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "stage": "finished",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        assert session_id == "sid"
        assert jwt == "jwt"
        return {
            "task_id": "86ead00315941d0810d9b564e2986013",
            "ready": True,
            "failed": False,
            "remote": {
                "code": "OK",
                "data": {
                    "items": [
                        {
                            "taskId": "86ead00315941d0810d9b564e2986013",
                            "taskStatus": "COMPLETED",
                            "tabTitle": "US(B0FQJR6RTS) | 文案质量分析 | Listing数据深度解析报告",
                            "module": "LA",
                        }
                    ]
                },
            },
        }

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: SubmittedScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["task_id"] == "86ead00315941d0810d9b564e2986013"



def test_listing_analysis_status_rejects_other_user_job(monkeypatch):
    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "owner@example.com"}

    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "intruder@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is False
    assert "无权读取" in result["error"]["message"]


def test_listing_analysis_result_reports_not_ready(monkeypatch):
    class PendingScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

    async def fake_remote_status(*args, **kwargs):
        return {"task_id": "task-1", "ready": False, "remote": {"data": {"taskStatus": "RUNNING"}}}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: PendingScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["task_id"] == "task-1"



def test_listing_analysis_result_prefers_history_task_id_over_submit_placeholder(monkeypatch):
    class ReadyTaskScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        return {
            "task_id": "f1f297d499620bd41177fa5455ff8001",
            "ready": True,
            "failed": False,
            "remote_status": "COMPLETED",
            "history_item": {
                "taskId": "f1f297d499620bd41177fa5455ff8001",
                "taskStatus": "COMPLETED",
                "tabTitle": "US(B0FQJR6RTS) | 全景分析 | Listing数据深度解析报告",
                "module": "LA",
            },
            "remote": {"code": "OK", "success": True},
        }

    async def fake_report_result(*, task_id, session_id, jwt):
        assert task_id == "f1f297d499620bd41177fa5455ff8001"
        return {"task_id": task_id, "ready": False, "failed": False, "analyzing": True, "remote": None}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyTaskScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_report_result)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["task_id"] == "f1f297d499620bd41177fa5455ff8001"



def test_listing_analysis_result_uses_report_page_when_history_task_ready(monkeypatch):
    class ReadyTaskScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "asin": "B0FQJR6RTS", "contentReady": False}],
            }

    class OwnerStore:
        def get_mcp_run(self, job_id):
            return {
                "job_id": job_id,
                "user_email": "mcp-user@example.com",
                "params_json": {"asin": "B0FQJR6RTS", "station": "GLOBAL"},
            }

    async def fail_old_remote_status(*args, **kwargs):
        raise AssertionError("result must open ai-report through browser-route instead of old task API")

    async def fake_history_status(*, asin, session_id, jwt):
        assert asin == "B0FQJR6RTS"
        return {"task_id": "task-1", "ready": True, "failed": False, "remote_status": "COMPLETED", "remote": {}}

    async def fake_report_result(*, task_id, session_id, jwt):
        assert task_id == "task-1"
        assert session_id == "sid"
        assert jwt == "jwt"
        return {"task_id": "task-1", "ready": False, "failed": False, "analyzing": True, "remote": None}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyTaskScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_remote_status", fail_old_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_history_status", fake_history_status)
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_report_result, raising=False)
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: OwnerStore())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["analyzing"] is True
    assert result["data"]["task_id"] == "task-1"



def test_listing_analysis_result_marks_remote_failure(monkeypatch):
    class FailedScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class RecordingStore:
        def __init__(self):
            self.fail_task_call = None
            self.finish_mcp_run_failed_call = None

        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

        def fail_task(self, **kwargs):
            self.fail_task_call = kwargs

        def finish_mcp_run_failed(self, job_id, error_payload):
            self.finish_mcp_run_failed_call = {"job_id": job_id, "error_payload": error_payload}

    async def fake_remote_status(*args, **kwargs):
        return {
            "task_id": "task-1",
            "ready": False,
            "failed": True,
            "remote": {"data": {"taskStatus": "FAILED", "message": "AI task failed"}},
        }

    store = RecordingStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: FailedScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["failed"] is True
    assert result["data"]["state"] == "failed"
    assert store.fail_task_call["job_id"] == "listing-job-1"
    assert store.finish_mcp_run_failed_call["error_payload"]["code"] == "SELLER_SPRITE_LISTING_ANALYSIS_FAILED"



def test_listing_analysis_result_persists_ready_remote_payload(monkeypatch, tmp_path):
    root_dir = tmp_path / "listing-job-1"

    class ReadyScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "site": "US",
                "period": "30d",
                "state": "succeeded",
                "root_dir": str(root_dir),
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    class RecordingStore:
        def __init__(self):
            self.finish_task_call = None
            self.finish_mcp_run_success_call = None

        def get_mcp_run(self, job_id):
            return {"job_id": job_id, "user_email": "mcp-user@example.com"}

        def finish_task(self, **kwargs):
            self.finish_task_call = kwargs

        def finish_mcp_run_success(self, job_id, row_count, export_payload):
            self.finish_mcp_run_success_call = {
                "job_id": job_id,
                "row_count": row_count,
                "export_payload": export_payload,
            }

    async def fake_remote_status(*args, **kwargs):
        return {
            "task_id": "task-1",
            "ready": True,
            "failed": False,
            "remote": {
                "code": "OK",
                "data": {
                    "taskId": "task-1",
                    "taskStatus": "COMPLETED",
                    "content": "Listing 分析正文",
                    "htmlContent": "<p>Listing 分析正文</p>",
                    "completedTime": "2026-07-09 12:00:00",
                },
            },
        }

    store = RecordingStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: ReadyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_report_result", fake_remote_status)
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["row_count"] == 1
    assert result["data"]["data"][0]["content"] == "Listing 分析正文"
    assert result["data"]["export"]["format"] == "json"
    assert Path(result["data"]["result_path"]).exists()
    assert Path(result["data"]["raw_path"]).exists()
    assert Path(result["data"]["export"]["path"]).exists()
    assert store.finish_task_call["job_id"] == "listing-job-1"
    assert store.finish_task_call["row_count"] == 1
    assert store.finish_mcp_run_success_call["export_payload"]["format"] == "json"



def test_seller_sprite_start_returns_queued_job(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(
        seller_sprite_tools,
        "_get_current_mcp_user_email",
        lambda: "mcp-user@example.com",
    )
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_start(
            scenario="product-research",
            site="US",
            period="30d",
            params={"nodeIdPaths": ["1055398:1063306:1063312:10824421"]},
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_request.scenario == "product-research"
    assert DummyScheduler.last_request.params == {
        "nodeIdPaths": ["1055398:1063306:1063312:10824421"]
    }
    assert DummyScheduler.last_request.export_format == "json"
    assert DummyScheduler.last_request.mode == "browser-route"


def test_seller_sprite_run_always_enqueues(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    _skip_wait_for_run(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="product-research",
            site="US",
            period="30d",
            params={"nodeIdPaths": ["1055398:1063306:1063312:10824421"]},
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.enqueue_calls == 1
    assert store.get_mcp_run("job-async-1")["job_id"] == "job-async-1"


def test_seller_sprite_run_waits_until_success(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    scheduler = SuccessPollingScheduler()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-success-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    monkeypatch.setattr(seller_sprite_tools, "SELLER_SPRITE_RUN_POLL_INTERVAL_SECONDS", 0, raising=False)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L"},
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-success-1"
    assert result["data"]["state"] == "succeeded"
    assert result["data"]["row_count"] == 3
    assert result["data"]["export"]["filename"] == "job-success-1.json"


def test_seller_sprite_run_returns_job_id_after_running_timeout(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    scheduler = RunningTimeoutScheduler()
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: scheduler)
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-timeout-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L"},
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-timeout-1"
    assert result["data"]["state"] == "running"
    assert result["data"]["queue_duration"] is not None
    assert result["data"]["running_duration"] is not None


def test_seller_sprite_export_returns_export_info(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    result = _run(seller_sprite_tools.seller_sprite_export("job-1"))

    assert result["success"] is True
    assert result["data"]["path"] == "/tmp/job-1.xlsx"
    assert result["data"]["url"].startswith("file://")


def test_seller_sprite_job_status_reads_scheduler(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    result = _run(seller_sprite_tools.seller_sprite_job_status("job-2"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-2"
    assert result["data"]["state"] == "queued"
    assert result["data"]["position"] == 2


def test_seller_sprite_run_is_wrapped_by_quota(monkeypatch):
    called = {"service": 0}

    class BlockingLimiter:
        async def before_call(self, tool_name):
            assert tool_name == "seller_sprite_run"
            return type(
                "Decision",
                (),
                {
                    "allowed": False,
                    "error_response": {
                        "success": False,
                        "data": None,
                        "error": {"code": "MCP_QUOTA_EXCEEDED", "message": "超出每日调用限额"},
                        "quota": {"service": "seller_sprite", "limit": 5, "used": 5, "remaining": 0},
                    },
                },
            )()

        async def after_call(self, ticket, response):
            raise AssertionError("blocked calls must not settle quota")

    async def limited_tool():
        called["service"] += 1
        return {"success": True, "data": {}, "error": None}

    limited_tool.__name__ = "seller_sprite_run"
    wrapped = _quota_wrap(limited_tool, limiter=BlockingLimiter())

    result = _run(wrapped())

    assert called["service"] == 0
    assert result["success"] is False
    assert result["error"]["code"] == "MCP_QUOTA_EXCEEDED"



def test_listing_analysis_submit_is_wrapped_by_seller_sprite_quota():
    called = {"service": 0}

    class BlockingLimiter:
        async def before_call(self, tool_name):
            assert tool_name == "seller_sprite_listing_analysis_submit"
            return type(
                "Decision",
                (),
                {
                    "allowed": False,
                    "error_response": {
                        "success": False,
                        "data": None,
                        "error": {"code": "MCP_QUOTA_EXCEEDED", "message": "超出每日调用限额"},
                        "quota": {"service": "seller_sprite", "limit": 5, "used": 5, "remaining": 0},
                    },
                },
            )()

        async def after_call(self, ticket, response):
            raise AssertionError("blocked calls must not settle quota")

    async def limited_tool():
        called["service"] += 1
        return {"success": True, "data": {}, "error": None}

    limited_tool.__name__ = "seller_sprite_listing_analysis_submit"
    wrapped = _quota_wrap(limited_tool, limiter=BlockingLimiter())

    result = _run(wrapped())

    assert called["service"] == 0
    assert result["success"] is False
    assert result["error"]["code"] == "MCP_QUOTA_EXCEEDED"


def test_seller_sprite_non_run_tools_are_not_wrapped_by_quota():
    called = {"service": 0}

    async def scenarios_tool():
        called["service"] += 1
        return {"success": True, "data": [], "error": None}

    scenarios_tool.__name__ = "seller_sprite_scenarios"
    wrapped = _quota_wrap(scenarios_tool)

    result = _run(wrapped())

    assert called["service"] == 1
    assert result["success"] is True


def test_seller_sprite_run_creates_mcp_run_before_enqueue(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    _skip_wait_for_run(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L", "keywords": ["router"]},
            export_format="json",
            job_id="mcp-job-run-1",
        )
    )

    assert result["success"] is True
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_enqueue_kwargs == {
        "credential_scope": "default",
        "expected_user_email": "mcp-user@example.com",
    }
    record = store.get_mcp_run("mcp-job-run-1")
    assert record["user_email"] == "mcp-user@example.com"
    assert record["scenario"] == "keyword-reverse"
    assert record["job_id"] == "mcp-job-run-1"
    assert record["mode"] == "browser-route"
    assert record["params_json"] == {"asin": "B07YRMT36L", "keywords": ["router"]}
    assert record["result_state"] == "queued"


def test_seller_sprite_run_ignores_legacy_explicit_auth_for_remote_mcp(monkeypatch, tmp_path):
    from opscli.mcp import context as mcp_context
    from opscli.mcp.ops_credentials import OpsCredentialBinding

    store = _make_store(tmp_path)
    _skip_wait_for_run(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())

    async def ensure_binding(*, provided_session, provided_jwt):
        assert provided_session == "explicit-session"
        assert provided_jwt == "explicit-jwt"
        return OpsCredentialBinding(
            credential_scope="isolated-user-scope",
            user_email="mcp-user@example.com",
            session_id="isolated-session",
            jwt="isolated-jwt",
        )

    monkeypatch.setattr(seller_sprite_tools, "ensure_ops_credentials", ensure_binding)
    monkeypatch.setattr(mcp_context, "get_current_api_key", lambda: "mcp-api-key")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
            job_id="mcp-job-explicit-auth",
            session_id="explicit-session",
            jwt="explicit-jwt",
        )
    )

    assert result["success"] is True
    assert DummyScheduler.enqueue_calls == 1
    assert DummyScheduler.last_enqueue_kwargs == {
        "credential_scope": "isolated-user-scope",
        "expected_user_email": "mcp-user@example.com",
    }
    assert store.get_mcp_run("mcp-job-explicit-auth")["result_state"] == "queued"


def test_seller_sprite_run_marks_mcp_run_failed_when_enqueue_raises(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: FailingScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="product-research",
            params={"asin": "B0FAIL1234"},
            job_id="mcp-job-run-failed",
        )
    )

    assert result["success"] is False
    record = store.get_mcp_run("mcp-job-run-failed")
    assert record["result_state"] == "failed"
    assert record["error_json"]["code"] == "RuntimeError"
    assert record["error_json"]["message"] == "enqueue boom"


def test_seller_sprite_run_returns_error_when_mcp_user_email_missing(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    DummyScheduler.enqueue_calls = 0
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: None)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]
    assert DummyScheduler.enqueue_calls == 0
    try:
        store.get_mcp_run("job-async-1")
        raise AssertionError("邮箱缺失时不应创建 MCP 调用记录")
    except ValueError:
        pass


def test_seller_sprite_run_does_not_mark_failed_when_create_record_itself_fails(monkeypatch):
    store = RecordingStore()
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is False
    assert store.create_calls == 1
    assert store.finish_failed_calls == 0


def test_seller_sprite_run_without_scheduler_normalize_still_creates_record(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    _skip_wait_for_run(monkeypatch)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: NoNormalizeScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "job-async-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    NoNormalizeScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="jp",
            period="nearly",
            params={"asin": "B07YRMT36L"},
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-async-1"
    assert result["data"]["site"] == "JP"
    assert result["data"]["period"] == "nearly"
    assert NoNormalizeScheduler.enqueue_calls == 1
    assert NoNormalizeScheduler.last_request.job_id == "job-async-1"
    assert store.get_mcp_run("job-async-1")["job_id"] == "job-async-1"
