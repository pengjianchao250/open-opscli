"""opscli MCP Server 入口。

基于 fastmcp 将 opscli 核心能力暴露为 MCP Tools。
默认使用 stdio transport，兼容 Claude Desktop / Claude Code 本地接入。

启动方式：
    opscli-mcp
    opscli-mcp --transport sse --port 8765
    OPSCLI_MCP_API_KEY=opscli-mcp-xxx opscli-mcp --multi-user
    opscli-mcp --transport sse --port 8765 --multi-user --require-auth
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

import httpx
from fastmcp import Context, FastMCP

from opscli.mcp.auth_middleware import MCPApiKeyAuthProvider, MCPAuthMiddleware
from opscli.mcp.context import configure_multi_user, get_credential_dir


mcp = FastMCP(
    name="opscli",
    instructions=(
        "Aukeys 运营 CLI 工具集 MCP 接口。\n"
        "提供数据查询（query_*）、认证（auth_*）和 Skill 管理（skills_*）能力。\n"
        "支持单用户本地凭证模式，也支持 --multi-user 多用户隔离模式。"
    ),
    middleware=[MCPAuthMiddleware()],
)


def _ok(data: Any) -> dict:
    """统一成功响应结构。"""
    return {"success": True, "data": data, "error": None}


def _err(exc: Exception) -> dict:
    """统一失败响应结构，保留异常类型信息。"""
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        error = to_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    return {"success": False, "data": None, "error": error}


async def _auth_client(ctx: Context | None = None):
    """按当前 MCP 上下文创建 AuthClient。"""
    from opscli.auth import AuthClient

    return AuthClient(base_dir=await get_credential_dir(ctx))


async def _query_manager(ctx: Context | None = None):
    """按当前 MCP 上下文创建 QueryManager。"""
    from opscli.query.services.manager import QueryManager

    return QueryManager(auth_client=await _auth_client(ctx))


async def _registry(ctx: Context | None = None):
    """按当前 MCP 上下文创建系统注册表。"""
    from opscli.auth import BUILTIN_SYSTEMS
    from opscli.auth.core.system_registry import SystemRegistry

    return SystemRegistry(
        base_dir=await get_credential_dir(ctx),
        builtin_systems=BUILTIN_SYSTEMS,
    )


async def _credential_store(ctx: Context | None = None):
    """按当前 MCP 上下文创建凭证存储。"""
    from opscli.auth.storage.credential_store import CredentialStore

    return CredentialStore(base_dir=await get_credential_dir(ctx))


@mcp.tool()
async def query_metadata(
    dataset: str | None = None,
    table_id: int | None = None,
    skills_dir: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """查询指定数据集的 metadata（维度/指标字段列表）。"""
    try:
        result = (await _query_manager(ctx)).metadata(
            dataset_alias=dataset,
            table_id=table_id,
            skills_dir=skills_dir,
        )
        return _ok(result.to_dict())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def query_build(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    where_conditions: list[str] | None = None,
    where_json: str | None = None,
    order_by: list[str] | None = None,
    having_conditions: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    data_comparison: str | None = None,
    output_path: str | None = None,
    skills_dir: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """基于简化参数构造标准 query payload（不执行查询）。"""
    try:
        result = (await _query_manager(ctx)).build(
            dataset_alias=dataset,
            table_id=table_id,
            dimensions=dimensions,
            metrics=metrics,
            where_conditions=where_conditions,
            where_json=where_json,
            order_by=order_by,
            having_conditions=having_conditions,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
            data_comparison=data_comparison,
            output_path=output_path,
            skills_dir=skills_dir,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def query_run(payload_path: str, ctx: Context | None = None) -> dict:
    """读取本地 payload JSON 文件并转发至服务端执行查询。"""
    try:
        result = (await _query_manager(ctx)).run(payload_path=payload_path)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def query_build_and_run(
    dataset: str | None = None,
    table_id: int | None = None,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
    where_conditions: list[str] | None = None,
    where_json: str | None = None,
    order_by: list[str] | None = None,
    having_conditions: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    dry_run: bool = False,
    data_comparison: str | None = None,
    skills_dir: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """构造 query payload 并立即执行，一步返回数据结果。"""
    try:
        result = (await _query_manager(ctx)).build_and_run(
            dataset_alias=dataset,
            table_id=table_id,
            dimensions=dimensions,
            metrics=metrics,
            where_conditions=where_conditions,
            where_json=where_json,
            order_by=order_by,
            having_conditions=having_conditions,
            limit=limit,
            offset=offset,
            dry_run=dry_run,
            data_comparison=data_comparison,
            skills_dir=skills_dir,
        )
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_login_start(ctx: Context | None = None) -> dict:
    """发起 Device Flow 登录第一步，返回验证 URL、用户码和设备码。"""
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow

    try:
        flow = DeviceFlow(ops_url=OPS_URL, store=await _credential_store(ctx))
        return _ok(flow.request_device_code())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_login_poll(
    device_code: str,
    timeout: int = 10,
    ctx: Context | None = None,
) -> dict:
    """单次轮询 Device Flow 授权状态，不进行长时间阻塞。"""
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow

    try:
        flow = DeviceFlow(ops_url=OPS_URL, store=await _credential_store(ctx))
        result = flow.poll_once(device_code, timeout=timeout)
        if result.get("status") == "authorized":
            try:
                await _sync_systems_after_login(ctx)
            except Exception:
                pass
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_logout(ctx: Context | None = None) -> dict:
    """清除当前用户的本地凭证。"""
    try:
        (await _credential_store(ctx)).clear()
        return _ok({"message": "已退出，本地凭证已清除"})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_get_token(system: str = "ops", ctx: Context | None = None) -> dict:
    """获取指定系统的有效 JWT（过期时自动刷新）。"""
    try:
        return _ok((await _auth_client(ctx)).get_token(system))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_check_token(system: str = "ops", ctx: Context | None = None) -> dict:
    """检测指定系统的 Token 有效性及剩余有效时间。"""
    try:
        return _ok((await _auth_client(ctx)).check_token(system))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_is_authenticated(ctx: Context | None = None) -> dict:
    """检查当前是否已登录。"""
    try:
        return _ok((await _auth_client(ctx)).is_authenticated())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_token_refresh(system: str = "__all__", ctx: Context | None = None) -> dict:
    """刷新指定系统 JWT，system='__all__' 时刷新全部系统。"""
    try:
        client = await _auth_client(ctx)
        if system == "__all__":
            return _ok(client._tm.refresh_all())
        return _ok(client.refresh_token(system))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_list(ctx: Context | None = None) -> dict:
    """列出所有已注册系统（builtin / local / ops_sync）。"""
    try:
        return _ok((await _registry(ctx)).list_all())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_add(
    alias: str,
    url: str,
    key: str | None = None,
    token_endpoint: str = "/api/auth/cli-token",
    ctx: Context | None = None,
) -> dict:
    """添加或更新用户自定义系统。"""
    try:
        registry = await _registry(ctx)
        system_key = key or alias.replace(" ", "_").lower()
        registry.add_local(alias, system_key, url, token_endpoint=token_endpoint)
        return _ok({"alias": alias, "system_key": system_key, "url": url})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_remove(alias: str, ctx: Context | None = None) -> dict:
    """移除用户自定义系统；内置系统不可删除。"""
    try:
        (await _registry(ctx)).remove(alias)
        return _ok({"removed": alias})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_sync(ctx: Context | None = None) -> dict:
    """从 ops 后端同步系统列表。"""
    try:
        return _ok(await _sync_systems_after_login(ctx))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_build_request_auth(system: str = "ops", ctx: Context | None = None) -> dict:
    """构造统一请求认证参数（JWT Bearer + Session Cookie）。"""
    try:
        headers, cookies = (await _auth_client(ctx)).build_request_auth(system)
        return _ok({"headers": headers, "cookies": cookies})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_doctor(ctx: Context | None = None) -> dict:
    """检查登录状态与各系统连通性，返回结构化诊断结果。"""
    try:
        client = await _auth_client(ctx)
        checks: list[dict] = []
        for system in client._registry.list_all():
            ok = False
            error = None
            try:
                httpx.get(system["url"], timeout=5)
                ok = True
            except Exception as exc:
                error = str(exc)
            checks.append(
                {
                    "alias": system["alias"],
                    "url": system["url"],
                    "reachable": ok,
                    "error": error,
                }
            )
        return _ok({"authenticated": client.is_authenticated(), "systems": checks})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def skills_list(skills_dir: str | None = None) -> dict:
    """列出当前环境中已安装的所有 Skill。"""
    from opscli.skills.services.manager import SkillsManager

    try:
        records = SkillsManager().list_skills(skills_dir=skills_dir)
        return _ok([item.to_dict() for item in records])
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def skills_status(skills_dir: str | None = None) -> dict:
    """查询 Skill 安装状态，包含本地版本与远端最新版本对比。"""
    from opscli.skills.services.manager import SkillsManager

    try:
        return _ok(SkillsManager().status(skills_dir=skills_dir))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def skills_install(
    name: str,
    skills_dir: str | None = None,
    runtime: str | None = None,
    force: bool = False,
) -> dict:
    """从内置模板安装 Skill。"""
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


@mcp.tool()
def skills_upgrade(
    name: str = "ops-dataset-query",
    skills_dir: str | None = None,
    force: bool = False,
) -> dict:
    """升级指定 Skill 到远端最新版本。"""
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


async def _sync_systems_after_login(ctx: Context | None = None) -> dict:
    """登录成功后同步 ops 系统列表。"""
    from opscli.auth import OPS_URL

    client = await _auth_client(ctx)
    response = httpx.get(
        f"{OPS_URL}/api/v1/cli/systems",
        headers=client.build_session_headers("ops"),
        timeout=10,
    )
    response.raise_for_status()
    systems = response.json().get("systems", [])
    (await _registry(ctx)).sync_from_ops(systems)
    return {"synced": len(systems), "systems": systems}


def run() -> None:
    """MCP Server 启动入口，由 pyproject.toml scripts 注册为 opscli-mcp。"""
    transport_val: str | None = None
    kwargs: dict[str, Any] = {}
    multi_user = False
    require_auth = False
    user_store_base_dir: Path | None = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--transport" and i + 1 < len(args):
            transport_val = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            kwargs["port"] = int(args[i + 1])
            i += 2
        elif args[i] == "--host" and i + 1 < len(args):
            kwargs["host"] = args[i + 1]
            i += 2
        elif args[i] == "--multi-user":
            multi_user = True
            i += 1
        elif args[i] == "--require-auth":
            require_auth = True
            i += 1
        elif args[i] == "--user-store-dir" and i + 1 < len(args):
            user_store_base_dir = Path(args[i + 1]).expanduser()
            i += 2
        else:
            i += 1

    configure_multi_user(
        enabled=multi_user,
        require_auth=require_auth,
        base_dir=user_store_base_dir,
    )
    if multi_user and require_auth and transport_val is not None:
        mcp.auth = MCPApiKeyAuthProvider(base_dir=user_store_base_dir)
    if multi_user and transport_val is None:
        from opscli.mcp.user_store import MCPUserStore

        api_key = os.getenv("OPSCLI_MCP_API_KEY")
        if MCPUserStore(base_dir=user_store_base_dir).verify_api_key(api_key) is None:
            raise SystemExit("stdio 多用户模式需要有效的 OPSCLI_MCP_API_KEY")
    mcp.run(transport=transport_val, **kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    run()
