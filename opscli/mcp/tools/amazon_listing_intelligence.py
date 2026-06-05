"""Amazon Listing Intelligence MCP 工具模块。

将 Listing 优化服务的确定性编排能力暴露为 MCP 工具：
- amazon_listing_intelligence_spec_must_read — 读取 MCP 使用规范
- amazon_listing_intelligence_data_sources   — 列出数据源接入计划
- amazon_listing_intelligence_objectives     — 列出分析目标
- amazon_listing_intelligence_intake_plan    — 生成单次分析的数据源接入计划
- amazon_listing_intelligence_schema         — 输出参数结构
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import _err, _ok, _parse_json_arg


async def amazon_listing_intelligence_spec_must_read() -> dict:
    """读取 Amazon Listing Intelligence MCP 使用规范。"""
    # 该 Skill 仍处于项目开发阶段，刻意放在 amazon_listing_intelligence/skill 下，
    # 不放入 opscli/skills/templates，避免被正式 Skill 模板发现或提前暴露。
    spec_path = (
        Path(__file__).resolve().parents[2]
        / "amazon_listing_intelligence"
        / "skill"
        / "ops-amazon-listing-intelligence"
        / "SKILL_MCP.md"
    )

    if not spec_path.exists():
        return _err(
            FileNotFoundError(f"Listing Intelligence MCP 规范文档不存在：{spec_path}"),
            tool="MCP → amazon_listing_intelligence_spec_must_read()",
        )

    try:
        content = spec_path.read_text(encoding="utf-8")
        return _ok({"spec": content, "source": str(spec_path)})
    except Exception as exc:
        return _err(exc, tool="MCP → amazon_listing_intelligence_spec_must_read()")


async def amazon_listing_intelligence_data_sources(phase: str | None = None) -> dict:
    """列出 Listing 优化服务数据源接入计划。

    Args:
        phase: 可选，按 mvp / enhanced / commercial 过滤。
    """
    try:
        from opscli.amazon_listing_intelligence.services import AmazonListingIntelligenceManager

        return _ok(AmazonListingIntelligenceManager().data_sources(phase=phase))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → amazon_listing_intelligence_data_sources(...)",
            call_params={"phase": phase},
        )


async def amazon_listing_intelligence_objectives() -> dict:
    """列出支持的 Listing 优化分析目标。"""
    try:
        from opscli.amazon_listing_intelligence.services import AmazonListingIntelligenceManager

        return _ok(AmazonListingIntelligenceManager().objectives())
    except Exception as exc:
        return _err(exc, tool="MCP → amazon_listing_intelligence_objectives()")


async def amazon_listing_intelligence_intake_plan(
    asin: str | None = None,
    keyword: str | None = None,
    marketplace: str = "US",
    objective: str = "listing_audit",
    available_sources: list[str] | str | None = None,
) -> dict:
    """生成 Listing 优化单次分析的数据源接入计划。

    Args:
        asin: Amazon ASIN。
        keyword: 显式关键词。
        marketplace: 站点代码，默认 US。
        objective: 分析目标，默认 listing_audit。
        available_sources: 已具备的数据源 ID 列表。
    """
    try:
        from opscli.amazon_listing_intelligence.domain import ListingIntelligenceRequest
        from opscli.amazon_listing_intelligence.services import AmazonListingIntelligenceManager

        parsed_sources = _parse_json_arg(available_sources, list) or []
        request = ListingIntelligenceRequest(
            asin=asin,
            keyword=keyword,
            marketplace=marketplace,
            objective=objective,
            available_sources=[str(item) for item in parsed_sources],
        )
        return _ok(AmazonListingIntelligenceManager().intake_plan(request))
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → amazon_listing_intelligence_intake_plan(...)",
            call_params={
                "asin": asin,
                "keyword": keyword,
                "marketplace": marketplace,
                "objective": objective,
                "available_sources": available_sources,
            },
        )


async def amazon_listing_intelligence_schema() -> dict:
    """输出 Listing 优化服务 MCP 参数结构。"""
    try:
        from opscli.amazon_listing_intelligence.services import AmazonListingIntelligenceManager

        return _ok(AmazonListingIntelligenceManager().schema())
    except Exception as exc:
        return _err(exc, tool="MCP → amazon_listing_intelligence_schema()")


_ALL_TOOLS = [
    amazon_listing_intelligence_spec_must_read,
    amazon_listing_intelligence_data_sources,
    amazon_listing_intelligence_objectives,
    amazon_listing_intelligence_intake_plan,
    amazon_listing_intelligence_schema,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册 Listing Intelligence 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
