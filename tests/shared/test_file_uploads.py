import httpx
import pytest

from opscli.shared import file_uploads
from opscli.shared.file_uploads import FileUploadBadJsonError, FileUploadClient, FileUploadHttpError


@pytest.mark.parametrize("response,error_class", [
    (httpx.Response(502, text="<html>private upstream data</html>"), FileUploadHttpError),
    (httpx.Response(400, json=["private upstream data"]), FileUploadHttpError),
    (httpx.Response(200, text="not json"), FileUploadBadJsonError),
    (httpx.Response(200, json=[]), FileUploadBadJsonError),
])
def test_upload_response_errors_keep_http_status_without_raw_body(response, error_class):
    """响应解析失败仍保留状态码，不把网关 HTML 或数组原样返回。"""
    with pytest.raises(error_class) as caught:
        file_uploads._parse_upload_response(response)
    assert caught.value.status_code == response.status_code
    assert "private upstream data" not in str(caught.value)


@pytest.mark.parametrize("value", ["sk-private-credential", "LTAI1234567890abc", {"token": "private"}, ["private"], "x" * 65, True])
def test_upload_error_rejects_unsafe_business_code(value):
    """业务码不能成为绕过消息脱敏的输出通道。"""
    from opscli.amazon_rufus.services.answer_report_publisher import _upload_error_details
    exc = FileUploadHttpError(403, "没有上传权限", business_code=value)
    assert exc.business_code is None
    assert _upload_error_details(exc)["business_code"] is None


def test_retry_exhaustion_is_safe_for_non_rufus_callers(monkeypatch, tmp_path):
    """其他模块直接序列化共享异常时也不能泄漏最后一次响应的认证材料。"""
    upload_file = tmp_path / "report.xlsx"
    upload_file.write_bytes(b"test")
    monkeypatch.setenv("OPSCLI_FILE_UPLOAD_RETRIES", "0")
    monkeypatch.setattr(file_uploads.httpx, "post", lambda *args, **kwargs: httpx.Response(
        503, json={"code": "sk-private-credential", "message": "Authorization: Bearer private-token"},
    ))
    with pytest.raises(FileUploadHttpError) as caught:
        FileUploadClient(auth_client=DummyAuthClient()).upload(upload_file, purpose="keepa_report")
    assert caught.value.to_dict()["message"] == "远端错误消息可能包含敏感信息，已隐藏"
    assert caught.value.business_code is None
    assert caught.value.status_code == 503


class DummyAuthClient:
    def build_request_auth(self, alias: str):
        assert alias == "ops"
        return {"Authorization": "Bearer test"}, {"ops_token": "test"}


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_upload_retry_exhaustion_preserves_last_error(monkeypatch, tmp_path, status):
    """重试耗尽后保留最后一次响应详情，不能只剩通用网关错误。"""
    upload_file = tmp_path / "report.md"
    upload_file.write_text("# report", encoding="utf-8")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(status)
        return httpx.Response(status, json={"code": "UPLOAD_BUSY", "message": f"服务繁忙 {len(calls)}"})

    monkeypatch.setattr(file_uploads.httpx, "post", fake_post)
    monkeypatch.setattr(file_uploads.time, "sleep", lambda _: None)
    monkeypatch.setenv("OPSCLI_FILE_UPLOAD_RETRIES", "1")
    with pytest.raises(FileUploadHttpError) as caught:
        FileUploadClient(auth_client=DummyAuthClient()).upload(upload_file, purpose="report")
    assert len(calls) == 2
    assert caught.value.status_code == status
    assert caught.value.business_code == "UPLOAD_BUSY"
    assert str(caught.value) == "服务繁忙 2"


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
