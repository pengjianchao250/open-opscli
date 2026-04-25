"""opscli MCP Server 入口。

基于 fastmcp 将 opscli 核心能力暴露为 MCP Tools。
**无状态设计**：服务器不保存任何用户 OAuth 凭证，所有认证信息由调用方传入。

典型授权流程：
    1. auth_login_start() → 返回 verification_url + user_code + device_code
    2. 用户在浏览器中打开 URL 并输入 user_code
    3. auth_login_poll(device_code) → 返回 {status: "authorized", session_id, ...}
    4. 调用方保存 session_id 到本地
    5. 后续 tool 调用传入 session_id（和可选的 jwt）

启动方式：
    opscli-mcp
    opscli-mcp --transport sse --port 8765
"""

from __future__ import annotations

import base64
import json
import secrets
import stat
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastmcp import Context, FastMCP

mcp = FastMCP(
    name="opscli",
    instructions=(
        "Aukeys 运营 CLI 工具集 MCP 接口（无状态模式）。\n"
        "服务器不保存用户凭证，所有认证信息（session_id / jwt）由调用方传入。\n"
        "典型流程：auth_login_start → 浏览器授权 → auth_login_poll → "
        "保存返回的 session_id → 后续 tool 调用传入 session_id（和可选的 jwt）。"
    ),
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


def _auth_client() -> Any:
    """创建 AuthClient（无状态，不读取本地凭证目录）。"""
    from opscli.auth import AuthClient

    return AuthClient()


def _query_manager(jwt: str | None = None, session_id: str | None = None) -> Any:
    """创建 QueryManager，支持外部传入凭证。"""
    from opscli.query.services.manager import QueryManager

    return QueryManager(auth_client=_auth_client(), jwt=jwt, session_id=session_id)


def _registry() -> Any:
    """创建系统注册表。"""
    from opscli.auth import BUILTIN_SYSTEMS
    from opscli.auth.core.system_registry import SystemRegistry

    return SystemRegistry(builtin_systems=BUILTIN_SYSTEMS)


def _decode_jwt_payload(jwt: str) -> dict:
    """解析 JWT payload（不验证签名），用于本地检查有效期。"""
    parts = jwt.split(".")
    if len(parts) != 3:
        raise ValueError("非法 JWT 格式")
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload))


# ── query tools ──────────────────────────────────────────────────

