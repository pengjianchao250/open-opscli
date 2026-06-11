"""Amazon Rufus 异常定义。"""

from __future__ import annotations


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
