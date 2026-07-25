"""仪表盘领域 MCP 规范读取工具。"""

from __future__ import annotations

from pathlib import Path

from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _ok


def _dashboard_skill_dir(skill_name: str) -> Path:
    """返回指定仪表盘 Skill 的内置模板目录。"""
    return get_builtin_templates_dir() / skill_name


def _read_spec_files(paths: list[Path], *, tool: str) -> dict:
    """读取并合并规范文件，返回统一 MCP 响应。"""
    for path in paths:
        if not path.exists():
            return _err(
                FileNotFoundError(f"仪表盘 MCP 规范文档不存在：{path}。请检查 opscli 安装是否完整。"),
                tool=tool,
            )

    try:
        content = "\n\n".join(path.read_text(encoding="utf-8") for path in paths)
        return _ok(
            {
                "spec": content,
                "source": str(paths[0]),
                "sources": [str(path) for path in paths],
            }
        )
    except Exception as exc:
        return _err(exc, tool=tool)


async def dashboard_data_analysis_spec_must_read() -> dict:
    """读取仪表盘只读数据分析规范。

    本工具只返回 `ops-dashboard-data-analysis` 的使用规范，不会创建、
    调用或代理 `dashboard_*` 页面工具。实际分析要求当前会话已绑定
    运营系统仪表盘编辑页，并已安装 `ops-dataset-query`。
    """
    skill_dir = _dashboard_skill_dir("ops-dashboard-data-analysis")
    return _read_spec_files(
        [skill_dir / "SKILL.md"],
        tool="MCP → dashboard_data_analysis_spec_must_read()",
    )


async def dashboard_ai_bridge_spec_must_read() -> dict:
    """读取仪表盘编辑与 Bridge 协议规范。

    返回 `ops-dashboard-ai-bridge` 的入口规范、操作规范、结果协议和工具流程。
    本工具只读取文档，不会提供或执行 `dashboard_*` 页面工具；实际页面操作
    仍要求 operation-frontend 为当前会话注入合法 Dashboard 页面上下文。
    """
    skill_dir = _dashboard_skill_dir("ops-dashboard-ai-bridge")
    paths = [
        skill_dir / "SKILL.md",
        skill_dir / "references" / "dashboard-operation-standards.md",
        skill_dir / "references" / "bridge-result-protocol.md",
        skill_dir / "references" / "tool-flow.md",
    ]
    return _read_spec_files(
        paths,
        tool="MCP → dashboard_ai_bridge_spec_must_read()",
    )


_ALL_TOOLS = [
    dashboard_data_analysis_spec_must_read,
    dashboard_ai_bridge_spec_must_read,
]


def register(mcp) -> None:
    """向指定 MCP 实例注册仪表盘规范工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
