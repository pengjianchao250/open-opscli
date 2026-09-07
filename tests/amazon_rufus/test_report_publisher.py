import codecs
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as RealDatetime
from pathlib import Path

import pytest
import httpx

from opscli.amazon_rufus.domain.exceptions import RufusReportUploadError
from opscli.amazon_rufus.services import answer_report_writer as writer_module
from opscli.amazon_rufus.services.answer_report_publisher import AnswerReportPublisher, PublishedAnswerReport
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.shared.file_uploads import FileUploadClient, FileUploadError, FileUploadHttpError, FileUploadResult


def test_default_publisher_uploads_utf8_bom_report(monkeypatch, tmp_path):
    """默认发布的中文报告携带 BOM，正文内容保持不变。"""
    monkeypatch.chdir(tmp_path)
    data = {
        "asin": "B0TEST1234",
        "country": "US",
        "questions": ["这个商品适合送礼吗？"],
        "answers": [{"text": "适合送礼", "isSuccess": True}],
    }
    plain_path = AnswerReportWriter().write(data, output_dir=tmp_path / "plain")

    class CheckingFileUploadClient:
        def upload(self, path, **kwargs):
            assert path.read_bytes() == codecs.BOM_UTF8 + plain_path.read_bytes()
            assert "优化诊断报告" in path.read_text(encoding="utf-8-sig")
            return FileUploadResult(url="https://files.example/report.md", raw={})

    result = AnswerReportPublisher(file_upload_client=CheckingFileUploadClient()).publish(data)
    assert result.path.read_bytes().startswith(codecs.BOM_UTF8)
    assert not plain_path.read_bytes().startswith(codecs.BOM_UTF8)


def test_report_publisher_uploads_exact_written_path_with_safe_metadata(tmp_path: Path):
    report_path = tmp_path / "B0TEST1234-20260904-120805.md"
    captured = {}

    class DummyWriter:
        def write(self, data: dict) -> Path:
            report_path.write_text("# report", encoding="utf-8")
            return report_path

    class DummyFileUploadClient:
        def upload(self, path: Path, **kwargs) -> FileUploadResult:
            captured["path"] = path
            captured["kwargs"] = kwargs
            return FileUploadResult(url="https://files.example/report.md", raw={"secret": "ignored"})

    result = AnswerReportPublisher(
        writer=DummyWriter(),
        file_upload_client=DummyFileUploadClient(),
    ).publish(
        {
            "asin": "b0test1234",
            "country": "us",
            "question_count": 1,
            "questions": ["这个商品适合送礼吗？"],
            "answers": [{"text": "适合"}],
            "seed_request": {"request_headers": {"cookie": "hidden"}},
        }
    )

    assert result == PublishedAnswerReport(path=report_path, url="https://files.example/report.md")
    assert captured == {
        "path": report_path,
        "kwargs": {
            "purpose": "amazon_rufus_report",
            "folder": "amazon-rufus/reports",
            "filename": report_path.name,
            "metadata": {
                "asin": "B0TEST1234",
                "country": "US",
                "question_count": 1,
                "answer_count": 1,
                "format": "markdown",
            },
        },
    }
    assert "public" not in captured["kwargs"]


def test_report_publisher_wraps_upload_error_and_keeps_local_report(tmp_path: Path):
    report_path = tmp_path / "B0TEST1234-20260904-120805.md"

    class DummyWriter:
        def write(self, data: dict) -> Path:
            report_path.write_text("# report", encoding="utf-8")
            return report_path

    class FailingFileUploadClient:
        def upload(self, path: Path, **kwargs) -> FileUploadResult:
            raise RuntimeError("upstream secret response")

    publisher = AnswerReportPublisher(
        writer=DummyWriter(),
        file_upload_client=FailingFileUploadClient(),
    )

    with pytest.raises(RufusReportUploadError) as exc_info:
        publisher.publish({"asin": "B0TEST1234", "country": "US", "answers": []})

    assert report_path.exists()
    assert exc_info.value.report_path == report_path
    assert exc_info.value.to_dict() == {
        "code": "RUFUS_REPORT_UPLOAD_ERROR",
        "message": "Rufus 报告上传失败，已保留本地文件",
        "report_path": report_path.as_posix(),
        "upload_error": {
            "type": "RuntimeError", "code": None, "http_status": None,
            "business_code": None, "message": "文件上传发生未预期异常，原始消息已隐藏",
        },
    }
    assert "upstream secret response" not in str(exc_info.value)


