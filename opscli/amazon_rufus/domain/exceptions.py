"""Amazon Rufus 异常定义。"""

from __future__ import annotations

from pathlib import Path


class RufusError(Exception):
    """Rufus 模块基础异常。"""

    code = "RUFUS_ERROR"

    def to_dict(self) -> dict:
        """转换为稳定 JSON 错误结构。"""
        return {"code": self.code, "message": str(self)}


class QuestionBankNotReadyError(RufusError):
    """题库尚未安装或升级。"""

    code = "QUESTION_BANK_NOT_READY"


class InvalidQuestionError(RufusError):
    """用户传入的问题参数无效。"""

    code = "INVALID_QUESTION"


class InvalidRufusCookieError(RufusError):
    """用户传入的 Cookie 参数无效。"""

    code = "INVALID_RUFUS_COOKIE"


class InvalidRufusCurlError(RufusError):
    """用户传入的 Rufus cURL 参数无效。"""

    code = "INVALID_RUFUS_CURL"


class InvalidRufusPlatformError(RufusError):
    """用户传入的平台 Cookie 参数无效。"""

    code = "INVALID_RUFUS_PLATFORM"


class InvalidRufusBrowserStateError(RufusError):
    """用户 Amazon 浏览器状态无效。"""

    code = "INVALID_RUFUS_BROWSER_STATE"


class ChromeCdpUnavailableError(RufusError):
    """Chrome CDP 端点不可用。"""

    code = "CHROME_CDP_UNAVAILABLE"


class SeedRequestNotCapturedError(RufusError):
    """未捕获到 Rufus seed request。"""

    code = "SEED_REQUEST_NOT_CAPTURED"


class RufusSecretNotReadyError(RufusError):
    """Rufus 后端请求凭证尚未准备好。"""

    code = "RUFUS_SECRET_NOT_READY"


class HeadlessRufusCaptureError(RufusError):
    """Rufus headless 捕获失败。"""

    code = "RUFUS_HEADLESS_CAPTURE_ERROR"


class HeadlessRufusRequestError(RufusError):
    """Rufus headless 请求失败。"""

    code = "RUFUS_HEADLESS_REQUEST_ERROR"


class RufusReportUploadError(RufusError):
    """Rufus 报告上传失败，本地文件仍然保留。"""

    code = "RUFUS_REPORT_UPLOAD_ERROR"

    def __init__(self, report_path: str | Path, *, upload_error: dict | None = None) -> None:
        super().__init__("Rufus 报告上传失败，已保留本地文件")
        self.report_path = Path(report_path)
        self.upload_error = upload_error

    def to_dict(self) -> dict:
        """返回包含本地报告路径的稳定错误结构。"""
        payload = super().to_dict()
        payload["report_path"] = self.report_path.as_posix()
        if self.upload_error is not None:
            payload["upload_error"] = self.upload_error
        return payload


class RufusReportContentError(RufusError):
    """Rufus 报告正文校验未通过：保留本地文件供排查，但不上传、不视为成功。

    RENDER_LOSS：有正文的题在报告里全部找不到（只剩链接和占位的空壳），是报告渲染问题，改写问题重试无效；
    只有部分题找不到时不抛错，由发布结果告警；
    EMPTY_CONTENT：所有题都没有拿到答案正文（Rufus 返回为空、只有商品链接或只是占位内容），
    可结合 answer_error_reasons 中每题的 error_reason 区分空答与拒答，按回答质量规则改写重试。
    """

    RENDER_LOSS = "RUFUS_REPORT_RENDER_LOSS"
    EMPTY_CONTENT = "RUFUS_REPORT_EMPTY_CONTENT"
    code = EMPTY_CONTENT

    def __init__(
        self,
        code: str,
        report_path: str | Path,
        *,
        lost_question_indexes: tuple[int, ...] | list[int] = (),
        empty_question_indexes: tuple[int, ...] | list[int] = (),
        answer_error_reasons: list[str] | None = None,
    ) -> None:
        if code == self.RENDER_LOSS:
            lost = "、".join(str(index) for index in lost_question_indexes)
            message = f"Rufus 报告渲染丢失了全部答案正文（第 {lost} 题），已保留本地文件但未上传；这是报告渲染问题，不要改写问题重试"
        else:
            message = "Rufus 所有题都没有返回答案正文（回答为空、只有商品链接或只是占位内容），报告已保留在本地但未上传"
        super().__init__(message)
        self.code = code
        self.report_path = Path(report_path)
        self.lost_question_indexes = list(lost_question_indexes)
        self.empty_question_indexes = list(empty_question_indexes)
        # 按题序保存 Rufus 回答的 errorReason（如 empty_answer、shopping_scope_refusal），空串表示未标记原因
        self.answer_error_reasons = list(answer_error_reasons or [])

    def to_dict(self) -> dict:
        """返回包含本地报告路径、丢失/无正文题号与每题 error_reason 的稳定错误结构。"""
        payload = super().to_dict()
        payload["report_path"] = self.report_path.as_posix()
        payload["lost_question_indexes"] = self.lost_question_indexes
        payload["empty_question_indexes"] = self.empty_question_indexes
        payload["answer_error_reasons"] = [
            {"question_index": index, "error_reason": reason}
            for index, reason in enumerate(self.answer_error_reasons, start=1)
        ]
        return payload


class RufusAnswerValidationError(RufusError):
    """Rufus 回答未通过完整性校验。"""

    code = "RUFUS_ANSWER_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        question_index: int | None = None,
        question: str | None = None,
        reason: str | None = None,
        attempt_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.question_index = question_index
        self.question = question
        self.reason = reason
        self.attempt_count = attempt_count

    def to_dict(self) -> dict:
        payload = super().to_dict()
        if self.question_index is not None:
            payload["question_index"] = self.question_index
        if self.question:
            payload["question"] = self.question
        if self.reason:
            payload["reason"] = self.reason
        if self.attempt_count is not None:
            payload["attempt_count"] = self.attempt_count
        return payload


class RufusReplayError(RufusError):
    """Rufus 重放失败。"""

    code = "RUFUS_REPLAY_ERROR"


class UnsupportedMarketplaceError(RufusError):
    """不支持的国家站点。"""

    code = "UNSUPPORTED_MARKETPLACE"


class RufusRemoteHttpError(RufusError):
    """Rufus 远端 HTTP 请求失败。"""

    code = "RUFUS_REMOTE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RufusPlatformCookieAuthError(RufusError):
    """OPS 平台 Cookie API 鉴权失败。"""

    code = "RUFUS_PLATFORM_COOKIE_AUTH_ERROR"

    def __init__(
        self,
        message: str = "OPS 平台 Cookie 接口未授权，请先刷新 OPS/MCP 认证；这不是亚马逊 Rufus 登录态缺失。",
        status_code: int = 401,
    ):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        """转换为包含 HTTP 状态码的稳定 JSON 错误结构。"""
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class RufusRemoteBusinessError(RufusError):
    """Rufus 远端业务错误。"""

    code = "RUFUS_REMOTE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class RufusBadRemoteJsonError(RufusError):
    """Rufus 远端返回非法 JSON。"""

    code = "RUFUS_BAD_REMOTE_JSON"
