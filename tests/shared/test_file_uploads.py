import httpx
import pytest

from opscli.shared import file_uploads
from opscli.shared.file_uploads import FileUploadClient, FileUploadHttpError


class DummyAuthClient:
    def build_request_auth(self, alias: str):
        assert alias == "ops"
        return {"Authorization": "Bearer test"}, {"ops_token": "test"}


def test_file_upload_retries_retryable_http_status(monkeypatch, tmp_path):
    calls = []
    upload_file = tmp_path / "report.xlsx"
    upload_file.write_bytes(b"test")

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if len(calls) == 1:
            return httpx.Response(502, json={"message": "bad gateway"})
        return httpx.Response(200, json={"code": 200, "data": {"url": "https://oss.example/report.xlsx"}})

    monkeypatch.setattr(file_uploads.httpx, "post", fake_post)
    monkeypatch.setenv("OPSCLI_FILE_UPLOAD_RETRIES", "1")

    result = FileUploadClient(auth_client=DummyAuthClient()).upload(upload_file, purpose="asin_data_live_xlsx")

    assert result.url == "https://oss.example/report.xlsx"
    assert len(calls) == 2
    assert calls[0]["files"][0][0] == "folder"
    assert calls[1]["files"][-1][1][0] == "report.xlsx"


def test_file_upload_does_not_retry_unauthorized(monkeypatch, tmp_path):
    calls = []
    upload_file = tmp_path / "report.xlsx"
    upload_file.write_bytes(b"test")

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(401, json={"message": "unauthorized"})

    monkeypatch.setattr(file_uploads.httpx, "post", fake_post)
    monkeypatch.setenv("OPSCLI_FILE_UPLOAD_RETRIES", "2")

    with pytest.raises(FileUploadHttpError) as exc:
        FileUploadClient(auth_client=DummyAuthClient()).upload(upload_file, purpose="asin_data_live_xlsx")

    assert exc.value.status_code == 401
    assert len(calls) == 1
