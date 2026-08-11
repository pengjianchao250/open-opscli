"""Scrape.do 场景执行、脱敏、上传和账号切换测试。"""

import asyncio
import json
from pathlib import Path

from opscli.scrape_do.config import ScrapeDoSettings
from opscli.scrape_do.domain.models import ScrapeDoCredential, ScrapeDoScenarioRequest
from opscli.scrape_do.domain.exceptions import ScrapeDoApiError
from opscli.scrape_do.services.api_manager import ScrapeDoApiManager


def _run(coro):
    return asyncio.run(coro)


class FakeCredentialProvider:
    def get_default(self, *, exclude_account_ids=None):
        return ScrapeDoCredential(name="default", token="secret-token", source="test")


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_json(self, endpoint, params):
        self.calls.append((endpoint, params))
        from opscli.scrape_do.api.client import ScrapeDoApiResponse

        assert params["token"] == "secret-token"
        return ScrapeDoApiResponse(
            payload={
                "asin": "B0C7BKZ883",
                "status": "success",
                "brand": "Gogoonike",
                "name": "Laptop Stand",
                "price": 14.99,
                "token": "secret-token",
                "access_token": "response-access-token",
                "html": "<html>secret-token</html>",
                "raw_html": "<html>raw</html>",
                "htmlContent": "<html>content</html>",
            },
            billing={"request_cost": 1, "remaining_credits": 99},
            safe_url="https://api.scrape.do/plugin/amazon/pdp?token=***&asin=B0C7BKZ883",
        )


class DisabledUploadClient:
    enabled = False

    def __init__(self, *args, **kwargs):
        pass


class EnabledUploadClient:
    enabled = True
    uploaded = None

    def __init__(self, *args, **kwargs):
        pass

    def upload(self, path, *, purpose, folder=None, public=None, metadata=None):
        self.__class__.uploaded = {
            "path": str(path),
            "purpose": purpose,
            "folder": folder,
            "metadata": metadata,
        }

        class Result:
            url = "https://ops.example.com/scrape-do-job.xlsx"

        return Result()


def test_run_writes_safe_files_and_export(monkeypatch, tmp_path: Path):
    from opscli.scrape_do.services import api_manager as module

    monkeypatch.setattr(module, "ScrapeDoApiClient", FakeClient)
    monkeypatch.setattr(module, "FileUploadClient", DisabledUploadClient)
    settings = ScrapeDoSettings(output_dir=tmp_path / "default-runs")
    manager = ScrapeDoApiManager(settings=settings, api_key_provider=FakeCredentialProvider())

    result = _run(
        manager.run(
            ScrapeDoScenarioRequest(
                scenario="amazon-pdp",
                site="US",
                params={
                    "asin": "B0C7BKZ883",
                    "token": "user-supplied-token",
                    "access_token": "user-access-token",
                    "html": "<html>request</html>",
                },
                output_dir=str(tmp_path),
                job_id="scrape-do-job",
            )
        )
    )

    assert result.job_id == "scrape-do-job"
    assert result.row_count == 1
    assert result.billing == {"request_cost": 1, "remaining_credits": 99}
    assert Path(result.export.path).exists()

    params_text = Path(result.params_path).read_text(encoding="utf-8")
    raw_text = Path(result.raw_path).read_text(encoding="utf-8")
    result_text = Path(result.result_path).read_text(encoding="utf-8")
    assert "secret-token" not in params_text
    assert "user-supplied-token" not in params_text
    assert "user-access-token" not in params_text
    assert "secret-token" not in raw_text
    assert "response-access-token" not in raw_text
    assert "user-supplied-token" not in raw_text
    assert "secret-token" not in result_text
    assert "response-access-token" not in result_text
    assert "user-supplied-token" not in result_text
    assert "user-access-token" not in result_text
    assert "<html" not in params_text
    assert "<html" not in raw_text
    assert "<html" not in result_text
    assert "raw_html" not in raw_text
    assert "htmlContent" not in raw_text
    assert "token" not in json.loads(params_text)["normalized_params"]
    assert "token" not in json.loads(params_text)["request"]["params"]
    assert "access_token" not in json.loads(params_text)["request"]["params"]

    status = manager.job_status("scrape-do-job")
    assert status["job_id"] == "scrape-do-job"
    assert status["row_count"] == 1

    fresh_manager = ScrapeDoApiManager(settings=settings, api_key_provider=FakeCredentialProvider())
    fresh_status = fresh_manager.job_status("scrape-do-job")
    assert fresh_status["job_id"] == "scrape-do-job"


def test_run_uses_enabled_upload_client(monkeypatch, tmp_path: Path):
    from opscli.scrape_do.services import api_manager as module

    EnabledUploadClient.uploaded = None
    monkeypatch.setattr(module, "ScrapeDoApiClient", FakeClient)
    monkeypatch.setattr(module, "FileUploadClient", EnabledUploadClient)
    manager = ScrapeDoApiManager(
        settings=ScrapeDoSettings(output_dir=tmp_path / "default-runs"),
        api_key_provider=FakeCredentialProvider(),
    )

    result = _run(
        manager.run(
            ScrapeDoScenarioRequest(
                scenario="amazon-pdp",
                site="US",
                params={"asin": "B0C7BKZ883"},
                output_dir=str(tmp_path),
                job_id="scrape-do-upload-job",
            )
        )
    )

    assert result.export.url == "https://ops.example.com/scrape-do-job.xlsx"
    assert EnabledUploadClient.uploaded["purpose"] == "scrape_do_export"
    assert EnabledUploadClient.uploaded["folder"] == "scrape-do/exports"
    assert EnabledUploadClient.uploaded["metadata"] == {
        "job_id": "scrape-do-upload-job",
        "scenario": "amazon-pdp",
        "site": "US",
    }


def test_run_fails_over_after_unauthorized_account(monkeypatch, tmp_path: Path):
    from opscli.scrape_do.services import api_manager as module
    from opscli.scrape_do.api.client import ScrapeDoApiResponse

    attempted_tokens = []

    class FailoverProvider:
        def get_default(self, *, exclude_account_ids=None):
            excluded = exclude_account_ids or set()
            account_id = 1 if 1 not in excluded else 2
            return ScrapeDoCredential(
                name=f"account-{account_id}",
                token=f"scrape-token-{account_id}",
                source="test",
                account_id=account_id,
                secret_version=1,
            )

        def report_failure(self, credential, exc):
            pass

        def report_success(self, credential, billing):
            pass

    class FailoverClient(FakeClient):
        async def get_json(self, endpoint, params):
            attempted_tokens.append(params["token"])
            if params["token"] == "scrape-token-1":
                raise ScrapeDoApiError("unauthorized", status_code=401)
            return ScrapeDoApiResponse(
                payload={"asin": "B0C7BKZ883", "status": "success"},
                billing={"remaining_credits": 9},
                safe_url="https://api.scrape.do/plugin/amazon/pdp?token=***",
            )

    monkeypatch.setattr(module, "ScrapeDoApiClient", FailoverClient)
    monkeypatch.setattr(module, "FileUploadClient", DisabledUploadClient)
    manager = ScrapeDoApiManager(
        settings=ScrapeDoSettings(output_dir=tmp_path),
        api_key_provider=FailoverProvider(),
    )

    result = _run(
        manager.run(
            ScrapeDoScenarioRequest(
                scenario="amazon-pdp",
                site="US",
                params={"asin": "B0C7BKZ883"},
                job_id="scrape-do-failover",
            )
        )
    )

    assert result.row_count == 1
    assert attempted_tokens == ["scrape-token-1", "scrape-token-2"]
