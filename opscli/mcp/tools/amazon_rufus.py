"""Amazon Rufus MCP 工具模块。

Rufus 获取能力由 MCP Tool 拥有，Skill 只保留题库数据与授权编排规则。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.types import ToolAnnotations

from opscli.amazon_rufus.constants import DEFAULT_RUFUS_TIMEOUT_SECONDS
from opscli.amazon_rufus.domain.mcp_models import (
    RufusGetRequest,
    RufusRemoteConsentRequest,
    RufusWatchLoginRequest,
)
from opscli.amazon_rufus.services.mcp_manager import RufusMcpManager

from .helpers import _err, _get_credential_dir, _ok


async def amazon_rufus_remote_consent_status(country: str) -> dict:
    """读取指定国家站点的 Rufus MCP/headless 授权偏好。

    Args:
        country: 国家站点代码，如 US、UK、DE、JP
    """
    try:
        data = await _run_mcp_manager("remote_consent_status", country=country)
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_remote_consent_status",
            exc,
            {"country": country},
        )


async def amazon_rufus_remote_consent_set(country: str, allowed: bool) -> dict:
    """保存指定国家站点的 Rufus MCP/headless 授权偏好。

    Args:
        country: 国家站点代码，如 US、UK、DE、JP
        allowed: 是否允许当前 MCP/headless 链路复用亚马逊 Rufus 登录态
    """
    try:
        data = await _run_mcp_manager(
            "remote_consent_set",
            request=RufusRemoteConsentRequest(country=country, allowed=allowed),
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_remote_consent_set",
            exc,
            {"country": country, "allowed": allowed},
        )


async def amazon_rufus_login_status(country: str) -> dict:
    """读取 Rufus 获取前可用的亚马逊 Rufus 登录态脱敏摘要。

    Args:
        country: 国家站点代码，如 US、UK、DE、JP
    """
    try:
        data = await _run_mcp_manager("login_status", country=country)
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_login_status",
            exc,
            {"country": country},
        )


async def amazon_rufus_watch_login(
    asin: str,
    country: str,
    timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
    chrome_path: str | None = None,
    launch_if_needed: bool = True,
    close_browser: bool = True,
) -> dict:
    """监听 Amazon 登录页并保存 Rufus streaming 请求种子。

    Args:
        asin: 目标 ASIN
        country: 国家站点代码，如 US、UK、DE、JP
        timeout_seconds: 等待用户登录和捕获 Rufus 请求的总超时秒数
        chrome_path: 可选，Chrome 可执行文件路径；仅自动发现失败时传入
        launch_if_needed: CDP 不可用时是否自动启动 Chrome
        close_browser: 采集完成后是否关闭本次由工具启动的调试浏览器
    """
    try:
        data = await _run_mcp_manager(
            "watch_login",
            request=RufusWatchLoginRequest(
                asin=asin,
                country=country,
                timeout_seconds=timeout_seconds,
                chrome_path=chrome_path,
                launch_if_needed=launch_if_needed,
                close_browser=close_browser,
            ),
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_watch_login",
            exc,
            {
                "asin": asin,
                "country": country,
                "timeout_seconds": timeout_seconds,
                "chrome_path_provided": bool(chrome_path),
                "launch_if_needed": launch_if_needed,
                "close_browser": close_browser,
            },
        )


async def amazon_rufus_logout(
    country: str,
    include_browser_profile: bool = True,
) -> dict:
    """清除指定国家站点的 Amazon/Rufus 登录态摘要。

    Args:
        country: 国家站点代码，如 US、UK、DE、JP
        include_browser_profile: 是否同时清除工具管理的 Chrome 调试 profile
    """
    try:
        data = await _run_mcp_manager(
            "logout",
            country=country,
            include_browser_profile=include_browser_profile,
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_logout",
            exc,
            {"country": country, "include_browser_profile": include_browser_profile},
        )


async def amazon_rufus_get(
    asin: str,
    country: str,
    question: str | None = None,
    questions: list[str] | None = None,
    skills_dir: str | None = None,
    timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
) -> dict:
    """获取指定 ASIN 的 Rufus 回答并写入本地报告。

    Args:
        asin: 目标 ASIN
        country: 国家站点代码，如 US、UK、DE、JP
        question: 可选，指定单题问题；为空时读取 Skill 默认题库
        questions: 可选，指定多题问题列表；传入后跳过 Skill 默认题库
        skills_dir: 可选，自定义 Skills 根目录
        timeout_seconds: Rufus 获取超时时间；默认按每题 180 秒计
    """
    try:
        data = await _run_mcp_manager(
            "get",
            request=RufusGetRequest(
                asin=asin,
                country=country,
                question=question,
                questions=questions,
                skills_dir=skills_dir,
                timeout_seconds=timeout_seconds,
            ),
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_get",
            exc,
            {
                "asin": asin,
                "country": country,
                "question": question,
                "questions": questions,
                "skills_dir": skills_dir,
            },
        )


async def amazon_rufus_platform_cookie_save(
    platform: str,
    country: str,
    content: str,
) -> dict:
    """通过 OPS 平台 Cookie 接口保存亚马逊 Rufus 登录态 content，不在响应中回显原文。

    Args:
        platform: 平台标识，如 amazon
        country: 国家站点代码，如 US、UK、DE、JP
        content: OPS 平台 Cookie 接口 content，当前规范直接承载 Rufus streaming cURL 命令态
    """
    try:
        data = await _run_mcp_manager(
            "platform_cookie_save",
            platform=platform,
            country=country,
            content=content,
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_platform_cookie_save",
            exc,
            {
                "platform": platform,
                "country": country,
                "content_provided": bool(str(content or "")),
                "content_length": len(str(content or "")),
            },
        )


async def amazon_rufus_platform_cookie_get(
    platform: str,
    country: str,
    include_content: bool = False,
) -> dict:
    """读取 OPS 平台 Cookie 接口 content，默认只返回脱敏摘要。

    Args:
        platform: 平台标识，如 amazon
        country: 国家站点代码，如 US、UK、DE、JP
        include_content: 是否显式返回完整 content，仅用于排障
    """
    try:
        data = await _run_mcp_manager(
            "platform_cookie_get",
            platform=platform,
            country=country,
            include_content=include_content,
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_platform_cookie_get",
            exc,
            {
                "platform": platform,
                "country": country,
                "include_content": include_content,
            },
        )


async def amazon_rufus_curl_save(
    asin: str,
    country: str,
    raw_curl: str,
) -> dict:
    """保存浏览器 Copy-as-cURL 状态，不在响应中回显原文。

    Args:
        asin: 目标 ASIN
        country: 国家站点代码，如 US、UK、DE、JP
        raw_curl: 浏览器 Copy-as-cURL 原文
    """
    try:
        data = await _run_mcp_manager(
            "curl_save",
            asin=asin,
            country=country,
            raw_curl=raw_curl,
        )
        return _ok(data)
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_curl_save",
            exc,
            {
                "asin": asin,
                "country": country,
                "raw_curl_provided": bool(str(raw_curl or "")),
                "raw_curl_length": len(str(raw_curl or "")),
            },
        )


async def _run_mcp_manager(method_name: str, **kwargs: Any) -> dict:
    """在线程中执行同步 Rufus MCP manager 方法，避免阻塞事件循环。"""

    def call() -> dict:
        manager = _rufus_mcp_manager_for_current_request()
        method = getattr(manager, method_name)
        return method(**kwargs)

    return await asyncio.to_thread(call)


def _rufus_mcp_manager_for_current_request() -> RufusMcpManager:
    """创建绑定当前 MCP 请求凭证目录的 Rufus MCP manager。"""
    return RufusMcpManager.for_current_request(credential_dir=_get_credential_dir())


def _rufus_error(tool: str, exc: Exception, call_params: dict) -> dict:
    """按 Rufus 错误语义返回 MCP 失败结构。"""
    return _err(exc, tool=tool, call_params=call_params)


_NETWORK_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=True,
    destructiveHint=False,
)


_ALL_TOOLS = [
    amazon_rufus_remote_consent_status,
    amazon_rufus_remote_consent_set,
    amazon_rufus_login_status,
    amazon_rufus_watch_login,
    amazon_rufus_logout,
    amazon_rufus_get,
    amazon_rufus_platform_cookie_save,
    amazon_rufus_platform_cookie_get,
    amazon_rufus_curl_save,
]


def register(mcp) -> None:
    """向指定 MCP 实例注册 Amazon Rufus 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_WRITE_ANNOTATIONS)(fn)
