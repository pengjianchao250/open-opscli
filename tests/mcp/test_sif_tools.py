import asyncio
from pathlib import Path

from opscli.mcp.tools import sif as sif_tools
from opscli.sif.domain.models import SifExportResult, SifRunResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def scenarios(self):
        return [{"feature": "查流量", "sections": ["流量结构"]}]

    def run(self, request):
        self.__class__.last_request = request
        return SifRunResult(
            job_id="job-sif",
            feature=request.feature,
            provider="sif",
            asin=request.asin,
            site=request.site,
            root_dir=str(Path("output/test-artifacts/job-sif").resolve()),
            params_path=str(Path("output/test-artifacts/job-sif/params.json").resolve()),
            raw_path=str(Path("output/test-artifacts/job-sif/raw.json").resolve()),
            result_path=str(Path("output/test-artifacts/job-sif/result.json").resolve()),
            exports={
                "traffic_structure_xlsx": SifExportResult(
                    path=str(Path("output/test-artifacts/job-sif/structure.xlsx").resolve()),
                    filename="structure.xlsx",
                    url="https://files.example.com/1780000000000_structure_1780000000001.xlsx",
                )
            },
        )

    def job_status(self, job_id, output_dir=None):
        return {"job_id": job_id, "exports": {}}

    def export(self, job_id, export_key=None, output_dir=None):
        return {
            "job_id": job_id,
            "exports": {
                "traffic_structure_xlsx": {
                    "path": str(Path("output/test-artifacts/job-sif/structure.xlsx").resolve()),
                    "filename": "structure.xlsx",
                    "url": "file:///structure.xlsx",
                }
            },
        }


def test_sif_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.sif.services.SifServiceManager", lambda **kwargs: DummyManager(**kwargs))

    result = _run(sif_tools.sif_scenarios())

    assert result["success"] is True
    assert result["data"][0]["feature"] == "查流量"


def test_sif_run_accepts_json_string_args(monkeypatch):
    monkeypatch.setattr("opscli.sif.services.SifServiceManager", lambda **kwargs: DummyManager(**kwargs))

    result = _run(
        sif_tools.sif_run(
            feature="traffic",
            asin="B01NBNDC1T",
            site="US",
            sections='["流量结构"]',
            params='{"keywordSearch":""}',
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-sif"
    assert result["data"]["download_links"][0]["filename"] == "structure.xlsx"
    assert result["data"]["download_links"][0]["markdown"].startswith("[structure.xlsx](")
    assert DummyManager.last_request.sections == ["流量结构"]
    assert DummyManager.last_request.params == {"keywordSearch": ""}
    assert DummyManager.last_request.time_piece_value == "7"


def test_sif_run_accepts_asins_list_for_compare(monkeypatch):
    monkeypatch.setattr("opscli.sif.services.SifServiceManager", lambda **kwargs: DummyManager(**kwargs))

    result = _run(
        sif_tools.sif_run(
            feature="compare",
            asins=["B075WPKK5P", "B07KVV8RFF"],
            sections="重点广告词",
        )
    )

    assert result["success"] is True
    assert DummyManager.last_request.asin == "B075WPKK5P,B07KVV8RFF"
    assert DummyManager.last_request.asins == ["B075WPKK5P", "B07KVV8RFF"]
    assert DummyManager.last_request.sections == ["重点广告词"]


def test_sif_export_returns_export_info(monkeypatch):
    monkeypatch.setattr("opscli.sif.services.SifServiceManager", lambda **kwargs: DummyManager(**kwargs))

    result = _run(sif_tools.sif_export("job-sif"))

    assert result["success"] is True
    assert result["data"]["exports"]["traffic_structure_xlsx"]["filename"] == "structure.xlsx"
    assert result["data"]["download_links"][0]["filename"] == "structure.xlsx"
