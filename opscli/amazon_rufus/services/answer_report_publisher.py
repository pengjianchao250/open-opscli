"""Amazon Rufus 答案报告发布服务。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from opscli.amazon_rufus.domain.exceptions import RufusReportContentError, RufusReportUploadError
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.report_validator import AnswerReportFidelityChecker, skeleton_report_data
from opscli.auth.exceptions import AuthError
from opscli.shared.file_uploads import FileUploadClient, FileUploadError

logger = logging.getLogger(__name__)


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
    # 以下两类题号仍算发布成功，但 CLI/MCP 需显式告警（Bug 12136）
    # 输入中没有答案正文的题号
    empty_question_indexes: tuple[int, ...] = ()
    # 输入有正文、报告里疑似找不到的题号（只有部分题如此；全部丢失时直接报 RENDER_LOSS）
    render_loss_question_indexes: tuple[int, ...] = ()


def report_warning_fields(report: Any) -> dict:
    """部分题无正文或疑似渲染丢失时返回 CLI 与 MCP 共用的告警字段，否则返回空 dict。

    report_publisher 可由调用方注入替换，返回对象缺少这两个属性时按无告警处理。
    """
    fields: dict = {}
    messages: list[str] = []
    for key, template in (
        ("empty_question_indexes", "第 {} 题未获取到答案正文"),
        ("render_loss_question_indexes", "第 {} 题答案正文疑似在报告渲染中丢失"),
    ):
        indexes = list(getattr(report, key, ()) or ())
        if indexes:
            fields[key] = indexes
            messages.append(template.format("、".join(str(index) for index in indexes)))
    if messages:
        fields["warning"] = "；".join(messages)
    return fields


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
        """写入报告、校验正文保真后上传确切路径，返回本地路径、远端地址和需告警的题号。

        Raises:
            RufusReportContentError: 有正文的题在报告中全部丢失（RENDER_LOSS）或所有题都没有答案正文
                （EMPTY_CONTENT），本地文件保留供排查，不上传；只有部分题丢失时照常上传并返回告警题号。
            RufusReportUploadError: 上传失败，本地文件保留。
        """
        report_path = self.writer.write(data)
        # 上传前比对输入正文与落盘报告：过去只要文件写成功就判成功，空壳报告也会提示已保存（Bug 12136）。
        # 读落盘文件而不是复用格式化结果，校验的就是即将上传的字节；utf-8-sig 兼容带或不带 BOM 的写入器。
        answers = data.get("answers")
        # 用同一渲染器渲染清空正文的骨架报告，校验时剔除模板自己生成的行；
        # 注入的写入器没有 formatter、或骨架渲染失败时，退化为不剔除模板行的比对，不能因此让发布失败。
        formatter = getattr(self.writer, "formatter", None)
        skeleton_text = None
        if formatter is not None:
            try:
                skeleton_text = formatter.format_data(skeleton_report_data(data))
            except Exception as exc:
                logger.warning(
                    "Rufus 报告骨架渲染失败（%s），正文校验退化为不剔除模板行：report_path=%s",
                    type(exc).__name__,
                    report_path.as_posix(),
                )
        fidelity = AnswerReportFidelityChecker().check(
            answers,
            report_path.read_text(encoding="utf-8-sig"),
            skeleton_text=skeleton_text,
            question_count=len(data.get("questions") or []),
        )
        if fidelity.error_code:
            raise RufusReportContentError(
                fidelity.error_code,
                report_path,
                lost_question_indexes=fidelity.lost_question_indexes,
                empty_question_indexes=fidelity.empty_question_indexes,
                # 带上每题 errorReason，调用方据此区分 Rufus 空答、拒答与渲染丢失
                answer_error_reasons=[
                    str(answer.get("errorReason") or "") if isinstance(answer, dict) else ""
                    for answer in (answers if isinstance(answers, list) else [])
                ],
            )
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
        return PublishedAnswerReport(
            path=report_path,
            url=upload_result.url,
            empty_question_indexes=fidelity.empty_question_indexes,
            render_loss_question_indexes=fidelity.lost_question_indexes,
        )
