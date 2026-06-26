import asyncio
from pathlib import Path

from opscli.keepa.domain.models import KeepaExportResult
from opscli.keepa.domain.models import KeepaScenarioResult
from opscli.mcp.tools import keepa as keepa_tools


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    def scenarios(self):
        return [{"scenario_id": "product", "title": "商品详情"}]

    async def run(self, request):
        self.__class__.last_request = request
        result = KeepaScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            site=request.site,
            root_dir=Path("/tmp/job-1"),
            params_path=Path("/tmp/job-1/params.json"),
            raw_path=Path("/tmp/job-1/raw.json"),
            result_path=Path("/tmp/job-1/result.json"),
        )
        result.row_count = 1
        result.export = KeepaExportResult(path="/tmp/job-1.xlsx", filename="job-1.xlsx")
        result.export.url = "https://example.com/job-1.xlsx"
        result.quota = {"estimated_tokens": 1, "after": {"tokensLeft": 1190, "tokensConsumed": 10}}
        result.warnings = [
            {
                "stage": "quota_precheck",
                "message": "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。",
                "tokens_left": 1,
                "estimated_tokens": 10,
                "reserve_tokens": 200,
            }
        ]
        return result

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "export": {
                "path": f"/tmp/{job_id}.xlsx",
                "url": f"https://example.com/{job_id}.xlsx",
                "filename": f"{job_id}.xlsx",
            },
            "quota": {"after": {"tokensLeft": 1190, "tokensConsumed": 10}},
        }


def test_keepa_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "product"


def test_keepa_quota_status_returns_snapshot(monkeypatch):
    class FakeLimiter:
        def quota_snapshot(self, tool_name, identity):
            assert tool_name == "keepa_run"
            assert identity == "email:mcp-user@example.com"
            return {
                "service": "keepa",
                "limit": 5,
                "used": 1,
                "remaining": 4,
                "failures": 0,
                "reset_at": "2026-06-24T00:00:00+08:00",
            }

    monkeypatch.setattr(keepa_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr("opscli.mcp.tools.keepa.get_quota_limiter", lambda: FakeLimiter())

    result = _run(keepa_tools.keepa_quota_status())

    assert result["success"] is True
    assert result["data"]["service"] == "keepa"
    assert result["data"]["remaining"] == 4


def test_keepa_quota_status_returns_error_when_user_email_missing(monkeypatch):
    monkeypatch.setattr(keepa_tools, "_get_current_mcp_user_email", lambda: None)

    result = _run(keepa_tools.keepa_quota_status())

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]


def test_keepa_spec_reads_internal_reference():
    result = _run(keepa_tools.keepa_spec_must_read())

    assert result["success"] is True
    assert "opscli/skills/templates/ops-keepa" in result["data"]["spec"]
    source = Path(result["data"]["source"])
    assert source.parts[-3:] == ("templates", "ops-keepa", "SKILL_MCP.md")
    assert any(path.endswith(("ops-keepa\\references\\OFFICIAL.md", "ops-keepa/references/OFFICIAL.md")) for path in result["data"]["sources"])


def test_keepa_run_accepts_params_json_string(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
            force=True,
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B0088PUEPK"}
    assert DummyManager.last_request.force is True
    assert DummyManager.last_request.export_format == "xls"
    assert "quota" not in result["data"]
    assert "params_path" not in result["data"]
    assert "raw_path" not in result["data"]
    assert result["data"]["export"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]["export"]
    assert "tokens_left" not in str(result["data"])
    assert result["data"]["warnings"][0]["message"] == "Keepa 当前可用额度不足，请稍后重试；如果持续卡住，请联系运营人员处理。"


def test_keepa_run_rejects_json_export_format(monkeypatch):
    DummyManager.last_request = None
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(
        keepa_tools.keepa_run(
            scenario="product",
            site="US",
            params='{"asin":"B0088PUEPK"}',
            export_format="json",
        )
    )

    assert result["success"] is False
    assert "不支持的导出格式" in result["error"]["message"]
    assert DummyManager.last_request is None


def test_keepa_job_status_hides_quota(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_job_status("job-1"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert "quota" not in result["data"]
    assert "tokensLeft" not in str(result["data"])
    assert result["data"]["export"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]["export"]


def test_keepa_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", DummyManager)

    result = _run(keepa_tools.keepa_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"] == "https://example.com/job-1.xlsx"
    assert "path" not in result["data"]


def test_keepa_job_status_warns_when_export_url_missing(monkeypatch):
    class NoUrlManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "row_count": 1,
                "export": {
                    "path": f"/tmp/{job_id}.xlsx",
                    "filename": f"{job_id}.xlsx",
                },
            }

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", NoUrlManager)

    result = _run(keepa_tools.keepa_job_status("job-2"))

    assert result["success"] is True
    assert result["data"]["export"]["filename"] == "job-2.xlsx"
    assert "path" not in result["data"]["export"]
    assert not result["data"]["export"].get("url")
    assert any(item["stage"] == "export_url_unavailable" for item in result["data"]["warnings"])


def test_keepa_export_fails_when_download_url_missing(monkeypatch):
    class NoUrlManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "export": {
                    "path": f"/tmp/{job_id}.xlsx",
                    "filename": f"{job_id}.xlsx",
                },
            }

    monkeypatch.setattr("opscli.keepa.services.KeepaApiManager", NoUrlManager)

    result = _run(keepa_tools.keepa_export("job-2"))

    assert result["success"] is False
    assert "没有可下载地址" in result["error"]["message"]
