"""opscli 通用 MCP Server 入口。"""

from __future__ import annotations

import importlib
import logging

from opscli.mcp.app_factory import (
    InstrumentedMcpProxy,
    _generate_api_key,
    _load_or_create_api_key as _load_service_api_key,
    build_dual_endpoint_app,
    create_mcp_app,
    run_mcp_app,
)
from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
from opscli.mcp.tool_catalog import get_catalog

_logger = logging.getLogger("opscli.mcp")

# 保留历史内部导出，避免现有测试和扩展模块因运行时提取而失效。
_quota_wrap = quota_wrap
_telemetry_wrap = telemetry_wrap
_TelemetryMcpProxy = InstrumentedMcpProxy

from opscli.mcp.tools import amazon_rufus as _amazon_rufus_tools
from opscli.mcp.tools import asin_data as _asin_data_tools
from opscli.mcp.tools import asin_review as _asin_review_tools
from opscli.mcp.tools import auth as _auth_tools
from opscli.mcp.tools import beta as _beta_tools
from opscli.mcp.tools import chatgpt as _chatgpt_tools
from opscli.mcp.tools import dashboard as _dashboard_tools
from opscli.mcp.tools import feedback as _feedback_tools
from opscli.mcp.tools import google_trends as _google_trends_tools
from opscli.mcp.tools import health as _health_tools
from opscli.mcp.tools import keepa as _keepa_tools
from opscli.mcp.tools import query as _query_tools
from opscli.mcp.tools import scrape_do as _scrape_do_tools
from opscli.mcp.tools import seller_sprite_proxy as _seller_sprite_proxy_tools
from opscli.mcp.tools import skills as _skills_tools


def _register_optional_asin_review_tool(mcp_proxy) -> None:
    """注册可选 asin_review 工具，仅在顶层模块缺失时降级跳过。"""
    try:
        asin_review_tools = importlib.import_module("opscli.mcp.tools.asin_review")
    except ModuleNotFoundError as exc:
        if exc.name != "opscli.mcp.tools.asin_review":
            raise
        _logger.info("asin_review 工具未加载：缺少可选模块 opscli.mcp.tools.asin_review")
        return
    asin_review_tools.register(mcp_proxy)


def _register_optional_amazon_tools(mcp_proxy) -> None:
    """可选安装 playwright 时注册 Amazon 工具。"""
    try:
        from opscli.mcp.tools import amazon as amazon_tools

        amazon_tools.register(mcp_proxy)
    except (ImportError, ModuleNotFoundError):
        _logger.info(
            "amazon 工具未加载：缺少 playwright 依赖，"
            "安装命令：pip install opscli[amazon] && playwright install chromium"
        )


_REGISTRARS = [
    _auth_tools.register,
    _amazon_rufus_tools.register,
    _beta_tools.register,
    _chatgpt_tools.register,
    _dashboard_tools.register,
    _feedback_tools.register,
    _google_trends_tools.register,
    _health_tools.register,
    _keepa_tools.register,
    _query_tools.register,
    _scrape_do_tools.register,
    _seller_sprite_proxy_tools.register,
    _asin_data_tools.register,
    _asin_review_tools.register,
    _skills_tools.register,
    # 保留当前通用服务的历史可选注册顺序，不在本次迁移中清理。
    _register_optional_asin_review_tool,
    _register_optional_amazon_tools,
]

mcp = create_mcp_app(
    name="opscli",
    instructions=(
        "Aukeys 运营 CLI 工具集 MCP 接口。\n"
        "服务器按 API Key 隔离用户凭证（远程校验模式下）。\n"
        "使用 auth_mcp_login 完成 MCP 一步登录后调用业务工具。"
    ),
    registrars=_REGISTRARS,
)


def _load_or_create_api_key() -> str:
    """加载或创建通用 MCP 固定 API Key。"""
    return _load_service_api_key("mcp_api_key")


def _build_dual_endpoint_app(
    *,
    api_key: str | None = None,
    auth_verify_url: str | None = None,
):
    """构建通用 MCP 的 SSE 与 Streamable HTTP 双端点。"""
    return build_dual_endpoint_app(
        mcp,
        api_key=api_key,
        auth_verify_url=auth_verify_url,
    )


def run() -> None:
    """运行通用 MCP 服务。"""
    run_mcp_app(
        mcp,
        service_name="opscli-mcp",
        catalog=get_catalog(),
    )


if __name__ == "__main__":
    run()
