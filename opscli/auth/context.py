"""显式凭证上下文（显式授权中间件核心）。

承载用户通过命令行显式传入的授权凭证，供全部子命令统一消费：
- ``session_id``：登录会话 ID，显式模式下为必填；缺少某系统 JWT 时用它向后端换取
- ``ops_jwt`` / ``polaris_jwt``：ops 与 polaris 两个业务系统各自的 JWT（可选）

设计要点（安全）：
- 采用 ``contextvars.ContextVar`` 存储，具备"请求级、进程内"特性，
  与 MCP 侧 ``get_mcp_request_headers`` 的上下文机制保持一致；
- **绝不落盘**：显式凭证只存活于当前进程调用期间，不写入本机 ``CredentialStore``，
  避免污染当前登录用户的持久化凭证。

典型写入方：CLI 入口 argv 预解析（``opscli/cli.py`` 的 ``main``）。
典型读取方：``AuthClient.get_token`` / ``get_session``（单点注入，全命令自动生效）。
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class ExplicitCredentials:
    """用户显式传入的一组授权凭证（不可变）。

    Attributes:
        session_id:  登录会话 ID（显式模式必填）
        ops_jwt:     ops 系统 JWT，未显式提供时为 None（回退用 session 换取）
        polaris_jwt: polaris 系统 JWT，未显式提供时为 None（回退用 session 换取）
    """

    session_id: str
    ops_jwt: str | None = None
    polaris_jwt: str | None = None

    def jwt_for(self, alias: str) -> str | None:
        """按系统别名返回对应的显式 JWT，未提供或别名未知时返回 None。

        Args:
            alias: 系统别名，当前支持 "ops" 与 "polaris"

        Returns:
            对应系统的 JWT 字符串，或 None
        """
        if alias == "ops":
            return self.ops_jwt
        if alias == "polaris":
            return self.polaris_jwt
        return None


# 进程内请求级上下文变量：默认 None 表示未启用显式凭证模式（走本地存储常规流程）
_explicit_credentials: contextvars.ContextVar["ExplicitCredentials | None"] = (
    contextvars.ContextVar("opscli_explicit_credentials", default=None)
)


def set_explicit_credentials(creds: "ExplicitCredentials | None") -> None:
    """设置当前上下文的显式凭证；传入 None 表示清除（回退本地存储流程）。"""
    _explicit_credentials.set(creds)


def get_explicit_credentials() -> "ExplicitCredentials | None":
    """读取当前上下文的显式凭证，未设置时返回 None。"""
    return _explicit_credentials.get()
