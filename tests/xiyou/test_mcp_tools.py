import asyncio
from pathlib import Path

from opscli.mcp.tools import xiyou as xiyou_tools
from opscli.xiyou.domain.exceptions import XiyouCredentialExpiredError


def _run(coro):
    return asyncio.run(coro)


class DummyResult:
    def to_dict(self):
        return {
            "job_id": "job-1",
            "row_count": 1,
            "export": {
                "filename": "job-1.xlsx",
                "url": "file:///C:/tmp/job-1.xlsx",
                "path": "C:\\tmp\\job-1.xlsx",
                "format": "xlsx",
            },
            "data": [{"asin": "B00TEST123"}],
            "warnings": [
                {
                    "stage": "file_upload",
                    "message": "upload failed",
                }
            ],
        }


class DummyManager:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        DummyManager.instances.append(self)

    def scenarios(self):
        return [{"function": "ranking"}]

    async def run(self, request):
        self.request = request
        return DummyResult()

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "export": {
                "path": str(Path("output.json").resolve()),
                "filename": "output.json",
            },
        }


def test_xiyou_scenarios(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)

    result = _run(xiyou_tools.xiyou_scenarios())

    assert result["success"] is True
    assert result["data"] == [{"function": "ranking"}]


def test_xiyou_run(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(xiyou_tools.xiyou_run(function="ranking", export_format="json"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert result["data"]["row_count"] == 1
    assert result["data"]["export"]["url"] == "file:///C:/tmp/job-1.xlsx"
    assert result["data"]["export"]["filename"] == "job-1.xlsx"
    assert result["data"]["export"]["json_data"] == [{"asin": "B00TEST123"}]
    assert result["data"]["warnings"][0]["stage"] == "file_upload"
    assert result["data"]["data"][0]["asin"] == "B00TEST123"
    assert "export_path" not in result["data"]
    assert DummyManager.instances[0].kwargs == {"jwt": "jwt", "session_id": "sid"}


def test_xiyou_run_passes_resource_params(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(
        xiyou_tools.xiyou_run(
            function="asin-compare",
            asins=["B0G33FZ8XS", "B0G337Q47M"],
            dataset="keywords",
            report_date="2026-06-08",
            view_mode="top10",
            keyword_type="organic",
            replay_type="ac",
            export_format="xlsx",
        )
    )

    assert result["success"] is True
    request = DummyManager.instances[0].request
    assert request.function == "asin-compare"
    assert request.asins == ["B0G33FZ8XS", "B0G337Q47M"]
    assert request.dataset == "keywords"
    assert request.report_date == "2026-06-08"
    assert request.view_mode == "top10"
    assert request.keyword_type == "organic"
    assert request.replay_type == "ac"


def test_xiyou_run_passes_reverse_keyword_params(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(
        xiyou_tools.xiyou_run(
            function="reverse-keyword",
            asin="B0DZFGTCLR",
            cycle_period="custom_month_range",
            start_month="2026-05",
            end_month="2026-06",
            view_mode="top10",
            keyword_type="advertising",
            export_format="xlsx",
        )
    )

    assert result["success"] is True
    request = DummyManager.instances[0].request
    assert request.function == "reverse-keyword"
    assert request.asin == "B0DZFGTCLR"
    assert request.cycle_period == "custom_month_range"
    assert request.start_month == "2026-05"
    assert request.end_month == "2026-06"
    assert request.view_mode == "top10"
    assert request.keyword_type == "advertising"


def test_xiyou_run_passes_new_reverse_keyword_family_params(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(
        xiyou_tools.xiyou_run(
            function="ad-analysis",
            asin="B0DZFGTCLR",
            parent_asin="B0FDB5VR1V",
            asins=["B0DZFGTCLR", "B0DZFW1QS1"],
            search_terms=["candle warmer"],
            start_date="2026-06-01",
            end_date="2026-06-02",
            export_format="json",
        )
    )

    assert result["success"] is True
    request = DummyManager.instances[0].request
    assert request.function == "ad-analysis"
    assert request.parent_asin == "B0FDB5VR1V"
    assert request.asins == ["B0DZFGTCLR", "B0DZFW1QS1"]
    assert request.search_terms == ["candle warmer"]
    assert request.start_date == "2026-06-01"
    assert request.end_date == "2026-06-02"


def test_xiyou_run_returns_terminal_error_for_expired_xiyou_credential(monkeypatch):
    class ExpiredManager(DummyManager):
        async def run(self, request):
            raise XiyouCredentialExpiredError(
                reason="jwt_expired",
                expires_at="2023-11-14T22:13:20+00:00",
                notify_result={"sent": True, "dedupe_key": "token_required"},
            )

    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", ExpiredManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(xiyou_tools.xiyou_run(function="ranking", export_format="json"))

    assert result["success"] is False
    assert result["error"]["code"] == "XIYOU_CREDENTIAL_EXPIRED"
    assert result["error"]["auth_system"] == "xiyou"
    assert result["retryable"] is False
    assert result["do_not_retry"] is True
    assert "auth_mcp_login" in result["do_not_call_tools"]
    assert "不要刷新 OPS/MCP 登录" in result["agent_message"]
    failed_call = result["feedback"]["execution_summary"]["failed_calls"][0]
    assert failed_call["call_params"]["function"] == "ranking"


def test_xiyou_run_passes_flow_diagnosis_download_params(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(
        xiyou_tools.xiyou_run(
            function="flow-diagnosis",
            asin="B0DZFGTCLR",
            report_date="2026-06-02",
            keyword_type="advertising",
            export_format="xlsx",
        )
    )

    assert result["success"] is True
    request = DummyManager.instances[0].request
    assert request.function == "flow-diagnosis"
    assert request.asin == "B0DZFGTCLR"
    assert request.report_date == "2026-06-02"
    assert request.keyword_type == "advertising"


def test_xiyou_run_passes_flow_diagnosis_alias(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)
    monkeypatch.setattr(xiyou_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))

    result = _run(
        xiyou_tools.xiyou_run(
            function="流量诊断仪",
            asin="B0DZFGTCLR",
            export_format="json",
        )
    )

    assert result["success"] is True
    request = DummyManager.instances[0].request
    assert request.function == "流量诊断仪"


def test_xiyou_export_adds_file_url(monkeypatch):
    DummyManager.instances = []
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", DummyManager)

    result = _run(xiyou_tools.xiyou_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"].startswith("file:")


def test_xiyou_export_returns_json_fallback_after_upload_failure(monkeypatch):
    class UploadFailedManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "data": [{"asin": "B00TEST123"}],
                "export": {
                    "path": str(Path("output.json").resolve()),
                    "filename": "output.json",
                },
                "warnings": [{"stage": "file_upload", "message": "upload failed"}],
            }

    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", UploadFailedManager)

    result = _run(xiyou_tools.xiyou_export("job-1"))

    assert result["success"] is True
    assert result["data"]["json_data"] == [{"asin": "B00TEST123"}]


def test_xiyou_export_prefers_download_url(monkeypatch):
    class ResourceExportManager(DummyManager):
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "resource_url": "https://excel.xydc.com/demo.xlsx?Expires=1&Signature=s",
                "export": {
                    "path": str(Path("output.json").resolve()),
                    "filename": "output.json",
                    "url": Path("output.json").resolve().as_uri(),
                },
            }

    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", ResourceExportManager)

    result = _run(xiyou_tools.xiyou_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"] == "https://excel.xydc.com/demo.xlsx?Expires=1&Signature=s"
    assert result["data"]["download_url"] == "https://excel.xydc.com/demo.xlsx?Expires=1&Signature=s"
    assert result["data"]["local_url"].startswith("file:")
