"""MCP 工具权限过滤中间件。

按当前用户的角色权限（由 OPS 后端计算）过滤 MCP 工具：
- on_list_tools：无权限的工具直接从工具列表中隐藏（减少 AI Agent 的上下文开销）
- on_call_tool：拦截越权调用（防止绕过 list_tools 直接调用）

全局管控开关：后端响应附带 permission_enabled 字段（来自 auto-scheduler 的
config('opscli.tool_permission_enabled')）。显式为 False 时表示后端未开启管控，
本端直接全量放行；字段缺失（旧后端，None）时维持按 allowed_tools 过滤的原有行为。

三种运行模式的权限来源（自动探测，无需启动参数）：
1. HTTP/SSE 远程校验模式：ApiKeyAuthMiddleware 调用 /v1/mcp/verify-key 时
   后端已返回 allowed_tools / permission_enabled，随用户信息注入请求上下文（contextvar/scope）
2. HTTP/SSE 固定 API Key 模式 / 旧后端：上下文中 allowed_tools 为 None
   → 全量放行（保持向后兼容，不破坏单用户部署）
3. stdio 本地模式：无 API Key，读取本地 CredentialStore 的 session_id，
   调用 GET /v1/mcp/allowed-tools 查询（结果缓存 5 分钟）

stdio 模式网络兜底策略：
- 404（旧后端未部署该端点）→ 全量放行（灰度兼容）
- 401（session 失效）→ 仅基础安全工具（用户仍可登录或读取 Dashboard 静态规范）
- 网络异常 → 有过期旧缓存则沿用旧值，否则仅基础安全工具（fail-closed，
  避免断网绕过权限；其他工具本身也依赖后端，离线时锁死代价低）
"""

from __future__ import annotations

import logging
import time

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

_logger = logging.getLogger("opscli.mcp.permissions")

# 基础 auth 工具白名单：无论权限如何配置始终可用，否则用户无法完成登录授权流程。
# 注意：必须与后端 auto-scheduler 的 McpToolPermissionService::BASE_AUTH_TOOLS 保持一致，双端同步维护。
BASE_AUTH_TOOLS: frozenset[str] = frozenset({
    "auth_login_start",
    "auth_login_poll",
    "auth_mcp_login",
    "auth_check_token",
    "auth_is_authenticated",
    "auth_logout",
    "auth_doctor",
    "auth_get_token",
    "auth_token_refresh",
    "auth_build_request_auth",
    "auth_system_list",
    "auth_system_sync",
    "auth_system_add",
    "auth_system_remove",
})

# Dashboard 规范工具只读取包内静态 Skill，不依赖登录态或用户业务数据。
BASE_DASHBOARD_SPEC_TOOLS: frozenset[str] = frozenset({
    "dashboard_ai_bridge_spec_must_read",
    "dashboard_data_analysis_spec_must_read",
})

BASE_ALWAYS_ALLOWED_TOOLS = BASE_AUTH_TOOLS | BASE_DASHBOARD_SPEC_TOOLS
"""未登录或权限接口不可用时仍可调用的基础安全工具。"""

# stdio 模式权限结果缓存时间（秒）：与后端 60s 缓存叠加，权限变更最长约 6 分钟生效
_STDIO_CACHE_TTL_SECONDS = 300

# stdio 模式缓存：(过期时间戳, 工具名集合或 None)；None 表示全量放行
_stdio_cache: tuple[float, frozenset[str] | None] | None = None


def invalidate_stdio_cache() -> None:
    """清空 stdio 模式的权限缓存。

    登录/登出后调用，使新登录用户的权限立即生效（否则需等缓存过期）。
    """
    global _stdio_cache
    _stdio_cache = None


