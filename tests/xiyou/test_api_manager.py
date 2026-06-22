import asyncio
import json
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from opscli.xiyou.config import XiyouSettings
from opscli.xiyou.credentials import XiyouCredential
from opscli.xiyou.domain.exceptions import XiyouConfigError
from opscli.xiyou.domain.models import XiyouRankingRequest
from opscli.xiyou.services import api_manager as api_manager_module
from opscli.xiyou.services.api_manager import (
    XiyouApiManager,
    _count_xlsx_rows,
    _extract_items,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def local_tmp_path():
    path = Path("output") / "test-runs" / f"xiyou-api-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class DummyCredentialProvider:
    def get_default(self):
        return XiyouCredential(authorization="token", cookie="cookie=value")


class DisabledUploadClient:
    def __init__(self, *, jwt=None, session_id=None):
        self.jwt = jwt
        self.session_id = session_id

    @property
    def enabled(self):
        return False


class DummyApiClient:
    calls = []

    def __init__(self, *, credential, settings):
        self.credential = credential
        self.settings = settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post_json(self, url, payload, *, request_url=None):
        self.calls.append({"url": url, "payload": payload, "request_url": request_url})
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

    async def get_bytes(self, url):
        self.calls.append({"url": url, "method": "GET"})
        return b"xlsx-bytes"


class DummyResourceApiClient(DummyApiClient):
    async def post_json(self, url, payload, *, request_url=None):
        self.calls.append({"url": url, "payload": payload, "request_url": request_url})
        if url.endswith("/resource/status"):
            resource_id = payload.get("resourceId")
            if not resource_id and isinstance(payload.get("biz"), dict):
                resource_id = payload["biz"].get("resourceId")
            return {
                "resourceId": resource_id,
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/demo.xlsx?Expires=1\\u0026Signature=s",
            }
        return {"resourceId": "resource-1"}

    async def get_json(self, url, *, request_url=None):
        self.calls.append({"url": url, "method": "GET", "request_url": request_url})
        return {}


class DummyVariationAwareResourceApiClient(DummyResourceApiClient):
    async def post_json(self, url, payload, *, request_url=None):
        self.calls.append({"url": url, "payload": payload, "request_url": request_url})
        if url == "/v4/asins/variations":
            return {"variationId": "VVNfQjBEWkZHVENMUg=="}
        if url.endswith("/resource/status"):
            return {
                "resourceId": payload["resourceId"],
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/demo.xlsx?Expires=1\\u0026Signature=s",
            }
        return {"resourceId": "resource-1"}

    async def get_json(self, url, *, request_url=None):
        self.calls.append({"url": url, "method": "GET", "request_url": request_url})
        return {
            "data": {
                "parentAsin": "B0FDB5VR1V",
                "variations": [
                    {"asin": "B0DZFW1QS1"},
                    {"asin": "B0DZFGTCLR"},
                    {"asin": "B0FDB5VR1V"},
                ],
            }
        }


class DummyTwoStepResourceApiClient(DummyApiClient):
    async def post_json(self, url, payload, *, request_url=None):
        self.calls.append({"url": url, "payload": payload, "request_url": request_url})
        if url.endswith("/flow/insights/resource/status"):
            return {
                "biz": {"resourceId": payload["biz"]["resourceId"]},
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/flow-insight.xlsx?Expires=1\\u0026Signature=s",
            }
        if url.endswith("/advertising/insights/resource/status"):
            return {
                "biz": {"resourceId": payload["biz"]["resourceId"]},
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/ad-insight.xlsx?Expires=1\\u0026Signature=s",
            }
        if url.endswith("/weeklyReport/resource/status"):
            return {
                "biz": {"resourceId": payload["biz"]["resourceId"]},
                "status": "Done",
                "resourceUrl": "https://excel.xydc.com/flow-weekly.xlsx?Expires=1\\u0026Signature=s",
            }
        return {"resourceId": "resource-2"}


class DummyUploadClient:
    instances = []

    def __init__(self, *, jwt=None, session_id=None):
        self.jwt = jwt
        self.session_id = session_id
        self.uploads = []
        DummyUploadClient.instances.append(self)

    @property
    def enabled(self):
        return True

    def upload(self, path, *, purpose, folder=None, public=None, metadata=None):
        self.uploads.append(
            {
                "path": path,
                "purpose": purpose,
                "folder": folder,
                "public": public,
                "metadata": metadata,
            }
        )

        class Result:
            url = "https://ops.example.com/download/job-json.json"

        return Result()


@pytest.fixture(autouse=True)
def disable_real_file_upload_client(monkeypatch):
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DisabledUploadClient)


