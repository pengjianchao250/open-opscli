"""`opscli app` 的稳定异常类型。"""

from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        fix_hint: str | None = None,
        request_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix_hint = fix_hint
        self.request_id = request_id
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "fix_hint": self.fix_hint,
            "request_id": self.request_id,
            "detail": self.detail or None,
        }


class AppProjectError(AppError):
    """本地目录或站点绑定不满足命令要求。"""


class AppGitError(AppError):
    """Git 初始化、提交或推送失败。"""


class GitUnavailableError(AppGitError):
    """本机未安装可用版本的 Git。"""


class AppHubHttpError(AppError):
    """AppHub 创建站点请求失败。"""
