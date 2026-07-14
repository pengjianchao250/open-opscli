import asyncio
import json

from opscli.mcp.tools import asin_data as asin_data_tools


def _run(coro):
    return asyncio.run(coro)


def test_build_auth_client_exchanges_polaris_token_by_session(monkeypatch):
    calls = []

    class DummyBaseAuthClient:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def get_token_by_session(self, session_id, alias):
            calls.append(("get_token_by_session", session_id, alias))
            return f"{alias}-jwt"

        def build_request_auth(self, alias):
            raise AssertionError(f"unexpected local auth fallback: {alias}")

        def refresh_token(self, alias):
            calls.append(("refresh_token", alias))
            return f"{alias}-refreshed"

        def get_session(self, alias=None):
            return "local-session"

        def get_device_code(self):
            return None

    monkeypatch.setattr("opscli.auth.AuthClient", DummyBaseAuthClient)

    auth_client = asin_data_tools._build_auth_client("sid-1", "ops-jwt")

    ops_headers, ops_cookies = auth_client.build_request_auth("ops")
    polaris_headers, polaris_cookies = auth_client.build_request_auth("polaris")
    refreshed = auth_client.refresh_token("polaris")

    assert ops_headers["Authorization"] == "Bearer ops-jwt"
    assert ops_cookies == {"polarisUserToken": "sid-1"}
    assert polaris_headers["Authorization"] == "Bearer polaris-jwt"
    assert polaris_cookies == {"polarisUserToken": "sid-1"}
    assert refreshed == "polaris-jwt"
    assert ("get_token_by_session", "sid-1", "polaris") in calls


