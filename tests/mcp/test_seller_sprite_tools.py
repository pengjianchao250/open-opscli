import asyncio

from opscli.mcp.tools import seller_sprite as seller_sprite_tools
from opscli.seller_sprite.domain.models import SellerSpriteScenarioResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def scenarios(self):
        return [{"scenario_id": "keyword-reverse", "title": "关键词反查"}]

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
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params='{"asin":"B07YRMT36L"}',
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B07YRMT36L"}
    assert DummyManager.last_request.page_size == 100
    assert DummyManager.last_request.export_format == "json"


def test_seller_sprite_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.seller_sprite.services.SellerSpriteApiManager", lambda: DummyManager())

    result = _run(seller_sprite_tools.seller_sprite_export("job-1"))

    assert result["success"] is True
    assert result["data"]["path"] == "/tmp/job-1.xlsx"
    assert result["data"]["url"].startswith("file://")
