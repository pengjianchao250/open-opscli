"""远端交互异常基类。

为 query、amazon 等模块的远端异常提供统一的序列化接口和
基础结构，消除各模块对 to_dict() / code / message 字段的重复实现。
"""
from __future__ import annotations


class RemoteError(Exception):
    """远端交互异常基类，提供统一 to_dict() 序列化。

    所有与远端服务交互的模块异常（如 QueryError、AmazonError）
    可继承此类获得 code + message 的标准化结构和 to_dict() 方法。
    子类只需覆盖类属性 code 即可。
    """

    code = "REMOTE_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的字典结构。"""
        return {
            "code": self.code,
            "message": self.message,
        }