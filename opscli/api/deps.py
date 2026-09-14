"""REST 端点共享依赖（FastAPI Depends）。

业务内核与凭证解析仍复用 opscli.mcp.tools.helpers，使 MCP Tool 与 REST API
在同一进程内共享同一套鉴权（fixed / remote 两种模式自动生效）与同一业务实现。
helpers 在函数体内惰性导入，保持 api 模块导入轻量、避免循环依赖。
"""

from __future__ import annotations

import hashlib

from fastapi import Depends

from opscli.api.auth import AppHubPrincipal, require_apphub_principal
from opscli.config import CONFIG_DIR


def require_authenticated_user(
    principal: AppHubPrincipal = Depends(require_apphub_principal),
) -> str:
    """要求当前请求已解析出已验证账号，否则以 401 信封拒绝。

    身份只来自传输层已验证账号（remote 模式的 transport 邮箱 / fixed 模式的
    API Key 隔离凭证缓存），不接受请求体里的自报身份。
    """
    return principal.email


def build_query_manager(timeout: float | None = None):
    """按当前请求的隔离凭证构造 QueryManager（同步业务内核，需放线程池执行）。

    Args:
        timeout: 查询执行接口的 HTTP 超时秒数，None 时用 QueryClient 默认值。
    """
    from opscli.mcp.context import get_current_jwt, get_current_session_id
    from opscli.mcp.tools.helpers import _query_manager

    return _query_manager(
        jwt=get_current_jwt(),
        session_id=get_current_session_id(),
        timeout=timeout,
    )


def get_credential_dir():
    """当前请求对应的凭证隔离目录（规划器元数据缓存的 base_dir）。"""
    from opscli.mcp.context import get_current_user_email

    email = str(get_current_user_email() or "anonymous").strip().lower()
    scope = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return CONFIG_DIR / "api_users" / scope
