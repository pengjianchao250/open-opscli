"""卖家精灵 MCP 工具模块。

将卖家精灵服务能力暴露为 MCP 工具：
- seller_sprite_spec_must_read — 读取卖家精灵 MCP 使用规范（SKILL_MCP.md）
- seller_sprite_scenarios      — 列出卖家精灵场景
- seller_sprite_run            — 执行卖家精灵场景并导出 XLS/JSON
- seller_sprite_job_status     — 读取卖家精灵任务结果
- seller_sprite_export         — 读取卖家精灵任务导出文件信息
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg


async def seller_sprite_spec_must_read() -> dict:
    """读取卖家精灵 MCP 使用规范（SKILL_MCP.md）。

    【首次使用提示】首次调用卖家精灵服务前，应先调用本工具读取完整规范，
    了解可用场景、参数格式、站点/周期约束、导出格式和任务查询流程。

    规范内容来自 opscli 内置 Skill 模板：
    opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md

    Returns:
        {"success": true, "data": {"spec": "<Markdown 文档内容>", "source": "<文件路径>"}}
        或 {"success": false, "error": "<错误原因>"}
    """
    spec_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "templates"
        / "ops-seller-sprite"
        / "SKILL_MCP.md"
    )

    if not spec_path.exists():
        return _err(
            FileNotFoundError(
                f"卖家精灵 MCP 规范文档不存在：{spec_path}。请检查 opscli 安装是否完整。"
            ),
            tool="MCP → seller_sprite_spec_must_read()",
        )

    try:
        content = spec_path.read_text(encoding="utf-8")
        return _ok({"spec": content, "source": str(spec_path)})
    except Exception as exc:
        return _err(exc, tool="MCP → seller_sprite_spec_must_read()")


async def seller_sprite_scenarios() -> dict:
    """列出卖家精灵场景。"""
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
    export_format: str = "xls",
    mode: str | None = None,
    page_prepare: bool | None = None,
    task_interval_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行卖家精灵场景并导出 XLS/JSON。

    如果未提供 session_id / jwt，会自动尝试从当前 MCP 会话隔离凭证中加载。
    """
    sid, jw = _get_auth_pair("ops", session_id, jwt)
    if not sid:
        return _err(
            ValueError("无 session_id：请完成 OPS 授权，或传入有效的 session_id"),
            tool="MCP → seller_sprite_run(...)",
            call_params={
                "scenario": scenario,
                "site": site,
                "period": period,
                "page_size": page_size,
                "export_format": export_format,
                "mode": mode,
                "page_prepare": page_prepare,
                "task_interval_seconds": task_interval_seconds,
                "cooldown_seconds": cooldown_seconds,
                "job_id": job_id,
            },
        )

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
            mode=mode,
            page_prepare=page_prepare,
            task_interval_seconds=task_interval_seconds,
            cooldown_seconds=cooldown_seconds,
        )
        result = await SellerSpriteApiManager(jwt=jw, session_id=sid).run(request)
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
                "mode": mode,
                "page_prepare": page_prepare,
                "task_interval_seconds": task_interval_seconds,
                "cooldown_seconds": cooldown_seconds,
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
    seller_sprite_spec_must_read,
    seller_sprite_scenarios,
    seller_sprite_run,
    seller_sprite_job_status,
    seller_sprite_export,
]


def register(mcp) -> None:
    """向 FastMCP 实例注册卖家精灵工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
