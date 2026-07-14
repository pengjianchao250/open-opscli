"""FeedTask 工具模块。

将 opscli feedtask 子模块的核心能力暴露为 MCP 工具：
- feedtask_create   — 创建工单（通用）
- feedtask_status   — 查询工单状态/详情

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _feedtask_manager, _ok


async def feedtask_create(
    payload: dict,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """创建工单（通用接口，接受完整的 createCustomTask payload）。

    Args:
        payload:    完整的 createCustomTask 请求体
        session_id: 可选，OAuth 授权后的 Session ID（为空则自动加载本地保存的）
        jwt:        可选，已有 JWT（为空则自动加载本地缓存的）
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        result = _feedtask_manager(jwt=jw, session_id=sid).create(payload)
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


async def feedtask_status(
    task_id: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """查询工单状态/详情。

    Args:
        task_id:    工单 ID
        session_id: 可选，OAuth 授权后的 Session ID
        jwt:        可选，已有 JWT
    """
    from opscli.mcp.tools.helpers import _get_auth_pair

    sid, jw = _get_auth_pair("polaris", session_id, jwt)
    if not sid:
        return _err(ValueError("无 session_id：请完成 polaris 授权登录"))
    try:
        result = _feedtask_manager(jwt=jw, session_id=sid).get_detail(task_id)
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    feedtask_create,
    feedtask_status,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 feedtask_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
