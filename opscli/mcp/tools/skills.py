"""Skills 工具模块。

将 opscli skills 子模块的核心能力暴露为 MCP 工具：
- skills_list               — 列出当前环境中已安装的所有 Skill
- skills_status             — 查询安装状态，包含本地与远端版本对比
- skills_install            — 从内置模板安装 Skill（支持远程 username@skill_name）
- skills_upgrade            — 升级指定 Skill 到远端最新版本
- skills_marketplace_list   — 浏览技能广场列表
- skills_marketplace_search — 关键词搜索技能广场
- skills_marketplace_info   — 查看技能详情
- skills_record_usage       — 记录技能使用次数（异步上报）

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
    version: str | None = None,
) -> dict:
    """安装 Skill 到本地目录。

    支持两种模式：
    1. 内置模板安装：name 不含 @ 符号，如 ops-auth
    2. 远程广场安装：name 格式为 username@skill_name，如 pengjianchao@ops-auth

    Args:
        name:       Skill 名称或广场标识符（username@skill_name）
        skills_dir: 可选，只安装到该目录：跳过运行时探测，不写入 ~/.claude、~/.codex
                    等其他任何目录（隔离安装场景专用，优先级高于 runtime）
        runtime:    可选，只安装到指定运行时；与 skills_dir 同传时被忽略
        force:      是否强制覆盖已有安装（默认 False）
        version:    可选，指定安装版本（仅远程安装有效）
    """
    if "@" in name:
        from opscli.skills.marketplace.remote_installer import install_remote_skill
        try:
            return install_remote_skill(
                identifier=name,
                version=version,
                skills_dir=skills_dir,
                runtime=runtime,
                force=force,
            )
        except Exception as exc:
            return _err(exc)

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


async def skills_marketplace_list(
    category: str | None = None,
    sort: str = "install_count",
    order: str = "desc",
    page: int = 1,
    limit: int = 20,
    official: bool = False,
    keyword: str | None = None,
) -> dict:
    """浏览或搜索技能广场列表。

    Args:
        category: 可选，按分类 slug 筛选（如 auth、data、monitor）
        sort:     排序字段：install_count / usage_count / rating_avg / new
        order:    排序方向：desc 或 asc
        page:     页码，从 1 开始
        limit:    每页条数，最大 100
        official: 只返回官方认证技能
        keyword:  关键词搜索（有值时走搜索接口）
    """
    from opscli.skills.marketplace.client import MarketplaceClient

    try:
        client = MarketplaceClient()
        params: dict = {"sort": sort, "order": order, "page": page, "limit": limit}

        if keyword:
            params["keyword"] = keyword
        if official:
            params["is_official"] = "true"
        if category:
            try:
                cats = client.get_categories()
                for c in cats:
                    if c.get("slug") == category:
                        params["category_id"] = c["id"]
                        break
            except Exception:
                pass

        raw = client.list_skills(params)
        return _ok(raw)
    except Exception as exc:
        return _err(exc)


async def skills_marketplace_info(identifier: str) -> dict:
    """查看技能广场中某个技能的详情。

    Args:
        identifier: 技能标识符，格式为 username@skill_name，如 pengjianchao@ops-auth
    """
    if "@" not in identifier:
        return _err(ValueError(f"标识符格式应为 username@skill_name，收到: {identifier!r}"))

    username, skill_name = identifier.split("@", 1)
    from opscli.skills.marketplace.client import MarketplaceClient

    try:
        raw = MarketplaceClient().get_by_identifier(username, skill_name)
        return _ok(raw)
    except Exception as exc:
        return _err(exc)


async def skills_record_usage(identifier: str) -> dict:
    """记录一次技能调用（异步上报，不阻塞主流程）。

    在 AI Agent 成功调用某个远程技能后，应调用此工具上报使用次数。
    上报失败时静默忽略，不影响正常工作流。

    Args:
        identifier: 技能标识符，格式为 username@skill_name
    """
    try:
        from opscli.skills.marketplace.usage_reporter import get_reporter
        get_reporter().record(identifier)
        return _ok({"recorded": True, "identifier": identifier})
    except Exception as exc:
        return _ok({"recorded": False, "identifier": identifier, "reason": str(exc)})


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS = [
    skills_list,
    skills_status,
    skills_install,
    skills_upgrade,
    skills_marketplace_list,
    skills_marketplace_info,
    skills_record_usage,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 skills_* 工具。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
