import json
from pathlib import Path
from uuid import uuid4

from opscli.sif.accounts import SifAccount
from opscli.sif.config import SifSettings
from opscli.sif.domain.models import SifExportResult, SifRunRequest, SifRunResult
from opscli.sif.services.manager import SifServiceManager, decorate_download_payload


class FakeAccountProvider:
    def get_default(self, *, refresh=False):
        return SifAccount(name="primary", username="sif-user", password="sif-secret")

    def list_public(self):
        return [self.get_default().to_public_dict()]


class FakeUploadResult:
    def __init__(self, url):
        self.url = url


class FakeUploadClient:
    enabled = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def upload(self, path, **kwargs):
        return FakeUploadResult("https://files.example.com/1780000000000_traffic_1780000000001.xlsx")


class FakeTrafficProvider:
    last_request = None

    def run(self, request, *, default_output_dir):
        self.__class__.last_request = request
        root = Path(request.output_dir) / "job-traffic"
        root.mkdir(parents=True, exist_ok=True)
        export_path = root / "traffic.xlsx"
        export_path.write_bytes(b"PK\x03\x04")
        result_path = root / "result.json"
        result_payload = {
            "schema_version": "sif_traffic.v1",
            "feature": request.feature,
            "exports": {
                "traffic_structure_xlsx": {
                    "path": str(export_path),
                    "filename": export_path.name,
                    "url": export_path.resolve().as_uri(),
                    "format": "xlsx",
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }
            },
            "summary": {"export_count": 1},
            "warnings": [],
        }
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")
        return SifRunResult(
            job_id="job-traffic",
            feature=request.feature,
            provider="sif",
            site=request.site,
            asin=request.asin,
            asins=[request.asin],
            root_dir=str(root),
            params_path=str(root / "params.json"),
            raw_path=str(root / "raw.json"),
            result_path=str(result_path),
            exports={
                "traffic_structure_xlsx": SifExportResult(
                    path=str(export_path),
                    filename=export_path.name,
                    url=export_path.resolve().as_uri(),
                )
            },
            summary={"export_count": 1},
        )


class FakeProductTimeMachineProvider:
    last_request = None

    def run(self, request, *, default_output_dir):
        self.__class__.last_request = request
        root = Path(request.output_dir) / "job-product"
        root.mkdir(parents=True, exist_ok=True)
        export_path = root / "product.xlsx"
        export_path.write_bytes(b"PK\x03\x04")
        result_path = root / "result.json"
        result_payload = {
            "schema_version": "sif_product_time_machine.v1",
            "feature": request.feature,
            "keyword": request.keyword,
            "exports": {
                "product_time_machine_xlsx": {
                    "path": str(export_path),
                    "filename": export_path.name,
                    "url": export_path.resolve().as_uri(),
                    "format": "xlsx",
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }
            },
            "summary": {"export_count": 1},
            "warnings": [],
        }
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False), encoding="utf-8")
        return SifRunResult(
            job_id="job-product",
            feature=request.feature,
            provider="sif",
            site=request.site,
            keyword=request.keyword,
            root_dir=str(root),
            params_path=str(root / "params.json"),
            raw_path=str(root / "raw.json"),
            result_path=str(result_path),
            exports={
                "product_time_machine_xlsx": SifExportResult(
                    path=str(export_path),
                    filename=export_path.name,
                    url=export_path.resolve().as_uri(),
                )
            },
            summary={"export_count": 1},
        )


def test_sif_service_manager_scenarios_include_new_features():
    manager = SifServiceManager(settings=SifSettings(output_dir=Path("output/test-artifacts")), account_provider=FakeAccountProvider())

    scenarios = {item["feature"]: item for item in manager.scenarios()}

    assert "查排名" in scenarios
    assert scenarios["查排名"]["default_granularity"] == "week"
    assert "运营时光机" in scenarios
    assert scenarios["运营时光机"]["default_last_months"] == 6
    assert "产品时光机" in scenarios


