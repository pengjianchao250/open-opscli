"""Skills 工具模块。

将 opscli skills 子模块的核心能力暴露为 MCP 工具：
- skills_list    — 列出当前环境中已安装的所有 Skill
- skills_status  — 查询安装状态，包含本地与远端版本对比
- skills_install — 从内置模板安装 Skill
- skills_upgrade — 升级指定 Skill 到远端最新版本

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from .helpers import _err, _ok


async def skills_list(skills_dir: str | None = None) -> dict:
    """列出当前环境中已安装的所有 Skill。

    Args:
        skills_dir: 可选，自定义 Skills 目录（不传则使用默认路径）
    """
    from opscli.skills.services.manager import SkillsManager

    try:
        records = SkillsManager().list_skills(skills_dir=skills_dir)
        return _ok([item.to_dict() for item in records])
    except Exception as exc:
        return _err(exc)


async def skills_status(skills_dir: str | None = None) -> dict:
    """查询 Skill 安装状态，包含本地版本与远端最新版本对比。

    Args:
        skills_dir: 可选，自定义 Skills 目录
    """
    from opscli.skills.services.manager import SkillsManager

    try:
        return _ok(SkillsManager().status(skills_dir=skills_dir))
    except Exception as exc:
        return _err(exc)


async def skills_install(
    name: str,
    skills_dir: str | None = None,
    runtime: str | None = None,
    force: bool = False,
) -> dict:
    """从内置模板安装 Skill。

    Args:
        name:       Skill 名称（必须带 ops- 前缀，如 ops-auth）
        skills_dir: 可选，安装到指定目录（不传则使用默认路径）
        runtime:    可选，指定运行时环境
        force:      是否强制覆盖已有安装（默认 False）
    """
    from opscli.skills.services.manager import SkillsManager

    try:
        result = SkillsManager().install(
            name,
            skills_dir=skills_dir,
            runtime=runtime,
            force=force,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


async def skills_upgrade(
    name: str = "ops-dataset-query",
    skills_dir: str | None = None,
    force: bool = False,
) -> dict:
    """升级指定 Skill 到远端最新版本。

    Args:
        name:       Skill 名称（默认 ops-dataset-query）
        skills_dir: 可选，自定义 Skills 目录
        force:      是否强制升级（即使已是最新版本）
    """
    from opscli.skills.services.manager import SkillsManager

    try:
        result = SkillsManager().upgrade(
            name=name,
            skills_dir=skills_dir,
            force=force,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    skills_list,
    skills_status,
    skills_install,
    skills_upgrade,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 skills_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
