import asyncio
from pathlib import Path

from opscli.mcp.tools import seller_sprite as seller_sprite_tools
from opscli.mcp.server import _quota_wrap


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    def scenarios(self):
        return [{"scenario_id": "keyword-reverse", "title": "关键词反查"}]


class DummyScheduler:
    last_request = None
    enqueue_calls = 0

    async def enqueue(self, request):
        self.__class__.last_request = request
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


class FailingScheduler:
    async def enqueue(self, request):
        raise RuntimeError("enqueue boom")


class NoNormalizeScheduler:
    last_request = None
    enqueue_calls = 0

    async def enqueue(self, request):
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


def test_seller_sprite_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "keyword-reverse"


def test_seller_sprite_spec_must_read_includes_scenario_param_manual():
    result = _run(seller_sprite_tools.seller_sprite_spec_must_read())

    assert result["success"] is True
    assert "# 卖家精灵场景参数手册" in result["data"]["spec"]


def test_seller_sprite_run_accepts_params_json_string(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
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


def test_seller_sprite_start_returns_queued_job(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
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
    record = store.get_mcp_run("mcp-job-run-1")
    assert record["user_email"] == "mcp-user@example.com"
    assert record["scenario"] == "keyword-reverse"
    assert record["job_id"] == "mcp-job-run-1"
    assert record["mode"] == "browser-route"
    assert record["params_json"] == {"asin": "B07YRMT36L", "keywords": ["router"]}
    assert record["result_state"] == "queued"


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
