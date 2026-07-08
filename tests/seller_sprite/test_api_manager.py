import asyncio
import json
from pathlib import Path

import pytest

from opscli.seller_sprite.accounts import SellerSpriteAccount
from opscli.seller_sprite.config import SellerSpriteSettings
from opscli.seller_sprite.domain.exceptions import SellerSpriteApiError, SellerSpriteConfigError
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest, SellerSpriteScenarioResult
from opscli.seller_sprite.services import api_manager as api_manager_module
from opscli.seller_sprite.services.api_manager import SellerSpriteApiManager


def _run(coro):
    return asyncio.run(coro)


class DummyAccountProvider:
    def get_default(self, *, refresh=False):
        return SellerSpriteAccount(name="default", username="user@example.com", password="secret")


class DummyApiClient:
    calls = []

    def __init__(self, *, account):
        self.account = account
        self.login_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def login(self):
        self.login_calls += 1
        return {"login_status": 302, "login_redirect": True, "cookie_names": ["SESSION"]}

    def has_cookies(self):
        return False

    def has_login_cookies(self):
        return False

    def cookie_names(self):
        return []

    def switch_account(self, account):
        self.account = account

    async def post_json(self, url, payload, *, referer=None):
        self.calls.append({"url": url, "payload": payload, "referer": referer})
        if "high" in url:
            return {"code": "OK", "data": [{"keyword": "flashlight", "frequency": 10}]}
        return {
            "code": "OK",
            "data": {
                "items": [
                    {
                        "keywords": "flashlight",
                        "keywordCn": "手电筒",
                        "searches": 1000,
                        "amazonChoice": True,
                    }
                ]
            },
        }


class SessionExpiredOnceApiClient(DummyApiClient):
    instance = None

    def __init__(self, *, account):
        super().__init__(account=account)
        self.has_failed = False
        SessionExpiredOnceApiClient.instance = self

    def has_cookies(self):
        return True

    def has_login_cookies(self):
        return True

    def cookie_names(self):
        return ["SESSION"]

    async def post_json(self, url, payload, *, referer=None):
        self.calls.append({"url": url, "payload": payload, "referer": referer})
        if not self.has_failed:
            self.has_failed = True
            raise SellerSpriteApiError("session expired", api_code="ERR_GLOBAL_SESSION_EXPIRED")
        return {"code": "OK", "data": {"items": [{"asin": "B00TEST"}]}}


# class ListingAnalysisApiClient(DummyApiClient):
#     calls = []
#     instance = None

#     def __init__(self, *, account):
#         super().__init__(account=account)
#         self.poll_calls = 0
#         ListingAnalysisApiClient.instance = self

#     def _browser_headers(self, *, referer=None):
#         return {"Referer": referer} if referer else {}

#     async def request_json(self, method, url, **kwargs):
#         self.calls.append(
#             {
#                 "method": method,
#                 "url": url,
#                 "params": kwargs.get("params"),
#                 "json": kwargs.get("json"),
#                 "headers": kwargs.get("headers"),
#             }
#         )
#         if url == "/v3/api/ai-workflow/listing-analysis":
#             return {
#                 "code": "OK",
#                 "success": True,
#                 "data": {
#                     "taskId": "task-listing-1",
#                     "taskStatus": "SUBMITTED",
#                     "content": None,
#                 },
#             }
#         raise AssertionError(f"unexpected url: {url}")

#     async def get_json(self, url, params, *, referer=None):
#         self.calls.append({"method": "GET", "url": url, "params": params, "referer": referer})
#         if url == "/v3/api/ai-analysis/task/task-listing-1":
#             self.poll_calls += 1
#             if self.poll_calls == 1:
#                 return {
#                     "code": "OK",
#                     "success": True,
#                     "data": {
#                         "taskId": "task-listing-1",
#                         "taskStatus": "SUBMITTED",
#                         "content": None,
#                     },
#                 }
#             return {
#                 "code": "OK",
#                 "success": True,
#                 "data": {
#                     "taskId": "task-listing-1",
#                     "taskStatus": "COMPLETED",
#                     "content": "listing report content",
#                     "completedTime": "2026-06-08 12:00:00",
#                 },
#             }
#         raise AssertionError(f"unexpected url: {url}")


async def _wait_for_state(manager, job_id: str, expected_state: str, *, attempts: int = 20):
    for _ in range(attempts):
        status = manager.job_status(job_id)
        if status.get("state") == expected_state:
            return status
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach state {expected_state}")