def test_manager_writes_job_files_and_json(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
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

    root_dir = local_tmp_path / "job-json"
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


def test_manager_ranking_uses_asin_as_query_fallback(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    _run(
        manager.run(
            XiyouRankingRequest(
                function="ranking",
                provider="xiyou",
                target="asin",
                site="US",
                period="week",
                rank_pattern="surge",
                asin="b08x4615sc",
                job_id="job-ranking-asin-query",
                export_format="json",
            )
        )
    )

    assert DummyApiClient.calls[0]["payload"]["biz"]["query"] == "B08X4615SC"


def test_manager_ranking_keeps_explicit_query_over_asin(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    _run(
        manager.run(
            XiyouRankingRequest(
                function="ranking",
                provider="xiyou",
                target="asin",
                site="US",
                period="week",
                rank_pattern="surge",
                asin="B08X4615SC",
                query="manual-query",
                job_id="job-ranking-query-priority",
                export_format="json",
            )
        )
    )

    assert DummyApiClient.calls[0]["payload"]["biz"]["query"] == "manual-query"


def test_manager_uploads_export_and_returns_download_url(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    DummyUploadClient.instances = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    monkeypatch.setattr(api_manager_module, "FileUploadClient", DummyUploadClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(
        settings=settings,
        credential_provider=DummyCredentialProvider(),
        jwt="jwt-token",
        session_id="session-id",
    )

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

    assert result.export is not None
    assert result.export.url == "https://ops.example.com/download/job-json.json"
    assert result.warnings == []
    assert DummyUploadClient.instances[0].jwt == "jwt-token"
    assert DummyUploadClient.instances[0].session_id == "session-id"
    upload = DummyUploadClient.instances[0].uploads[0]
    assert upload["purpose"] == "xiyou_export"
    assert upload["folder"] == "xiyou/exports"
    assert upload["public"] == "1"
    assert upload["metadata"]["job_id"] == "job-json"
    assert upload["metadata"]["target"] == "asin"

    saved = json.loads((local_tmp_path / "job-json" / "result.json").read_text(encoding="utf-8"))
    assert saved["export"]["url"] == "https://ops.example.com/download/job-json.json"


def test_manager_passes_explicit_session_and_jwt_to_default_credential_provider(local_tmp_path: Path):
    captured = {}

    class RecordingCredentialProvider:
        def __init__(self, settings, *, auth_client=None, jwt=None, session_id=None):
            captured["settings"] = settings
            captured["auth_client"] = auth_client
            captured["jwt"] = jwt
            captured["session_id"] = session_id

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(api_manager_module, "XiyouCredentialProvider", RecordingCredentialProvider)
    try:
        settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
        manager = XiyouApiManager(settings=settings, jwt="jwt-token", session_id="session-id")
    finally:
        monkeypatch.undo()

    assert isinstance(manager.credential_provider, RecordingCredentialProvider)
    assert captured["settings"] == settings
    assert captured["jwt"] == "jwt-token"
    assert captured["session_id"] == "session-id"


def test_manager_writes_xlsx(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path)
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


def test_job_status_reads_existing_result(local_tmp_path: Path):
    root_dir = local_tmp_path / "job-1"
    root_dir.mkdir()
    (root_dir / "result.json").write_text('{"job_id":"job-1","row_count":3}', encoding="utf-8")
    settings = XiyouSettings(output_dir=local_tmp_path)
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


def test_invalid_function_is_rejected(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError):
        _run(manager.run(XiyouRankingRequest(function="unknown")))


def test_keyword_ranking_rejects_month_period(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError) as exc:
        _run(
            manager.run(
                XiyouRankingRequest(
                    function="ranking",
                    target="keyword",
                    period="month",
                )
            )
        )

    assert "keyword ranking period only supports: week" in str(exc.value)


def test_manager_downloads_resource_xlsx(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                job_id="job-resource",
                export_format="xlsx",
            )
        )
    )

    root_dir = local_tmp_path / "job-resource"
    assert result.data_mode == "resource_export"
    assert result.dataset == "keywords"
    assert result.resource_id == "resource-1"
    assert result.resource_url == "https://excel.xydc.com/demo.xlsx?Expires=1&Signature=s"
    assert result.export is not None
    assert result.export.filename == "job-resource.xlsx"
    assert Path(result.export.path).read_bytes() == b"xlsx-bytes"
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/asins/research/list/resource"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/asin/look_up/US/B0G33FZ8XS"
    assert DummyResourceApiClient.calls[1]["url"] == "/v4/resource/status"
    assert DummyResourceApiClient.calls[2]["method"] == "GET"


def test_reverse_keyword_uses_trends_request_url_and_payload(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                cycle_period="last3months",
                view_mode="trends",
                keyword_type="organic",
                page_size=20,
                job_id="job-reverse-keyword-trends",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/asins/research/list/resource"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/asin/look_up/US/B0DZFGTCLR?listType=trendsViewList"
    )
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["orders"] == [
        {"field": "organicTraffic", "order": "desc"}
    ]
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["filters"] == [
        {"field": "asinResearchType", "filter": ["organic"]}
    ]
    assert (
        DummyResourceApiClient.calls[0]["payload"]["biz"]["tableType"]
        == "asinResearchTrendsViewOrganicSearchTerm"
    )
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_reverse_keyword_data_view_uses_data_list_request_url_for_organic_keywords(
    monkeypatch, local_tmp_path: Path
):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                cycle_period="last1month",
                view_mode="data",
                keyword_type="organic",
                job_id="job-reverse-keyword-data-organic",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/asin/look_up/US/B0DZFGTCLR?listType=dataList"
    )
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["tableType"] == "asinResearchOrganicList"
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_reverse_keyword_data_view_uses_data_list_request_url_for_ad_keywords(
    monkeypatch, local_tmp_path: Path
):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                cycle_period="last1month",
                view_mode="data",
                keyword_type="advertising",
                job_id="job-reverse-keyword-data-advertising",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/asin/look_up/US/B0DZFGTCLR?listType=dataList"
    )
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["tableType"] == "asinResearchAdvertisingList"
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_reverse_keyword_with_query_keeps_resource_export_flow(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                query="home decor",
                job_id="job-reverse-keyword-query-guard",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/asins/research/list"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/asin/look_up/US/B0DZFGTCLR"
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["query"] == "home decor"
    assert "tableType" not in DummyResourceApiClient.calls[0]["payload"]["biz"]
    assert DummyResourceApiClient.calls[1]["url"] == "/v3/asins/research/list/resource"
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]
    assert DummyResourceApiClient.calls[1]["payload"]["biz"]["query"] == "home decor"
    assert DummyResourceApiClient.calls[1]["payload"]["biz"]["tableType"] == "asinResearchTotalList"
    assert DummyResourceApiClient.calls[2]["url"] == "/v4/resource/status"
    assert DummyResourceApiClient.calls[2]["request_url"] == DummyResourceApiClient.calls[1]["request_url"]


def test_reverse_keyword_uses_top10_request_url_and_payload(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                cycle_period="custom_month_range",
                start_month="2026-05",
                end_month="2026-06",
                view_mode="top10",
                keyword_type="advertising",
                job_id="job-reverse-keyword-top10",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/asin/look_up/US/B0DZFGTCLR?listType=topDataList"
    )
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["orders"] == [
        {"field": "adTraffic", "order": "desc"}
    ]
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["filters"] == [
        {"field": "asinResearchType", "filter": ["advertising"]}
    ]
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["tableType"] == "asinResearchOrganicTop10"


def test_asin_compare_ignores_view_mode_for_download_request(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="asin-compare",
                provider="xiyou",
                asins=["B08X4615SC", "B07BJN11KV"],
                site="US",
                cycle_period="last1month",
                view_mode="top10",
                keyword_type="organic",
                job_id="job-asin-compare-top10",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v4/asins/compare/list/resource"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/asin_compare/look_up/US/B08X4615SC,B07BJN11KV"
    )
    assert DummyResourceApiClient.calls[0]["payload"]["tableType"] == "multiAsinsComparisonList"
    assert DummyResourceApiClient.calls[0]["payload"]["filters"] == [
        {"field": "asinResearchType", "filter": ["organic"]}
    ]
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_ad_analysis_uses_request_url_and_payload(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ad-analysis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                parent_asin="B0FDB5VR1V",
                asins=["B0DZFGTCLR", "B0DZFW1QS1"],
                site="US",
                search_terms="candle warmer",
                job_id="job-ad-analysis",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/advertising/research/searchTerm/list/resource"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/asin/ad_analysis/US/B0DZFGTCLR"
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["filters"]["searchTerms"] == ["candle warmer"]
    assert DummyResourceApiClient.calls[1]["payload"] == {
        "resource": {"country": "US", "asin": "B0DZFGTCLR"},
        "biz": {"resourceId": "resource-1"},
    }


def test_ad_analysis_auto_hydrates_parent_asin_and_asins(monkeypatch, local_tmp_path: Path):
    DummyVariationAwareResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyVariationAwareResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ad-analysis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                search_terms="candle warmer",
                job_id="job-ad-analysis-auto",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert DummyVariationAwareResourceApiClient.calls[0]["url"] == "/v4/asins/variations"
    assert (
        DummyVariationAwareResourceApiClient.calls[1]["url"]
        == "/v4/asins/variations/status?variationId=VVNfQjBEWkZHVENMUg%3D%3D"
    )
    assert DummyVariationAwareResourceApiClient.calls[2]["url"] == "/v3/advertising/research/searchTerm/list/resource"
    assert DummyVariationAwareResourceApiClient.calls[2]["payload"]["biz"]["parentAsin"] == "B0FDB5VR1V"
    assert DummyVariationAwareResourceApiClient.calls[2]["payload"]["biz"]["asins"] == [
        "B0DZFW1QS1",
        "B0DZFGTCLR",
    ]


def test_ad_analysis_allows_empty_search_terms(monkeypatch, local_tmp_path: Path):
    DummyVariationAwareResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyVariationAwareResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ad-analysis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                cycle_period="last1month",
                job_id="job-ad-analysis-empty-search",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert DummyVariationAwareResourceApiClient.calls[2]["url"] == "/v3/advertising/research/searchTerm/list/resource"
    assert DummyVariationAwareResourceApiClient.calls[2]["payload"]["biz"]["pageSize"] == 20
    assert DummyVariationAwareResourceApiClient.calls[2]["payload"]["biz"]["filters"]["searchTerms"] == []


def test_parent_analysis_uses_request_url_and_payload(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="parent-analysis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                parent_asin="B0FDB5VR1V",
                asins=["B0DZFGTCLR", "B0DZFW1QS1"],
                query="candle warmer lamp",
                site="US",
                cycle_period="last1month",
                keyword_type="organic",
                job_id="job-parent-analysis",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert DummyResourceApiClient.calls[0]["url"] == "/v4/variation/compare/list/resource"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/asin/variations_insight/US/B0DZFGTCLR?listType=dataList"
    assert DummyResourceApiClient.calls[0]["payload"]["tableType"] == "variationCompareList"


def test_sales_analysis_uses_request_url_and_payload(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="sales-analysis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                parent_asin="B0FDB5VR1V",
                site="US",
                cycle_period="custom_month_range",
                start_month="2024-02",
                end_month="2026-05",
                job_id="job-sales-analysis",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/asins/sales/list/resource"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/asin/sales_analysis/US/B0DZFGTCLR?listType=dataList"
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["query"] == "B0DZFGTCLR"


def test_flow_insight_uses_two_step_resource_flow(monkeypatch, local_tmp_path: Path):
    DummyTwoStepResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyTwoStepResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="flow-insight",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                start_date="2026-05-27",
                end_date="2026-06-09",
                job_id="job-flow-insight",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-2"
    assert result.resource_url == "https://excel.xydc.com/flow-insight.xlsx?Expires=1&Signature=s"
    assert DummyTwoStepResourceApiClient.calls[0]["url"] == "/v2/asins/flow/insights/resource"
    assert DummyTwoStepResourceApiClient.calls[1]["url"] == "/v2/asins/flow/insights/resource/status"
    assert DummyTwoStepResourceApiClient.calls[1]["payload"]["biz"]["resourceId"] == "resource-2"


def test_ad_insight_uses_two_step_resource_flow(monkeypatch, local_tmp_path: Path):
    DummyTwoStepResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyTwoStepResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="ad-insight",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                start_date="2026-06-01",
                end_date="2026-06-02",
                job_id="job-ad-insight",
                export_format="json",
            )
        )
    )

    assert result.resource_url == "https://excel.xydc.com/ad-insight.xlsx?Expires=1&Signature=s"
    assert DummyTwoStepResourceApiClient.calls[0]["request_url"] == "/detail/asin/ad_insight/US/B0DZFGTCLR?listType=dataList"
    assert DummyTwoStepResourceApiClient.calls[1]["url"] == "/v2/asins/advertising/insights/resource/status"


def test_flow_weekly_uses_two_step_resource_flow(monkeypatch, local_tmp_path: Path):
    DummyTwoStepResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyTwoStepResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="flow-weekly",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                start_date="2026-05-25",
                end_date="2026-05-31",
                job_id="job-flow-weekly",
                export_format="json",
            )
        )
    )

    assert result.resource_url == "https://excel.xydc.com/flow-weekly.xlsx?Expires=1&Signature=s"
    assert DummyTwoStepResourceApiClient.calls[0]["request_url"] == "/detail/asin/flow_weekly/US/B0DZFGTCLR?listType=dataList"
    assert DummyTwoStepResourceApiClient.calls[1]["url"] == "/v2/asins/flow/weeklyReport/resource/status"


