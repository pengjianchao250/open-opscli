"""AppHub 发布链的稳定异常类型。"""

from __future__ import annotations


class AppError(Exception):
    """所有 app 命令可预期错误的基类。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        fix_hint: str | None = None,
        request_id: str | None = None,
        release_id: int | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix_hint = fix_hint
        self.request_id = request_id
        self.release_id = release_id
        self.detail = detail or {}

    def to_dict(self) -> dict:
        """转换为不包含凭据的稳定错误结构。"""
        return {
            "code": self.code,
            "message": self.message,
            "fix_hint": self.fix_hint,
            "request_id": self.request_id,
            "release_id": self.release_id,
            "detail": self.detail or None,
        }


class AppProjectError(AppError):
    """项目目录或 manifest 不满足发布要求。"""


class AppManifestError(AppProjectError):
    """app.yaml 内容不合法。"""


class AppRuntimeUnsupportedError(AppProjectError):
    """AppHub 当前不支持项目运行时。"""


class AppValidationError(AppProjectError):
    """本地规范校验存在阻断问题。"""


class AppGitError(AppError):
    """Git 前置条件或命令失败。"""


class GitUnavailableError(AppGitError):
    """Git 未安装或版本过低。"""


class GitCredentialError(AppGitError):
    """Git 凭据不存在或不可用。"""


class GitNonFastForwardError(AppGitError):
    """本地和远端分支已经分叉。"""


class AppHubHttpError(AppError):
    """AppHub HTTP 请求失败。"""


class AppHubBusinessError(AppError):
    """AppHub 发布流返回业务失败终态。"""


class AppHubProtocolError(AppError):
    """AppHub SSE 或响应结构违反协议。"""


class PublishInterruptedError(AppError):
    """发布流中断，可使用句柄续订。"""
