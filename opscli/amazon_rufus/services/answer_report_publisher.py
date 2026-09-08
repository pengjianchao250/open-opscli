"""Amazon Rufus 答案报告发布服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from opscli.amazon_rufus.domain.exceptions import RufusReportUploadError
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.auth.exceptions import AuthError
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


def _upload_error_details(exc: Exception) -> dict:
    """只返回可诊断的错误字段，敏感消息整体隐藏，不复制原始响应。"""
    cause = exc
    for _ in range(10):
        if isinstance(cause, (httpx.TransportError, AuthError)) or cause.__cause__ is None:
            break
        cause = cause.__cause__
    if isinstance(cause, httpx.TimeoutException):
        message = "文件上传请求超时"
    elif isinstance(cause, httpx.TransportError):
        message = "文件上传网络连接失败"
    elif isinstance(cause, AuthError):
        message = "OPS 上传鉴权失败，请检查登录状态或凭证"
    elif isinstance(exc, FileUploadError):
        # 共享上传异常已过滤敏感消息，CLI/MCP 不再重复处理原始响应。
        message = str(exc)
    else:
        message = "文件上传发生未预期异常，原始消息已隐藏"
    return {
        "type": type(cause if isinstance(cause, (httpx.TransportError, AuthError)) else exc).__name__,
        "code": exc.code if isinstance(exc, FileUploadError) else None,
        "http_status": getattr(exc, "status_code", None) if isinstance(exc, FileUploadError) else None,
        "business_code": getattr(exc, "business_code", None) if isinstance(exc, FileUploadError) else None,
        "message": message,
    }


@dataclass(frozen=True)
class PublishedAnswerReport:
    """已写入并上传的 Rufus 答案报告。"""

    path: Path
    url: str


class AnswerReportPublisher:
    """写入 Rufus 报告并上传本次生成的文件。"""

    def __init__(
        self,
        writer: AnswerReportWriter | None = None,
        file_upload_client: FileUploadClient | None = None,
    ) -> None:
        # OSS 不保留 charset 参数，使用 BOM 让中文报告自带 UTF-8 编码标识。
        self.writer = writer or AnswerReportWriter(unique_filenames=True, encoding="utf-8-sig")
        self.file_upload_client = file_upload_client or FileUploadClient()

    def publish(self, data: dict) -> PublishedAnswerReport:
        """写入报告、上传确切路径并返回本地路径和远端地址。"""
        report_path = self.writer.write(data)
        answers = data.get("answers")
        questions = data.get("questions")
        question_count = data.get("question_count")
        metadata = {
            "asin": str(data.get("asin") or "").strip().upper(),
            "country": str(data.get("country") or "").strip().upper(),
            "question_count": question_count if question_count is not None else len(questions or []),
            "answer_count": len(answers) if isinstance(answers, list) else 0,
            "format": "markdown",
        }
        try:
            upload_result = self.file_upload_client.upload(
                report_path,
                purpose="amazon_rufus_report",
                folder="amazon-rufus/reports",
                filename=report_path.name,
                metadata=metadata,
            )
        except Exception as exc:
            raise RufusReportUploadError(report_path, upload_error=_upload_error_details(exc)) from exc
        return PublishedAnswerReport(path=report_path, url=upload_result.url)