def test_sif_service_manager_injects_account_and_uploads_exports(monkeypatch):
    output_dir = Path("output") / "test-artifacts" / f"sif-service-{uuid4().hex}"
    monkeypatch.setattr("opscli.sif.services.manager.SifTrafficProvider", lambda: FakeTrafficProvider())
    monkeypatch.setattr("opscli.sif.services.manager.FileUploadClient", lambda **kwargs: FakeUploadClient(**kwargs))

    manager = SifServiceManager(
        settings=SifSettings(output_dir=output_dir),
        account_provider=FakeAccountProvider(),
        jwt="jwt-1",
        session_id="session-1",
    )
    result = manager.run(
        SifRunRequest(
            feature="traffic",
            asin="B01NBNDC1T",
            site="US",
            sections=["流量结构"],
            output_dir=str(output_dir),
        )
    )

    assert result.exports["traffic_structure_xlsx"].url == "https://files.example.com/1780000000000_traffic_1780000000001.xlsx"
    assert FakeTrafficProvider.last_request.sif_username == "sif-user"
    assert FakeTrafficProvider.last_request.sif_password == "sif-secret"
    persisted = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert persisted["exports"]["traffic_structure_xlsx"]["url"] == "https://files.example.com/1780000000000_traffic_1780000000001.xlsx"
    assert persisted["exports"]["traffic_structure_xlsx"]["display_filename"] == "traffic.xlsx"
    assert persisted["download_links"][0]["filename"] == "traffic.xlsx"
    assert persisted["download_links"][0]["markdown"].startswith("[traffic.xlsx](")
    assert "sif-secret" not in Path(result.result_path).read_text(encoding="utf-8")


def test_sif_service_manager_routes_product_time_machine(monkeypatch):
    output_dir = Path("output") / "test-artifacts" / f"sif-service-product-{uuid4().hex}"
    monkeypatch.setattr("opscli.sif.services.manager.SifProductTimeMachineProvider", lambda: FakeProductTimeMachineProvider())
    monkeypatch.setattr("opscli.sif.services.manager.FileUploadClient", lambda **kwargs: FakeUploadClient(**kwargs))

    manager = SifServiceManager(settings=SifSettings(output_dir=output_dir), account_provider=FakeAccountProvider())
    result = manager.run(
        SifRunRequest(
            feature="产品时光机",
            keyword="balloon pump",
            site="US",
            output_dir=str(output_dir),
        )
    )

    assert result.keyword == "balloon pump"
    assert FakeProductTimeMachineProvider.last_request.sif_username == "sif-user"
    assert FakeProductTimeMachineProvider.last_request.sif_password == "sif-secret"


def test_sif_service_manager_job_status_adds_file_url():
    output_dir = Path("output") / "test-artifacts" / f"sif-service-status-{uuid4().hex}"
    root = output_dir / "job-local"
    root.mkdir(parents=True)
    export_path = root / "local.xlsx"
    export_path.write_bytes(b"PK\x03\x04")
    (root / "result.json").write_text(
        json.dumps(
            {
                "job_id": "job-local",
                "exports": {
                    "traffic_structure_xlsx": {
                        "path": str(export_path),
                        "filename": export_path.name,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manager = SifServiceManager(settings=SifSettings(output_dir=output_dir), account_provider=FakeAccountProvider())
    status = manager.job_status("job-local")

    assert status["exports"]["traffic_structure_xlsx"]["url"].startswith("file://")
    assert status["exports"]["traffic_structure_xlsx"]["display_filename"] == "local.xlsx"
    assert status["download_links"][0]["filename"] == "local.xlsx"


def test_decorate_download_payload_strips_leading_upload_timestamp():
    payload = {
        "exports": {
            "traffic_structure_xlsx": {
                "url": "https://files.example.com/1780000000000_traffic_1780000000001.xlsx",
            }
        }
    }

    decorate_download_payload(payload)

    assert payload["exports"]["traffic_structure_xlsx"]["display_filename"] == "traffic_1780000000001.xlsx"
    assert payload["download_links"][0]["markdown"].startswith("[traffic_1780000000001.xlsx](")
