"""卖家精灵 MCP 工具模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import _err, _ok, _parse_json_arg


async def seller_sprite_scenarios() -> dict:
    """列出卖家精灵接口直连场景。"""
    try:
        from opscli.seller_sprite.services import SellerSpriteApiManager

        return _ok(SellerSpriteApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_scenarios()")


async def seller_sprite_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    period: str = "30d",
    page_size: int = 100,
    export_format: str = "xlsx",
    output_dir: str | None = None,
    job_id: str | None = None,
) -> dict:
    """执行卖家精灵接口场景并导出 XLSX。"""
    try:
        from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
        from opscli.seller_sprite.services import SellerSpriteApiManager

        parsed_params = _parse_json_arg(params, dict) or {}
        request = SellerSpriteScenarioRequest(
            scenario=scenario,
            site=site,
            period=period,
            params=parsed_params,
            page_size=page_size,
            job_id=job_id,
            output_dir=output_dir,
            export_format=export_format,
        )
        result = await SellerSpriteApiManager().run(request)
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → seller_sprite_run(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "job_id": job_id,
            },
        )


async def seller_sprite_job_status(job_id: str) -> dict:
    """读取卖家精灵任务结果。"""
    try:
        from opscli.seller_sprite.services import SellerSpriteApiManager

        return _ok(SellerSpriteApiManager().job_status(job_id))
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_job_status(...)", call_params={"job_id": job_id})


async def seller_sprite_export(job_id: str) -> dict:
    """读取卖家精灵任务导出文件信息。"""
    try:
        from opscli.seller_sprite.services import SellerSpriteApiManager

        status = SellerSpriteApiManager().job_status(job_id)
        export = status.get("export")
        if not export:
            raise ValueError(f"任务无导出文件：{job_id}")
        if export.get("path") and not export.get("url"):
            export["url"] = Path(export["path"]).expanduser().resolve().as_uri()
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [
    seller_sprite_scenarios,
    seller_sprite_run,
    seller_sprite_job_status,
    seller_sprite_export,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册卖家精灵工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
