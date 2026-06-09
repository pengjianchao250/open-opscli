import asyncio
import json
from pathlib import Path

from openpyxl import load_workbook

from opscli.keepa.accounts import KeepaApiKey
from opscli.keepa.config import KeepaSettings
from opscli.keepa.domain.models import KeepaScenarioRequest
from opscli.keepa.services import api_manager as api_manager_module
from opscli.keepa.services.api_manager import KeepaApiManager


def _run(coro):
    return asyncio.run(coro)


class DummyApiKeyProvider:
    def get_default(self, *, refresh=False):
        return KeepaApiKey(name="default", api_key="keepa-test-key", source="test")


class DummyKeepaClient:
    requests = []

    def __init__(self, *, api_key):
        self.api_key = api_key

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def token_status(self):
        return {
            "timestamp": 1000,
            "tokensLeft": 50,
            "refillIn": 300000,
            "refillRate": 5,
        }

    async def get_json(self, endpoint, params):
        self.__class__.requests.append({"endpoint": endpoint, "params": params})
        return {
            "timestamp": 2000,
            "tokensLeft": 49,
            "tokensConsumed": 1,
            "products": [{"asin": "B0088PUEPK", "title": "Test Product", "lastUpdate": 7588958}],
        }


class DisabledUploadClient:
    def __init__(self, *args, **kwargs):
        self.enabled = False


def test_manager_writes_params_raw_result_and_xlsx_export(monkeypatch, tmp_path: Path):
    DummyKeepaClient.requests = []
    monkeypatch.setattr(api_manager_module, "KeepaApiClient", DummyKeepaClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)
    settings = KeepaSettings(output_dir=tmp_path, api_key=None, reserve_tokens=10)
    manager = KeepaApiManager(settings=settings, api_key_provider=DummyApiKeyProvider())

    result = _run(
        manager.run(
            KeepaScenarioRequest(
                scenario="product",
                site="US",
                params={"asin": "B0088PUEPK", "stats": 30, "history": False},
                job_id="keepa-offline-regression",
            )
        )
    )

    root_dir = tmp_path / "keepa-offline-regression"
    assert result.row_count == 1
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert result.export is not None
    assert result.export.path.endswith("keepa-offline-regression.xlsx")
    assert result.export.format == "xlsx"

    params_payload = json.loads((root_dir / "params.json").read_text(encoding="utf-8"))
    raw_payload = json.loads((root_dir / "raw.json").read_text(encoding="utf-8"))

    assert params_payload["normalized_params"]["asin"] == "B0088PUEPK"
    assert raw_payload["request_params"]["history"] is False
    assert result.data[0]["lastUpdateUtc"] == "2025-06-06T02:38:00Z"
    assert DummyKeepaClient.requests[0]["endpoint"] == "product"

    workbook = load_workbook(result.export.path)
    sheet = workbook.active
    headers = [cell.value for cell in sheet[1]]
    assert headers[:3] == ["ASIN", "标题", "最近更新(Keepa分钟)"]
    assert sheet.cell(row=2, column=1).value == "B0088PUEPK"
    assert sheet.cell(row=2, column=2).value == "Test Product"
    assert sheet.cell(row=2, column=3).value == 7588958


def test_manager_writes_json_export_when_requested(monkeypatch, tmp_path: Path):
    DummyKeepaClient.requests = []
    monkeypatch.setattr(api_manager_module, "KeepaApiClient", DummyKeepaClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)
    settings = KeepaSettings(output_dir=tmp_path, api_key=None, reserve_tokens=10)
    manager = KeepaApiManager(settings=settings, api_key_provider=DummyApiKeyProvider())

    result = _run(
        manager.run(
            KeepaScenarioRequest(
                scenario="product",
                site="US",
                params={"asin": "B0088PUEPK", "stats": 30, "history": False},
                job_id="keepa-json-regression",
                export_format="json",
            )
        )
    )

    export_payload = json.loads((tmp_path / "keepa-json-regression" / "keepa-json-regression.json").read_text(encoding="utf-8"))

    assert result.export is not None
    assert result.export.filename == "keepa-json-regression.json"
    assert result.export.format == "json"
    assert export_payload["request_params"]["stats"] == 30
    assert export_payload["raw_response"]["tokensConsumed"] == 1
    assert export_payload["raw_response"]["products"][0]["lastUpdate"] == 7588958
    assert export_payload["rows"][0]["lastUpdateUnixSeconds"] == 1749177480


def test_manager_blocks_low_quota_without_force(monkeypatch, tmp_path: Path):
    class LowQuotaClient(DummyKeepaClient):
        async def token_status(self):
            return {"timestamp": 1000, "tokensLeft": 1, "refillIn": 300000, "refillRate": 5}

    monkeypatch.setattr(api_manager_module, "KeepaApiClient", LowQuotaClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)
    settings = KeepaSettings(output_dir=tmp_path, api_key=None, reserve_tokens=10)
    manager = KeepaApiManager(settings=settings, api_key_provider=DummyApiKeyProvider())

    try:
        _run(
            manager.run(
                KeepaScenarioRequest(
                    scenario="product",
                    site="US",
                    params={"asin": "B0088PUEPK"},
                    job_id="low-quota",
                )
            )
        )
    except Exception as exc:
        assert "可用额度不足" in str(exc)
    else:
        raise AssertionError("expected quota precheck failure")

    assert (tmp_path / "low-quota" / "params.json").exists()
