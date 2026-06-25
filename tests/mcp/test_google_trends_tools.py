import asyncio
from pathlib import Path

from fastmcp import Client

from opscli.google_trends.domain.models import GoogleTrendsExportResult
from opscli.google_trends.domain.models import GoogleTrendsScenarioResult
from opscli.mcp.server import mcp
from opscli.mcp.tools import google_trends as google_trends_tools


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    def scenarios(self):
        return [{"scenario_id": "interest-over-time", "title": "关键词趋势时间序列"}]

    async def run(self, request):
        self.__class__.last_request = request
        result = GoogleTrendsScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            geo=request.geo,
            root_dir=Path("/tmp/job-1"),
            params_path=Path("/tmp/job-1/params.json"),
            raw_path=Path("/tmp/job-1/raw.json"),
            result_path=Path("/tmp/job-1/result.json"),
        )
        result.row_count = 1
        result.export = GoogleTrendsExportResult(path="/tmp/job-1.xlsx", filename="job-1.xlsx")
        result.data = [{"date": "2026-01-01", "flashlight": 42}]
        result.warnings = [
            {
                "stage": "file_upload",
                "message": "导出文件上传失败，已保留服务端本地文件",
                "error": {"code": "FileUploadError", "message": "offline"},
            }
        ]
        return result

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "params_path": f"/tmp/{job_id}/params.json",
            "raw_path": f"/tmp/{job_id}/raw.json",
            "raw_response": {"records": []},
            "request_params": {"kw_list": ["flashlight"]},
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx"},
        }


def test_google_trends_tools_are_registered():
    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    names = [tool.name for tool in tools]

    assert "google_trends_spec_must_read" in names
    assert "google_trends_scenarios" in names
    assert "google_trends_run" in names
    assert "google_trends_job_status" in names
    assert "google_trends_export" in names


def test_google_trends_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.google_trends.services.GoogleTrendsApiManager", DummyManager)

    result = _run(google_trends_tools.google_trends_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "interest-over-time"


def test_google_trends_spec_reads_internal_reference():
    result = _run(google_trends_tools.google_trends_spec_must_read())

    assert result["success"] is True
    assert "Google Trends MCP" in result["data"]["spec"]
    source = Path(result["data"]["source"])
    assert source.parts[-4:] == ("mcp", "references", "google_trends", "SKILL_MCP.md")


def test_google_trends_run_accepts_params_json_string(monkeypatch):
    monkeypatch.setattr("opscli.google_trends.services.GoogleTrendsApiManager", DummyManager)

    result = _run(
        google_trends_tools.google_trends_run(
            scenario="interest-over-time",
            geo="US",
            params='{"keyword":"flashlight"}',
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"keyword": "flashlight"}
    assert DummyManager.last_request.geo == "US"
    assert DummyManager.last_request.export_format == "json"
    assert "params_path" not in result["data"]
    assert "raw_path" not in result["data"]
    assert "raw_response" not in result["data"]
    assert result["data"]["warnings"][0]["message"] == "导出文件上传失败，已保留服务端本地文件"


def test_google_trends_job_status_hides_internal_paths_and_raw(monkeypatch):
    monkeypatch.setattr("opscli.google_trends.services.GoogleTrendsApiManager", DummyManager)

    result = _run(google_trends_tools.google_trends_job_status("job-1"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert "params_path" not in result["data"]
    assert "raw_path" not in result["data"]
    assert "raw_response" not in result["data"]
    assert "request_params" not in result["data"]
    assert "path" not in result["data"]["export"]
    assert not result["data"]["export"].get("url")
    assert any(item["stage"] == "export_url_unavailable" for item in result["data"]["warnings"])


def test_google_trends_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.google_trends.services.GoogleTrendsApiManager", DummyManager)

    result = _run(google_trends_tools.google_trends_export("job-1"))

    assert result["success"] is False
    assert "没有可下载地址" in result["error"]["message"]


def test_google_trends_export_returns_remote_url_when_available(monkeypatch):
    class RemoteUrlManager(DummyManager):
        def job_status(self, job_id):
            payload = super().job_status(job_id)
            payload["export"]["url"] = f"https://example.com/{job_id}.xlsx"
            return payload

    monkeypatch.setattr("opscli.google_trends.services.GoogleTrendsApiManager", RemoteUrlManager)

    result = _run(google_trends_tools.google_trends_export("job-2"))

    assert result["success"] is True
    assert result["data"]["url"] == "https://example.com/job-2.xlsx"
    assert "path" not in result["data"]
