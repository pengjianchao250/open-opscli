import asyncio
from pathlib import Path

from opscli.mcp.tools import xiyou as xiyou_tools


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
        }


class DummyManager:
    def scenarios(self):
        return [{"function": "ranking"}]

    async def run(self, request):
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
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", lambda: DummyManager())

    result = _run(xiyou_tools.xiyou_scenarios())

    assert result["success"] is True
    assert result["data"] == [{"function": "ranking"}]


def test_xiyou_run(monkeypatch):
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", lambda: DummyManager())

    result = _run(xiyou_tools.xiyou_run(function="ranking", export_format="json"))

    assert result["success"] is True
    assert result["data"]["job_id"] == "job-1"
    assert result["data"]["row_count"] == 1
    assert result["data"]["url"] == "file:///C:/tmp/job-1.xlsx"
    assert "export_path" not in result["data"]
    assert "data" not in result["data"]


def test_xiyou_export_adds_file_url(monkeypatch):
    monkeypatch.setattr("opscli.xiyou.services.XiyouApiManager", lambda: DummyManager())

    result = _run(xiyou_tools.xiyou_export("job-1"))

    assert result["success"] is True
    assert result["data"]["url"].startswith("file:")