def test_flow_diagnosis_uses_rows_download_with_doc_request_url(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="flow-diagnosis",
                provider="xiyou",
                asin="B0DZFGTCLR",
                site="US",
                report_date="2026-06-02",
                keyword_type="organic",
                job_id="job-flow-diagnosis-json",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "rows"
    assert result.row_count == 1
    assert result.export is not None
    assert result.export.filename == "job-flow-diagnosis-json.json"
    assert DummyApiClient.calls[0]["url"] == "/v3/asins/traffic/diagnosis/list"
    assert DummyApiClient.calls[0]["request_url"] == "/detail/asin/flow_diagnosis/US/B0DZFGTCLR"
    assert DummyApiClient.calls[0]["payload"]["biz"]["date"] == "2026-06-02"
    assert DummyApiClient.calls[0]["payload"]["biz"]["trafficType"] == "organic"


def test_flow_diagnosis_aliases_are_normalized(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="流量诊断", asin="B0DZFGTCLR", export_format="xlsx")

    assert request.function == "流量诊断"
    manager._normalize_request(request)

    assert request.function == "flow-diagnosis"


def test_ad_analysis_period_week_is_normalized_to_last7days_and_default_page_size_20(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="ad-analysis", asin="B0DZFGTCLR", period="week")

    manager._normalize_request(request)

    assert request.cycle_period == "last7days"
    assert request.page_size == 20


def test_ad_analysis_period_month_is_normalized_to_last1month(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="ad-analysis", asin="B0DZFGTCLR", period="month")

    manager._normalize_request(request)

    assert request.cycle_period == "last30days"


def test_ad_analysis_period_last14days_is_normalized_to_last14days_and_default_page_size_20(
    local_tmp_path: Path,
):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="ad-analysis", asin="B0DZFGTCLR", period="last14days")

    manager._normalize_request(request)

    assert request.cycle_period == "last14days"
    assert request.page_size == 20


