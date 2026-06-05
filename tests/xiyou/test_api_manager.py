import asyncio
import json
from pathlib import Path

import pytest

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.xiyou.domain.models import XiyouRankingRequest
from opscli.xiyou.services import api_manager as api_manager_module
from opscli.xiyou.services.api_manager import XiyouApiManager, _extract_items


def _run(coro):
    return asyncio.run(coro)


class DummyCredentialProvider:
    def get_default(self):
        return XiyouCredential(authorization="token", cookie="cookie=value")


class DummyApiClient:
    calls = []

    def __init__(self, *, credential, settings):
        self.credential = credential
        self.settings = settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post_json(self, url, payload):
        self.calls.append({"url": url, "payload": payload})
        return {
            "code": 200,
            "list": [
                {
                    "product": {
                        "asin": "B00TEST123",
                        "title": "Demo Product",
                        "price": 9.99,
                    },
                    "flow": {"score": 100},
                    "flowRank": 1,
                }
            ],
        }


def test_manager_writes_job_files_and_json(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ranking",
                provider="xiyou",
                target="asin",
                site="US",
                period="week",
                rank_pattern="flow",
                job_id="job-json",
                export_format="json",
            )
        )
    )

    root_dir = tmp_path / "job-json"
    assert result.row_count == 1
    assert result.export is not None
    assert result.export.filename == "job-json.json"
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert DummyApiClient.calls[0]["url"] == "/v2/rankingList/asins"
    assert DummyApiClient.calls[0]["payload"]["biz"]["rankPattern"] == "flow"

    exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
    assert exported["target"] == "asin"
    assert exported["rows"][0]["product"]["asin"] == "B00TEST123"


def test_manager_writes_xlsx(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=tmp_path)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                target="keyword",
                site="US",
                period="week",
                rank_pattern="aba",
                job_id="job-xlsx",
                export_format="xlsx",
            )
        )
    )

    assert result.export is not None
    assert result.export.filename == "job-xlsx.xlsx"
    assert Path(result.export.path).exists()
    assert DummyApiClient.calls[0]["url"] == "/v3/rankingList/searchTerms"
    assert DummyApiClient.calls[0]["payload"]["biz"]["rankPattern"] == "aba"


def test_job_status_reads_existing_result(tmp_path: Path):
    root_dir = tmp_path / "job-1"
    root_dir.mkdir()
    (root_dir / "result.json").write_text('{"job_id":"job-1","row_count":3}', encoding="utf-8")
    settings = XiyouSettings(output_dir=tmp_path)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = manager.job_status("job-1")

    assert result == {"job_id": "job-1", "row_count": 3}


@pytest.mark.parametrize(
    "response",
    [
        {"data": {"items": [{"a": 1}]}},
        {"data": {"list": [{"a": 1}]}},
        {"data": {"records": [{"a": 1}]}},
        {"data": [{"a": 1}]},
        {"biz": {"rows": [{"a": 1}]}},
        {"list": [{"a": 1}]},
    ],
)
def test_extract_items_supports_common_response_shapes(response):
    assert _extract_items(response) == [{"a": 1}]


def test_invalid_function_is_rejected(tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError):
        _run(manager.run(XiyouRankingRequest(function="reverse-keyword")))
