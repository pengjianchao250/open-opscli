import asyncio
import json

from opscli.mcp.tools import asin_data as asin_data_tools


def _run(coro):
    return asyncio.run(coro)


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
        "asin_data_fetch_file",
        "asin_data_report_url",
    ]
