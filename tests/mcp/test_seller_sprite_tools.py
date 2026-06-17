import asyncio

from opscli.mcp.tools import seller_sprite as seller_sprite_tools
from opscli.mcp.server import _quota_wrap
from opscli.seller_sprite.domain.models import SellerSpriteScenarioResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None
    start_calls = 0

    def scenarios(self):
        return [{"scenario_id": "keyword-reverse", "title": "关键词反查"}]

    async def start(self, request):
        self.__class__.last_request = request
        self.__class__.start_calls += 1
        return {
            "job_id": "job-async-1",
            "scenario": request.scenario,
            "site": request.site,
            "period": request.period,
            "state": "queued",
            "stage": "created",
        }

    def browser_route_busy(self, request):
        return False

    async def run(self, request):
        self.__class__.last_request = request
        return SellerSpriteScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            root_dir=__import__("pathlib").Path("/tmp/job-1"),
            params_path=__import__("pathlib").Path("/tmp/job-1/params.json"),
            raw_path=__import__("pathlib").Path("/tmp/job-1/raw.json"),
            result_path=__import__("pathlib").Path("/tmp/job-1/result.json"),
        )

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx"},
        }


def test_seller_sprite_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "keyword-reverse"


def test_seller_sprite_run_accepts_params_json_string(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda **kwargs: DummyManager())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    DummyManager.start_calls = 0

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
    assert result["data"]["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B07YRMT36L"}
    assert DummyManager.last_request.page_size == 100
    assert DummyManager.last_request.export_format == "json"
    assert DummyManager.last_request.mode is None
    assert DummyManager.start_calls == 0


def test_seller_sprite_start_returns_queued_job(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda **kwargs: DummyManager())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    DummyManager.start_calls = 0

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
    assert DummyManager.start_calls == 1
    assert DummyManager.last_request.scenario == "product-research"
    assert DummyManager.last_request.params == {
        "nodeIdPaths": ["1055398:1063306:1063312:10824421"]
    }
    assert DummyManager.last_request.export_format == "json"


def test_seller_sprite_run_auto_starts_long_running_scenario(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda **kwargs: DummyManager())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    DummyManager.start_calls = 0

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
    assert DummyManager.start_calls == 1


def test_seller_sprite_run_auto_starts_when_browser_queue_is_busy(monkeypatch):
    class BusyManager(DummyManager):
        def browser_route_busy(self, request):
            return True

    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda **kwargs: BusyManager())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    BusyManager.start_calls = 0

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
    assert BusyManager.start_calls == 1


def test_seller_sprite_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_export("job-1"))

    assert result["success"] is True
    assert result["data"]["path"] == "/tmp/job-1.xlsx"
    assert result["data"]["url"].startswith("file://")


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