def test_ad_analysis_period_last30days_is_normalized_to_last30days(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="ad-analysis", asin="B0DZFGTCLR", period="last30days")

    manager._normalize_request(request)

    assert request.cycle_period == "last30days"


def test_ad_analysis_period_7d_is_normalized_to_last7days(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    request = XiyouRankingRequest(function="ad-analysis", asin="B0DZFGTCLR", period="7d")

    manager._normalize_request(request)

    assert request.cycle_period == "last7days"


def test_standalone_diagnosis_alias_is_not_normalized(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError):
        _run(manager.run(XiyouRankingRequest(function="诊断仪", asin="B0DZFGTCLR", export_format="xlsx")))


def test_manager_writes_resource_json_metadata(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-explorer",
                keyword="tv stand",
                site="US",
                job_id="job-resource-json",
                export_format="json",
            )
        )
    )

    assert result.export is not None
    exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/searchTerm_explorer/US/tv%20stand"
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]
    assert exported["function"] == "keyword-explorer"
    assert exported["dataset"] == "keywords"
    assert exported["resource_id"] == "resource-1"
    assert exported["resource_url"].endswith("Signature=s")


def test_keyword_analysis_json_uses_live_list_endpoint(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-analysis",
                provider="xiyou",
                keyword="tv stands for living room",
                site="US",
                cycle_period="last3months",
                view_mode="trends",
                job_id="job-keyword-analysis-json",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "rows"
    assert result.row_count == 1
    assert result.export is not None
    assert result.export.filename == "job-keyword-analysis-json.json"
    assert DummyApiClient.calls[0]["url"] == "/v4/searchTerms/analysis/list"
    assert DummyApiClient.calls[0]["payload"]["resource"]["searchTerm"] == "tv stands for living room"
    assert DummyApiClient.calls[0]["payload"]["cycleFilter"]["cycle"] == "monthly"
    assert "listType=trendsViewList" in DummyApiClient.calls[0]["request_url"]


def test_keyword_analysis_resource_export_uses_doc_request_url(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-analysis",
                provider="xiyou",
                keyword="backpack",
                site="US",
                cycle_period="last3months",
                view_mode="trends",
                job_id="job-keyword-analysis-xlsx",
                export_format="xlsx",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v4/searchTerms/analysis/list/resource"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/search_term/look_up/US/backpack"
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_keyword_historical_traffic_json_uses_rows_endpoint(monkeypatch, local_tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyApiClient)
    monkeypatch.setattr("opscli.xiyou.api.payloads._today", lambda: date(2026, 6, 9))
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-historical-traffic",
                provider="xiyou",
                keyword="backpack",
                site="US",
                period="month",
                job_id="job-keyword-historical-traffic-json",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "rows"
    assert result.row_count == 1
    assert result.export is not None
    assert result.export.filename == "job-keyword-historical-traffic-json.json"
    assert result.period == "last1month"
    assert DummyApiClient.calls[0]["url"] == "/v3/searchTerms/historicalTrafficRatio/list"
    assert DummyApiClient.calls[0]["request_url"].endswith(
        "/detail/search_term/historical_traffic_analysis/US/backpack"
    )
    assert DummyApiClient.calls[0]["payload"]["biz"]["cycleFilter"] == {
        "cycle": "daily",
        "period": "",
        "startCycle": {"startDate": "2026-05-09", "endDate": "2026-05-09"},
        "endCycle": {"startDate": "2026-06-07", "endDate": "2026-06-07"},
    }


def test_keyword_historical_traffic_rejects_custom_date_range(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError) as exc:
        _run(
            manager.run(
                XiyouRankingRequest(
                    function="keyword-historical-traffic",
                    keyword="backpack",
                    start_date="2026-05-09",
                    end_date="2026-06-07",
                )
            )
        )

    assert "不支持用户自定义时间范围" in str(exc.value)


def test_keyword_historical_traffic_rejects_cycle_period_override(local_tmp_path: Path):
    manager = XiyouApiManager(
        settings=XiyouSettings(output_dir=local_tmp_path),
        credential_provider=DummyCredentialProvider(),
    )

    with pytest.raises(XiyouConfigError) as exc:
        _run(
            manager.run(
                XiyouRankingRequest(
                    function="keyword-historical-traffic",
                    keyword="backpack",
                    cycle_period="last1month",
                )
            )
        )

    assert "不支持用户自定义时间范围" in str(exc.value)


def test_keyword_ad_replay_uses_doc_request_url_and_report_date(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-ad-replay",
                provider="xiyou",
                keyword="backpack",
                site="US",
                report_date="2026-06-08",
                replay_type="ac",
                view_mode="trends",
                job_id="job-keyword-ad-replay",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v4/searchTerms/advertisingReplay/resource"
    assert DummyResourceApiClient.calls[0]["payload"]["reportDate"] == "2026-06-08"
    assert DummyResourceApiClient.calls[0]["request_url"] == "/detail/search_term/ad_once_more/US/backpack"
    assert DummyResourceApiClient.calls[1]["payload"] == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "resourceId": "resource-1",
    }
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_keyword_organic_replay_uses_doc_request_url_and_report_date(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-organic-replay",
                provider="xiyou",
                keyword="backpack",
                site="US",
                report_date="2026-06-08",
                replay_type="ac",
                view_mode="trends",
                job_id="job-keyword-organic-replay",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v3/searchTerms/organic/replay/resource"
    assert DummyResourceApiClient.calls[0]["payload"]["biz"]["reportDate"] == "2026-06-08"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/search_term/na_once_more/US/backpack?adOnceMoreType=na"
    )
    assert DummyResourceApiClient.calls[1]["payload"] == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "biz": {"resourceId": "resource-1"},
    }
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]