class ControlledAsyncManager(SellerSpriteApiManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_started = asyncio.Event()
        self.allow_finish = asyncio.Event()
        self.last_request = None

    async def run(self, request):
        self.last_request = request
        self.run_started.set()
        await self.allow_finish.wait()
        root_dir = self._build_root_dir(request, request.job_id or "job-controlled")
        return SellerSpriteScenarioResult.empty(
            job_id=request.job_id or "job-controlled",
            scenario=request.scenario,
            site=request.site,
            period=request.period,
            root_dir=root_dir,
            params_path=root_dir / "params.json",
            raw_path=root_dir / "raw.json",
            result_path=root_dir / "result.json",
        )


class FailingAsyncManager(SellerSpriteApiManager):
    async def run(self, request):
        raise ValueError("boom from async seller sprite")


def test_manager_writes_job_files_and_xlsx(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", DummyApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = _run(
        manager.run(
            SellerSpriteScenarioRequest(
                scenario="keyword-reverse",
                site="JP",
                period="nearly",
                params={"asin": "B07YRMT36L"},
                page_size=100,
                job_id="job-offline-regression",
            )
        )
    )

    root_dir = tmp_path / "job-offline-regression"
    assert result.row_count == 1
    assert (root_dir / "params.json").exists()
    assert (root_dir / "raw.json").exists()
    assert (root_dir / "result.json").exists()
    assert result.export is not None
    assert result.export.path.endswith("job-offline-regression.xlsx")
    assert Path(result.export.path).exists()

    saved = json.loads((root_dir / "result.json").read_text(encoding="utf-8"))
    assert saved["row_count"] == 1
    assert saved["export"]["filename"] == "job-offline-regression.xlsx"
    assert DummyApiClient.calls[0]["payload"]["asin"] == "B07YRMT36L"
    assert "market" not in DummyApiClient.calls[0]["payload"]


def test_manager_normalizes_competitor_lookup_singular_asin_before_api_call(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", DummyApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = _run(
        manager.run(
            SellerSpriteScenarioRequest(
                scenario="competitor-lookup",
                site="US",
                period="30d",
                params={"asin": "B00FLYWNYQ"},
                job_id="job-competitor-asin",
                export_format="json",
            )
        )
    )

    assert result.row_count == 1
    assert DummyApiClient.calls[0]["payload"]["asins"] == ["B00FLYWNYQ"]
    assert "asin" not in DummyApiClient.calls[0]["payload"]


def test_manager_fast_fails_empty_competitor_lookup_before_api_call(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", DummyApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    with pytest.raises(SellerSpriteConfigError, match="至少需要一个主筛选条件"):
        _run(
            manager.run(
                SellerSpriteScenarioRequest(
                    scenario="competitor-lookup",
                    site="US",
                    period="30d",
                    params={},
                    job_id="job-competitor-empty",
                    export_format="json",
                )
            )
        )

    assert DummyApiClient.calls == []


def test_manager_generates_camel_case_job_id(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", DummyApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = _run(
        manager.run(
            SellerSpriteScenarioRequest(
                scenario="keyword-reverse",
                site="JP",
                period="nearly",
                params={"asin": "B07YRMT36L"},
            )
        )
    )

    assert result.export is not None
    assert result.export.filename.startswith("SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-")
    assert result.export.filename.endswith(".xlsx")
    assert Path(result.export.path).exists()


def test_manager_writes_json_export(monkeypatch, tmp_path: Path):
    DummyApiClient.calls = []
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", DummyApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = _run(
        manager.run(
            SellerSpriteScenarioRequest(
                scenario="keyword-reverse",
                site="JP",
                period="nearly",
                params={"asin": "B07YRMT36L"},
                job_id="job-json-regression",
                export_format="json",
            )
        )
    )

    assert result.export is not None
    assert result.export.filename == "job-json-regression.json"
    assert result.export.format == "json"
    assert result.export.mime_type == "application/json"
    exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
    assert exported["job_id"] == "job-json-regression"
    assert exported["scenario"] == "keyword-reverse"
    assert exported["row_count"] == 1
    assert exported["rows"][0]["keywords"] == "flashlight"


def test_export_output_path_uses_short_filename_for_windows_compatibility(tmp_path: Path):
    job_id = "SellerSprite-ListingAnalysis-US-B0TEST1234-Last-30-days-" + ("a" * 90)
    root_dir = tmp_path / job_id

    export_path = api_manager_module._export_output_path(root_dir, job_id, "json")

    assert export_path == root_dir / "export.json"


def test_job_status_reads_existing_result(tmp_path: Path):
    root_dir = tmp_path / "job-1"
    root_dir.mkdir()
    (root_dir / "result.json").write_text('{"job_id":"job-1","row_count":3}', encoding="utf-8")
    settings = SellerSpriteSettings(output_dir=tmp_path)
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = manager.job_status("job-1")

    assert result == {"job_id": "job-1", "row_count": 3}


def test_job_status_merges_completed_async_status_with_result(tmp_path: Path):
    root_dir = tmp_path / "job-async-complete"
    root_dir.mkdir()
    (root_dir / "status.json").write_text(
        json.dumps(
            {
                "job_id": "job-async-complete",
                "state": "succeeded",
                "stage": "finished",
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    (root_dir / "result.json").write_text(
        json.dumps({"job_id": "job-async-complete", "row_count": 3}),
        encoding="utf-8",
    )
    settings = SellerSpriteSettings(output_dir=tmp_path)
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = manager.job_status("job-async-complete")

    assert result["job_id"] == "job-async-complete"
    assert result["state"] == "succeeded"
    assert result["stage"] == "finished"
    assert result["row_count"] == 3


def test_manager_start_returns_before_background_task_finishes(tmp_path: Path):
    async def scenario():
        settings = SellerSpriteSettings(output_dir=tmp_path)
        manager = ControlledAsyncManager(settings=settings, account_provider=DummyAccountProvider())

        status = await manager.start(
            SellerSpriteScenarioRequest(
                scenario="keyword-reverse",
                site="JP",
                period="nearly",
                params={"asin": "B07YRMT36L"},
                job_id="job-async-controlled",
            )
        )

        assert status["job_id"] == "job-async-controlled"
        assert status["state"] == "queued"
        assert status["stage"] == "created"
        assert manager.last_request is None

        await manager.run_started.wait()
        running = manager.job_status("job-async-controlled")
        assert running["state"] == "running"
        assert running["stage"] == "running"

        manager.allow_finish.set()
        succeeded = await _wait_for_state(manager, "job-async-controlled", "succeeded")
        assert succeeded["state"] == "succeeded"
        assert succeeded["stage"] == "finished"
        assert succeeded["error"] is None

    _run(scenario())


def test_manager_start_records_failed_status(tmp_path: Path):
    async def scenario():
        settings = SellerSpriteSettings(output_dir=tmp_path)
        manager = FailingAsyncManager(settings=settings, account_provider=DummyAccountProvider())

        status = await manager.start(
            SellerSpriteScenarioRequest(
                scenario="keyword-reverse",
                site="JP",
                period="nearly",
                params={"asin": "B07YRMT36L"},
                job_id="job-async-failed",
            )
        )

        assert status["state"] == "queued"
        failed = await _wait_for_state(manager, "job-async-failed", "failed")
        assert failed["stage"] == "failed"
        assert failed["error"]["code"] == "ValueError"
        assert failed["error"]["message"] == "boom from async seller sprite"

    _run(scenario())


def test_manager_relogs_and_retries_when_session_expires(monkeypatch, tmp_path: Path):
    SessionExpiredOnceApiClient.calls = []
    SessionExpiredOnceApiClient.instance = None
    monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", SessionExpiredOnceApiClient)
    settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
    manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

    result = _run(
        manager.run(
            SellerSpriteScenarioRequest(
                scenario="competitor-lookup",
                site="US",
                period="30d",
                params={"keyword": "toy car"},
                job_id="job-session-retry",
                export_format="json",
            )
        )
    )

    assert result.row_count == 1
    assert result.warnings[0]["message"] == "卖家精灵会话过期，已重新登录并重试一次"
    assert SessionExpiredOnceApiClient.instance is not None
    assert SessionExpiredOnceApiClient.instance.login_calls == 1
    assert len(SessionExpiredOnceApiClient.calls) == 2


# def test_manager_polls_listing_analysis_task_content(monkeypatch, tmp_path: Path):
#     ListingAnalysisApiClient.calls = []
#     ListingAnalysisApiClient.instance = None
#     monkeypatch.setattr(api_manager_module, "SellerSpriteApiClient", ListingAnalysisApiClient)
#     settings = SellerSpriteSettings(output_dir=tmp_path, username=None, password=None, default_mode="api-direct")
#     manager = SellerSpriteApiManager(settings=settings, account_provider=DummyAccountProvider())

#     result = _run(
#         manager.run(
#             SellerSpriteScenarioRequest(
#                 scenario="listing-analysis",
#                 site="US",
#                 period="30d",
#                 params={"asin": "B0D3845MWD", "pollInterval": 0},
#                 job_id="job-listing-analysis",
#                 export_format="json",
#             )
#         )
#     )

#     assert result.row_count == 1
#     assert result.data[0]["taskId"] == "task-listing-1"
#     assert result.data[0]["content"] == "listing report content"
#     assert ListingAnalysisApiClient.instance is not None
#     assert ListingAnalysisApiClient.instance.poll_calls == 2
#     assert ListingAnalysisApiClient.calls[0]["method"] == "POST"
#     assert ListingAnalysisApiClient.calls[0]["url"] == "/v3/api/ai-workflow/listing-analysis"
#     assert ListingAnalysisApiClient.calls[0]["json"] == {}
#     assert ListingAnalysisApiClient.calls[0]["headers"]["Content-Type"] == "application/json;charset=UTF-8"
#     assert ListingAnalysisApiClient.calls[0]["params"] == {
#         "asin": "B0D3845MWD",
#         "station": "GLOBAL",
#     }

#     raw = json.loads((tmp_path / "job-listing-analysis" / "raw.json").read_text(encoding="utf-8"))
#     assert raw["response"]["data"]["content"] == "listing report content"
#     assert raw["response"]["data"]["submitTask"]["taskId"] == "task-listing-1"
#     exported = json.loads(Path(result.export.path).read_text(encoding="utf-8"))
#     assert exported["rows"][0]["content"] == "listing report content"