@pytest.mark.parametrize("status,payload,error_type,business_code,message", [
    (403, {"code": "UPLOAD_DENIED", "message": "没有文件上传权限"}, "FileUploadHttpError", "UPLOAD_DENIED", "没有文件上传权限"),
    (200, {"code": 40001, "message": "文件类型不支持"}, "FileUploadBusinessError", 40001, "文件类型不支持"),
    (400, {"message": "Authorization: Bearer secret-value"}, "FileUploadHttpError", None, "远端错误消息可能包含敏感信息，已隐藏"),
])
def test_publisher_returns_safe_api_error_details(monkeypatch, tmp_path, status, payload, error_type, business_code, message):
    """通过真实上传客户端解析响应，再验证发布层的错误契约。"""
    monkeypatch.chdir(tmp_path)

    class DummyAuth:
        def build_request_auth(self, alias):
            return {}, {}

    monkeypatch.setattr("opscli.shared.file_uploads.httpx.post", lambda *args, **kwargs: httpx.Response(status, json=payload))
    publisher = AnswerReportPublisher(file_upload_client=FileUploadClient(auth_client=DummyAuth()))
    with pytest.raises(RufusReportUploadError) as caught:
        publisher.publish({"asin": "B0TEST1234", "answers": []})
    result = caught.value.to_dict()
    assert caught.value.report_path.exists()
    assert result["upload_error"] == {
        "type": error_type,
        "code": "FILE_UPLOAD_HTTP_ERROR" if status >= 400 else "FILE_UPLOAD_BUSINESS_ERROR",
        "http_status": status, "business_code": business_code, "message": message,
    }
    assert "report_url" not in result


@pytest.mark.parametrize("secret_message", [
    'Cookie: polarisUserToken=private-value; other=other-value',
    '{"headers": {"X-MCP-API-Key": "private-value"}}',
    'https://oss.example/report.md?Signature=private-value',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0.signature',
    'password=private-value',
])
def test_upload_error_hides_sensitive_messages(secret_message):
    """响应中的凭证、签名链接和请求转储不进入公开错误消息。"""
    from opscli.amazon_rufus.services.answer_report_publisher import _upload_error_details
    details = _upload_error_details(FileUploadHttpError(403, secret_message))
    assert details["http_status"] == 403
    assert details["message"] == "远端错误消息可能包含敏感信息，已隐藏"


@pytest.mark.parametrize("cause,expected", [
    (httpx.ReadTimeout("private transport data"), "文件上传请求超时"),
    (httpx.ConnectError("private transport data"), "文件上传网络连接失败"),
])
def test_upload_error_preserves_wrapped_network_type(cause, expected):
    """重试层包装后仍能区分超时和网络错误，不返回原始连接信息。"""
    from opscli.amazon_rufus.services.answer_report_publisher import _upload_error_details
    wrapped = FileUploadError("sensitive endpoint")
    wrapped.__cause__ = cause
    result = _upload_error_details(wrapped)
    assert result["type"] == type(cause).__name__
    assert result["message"] == expected
    assert result["http_status"] is None


def test_upload_error_preserves_auth_type():
    """鉴权失败保留类型，但不返回可能携带凭证的原始文本。"""
    from opscli.auth.exceptions import NotAuthenticatedError
    from opscli.amazon_rufus.services.answer_report_publisher import _upload_error_details
    details = _upload_error_details(NotAuthenticatedError("session_id=private-value"))
    assert details["type"] == "NotAuthenticatedError"
    assert details["message"] == "OPS 上传鉴权失败，请检查登录状态或凭证"


def test_report_publisher_keeps_same_second_concurrent_reports_isolated(monkeypatch, tmp_path: Path):
    """同一 ASIN 的并发请求必须写入并上传各自的报告。"""

    class FixedDatetime:
        @classmethod
        def now(cls) -> RealDatetime:
            return RealDatetime(2026, 9, 4, 12, 8, 5)

    class MarkerFormatter:
        def format_data(self, data: dict) -> str:
            return data["marker"]

    class CoordinatedFileUploadClient:
        def __init__(self) -> None:
            self.barrier = threading.Barrier(2)
            self.lock = threading.Lock()
            self.uploaded_contents: dict[Path, str] = {}

        def upload(self, path: Path, **kwargs) -> FileUploadResult:
            self.barrier.wait(timeout=5)
            content = path.read_text(encoding="utf-8")
            with self.lock:
                self.uploaded_contents[path] = content
            return FileUploadResult(url=f"https://files.example/{path.name}", raw={})

    monkeypatch.setattr(writer_module, "datetime", FixedDatetime)
    monkeypatch.chdir(tmp_path)
    upload_client = CoordinatedFileUploadClient()
    publisher = AnswerReportPublisher(
        writer=AnswerReportWriter(formatter=MarkerFormatter(), unique_filenames=True),
        file_upload_client=upload_client,
    )

    def publish(marker: str) -> PublishedAnswerReport:
        return publisher.publish(
            {
                "asin": "B0TEST1234",
                "country": "US",
                "marker": marker,
                "answers": [],
            }
        )

    markers = ["first request", "second request"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(publish, markers))

    assert reports[0].path != reports[1].path
    for marker, report in zip(markers, reports, strict=True):
        assert upload_client.uploaded_contents[report.path] == marker
        assert report.url.endswith(report.path.name)
