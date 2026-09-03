import asyncio
from pathlib import Path

from fastmcp import Client

from opscli.mcp.server import mcp
from opscli.mcp.tools import scrape_do as scrape_do_tools
from opscli.scrape_do.domain.models import ScrapeDoExportResult, ScrapeDoScenarioResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    def scenarios(self):
        return [{"scenario_id": "amazon-pdp", "title": "Amazon PDP 商品详情", "endpoint": "/plugin/amazon/pdp"}]

    async def run(self, request):
        self.__class__.last_request = request
        result = ScrapeDoScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            site=request.site,
            root_dir=Path("/tmp/job-1"),
            params_path=Path("/tmp/job-1/params.json"),
            raw_path=Path("/tmp/job-1/raw.json"),
            result_path=Path("/tmp/job-1/result.json"),
        )
        result.row_count = 1
        result.export = ScrapeDoExportResult(path="/tmp/job-1.xlsx", filename="job-1.xlsx")
        result.data = [{"asin": "B0C7BKZ883", "title": "Laptop Stand", "local_path": "/tmp/hidden", "html": "<html>x</html>"}]
        result.request = {"params": {"token": "secret-token", "asin": "B0C7BKZ883"}}
        result.billing = {"request_cost": 1, "remaining_credits": 99}
        result.warnings = [{"stage": "file_upload", "message": "upload failed"}]
        return result

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "root_dir": f"/tmp/{job_id}",
            "params_path": f"/tmp/{job_id}/params.json",
            "raw_path": f"/tmp/{job_id}/raw.json",
            "result_path": f"/tmp/{job_id}/result.json",
            "request": {"params": {"token": "secret-token", "asin": "B0C7BKZ883"}},
            "response": {"asin": "B0C7BKZ883"},
            "artifact": {"local_path": f"/tmp/{job_id}/private.json", "url": "file:///tmp/private.json"},
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx", "url": None},
            "data": [{"asin": "B0C7BKZ883", "title": "Laptop Stand"}],
            "warnings": [{"stage": "file_upload", "message": "upload failed"}],
        }


def test_scrape_do_tools_are_registered():
    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    names = [tool.name for tool in _run(scenario())]

    assert "scrape_do_spec_must_read" in names
    assert "scrape_do_scenarios" in names
    assert "scrape_do_run" in names
    assert "scrape_do_job_status" in names
    assert "scrape_do_export" in names


def test_scrape_do_spec_uses_logical_source_without_local_path():
    result = _run(scrape_do_tools.scrape_do_spec_must_read())

    assert result["success"] is True
    assert "ops-amazon-product-data MCP" in result["data"]["spec"]
    assert result["data"]["source"] == "ops-amazon-product-data/SKILL_MCP.md"
    assert result["data"]["sources"] == ["ops-amazon-product-data/SKILL_MCP.md"]
    assert "Gitlab" not in str(result["data"])
    assert "/plugin/amazon" not in result["data"]["spec"]
    assert "token" not in result["data"]["spec"].lower()
    assert "raw HTML" not in result["data"]["spec"]


def test_scrape_do_spec_missing_file_error_hides_local_path(monkeypatch, tmp_path):
    monkeypatch.setattr(scrape_do_tools, "_scrape_do_skill_dir", lambda: tmp_path / "missing-skill")

    result = _run(scrape_do_tools.scrape_do_spec_must_read())

    assert result["success"] is False
    assert str(tmp_path) not in str(result)
    assert "missing-skill" not in str(result)


