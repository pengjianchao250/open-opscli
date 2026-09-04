"""Amazon Rufus 答案报告发布服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opscli.amazon_rufus.domain.exceptions import RufusReportUploadError
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.shared.file_uploads import FileUploadClient


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
        self.writer = writer or AnswerReportWriter(unique_filenames=True)
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
            raise RufusReportUploadError(report_path) from exc
        return PublishedAnswerReport(path=report_path, url=upload_result.url)