async def _resolve_allowed_tools() -> frozenset[str] | None:
    """解析当前请求允许使用的工具名集合。

    Returns:
        工具名集合（已并入基础 auth 白名单），或 None 表示全量放行
    """
    from opscli.mcp.context import get_current_api_key, mcp_request_ctx
    from opscli.mcp.context import _get_scope_from_mcp_request_ctx

    # ── HTTP/SSE 模式：上下文中存在 API Key ──────────────────────────
    if get_current_api_key():
        # 双重读取：优先 contextvar，降级读 POST 请求 scope（SSE 模式下 contextvar 可能丢失）
        allowed: list | None = None
        permission_enabled: bool | None = None
        ctx = mcp_request_ctx.get()
        if ctx:
            allowed = ctx.get("allowed_tools")
            permission_enabled = ctx.get("permission_enabled")
        if allowed is None:
            scope = _get_scope_from_mcp_request_ctx()
            if scope:
                allowed = scope.get("mcp_allowed_tools")
                if permission_enabled is None:
                    permission_enabled = scope.get("mcp_permission_enabled")

        # 后端显式关闭权限管控（permission_enabled=False）→ 全量放行
        if permission_enabled is False:
            return None
        if allowed is None:
            # 固定 API Key 模式 / 旧后端（verify-key 响应无 allowed_tools 字段）→ 全量放行
            return None
        return frozenset(allowed) | BASE_ALWAYS_ALLOWED_TOOLS

    # ── stdio 模式：无 API Key，按本地登录用户查询 ──────────────────
    return await _stdio_allowed_tools()


async def _stdio_allowed_tools() -> frozenset[str] | None:
    """stdio 模式下查询当前登录用户的工具白名单（带缓存与网络兜底）。

    Returns:
        工具名集合，或 None 表示全量放行（旧后端兼容）
    """
    global _stdio_cache

    now = time.time()
    if _stdio_cache and _stdio_cache[0] > now:
        return _stdio_cache[1]

    # 读取本地默认凭证（stdio 模式与 CLI 共用同一份登录态）
    from opscli.mcp.tools.helpers import _get_session_id

    session_id = _get_session_id()
    if not session_id:
        # 未登录：只开放基础 auth 工具引导用户完成登录
        result: frozenset[str] | None = BASE_ALWAYS_ALLOWED_TOOLS
        _stdio_cache = (now + _STDIO_CACHE_TTL_SECONDS, result)
        return result

    try:
        import httpx

        from opscli.auth.config import get_ops_url

        url = f"{get_ops_url().rstrip('/')}/v1/mcp/allowed-tools"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"X-Session-Id": session_id},
                timeout=10,
            )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                if data.get("permission_enabled") is False:
                    # 后端关闭权限管控 → 全量放行
                    result = None
                else:
                    result = (
                        frozenset(data.get("allowed_tools") or [])
                        | BASE_ALWAYS_ALLOWED_TOOLS
                    )
            else:
                result = BASE_ALWAYS_ALLOWED_TOOLS
        elif resp.status_code == 404:
            # 旧后端未部署 allowed-tools 端点 → 全量放行（灰度兼容）
            result = None
        elif resp.status_code == 401:
            # session 失效 → 仅基础安全工具，引导重新登录或读取 Dashboard 静态规范
            result = BASE_ALWAYS_ALLOWED_TOOLS
        else:
            # 其他异常状态码按网络异常处理
            raise RuntimeError(f"allowed-tools 返回异常状态码 {resp.status_code}")

        _stdio_cache = (now + _STDIO_CACHE_TTL_SECONDS, result)
        return result
    except Exception as exc:
        _logger.warning("stdio 模式查询 MCP 工具权限失败: %s", exc)
        if _stdio_cache:
            # 有过期旧缓存则沿用（stale-while-error），并续期避免每次请求都重试网络
            stale = _stdio_cache[1]
            _stdio_cache = (now + _STDIO_CACHE_TTL_SECONDS, stale)
            return stale
        # 从未成功过 → fail-closed，仅开放基础 auth 工具
        return BASE_ALWAYS_ALLOWED_TOOLS


class ToolPermissionMiddleware(Middleware):
    """MCP 工具权限中间件：列表过滤 + 调用拦截。"""

    async def on_list_tools(self, context, call_next):
        """过滤工具列表：无权限的工具直接隐藏，不进入 AI Agent 上下文。"""
        tools = await call_next(context)
        allowed = await _resolve_allowed_tools()
        if allowed is None:
            return tools
        return [tool for tool in tools if tool.name in allowed]

    async def on_call_tool(self, context, call_next):
        """拦截越权工具调用（防止绕过 list_tools 直接按名调用）。"""
        allowed = await _resolve_allowed_tools()
        tool_name = context.message.name
        if allowed is not None and tool_name not in allowed:
            raise ToolError(
                f"无权限调用工具 {tool_name}：当前账号的角色未开通该工具，请联系管理员配置 MCP 工具权限"
            )
        return await call_next(context)
