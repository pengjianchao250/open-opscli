"""skills 模块异常定义。

统一封装对外错误对象，保证 CLI JSON 输出结构稳定。
"""

from __future__ import annotations


class SkillsError(Exception):
    """skills 模块统一异常基类。"""

    def to_dict(self) -> dict[str, object]:
        """转换为稳定的错误对象，便于 CLI 直接输出 JSON。"""
        return {
            "type": self.__class__.__name__,
            "message": str(self),
        }


class SkillRemoteError(SkillsError):
    """远端 Skill 接口异常。"""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        """输出附带远端定位信息的错误对象。"""
        payload = super().to_dict()
        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


def error_to_dict(exc: Exception) -> dict[str, object]:
    """将任意异常转换为稳定的错误对象。"""
    if isinstance(exc, SkillsError):
        return exc.to_dict()
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