def test_asin_data_live_data_passes_realtime_params(monkeypatch, tmp_path):
    calls = {}
    metrics_path = tmp_path / "metrics.jsonl"

    class DummyBiClient:
        def __init__(self, **kwargs):
            calls["bi_client_kwargs"] = kwargs

    class DummyCollector:
        def __init__(self, **kwargs):
            calls["collector_kwargs"] = kwargs

    class DummyUploadClient:
        def __init__(self, **kwargs):
            calls["upload_client_kwargs"] = kwargs

    class DummyService:
        def __init__(self, **kwargs):
            calls["service_kwargs"] = kwargs

        def run(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return {
                "data_scope": kwargs["data_scope"],
                "split_file_urls": {
                    "B0TEST1234": {
                        "basic": "https://example.oss/basic.xlsx",
                    }
                },
            }

    class DummySlot:
        def __init__(self):
            self.released = False

        def release(self):
            self.released = True

    slot = DummySlot()

    async def fake_acquire_slot():
        calls["slot_acquired"] = True
        return slot

    monkeypatch.setenv("OPSCLI_ASIN_DATA_METRICS_PATH", str(metrics_path))
    monkeypatch.setattr(asin_data_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(asin_data_tools, "_build_auth_client", lambda session_id, jwt: "auth-client")
    monkeypatch.setattr("opscli.mcp.asin_data_limit.acquire_asin_data_slot", fake_acquire_slot)
    monkeypatch.setattr("opscli.asin_data.services.bi_report_data.AsinBiReportDataClient", DummyBiClient)
    monkeypatch.setattr("opscli.asin_data.services.collector.AsinDataCollector", DummyCollector)
    monkeypatch.setattr("opscli.asin_data.services.live_data.AsinLiveDataService", DummyService)
    monkeypatch.setattr("opscli.shared.file_uploads.FileUploadClient", DummyUploadClient)

    result = _run(
        asin_data_tools.asin_data_live_data(
            asin="B0TEST1234",
            site="US",
            data_scope="basic",
            sales_start="2026-07-01",
            sales_end="2026-07-08",
            keywords='["bed frame"]',
            upload_xlsx=True,
            run_id="run-1",
        )
    )

    assert result["success"] is True
    assert calls["slot_acquired"] is True
    assert slot.released is True
    assert result["data"]["data_scope"] == "basic"
    assert calls["bi_client_kwargs"] == {"auth_client": "auth-client"}
    assert calls["collector_kwargs"]["bi_report_data_client"].__class__ is DummyBiClient
    assert calls["run_kwargs"]["asin"] == "B0TEST1234"
    assert calls["run_kwargs"]["site"] == "US"
    assert calls["run_kwargs"]["data_scope"] == "basic"
    assert calls["run_kwargs"]["sales_start"] == "2026-07-01"
    assert calls["run_kwargs"]["sales_end"] == "2026-07-08"
    assert calls["run_kwargs"]["keywords"] == ["bed frame"]
    assert calls["run_kwargs"]["upload_xlsx"] is True
    assert calls["run_kwargs"]["return_mode"] == "ai_ready"
    metric = json.loads(metrics_path.read_text(encoding="utf-8").splitlines()[0])
    assert metric["tool"] == "asin_data_live_data"
    assert metric["status"] == "success"
    assert metric["request"]["data_scope"] == "basic"


def test_asin_data_live_data_passes_return_mode(monkeypatch, tmp_path):
    calls = {}

    class DummyBiClient:
        def __init__(self, **kwargs):
            calls["bi_client_kwargs"] = kwargs

    class DummyCollector:
        def __init__(self, **kwargs):
            calls["collector_kwargs"] = kwargs

    class DummyUploadClient:
        def __init__(self, **kwargs):
            calls["upload_client_kwargs"] = kwargs

    class DummyService:
        def __init__(self, **kwargs):
            calls["service_kwargs"] = kwargs

        def run(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return {
                "return_mode": kwargs["return_mode"],
                "split_file_urls": {
                    "B0TEST1234": {
                        "bi": "https://example.oss/bi.xlsx",
                    }
                },
            }

    monkeypatch.setenv("OPSCLI_ASIN_DATA_METRICS_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setattr(asin_data_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(asin_data_tools, "_build_auth_client", lambda session_id, jwt: "auth-client")
    monkeypatch.setattr("opscli.asin_data.services.bi_report_data.AsinBiReportDataClient", DummyBiClient)
    monkeypatch.setattr("opscli.asin_data.services.collector.AsinDataCollector", DummyCollector)
    monkeypatch.setattr("opscli.asin_data.services.live_data.AsinLiveDataService", DummyService)
    monkeypatch.setattr("opscli.shared.file_uploads.FileUploadClient", DummyUploadClient)

    result = _run(
        asin_data_tools.asin_data_live_data(
            asin="B0TEST1234",
            data_scope="bi",
            upload_xlsx=True,
            return_mode="url_only",
        )
    )

    assert result["success"] is True
    assert result["data"]["return_mode"] == "url_only"
    assert calls["run_kwargs"]["return_mode"] == "url_only"


def test_asin_data_live_data_records_error_metric_and_releases_slot(monkeypatch, tmp_path):
    calls = {}
    metrics_path = tmp_path / "metrics.jsonl"

    class DummyBiClient:
        def __init__(self, **kwargs):
            calls["bi_client_kwargs"] = kwargs

    class DummyCollector:
        def __init__(self, **kwargs):
            calls["collector_kwargs"] = kwargs

    class DummyUploadClient:
        def __init__(self, **kwargs):
            calls["upload_client_kwargs"] = kwargs

    class DummyService:
        def __init__(self, **kwargs):
            calls["service_kwargs"] = kwargs

        def run(self, **kwargs):
            raise RuntimeError("boom")

    class DummySlot:
        def __init__(self):
            self.released = False

        def release(self):
            self.released = True

    slot = DummySlot()

    async def fake_acquire_slot():
        return slot

    monkeypatch.setenv("OPSCLI_ASIN_DATA_METRICS_PATH", str(metrics_path))
    monkeypatch.setattr(asin_data_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(asin_data_tools, "_build_auth_client", lambda session_id, jwt: "auth-client")
    monkeypatch.setattr("opscli.mcp.asin_data_limit.acquire_asin_data_slot", fake_acquire_slot)
    monkeypatch.setattr("opscli.asin_data.services.bi_report_data.AsinBiReportDataClient", DummyBiClient)
    monkeypatch.setattr("opscli.asin_data.services.collector.AsinDataCollector", DummyCollector)
    monkeypatch.setattr("opscli.asin_data.services.live_data.AsinLiveDataService", DummyService)
    monkeypatch.setattr("opscli.shared.file_uploads.FileUploadClient", DummyUploadClient)

    result = _run(asin_data_tools.asin_data_live_data(asin="B0TEST1234", data_scope="bi"))

    assert result["success"] is False
    assert result["error"]["code"] == "RuntimeError"
    assert slot.released is True
    metric = json.loads(metrics_path.read_text(encoding="utf-8").splitlines()[0])
    assert metric["tool"] == "asin_data_live_data"
    assert metric["status"] == "error"
    assert metric["error_code"] == "RuntimeError"


def test_asin_data_fetch_file_uses_report_client(monkeypatch, tmp_path):
    calls = {}
    metrics_path = tmp_path / "metrics.jsonl"

    class DummyReportClient:
        def __init__(self, **kwargs):
            calls["report_client_kwargs"] = kwargs

    def fake_fetch_split_file(**kwargs):
        calls["fetch_split_file_kwargs"] = kwargs
        return {
            "asin": "B0TEST1234",
            "site": "US",
            "file_key": "rufus",
            "file_url": "https://example.oss/rufus.md",
            "content": "# Rufus",
        }

    monkeypatch.setenv("OPSCLI_ASIN_DATA_METRICS_PATH", str(metrics_path))
    monkeypatch.setattr(asin_data_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(asin_data_tools, "_build_auth_client", lambda session_id, jwt: "auth-client")
    monkeypatch.setattr("opscli.asin_data.services.report_files.AsinReportFileClient", DummyReportClient)
    monkeypatch.setattr("opscli.asin_data.services.live_data.fetch_split_file", fake_fetch_split_file)

    result = _run(asin_data_tools.asin_data_fetch_file("B0TEST1234", "rufus", site="US"))

    assert result["success"] is True
    assert result["data"]["content"] == "# Rufus"
    assert calls["report_client_kwargs"] == {"auth_client": "auth-client"}
    assert calls["fetch_split_file_kwargs"]["asin"] == "B0TEST1234"
    assert calls["fetch_split_file_kwargs"]["file_key"] == "rufus"
    assert calls["fetch_split_file_kwargs"]["report_file_client"].__class__ is DummyReportClient
    metric = json.loads(metrics_path.read_text(encoding="utf-8").splitlines()[0])
    assert metric["tool"] == "asin_data_fetch_file"
    assert metric["status"] == "success"
    assert metric["artifact_uri_count"] == 1


def test_asin_data_yicopy_keyword_engine_returns_rendered_result(monkeypatch, tmp_path):
    """MCP yicopy 工具应返回渲染结果并可写本地输出文件。"""

    calls = {}

    class DummyEngine:
        async def run(self, sources, options):
            calls["sources"] = sources
            calls["options"] = options
            return {
                "status": "succeeded",
                "keywordRows": [
                    {
                        "keyword": "wireless mouse",
                        "titleFrequency": 0,
                        "bulletsFrequency": 0,
                        "totalFrequency": 0,
                    }
                ],
                "summary": {"asinCount": 1, "keywordReverseCount": 1},
            }

    from opscli.asin_data.services import yicopy_keyword_engine as engine_module

    monkeypatch.setattr(engine_module, "YicopyKeywordEngine", lambda: DummyEngine())
    output_path = tmp_path / "yicopy.json"

    result = _run(
        asin_data_tools.asin_data_yicopy_keyword_engine(
            asin="B0TEST1234",
            result_format="keyword-reverse",
            max_prefixes_per_asin=1,
            output_path=str(output_path),
        )
    )

    assert result["success"] is True
    data = result["data"]
    assert data["status"] == "succeeded"
    assert data["result"] == [
        {
            "keyword": "wireless mouse",
            "titleFrequency": 0,
            "bulletsFrequency": 0,
            "totalFrequency": 0,
        }
    ]
    assert data["output_file"] == str(output_path)
    assert data["metadata"]["protocol"] == "asin_data_ai_response"
    assert data["metadata"]["tool"] == "asin_data_yicopy_keyword_engine"
    assert data["metadata"]["data_scope"] == "yicopy_keyword_reverse"
    assert data["metadata"]["request"]["asin"] == "B0TEST1234"
    assert data["run"]["output_dir"] == output_path.parent.as_posix()
    assert data["summary"]["keywordReverseCount"] == 1
    item = data["items"][0]
    assert item["asin"] == "B0TEST1234"
    assert item["artifacts"][0]["file_key"] == "yicopy_keyword_reverse"
    assert item["datasets"][0]["source_key"] == "yicopy_keyword_reverse"
    assert item["datasets"][0]["preview_rows"][0]["keyword"] == "wireless mouse"
    assert data["diagnostics"] == []
    assert json.loads(output_path.read_text(encoding="utf-8")) == data["result"]
    assert calls["sources"] == ["B0TEST1234"]
    assert calls["options"].max_prefixes_per_asin == 1


def test_asin_data_category_top_uses_service(monkeypatch):
    calls = {}

    class DummyService:
        def __init__(self, **kwargs):
            calls["service_kwargs"] = kwargs

        def run(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return {
                "success": True,
                "metadata": {"protocol": "asin_data_ai_response", "tool": "asin_data_category_top"},
                "run": {"run_id": "run-1"},
                "summary": {"asin_count": 1},
                "items": [
                    {
                        "asin": "B0TEST1234",
                        "artifacts": [{"file_key": "category_top_json", "uri": "https://example.oss/asin-data/category-top.json"}],
                        "datasets": [],
                        "diagnostics": [],
                    }
                ],
                "diagnostics": [],
            }

    from opscli.asin_data.services import category_top as category_top_module

    monkeypatch.setattr(asin_data_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(asin_data_tools, "_build_auth_client", lambda session_id, jwt: "auth-client")
    monkeypatch.setattr(category_top_module, "AsinCategoryTopService", DummyService)

    result = _run(
        asin_data_tools.asin_data_category_top(
            category="Bed Frames",
            date_from="2026-07-01",
            date_to="2026-07-13",
            limit=5,
            site="US",
            upload=True,
            enrich=True,
            return_content=False,
            output_dir="output/asin-data",
            run_id="run-1",
        )
    )

    assert result["success"] is True
    assert result["data"]["metadata"]["protocol"] == "asin_data_ai_response"
    assert result["data"]["items"][0]["artifacts"][0]["uri"] == "https://example.oss/asin-data/category-top.json"
    assert calls["run_kwargs"] == {
        "category": "Bed Frames",
        "date_from": "2026-07-01",
        "date_to": "2026-07-13",
        "limit": 5,
        "site": "US",
        "output_dir": "output/asin-data",
        "run_id": "run-1",
        "upload": True,
        "enrich": True,
        "return_content": False,
    }


def test_asin_data_registers_all_tools():
    registered = []

    class DummyMcp:
        def tool(self):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn

            return decorator

    asin_data_tools.register(DummyMcp())

    assert registered == [
        "asin_data_live_data",
        "asin_data_category_top",
        "asin_data_fetch_file",
        "asin_data_report_url",
        "asin_data_yicopy_keyword_engine",
    ]