def test_scrape_do_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(scrape_do_tools.scrape_do_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "amazon-pdp"
    assert "endpoint" not in result["data"][0]
    assert "/plugin/amazon" not in str(result["data"])


def test_scrape_do_run_hides_token_paths_and_raw(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(
        scrape_do_tools.scrape_do_run(
            scenario="amazon-pdp",
            site="US",
            params='{"asin":"B0C7BKZ883"}',
            export_format="xls",
        )
    )

    assert result["success"] is True
    data = result["data"]
    assert data["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B0C7BKZ883"}
    assert "params_path" not in data
    assert "raw_path" not in data
    assert "result_path" not in data
    assert "root_dir" not in data
    assert "secret-token" not in str(data)
    assert "token" not in str(data)
    assert "/tmp" not in str(data)
    assert "file://" not in str(data)
    assert "<html" not in str(data)
    assert data["data_preview"][0]["asin"] == "B0C7BKZ883"


def test_scrape_do_job_status_hides_internal_paths_and_response(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(scrape_do_tools.scrape_do_job_status("job-1"))

    assert result["success"] is True
    data = result["data"]
    assert "root_dir" not in data
    assert "params_path" not in data
    assert "raw_path" not in data
    assert "result_path" not in data
    assert "response" not in data
    assert "path" not in data["export"]
    assert "artifact" not in data
    assert "secret-token" not in str(data)
    assert "/tmp" not in str(data)
    assert "file://" not in str(data)
    assert data["export"]["json_data"] == [{"asin": "B0C7BKZ883", "title": "Laptop Stand"}]
    assert not any(item["stage"] == "export_url_unavailable" for item in data["warnings"])


def test_scrape_do_run_sanitizes_forbidden_strings_inside_success_payload(monkeypatch):
    class DirtySuccessManager(DummyManager):
        async def run(self, request):
            result = await super().run(request)
            result.data = [
                {
                    "asin": "B0C7BKZ883",
                    "note": "debug /tmp/private file:///tmp/private /plugin/amazon/pdp token=secret-token <html>x</html>",
                }
            ]
            result.warnings = [
                {
                    "stage": "file_upload",
                    "message": "failed at /tmp/private file:///tmp/private /plugin/amazon/pdp token=secret-token <html>x</html>",
                }
            ]
            return result

    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DirtySuccessManager)

    result = _run(scrape_do_tools.scrape_do_run(scenario="amazon-pdp", params={"asin": "B0C7BKZ883"}))

    assert result["success"] is True
    assert "/tmp" not in str(result["data"])
    assert "file://" not in str(result["data"])
    assert "/plugin/amazon" not in str(result["data"])
    assert "secret-token" not in str(result["data"])
    assert "token" not in str(result["data"])
    assert "<html" not in str(result["data"])


def test_scrape_do_export_returns_remote_url_without_path(monkeypatch):
    class RemoteUrlManager(DummyManager):
        def job_status(self, job_id):
            payload = super().job_status(job_id)
            payload["export"]["url"] = f"https://ops.example.com/{job_id}.xlsx"
            return payload

    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", RemoteUrlManager)

    result = _run(scrape_do_tools.scrape_do_export("job-2"))

    assert result["success"] is True
    assert result["data"]["url"] == "https://ops.example.com/job-2.xlsx"
    assert "path" not in result["data"]
    assert "/tmp" not in str(result["data"])


def test_scrape_do_run_error_hides_endpoint_and_token(monkeypatch):
    class ErrorManager(DummyManager):
        async def run(self, request):
            raise ValueError("请求失败：/plugin/amazon/pdp token=secret-token")

    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", ErrorManager)

    result = _run(
        scrape_do_tools.scrape_do_run(
            scenario="/plugin/amazon/pdp",
            site="US",
            params={"token": "secret-token"},
        )
    )

    assert result["success"] is False
    assert "/plugin/amazon" not in str(result)
    assert "secret-token" not in str(result)
    assert "token" not in str(result)


def test_scrape_do_job_status_error_hides_path_like_job_id(monkeypatch):
    class ErrorManager(DummyManager):
        def job_status(self, job_id):
            raise ValueError(f"任务不存在：/tmp/{job_id}/result.json file:///tmp/private.json")

    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", ErrorManager)

    result = _run(scrape_do_tools.scrape_do_job_status("job-1"))

    assert result["success"] is False
    assert "/tmp" not in str(result)
    assert "file://" not in str(result)


def test_scrape_do_export_error_hides_path_like_job_id(monkeypatch):
    class ErrorManager(DummyManager):
        def job_status(self, job_id):
            raise ValueError(f"任务不存在：C:\\temp\\{job_id}\\result.json")

    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", ErrorManager)

    result = _run(scrape_do_tools.scrape_do_export("C:\\temp\\job-1"))

    assert result["success"] is False
    assert "C:\\temp" not in str(result)
    assert "job-1" not in str(result["feedback"])
