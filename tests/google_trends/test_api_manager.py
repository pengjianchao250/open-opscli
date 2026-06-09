import asyncio
import json
from pathlib import Path

from opscli.google_trends.config import GoogleTrendsSettings
from opscli.google_trends.domain.models import GoogleTrendsExportResult
from opscli.google_trends.domain.models import GoogleTrendsScenarioRequest
from opscli.google_trends.services import api_manager as api_manager_module
from opscli.google_trends.services.api_manager import GoogleTrendsApiManager


def _run(coro):
    return asyncio.run(coro)


class DummyGoogleTrendsClient:
    requests = []

    def __init__(self, *, settings=None, hl=None, tz=None):
        self.settings = settings
        self.hl = hl
        self.tz = tz

    def run(self, scenario, params):
        self.__class__.requests.append({"scenario": scenario, "params": params, "hl": self.hl, "tz": self.tz})
        return {"records": [{"date": "2026-01-01", "flashlight": 42, "isPartial": False}]}


class DisabledUploadClient:
    def __init__(self, *args, **kwargs):
        self.enabled = False


def test_manager_writes_params_raw_result_and_json_export(monkeypatch, tmp_path: Path):
    DummyGoogleTrendsClient.requests = []
    monkeypatch.setattr(api_manager_module, "GoogleTrendsApiClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)
    settings = GoogleTrendsSettings(output_dir=tmp_path)
    manager = GoogleTrendsApiManager(settings=settings)

    result = _run(
        manager.run(
            GoogleTrendsScenarioRequest(
                scenario="interest-over-time",
                geo="US",
                params={"keyword": "flashlight", "timeframe": "today 12-m"},
                job_id="google-trends-offline-regression",
                export_format="json",
                hl="en-US",
                tz=360,
            )
        )
    )

    root_dir = tmp_path / "google-trends-offline-regression"
    assert result.row_count == 1
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert result.export is not None
    assert result.export.filename == "google-trends-offline-regression.json"
    assert result.export.format == "json"

    params_payload = json.loads((root_dir / "params.json").read_text(encoding="utf-8"))
    raw_payload = json.loads((root_dir / "raw.json").read_text(encoding="utf-8"))
    result_payload = json.loads((root_dir / "result.json").read_text(encoding="utf-8"))
    export_payload = json.loads((root_dir / "google-trends-offline-regression.json").read_text(encoding="utf-8"))

    assert params_payload["normalized_params"]["kw_list"] == ["flashlight"]
    assert raw_payload["request_params"]["timeframe"] == "today 12-m"
    assert result_payload["row_count"] == 1
    assert export_payload["rows"][0]["flashlight"] == 42
    assert DummyGoogleTrendsClient.requests[0]["scenario"] == "interest-over-time"
    assert DummyGoogleTrendsClient.requests[0]["hl"] == "en-US"
    assert DummyGoogleTrendsClient.requests[0]["tz"] == 360


def test_manager_uses_xlsx_export_by_default(monkeypatch, tmp_path: Path):
    DummyGoogleTrendsClient.requests = []
    monkeypatch.setattr(api_manager_module, "GoogleTrendsApiClient", DummyGoogleTrendsClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)

    def fake_export_rows_to_xlsx(*, rows, output_path, scenario, geo, params):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("xlsx-placeholder", encoding="utf-8")
        return GoogleTrendsExportResult(path=str(output_path), filename=output_path.name)

    monkeypatch.setattr(api_manager_module, "export_rows_to_xlsx", fake_export_rows_to_xlsx)
    settings = GoogleTrendsSettings(output_dir=tmp_path)
    manager = GoogleTrendsApiManager(settings=settings)

    result = _run(
        manager.run(
            GoogleTrendsScenarioRequest(
                scenario="interest-over-time",
                geo="US",
                params={"keyword": "flashlight"},
                job_id="google-trends-xlsx-regression",
            )
        )
    )

    assert result.export is not None
    assert result.export.filename == "google-trends-xlsx-regression.xlsx"
    assert (tmp_path / "google-trends-xlsx-regression" / "google-trends-xlsx-regression.xlsx").exists()
    status = manager.job_status("google-trends-xlsx-regression")
    assert status["job_id"] == "google-trends-xlsx-regression"
    assert status["export"]["filename"] == "google-trends-xlsx-regression.xlsx"
