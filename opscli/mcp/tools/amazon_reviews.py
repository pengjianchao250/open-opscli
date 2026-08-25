"""Amazon 评论页面工具的 MCP 静态规范入口。"""

from __future__ import annotations

from pathlib import Path

from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _ok


_SPEC_SOURCE = "ops-amazon-reviews/SKILL_MCP.md"
"""返回给调用方的稳定包内逻辑路径。"""


def _amazon_reviews_skill_dir() -> Path:
    """返回 Amazon 评论 Skill 的内置模板目录。"""
    return get_builtin_templates_dir() / "ops-amazon-reviews"


async def amazon_reviews_spec_must_read() -> dict:
    """读取 Amazon 评论页面工具使用规范。

    本工具只返回静态规范，不会提供、调用或代理页面工具
    `amazon_reviews_get`。实际评论读取仍要求宿主注入合法页面上下文。
    """
    spec_path = _amazon_reviews_skill_dir() / "SKILL_MCP.md"
    if not spec_path.is_file():
        return _err(
            FileNotFoundError(
                "Amazon 评论 MCP 规范文档不存在，请检查 opscli 安装是否完整。"
            ),
            tool="MCP → amazon_reviews_spec_must_read()",
        )

    try:
        return _ok(
            {
                "spec": spec_path.read_text(encoding="utf-8"),
                "source": _SPEC_SOURCE,
                "sources": [_SPEC_SOURCE],
            }
        )
    except Exception as exc:
        return _err(exc, tool="MCP → amazon_reviews_spec_must_read()")


_ALL_TOOLS = [amazon_reviews_spec_must_read]


def register(mcp) -> None:
    """向指定 MCP 实例注册 Amazon 评论规范工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