def test_keyword_ad_toppers_uses_doc_request_url(monkeypatch, local_tmp_path: Path):
    DummyResourceApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceApiClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="keyword-ad-toppers",
                provider="xiyou",
                keyword="backpack",
                site="US",
                view_mode="data",
                replay_type="oor",
                job_id="job-keyword-ad-toppers",
                export_format="json",
            )
        )
    )

    assert result.data_mode == "resource_export"
    assert result.resource_id == "resource-1"
    assert DummyResourceApiClient.calls[0]["url"] == "/v2/searchTerms/advertising/toppers/excel/resource"
    assert (
        DummyResourceApiClient.calls[0]["request_url"]
        == "/detail/search_term/ad_display_insight/US/backpack?adOnceMoreType=na"
    )
    assert DummyResourceApiClient.calls[1]["payload"] == {
        "resource": {"country": "US", "searchTerm": "backpack"},
        "biz": {"resourceId": "resource-1"},
    }
    assert DummyResourceApiClient.calls[1]["request_url"] == DummyResourceApiClient.calls[0]["request_url"]



def _build_xlsx_bytes(data_rows: int) -> bytes:
    """生成包含 1 行表头 + data_rows 行数据的 xlsx 字节，供 mock 下载使用。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["keyword", "traffic"])
    for index in range(data_rows):
        ws.append([f"kw-{index}", index])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_count_xlsx_rows_returns_data_row_count(local_tmp_path: Path):
    # 真实 xlsx：表头 1 行 + 数据 5 行，_count_xlsx_rows 应返回 5
    xlsx_path = local_tmp_path / "sample.xlsx"
    xlsx_path.write_bytes(_build_xlsx_bytes(5))

    assert _count_xlsx_rows(xlsx_path) == 5


def test_count_xlsx_rows_returns_zero_for_corrupt_file(local_tmp_path: Path):
    # 非标准 xlsx（伪字节）必须返回 0，不能抛异常导致主任务失败
    corrupt_path = local_tmp_path / "broken.xlsx"
    corrupt_path.write_bytes(b"not-an-xlsx")

    assert _count_xlsx_rows(corrupt_path) == 0


class DummyResourceXlsxClient(DummyResourceApiClient):
    """返回真实 xlsx 字节的 DummyResourceApiClient，用于验证 row_count/warning。"""

    xlsx_bytes: bytes = b""

    async def get_bytes(self, url):
        self.calls.append({"url": url, "method": "GET"})
        return self.__class__.xlsx_bytes


def test_resource_xlsx_populates_row_count_and_warns_on_page_size_mismatch(
    monkeypatch, local_tmp_path: Path
):
    # 模拟西柚返回 5 行全量数据，但调用方仅请求 2 行，应触发 page_size warning
    DummyResourceXlsxClient.calls = []
    DummyResourceXlsxClient.xlsx_bytes = _build_xlsx_bytes(5)
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceXlsxClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                page_size=2,
                job_id="job-resource-warn",
                export_format="xlsx",
            )
        )
    )

    assert result.row_count == 5
    # 仅校验 resource_export 阶段的 warning，避免环境内 file_upload 失败导致干扰
    resource_warnings = [w for w in result.warnings if w.get("stage") == "resource_export"]
    assert len(resource_warnings) == 1
    warning = resource_warnings[0]
    assert "page_size=2" in warning["message"]
    assert "5 行" in warning["message"]


def test_resource_xlsx_no_warning_when_page_size_not_exceeded(
    monkeypatch, local_tmp_path: Path
):
    # 默认 page_size=50，xlsx 仅 3 行时不应追加 page_size 相关 warning
    DummyResourceXlsxClient.calls = []
    DummyResourceXlsxClient.xlsx_bytes = _build_xlsx_bytes(3)
    monkeypatch.setattr(api_manager_module, "XiyouApiClient", DummyResourceXlsxClient)
    settings = XiyouSettings(output_dir=local_tmp_path, authorization=None, cookie=None)
    manager = XiyouApiManager(settings=settings, credential_provider=DummyCredentialProvider())

    result = _run(
        manager.run(
            XiyouRankingRequest(
                function="reverse-keyword",
                provider="xiyou",
                asin="B0G33FZ8XS",
                site="US",
                job_id="job-resource-ok",
                export_format="xlsx",
            )
        )
    )

    assert result.row_count == 3
    assert all(w.get("stage") != "resource_export" for w in result.warnings)