@mcp.tool()
async def query_metadata(
    dataset: str | None = None,
    table_id: int | None = None,
    skills_dir: str | None = None,
) -> dict:
    """查询指定数据集的 metadata（维度/指标字段列表）。不需要认证。"""
    try:
        result = _query_manager().metadata(
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
) -> dict:
    """基于简化参数构造标准 query payload（不执行查询）。不需要认证。"""
    try:
        result = _query_manager().build(
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
async def query_run(
    payload_path: str,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取本地 payload JSON 文件并转发至服务端执行查询。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        result = _query_manager(jwt=jwt, session_id=session_id).run(payload_path=payload_path)
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
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """构造 query payload 并立即执行，一步返回数据结果。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        result = _query_manager(jwt=jwt, session_id=session_id).build_and_run(
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


# ── auth tools ───────────────────────────────────────────────────

@mcp.tool()
async def auth_login_start() -> dict:
    """发起 Device Flow 登录第一步，返回验证 URL、用户码和设备码。"""
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow

    try:
        flow = DeviceFlow(ops_url=OPS_URL, store=None)  # 无状态模式不保存
        return _ok(flow.request_device_code())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_login_poll(device_code: str, timeout: int = 10) -> dict:
    """单次轮询 Device Flow 授权状态。

    授权成功后返回 session_id，调用方需自行保存到本地。
    服务器不保存任何凭证。
    """
    from opscli.auth import OPS_URL
    from opscli.auth.core.device_flow import DeviceFlow

    try:
        flow = DeviceFlow(ops_url=OPS_URL, store=None)  # 无状态模式不保存
        result = flow.poll_once(device_code, timeout=timeout)
        return _ok(result)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_get_token(system: str = "ops", session_id: str | None = None) -> dict:
    """获取指定系统的有效 JWT。

    无状态模式下必须提供 session_id，服务器会直接向后端请求 JWT，不读取本地存储。
    """
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        jwt = _auth_client().get_token_by_session(session_id, system)
        return _ok(jwt)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_check_token(jwt: str | None = None) -> dict:
    """检测 JWT 有效性及剩余有效时间（秒）。纯本地解析，不向后端发请求。"""
    if not jwt:
        return _ok({"valid": False, "expires_in": 0})
    try:
        payload = _decode_jwt_payload(jwt)
        exp = payload.get("exp")
        if not exp:
            return _ok({"valid": False, "expires_in": 0})
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        return _ok({"valid": remaining > 0, "expires_in": max(0, remaining)})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_is_authenticated(session_id: str | None = None) -> dict:
    """检查 session_id 是否有效（尝试用其获取 JWT）。"""
    if not session_id:
        return _ok(False)
    try:
        _auth_client().get_token_by_session(session_id, "ops")
        return _ok(True)
    except Exception:
        return _ok(False)


@mcp.tool()
async def auth_token_refresh(system: str = "__all__", session_id: str | None = None) -> dict:
    """刷新指定系统 JWT。必须有 session_id。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        client = _auth_client()
        if system == "__all__":
            results = {}
            for sys in client._registry.list_all():
                try:
                    jwt = client.get_token_by_session(session_id, sys["alias"])
                    results[sys["alias"]] = {"jwt": jwt, "ok": True}
                except Exception as e:
                    results[sys["alias"]] = {"ok": False, "error": str(e)}
            return _ok(results)
        jwt = client.get_token_by_session(session_id, system)
        return _ok({"jwt": jwt})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_list() -> dict:
    """列出所有已注册系统（builtin / local / ops_sync）。不需要认证。"""
    try:
        return _ok(_registry().list_all())
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_add(
    alias: str,
    url: str,
    key: str | None = None,
    token_endpoint: str = "/api/auth/cli-token",
) -> dict:
    """添加或更新用户自定义系统。不需要认证。"""
    try:
        registry = _registry()
        system_key = key or alias.replace(" ", "_").lower()
        registry.add_local(alias, system_key, url, token_endpoint=token_endpoint)
        return _ok({"alias": alias, "system_key": system_key, "url": url})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_remove(alias: str) -> dict:
    """移除用户自定义系统；内置系统不可删除。不需要认证。"""
    try:
        _registry().remove(alias)
        return _ok({"removed": alias})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_system_sync(session_id: str | None = None) -> dict:
    """从 ops 后端同步系统列表。需要 session_id。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        return _ok(await _sync_systems_after_login(session_id))
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_build_request_auth(
    system: str = "ops",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """构造统一请求认证参数（JWT Bearer + Session Cookie）。"""
    if not session_id:
        return _err(ValueError("无状态模式下必须提供 session_id"))
    try:
        headers, cookies = _auth_client().build_request_auth_with_session(
            session_id, jwt, system
        )
        return _ok({"headers": headers, "cookies": cookies})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def auth_doctor(session_id: str | None = None) -> dict:
    """检查 session 有效性与各系统连通性，返回结构化诊断结果。"""
    try:
        client = _auth_client()
        checks: list[dict] = []
        authenticated = False
        if session_id:
            try:
                client.get_token_by_session(session_id, "ops")
                authenticated = True
            except Exception:
                pass
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
        return _ok({"authenticated": authenticated, "systems": checks})
    except Exception as exc:
        return _err(exc)


# ── skills tools ─────────────────────────────────────────────────

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


# ── internal helpers ─────────────────────────────────────────────

async def _sync_systems_after_login(session_id: str) -> dict:
    """使用外部传入的 session_id 同步 ops 系统列表。"""
    from opscli.auth import OPS_URL

    response = httpx.get(
        f"{OPS_URL}/api/v1/cli/systems",
        headers={"X-Session-Id": session_id},
        timeout=10,
    )
    response.raise_for_status()
    systems = response.json().get("systems", [])
    _registry().sync_from_ops(systems)
    return {"synced": len(systems), "systems": systems}


def _generate_api_key() -> str:
    """生成固定格式的高熵 API Key。"""
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(32))
    return "opscli-mcp-" + random_part


def _load_or_create_api_key() -> str:
    """加载或创建 MCP 服务固定 API Key。

    Key 持久化保存在 ~/.config/opscli/mcp_api_key 中，避免每次重启都更换。
    首次启动时自动生成并打印，管理员需记录后分发给用户。
    """
    from opscli.config import CONFIG_DIR

    key_path = Path(CONFIG_DIR) / "mcp_api_key"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()

    api_key = _generate_api_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(api_key, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return api_key


def run() -> None:
    """MCP Server 启动入口，由 pyproject.toml scripts 注册为 opscli-mcp。"""
    transport_val: str | None = None
    kwargs: dict[str, Any] = {}

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
        else:
            i += 1

    # SSE 模式下自动启用固定 API Key 鉴权
    if transport_val == "sse":
        api_key = _load_or_create_api_key()
        from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware
        from starlette.middleware import Middleware

        # 不再使用 FastMCP 内置 AuthProvider，统一由自定义中间件处理
        # 同时支持 Header (Authorization: Bearer) 和 Query Param (?api_key=)
        kwargs["middleware"] = [
            Middleware(ApiKeyAuthMiddleware, api_key=api_key),
        ]
        print(f"\n[opscli-mcp] SSE 服务已启用 API Key 鉴权")
        print(f"[opscli-mcp] API Key: {api_key}\n")
        print("支持两种方式传入 API Key：")
        print("  1. HTTP Header: Authorization: Bearer <api_key>")
        print("  2. URL Query:   ?api_key=<api_key>\n")

    mcp.run(transport=transport_val, **kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    run()
