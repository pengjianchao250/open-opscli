"""opscli MCP Server 入口。

基于 fastmcp 将 opscli 核心能力暴露为 MCP Tools。
**无状态设计**：服务器不保存任何用户 OAuth 凭证，所有认证信息由调用方传入。

支持两种 API Key 鉴权模式：
1. 固定 API Key 模式（单用户/向后兼容）：
   - 使用 --transport sse/http/both 启动
   - 服务器自动生成并持久化一个固定 API Key
   - 所有连接者共享同一个 Key

2. 远程校验模式（多用户/OPS 管控）：
   - 使用 --transport sse/http/both --auth-verify-url <url> 启动
   - 每个用户拥有独立的 API Key（由 OPS 后端生成和管理）
   - MCP Server 通过远程调用 OPS 后端校验 API Key 有效性
   - 按 API Key 隔离凭证存储，解决用户间 session 串用问题

典型授权流程：
    1. auth_login_start() → 返回 verification_url + user_code + device_code
    2. 用户在浏览器中打开 URL 并输入 user_code
    3. auth_login_poll(device_code) → 返回 {status: "authorized", session_id, ...}
    4. 调用方保存 session_id 到本地
    5. 后续 tool 调用传入 session_id（和可选的 jwt）

工具模块分层（tools/ 目录）：
    - tools/helpers.py  — 共享辅助函数（_ok / _err / 工厂函数）
    - tools/auth.py     — 认证授权工具（auth_*）
    - tools/query.py    — 数据查询工具（query_*）
    - tools/skills.py   — Skill 管理工具（skills_*）

    启动方式：
    opscli-mcp                                    # stdio 模式（默认）
    opscli-mcp --transport sse --port 8765        # 仅 /sse 端点
    opscli-mcp --transport http --port 8765       # 仅 /mcp 端点（Streamable HTTP）
    opscli-mcp --transport both --port 8765       # /sse + /mcp 双端点（自动远程校验）
    opscli-mcp --transport both --auth-verify-url https://custom.com/v1/mcp/verify-key

传输协议说明：
    - sse:   旧式 SSE 传输，在 GET /sse 建立事件流，POST /messages/ 投递消息
             兼容 Cursor、Claude Desktop、Cherry Studio 等客户端
    - http:  Streamable HTTP 传输，所有请求走 POST /mcp
             为 ChatGPT / OpenAI Apps SDK 等推荐协议
    - both:  同时暴露 /sse（SSE）和 /mcp（Streamable HTTP），推荐远程部署使用
"""

from __future__ import annotations

import importlib
import logging
import secrets
import stat
import string
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastmcp import FastMCP

_logger = logging.getLogger("opscli.mcp")

# ── MCP 实例（全局唯一，工具注册后由 run() 启动）──────────────────
mcp = FastMCP(
    name="opscli",
    instructions=(
        "Aukeys 运营 CLI 工具集 MCP 接口。\n"
        "服务器按 API Key 隔离用户凭证（远程校验模式下）。\n"
        "典型流程：auth_login_start → 浏览器授权 → auth_login_poll → "
        "保存返回的 session_id → 后续 tool 调用传入 session_id（和可选的 jwt）。"
    ),
)

# ── 遥测代理（包裹 tool 注册，无侵入采集 MCP Tool 调用数据）──────────

import functools
import time as _time


def _quota_wrap(fn, *, limiter=None):
    """将 MCP tool 函数包裹限额切面。

    限额策略按 tool 函数名匹配。未配置策略的工具会直接放行，
    因此 seller_sprite_scenarios / job_status / export 不会消耗次数。
    """
    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        from opscli.mcp.quota import get_quota_limiter

        quota_limiter = limiter or get_quota_limiter()
        decision = await quota_limiter.before_call(fn.__name__)
        if not decision.allowed:
            return decision.error_response

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            await quota_limiter.after_exception(decision.ticket)
            raise

        if isinstance(result, dict):
            return await quota_limiter.after_call(decision.ticket, result)
        return result

    return _wrapper


def _telemetry_wrap(fn):
    """将 MCP tool 函数包裹遥测装饰器。

    自动记录 tool 名称、耗时、成功/失败状态，
    命令执行完后异步上报到后端。

    Args:
        fn: 原始 MCP tool 异步函数

    Returns:
        包裹了遥测逻辑的新函数（保留原函数签名和文档）
    """
    @functools.wraps(fn)
    async def _wrapper(*args, **kwargs):
        start = _time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            _fire_mcp_event(
                fn.__name__, status="success",
                duration_ms=int((_time.monotonic() - start) * 1000),
                params=kwargs,
            )
            return result
        except Exception as exc:
            _fire_mcp_event(
                fn.__name__,
                status="error",
                duration_ms=int((_time.monotonic() - start) * 1000),
                error_type=type(exc).__name__,
                params=kwargs,
            )
            raise

    return _wrapper


def _get_current_mcp_user_email() -> str | None:
    """获取当前 MCP 请求关联的用户邮箱（telemetry 专用，静默失败）。

    按以下优先级回退，覆盖 MCP 的三种运行模式：

    1. HTTP/SSE 远程校验模式：直接读取 `mcp.context.get_current_user_email()`，
       中间件已从 OPS `/v1/mcp/verify-key` 拿到 email 并注入 contextvar / scope。
    2. HTTP/SSE 固定 API Key 模式：context 拿不到 email，按 API Key 隔离目录
       读取 CredentialStore 中保存的 email。
    3. stdio 模式：`_get_credential_dir()` 返回 None，回退到默认凭证目录，
       与 CLI 共用同一份登录态。

    Returns:
        用户邮箱字符串，或 None（未登录 / 任一环节异常）
    """
    try:
        # 优先：远程校验模式下中间件已注入 email
        from opscli.mcp.context import get_current_user_email

        email = get_current_user_email()
        if email:
            return email

        # 回退：从凭证存储读取（固定 API Key 模式 / stdio 模式）
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.tools.helpers import _get_credential_dir

        cred_dir = _get_credential_dir()
        store = CredentialStore(base_dir=cred_dir) if cred_dir else CredentialStore()
        data = store.load()
        return data.get("email") if data else None
    except Exception:
        # telemetry 不允许影响主流程，任何异常静默吞掉
        return None


def _get_current_mcp_skill_name() -> str | None:
    """获取当前 MCP 调用方的标识（telemetry 专用，静默失败）。

    MCP 协议层无法直接拿到"业务 Skill 名"，此处退而求其次使用
    `clientInfo.name`（MCP initialize 握手中的客户端 Agent 名，
    如 claude / cursor / codex），作为调用方近似标识填入 skill_name。

    语义说明：
        - skill_name 字段后端定义为"调用方 Skill 名称"
        - 但 MCP 协议层只能识别到 Agent 名，无法识别到 Skill 名
        - 用 Agent 名作为近似值，至少可以统计哪个 Agent 工具调用了 MCP

    Returns:
        客户端 Agent 名（已 lowercase + strip），或 None
    """
    try:
        from opscli.mcp.context import get_current_client_name

        return get_current_client_name()
    except Exception:
        return None


def _fire_mcp_event(
    tool_name: str, *, status: str, duration_ms: int,
    error_type: str | None = None,
    params: dict | None = None,
) -> None:
    """异步上报 MCP tool 遥测事件（fire-and-forget）。

    Args:
        tool_name:   MCP tool 函数名，如 "query_simple"
        status:      "success" 或 "error"
        duration_ms: 耗时毫秒
        error_type:  异常类名（status=error 时有值）
        params:      tool 调用时传入的参数 dict
    """
    try:
        # 模块名取 tool_name 第一段下划线前的部分，如 query_simple → query
        module = tool_name.split("_")[0]
        from opscli.telemetry.collector import build_event
        from opscli.telemetry.reporter import TelemetryReporter

        event = build_event(
            event_type="mcp_tool",
            command=tool_name,
            module=module,
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            user_email=_get_current_mcp_user_email(),
            skill_name=_get_current_mcp_skill_name(),
            raw_payload={"params": params} if params else None,
        )
        TelemetryReporter.fire(**event)
    except Exception:
        # 遥测自身异常不能影响 MCP 工具的正常返回
        pass


class _TelemetryMcpProxy:
    """FastMCP 代理，在 tool 注册时自动插入遥测装饰器并采集工具清单。

    替换各 register(mcp) 调用中的 mcp 参数，
    使所有 tool 函数在注册时被 _telemetry_wrap 包裹，
    无需修改任何 tools/ 模块代码。

    同时将每个工具的元数据（名称/模块/描述）记入 tool_catalog，
    供 HTTP 模式启动时自动上报后端管理清单。
    """

    def __init__(self, real_mcp: FastMCP) -> None:
        self._real = real_mcp

    def tool(self, *args, **kwargs):
        """拦截 mcp.tool() 装饰器调用，注册时自动插入遥测包裹。"""
        real_decorator = self._real.tool(*args, **kwargs)

        def wrap(fn):

            # 采集工具清单元数据：
            # - 工具名优先取 name= 覆盖（如 chatgpt 模块的 fetch/search）
            # - 模块取注册函数 __module__ 末段（精确归属，避免按前缀切分出错）
            from opscli.mcp.tool_catalog import extract_description, record_tool

            record_tool(
                name=kwargs.get("name") or fn.__name__,
                module=fn.__module__.rsplit(".", 1)[-1],
                description=extract_description(fn, kwargs),
            )
            # 先包裹遥测，再注册到 FastMCP
            return real_decorator(_telemetry_wrap(_quota_wrap(fn)))


        return wrap

    def __getattr__(self, name: str):
        """其余属性直接转发到真实 FastMCP 实例。"""
        return getattr(self._real, name)


# ── 工具注册（使用遥测代理，自动包裹所有 tool 函数）──────────────────
_telemetry_mcp = _TelemetryMcpProxy(mcp)

from opscli.mcp.tools import auth as _auth_tools
from opscli.mcp.tools import amazon_rufus as _amazon_rufus_tools
from opscli.mcp.tools import beta as _beta_tools
from opscli.mcp.tools import chatgpt as _chatgpt_tools
from opscli.mcp.tools import feedback as _feedback_tools
from opscli.mcp.tools import google_trends as _google_trends_tools
from opscli.mcp.tools import keepa as _keepa_tools
from opscli.mcp.tools import query as _query_tools
from opscli.mcp.tools import scrape_do as _scrape_do_tools
from opscli.mcp.tools import seller_sprite as _seller_sprite_tools
from opscli.mcp.tools import skills as _skills_tools
from opscli.mcp.tools import asin_review as _asin_review_tools
# Sif / 西柚暂不开放 MCP 工具：保留工具模块代码，待业务确认后再恢复注册。
# from opscli.mcp.tools import sif as _sif_tools
# from opscli.mcp.tools import xiyou as _xiyou_tools

_auth_tools.register(_telemetry_mcp)
_amazon_rufus_tools.register(_telemetry_mcp)
_beta_tools.register(_telemetry_mcp)
_chatgpt_tools.register(_telemetry_mcp)
_feedback_tools.register(_telemetry_mcp)
_google_trends_tools.register(_telemetry_mcp)
_keepa_tools.register(_telemetry_mcp)
_query_tools.register(_telemetry_mcp)
_scrape_do_tools.register(_telemetry_mcp)
_seller_sprite_tools.register(_telemetry_mcp)
_asin_review_tools.register(_telemetry_mcp)
# _sif_tools.register(_telemetry_mcp)
# _xiyou_tools.register(_telemetry_mcp)
_skills_tools.register(_telemetry_mcp)

def _register_optional_asin_review_tool(telemetry_mcp) -> None:
    """注册可选的 asin_review 工具，仅在顶层模块缺失时降级跳过。"""
    try:
        asin_review_tools = importlib.import_module("opscli.mcp.tools.asin_review")
    except ModuleNotFoundError as exc:
        if exc.name != "opscli.mcp.tools.asin_review":
            raise
        _logger.info("asin_review 工具未加载：缺少可选模块 opscli.mcp.tools.asin_review")
        return

    asin_review_tools.register(telemetry_mcp)


_register_optional_asin_review_tool(_telemetry_mcp)

# amazon 工具依赖可选扩展 playwright，未安装时跳过注册不影响其他工具
try:
    from opscli.mcp.tools import amazon as _amazon_tools

    _amazon_tools.register(_telemetry_mcp)
except (ImportError, ModuleNotFoundError):
    # playwright 或 opscli[amazon] 未安装，amazon_* 工具不可用
    _logger.info("amazon 工具未加载：缺少 playwright 依赖，安装命令：pip install opscli[amazon] && playwright install chromium")


# ── 工具权限过滤（按用户角色隐藏无权限工具 + 拦截越权调用）──────────
from opscli.mcp.permissions import ToolPermissionMiddleware

mcp.add_middleware(ToolPermissionMiddleware())


# ── API Key 管理（HTTP 模式使用）─────────────────────────────────────

def _generate_api_key() -> str:
    """生成固定格式的高熵 API Key。

    格式：opscli-mcp-<32位随机字母数字>

    Returns:
        高熵 API Key 字符串
    """
    from opscli.mcp.user_store import generate_api_key
    return generate_api_key()


def _load_or_create_api_key() -> str:
    """加载或创建 MCP 服务固定 API Key。

    Key 持久化保存在 ~/.config/opscli/mcp_api_key 中，避免每次重启都更换。
    首次启动时自动生成并打印，管理员需记录后分发给用户。

    Returns:
        API Key 字符串
    """
    from opscli.config import CONFIG_DIR

    key_path = Path(CONFIG_DIR) / "mcp_api_key"
    if key_path.exists():
        # 已有 Key 直接读取，避免重启后失效
        return key_path.read_text(encoding="utf-8").strip()

    # 首次启动：生成新 Key 并以 600 权限写入（仅所有者可读写）
    api_key = _generate_api_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(api_key, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return api_key


def _build_dual_endpoint_app(
    *,
    api_key: str | None = None,
    auth_verify_url: str | None = None,
) -> Any:
    """构建同时暴露 /sse 和 /mcp 两个端点的组合 ASGI 应用。

    端点说明：
        GET  /sse        — SSE 事件流（旧式客户端：Cursor、Claude Desktop 等）
        POST /messages/  — SSE 消息投递（配合 /sse 使用）
        POST /mcp        — Streamable HTTP（ChatGPT / OpenAI Apps SDK 推荐）

    实现原理：
        两套传输层的路由路径完全不冲突，直接合并到同一 Starlette 应用。
        FastMCP 的 _lifespan_manager() 内部有引用计数，嵌套调用安全，
        只会初始化一次 MCP 服务器，引用归零时统一清理。

    Args:
        api_key: 固定 API Key（单用户模式，向后兼容）
        auth_verify_url: OPS 后端校验地址（多用户模式），
                         如 https://ops.example.com/v1/mcp/verify-key

    Returns:
        包裹了 ApiKeyAuthMiddleware 的 ASGI 应用。
    """
    from starlette.applications import Starlette

    from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

    # 创建 SSE 传输子应用：提供 GET /sse 和 POST /messages/ 两条路由
    sse_sub_app = mcp.http_app(path="/sse", transport="sse")
    # 创建 Streamable HTTP 子应用：提供 /mcp 路由，ChatGPT 推荐传输协议
    http_sub_app = mcp.http_app(path="/mcp", transport="streamable-http")

    # 合并路由：/sse + /messages/ + /mcp 三条路径互不冲突，直接拼接
    combined_routes = list(sse_sub_app.routes) + list(http_sub_app.routes)

    # 链式生命周期：先启动 SSE 层，再启动 Streamable HTTP 层
    # FastMCP._lifespan_manager() 内部引用计数，嵌套安全，MCP 服务器只初始化一次
    @asynccontextmanager
    async def _combined_lifespan(_app: Any):
        async with sse_sub_app.lifespan(sse_sub_app):
            async with http_sub_app.lifespan(http_sub_app):
                yield

    # 合并后的 Starlette 应用（不含中间件，中间件由外层 ASGI 包裹统一处理）
    combined = Starlette(routes=combined_routes, lifespan=_combined_lifespan)

    # 用 API Key 鉴权中间件统一包裹整个合并应用
    # 支持 Authorization: Bearer <key> 和 ?api_key=<key> 两种传入方式
    return ApiKeyAuthMiddleware(
        combined,
        api_key=api_key,
        auth_verify_url=auth_verify_url,
    )


def _print_http_startup_banner(
    host: str,
    port: int,
    mode: str,
    *,
    api_key: str | None = None,
    auth_verify_url: str | None = None,
) -> None:
    """打印 HTTP 模式启动信息。

    Args:
        host: 监听地址
        port: 监听端口
        mode: "sse" | "http" | "both"
        api_key: 固定 API Key（单用户模式）
        auth_verify_url: 远程校验地址（多用户模式）
    """
    base_url = f"https://<your-domain>"  # 实际部署时替换为公网域名
    local_url = f"http://{host}:{port}"

    print(f"\n[opscli-mcp] 服务已启动（模式：{mode}）")

    if auth_verify_url:
        print(f"[opscli-mcp] 远程校验模式：{auth_verify_url}")
        print(f"[opscli-mcp] 每个用户需使用独立的 API Key（由 OPS 后端生成）")
    elif api_key:
        print(f"[opscli-mcp] 固定 API Key: {api_key}")

    print()
    print("鉴权方式（选其一）：")
    print(f"  Authorization: Bearer <your-api-key>")
    print(f"  ?api_key=<your-api-key>")
    print()

    if mode in ("sse", "both"):
        print("SSE 端点（兼容 Cursor / Claude Desktop 等）：")
        print(f"  {local_url}/sse")
        print(f"  {local_url}/messages/  （SSE 消息投递）")
        print()

    if mode in ("http", "both"):
        print("Streamable HTTP 端点（ChatGPT / OpenAI Apps SDK 推荐）：")
        print(f"  {local_url}/mcp")
        print()
        print("ChatGPT connector 配置示例：")
        print(f"  Connector URL: {base_url}/mcp")
        print("  （注意：ChatGPT 需要公网 HTTPS，本地地址仅供开发调试）")
        print()


# ── 启动入口 ─────────────────────────────────────────────────────────

def run() -> None:
    """MCP Server 启动入口，由 pyproject.toml scripts 注册为 opscli-mcp。

    支持命令行参数：
        --transport stdio|sse|http|both  传输协议（默认 stdio）
        --port <int>                     HTTP 模式监听端口（默认 8765）
        --host <str>                     HTTP 模式监听地址（默认 0.0.0.0）
        --auth-verify-url <url>          自定义 API Key 校验地址（可选）

    transport 取值说明：
        stdio  — 标准输入输出（本地 AI 工具集成，默认值）
        sse    — 仅 /sse 端点（SSE 传输，兼容旧客户端）
        http   — 仅 /mcp 端点（Streamable HTTP，ChatGPT 推荐）
        both   — /sse + /mcp 双端点（推荐远程部署方式）

    远程校验说明：
        HTTP/SSE 模式默认启用 OPS 远程校验（从 config.ini 读取 ops_url）。
        如需覆盖，使用 --auth-verify-url 指定自定义地址。

    启动示例：
        opscli-mcp --transport both --port 8765          # 自动远程校验
        opscli-mcp --transport both --auth-verify-url https://custom.com/v1/mcp/verify-key
    """
    from opscli.auth.config import get_ops_url

    transport_val: str | None = None
    host = "0.0.0.0"
    port = 8765
    auth_verify_url: str | None = None

    # 手动解析命令行参数（避免引入额外依赖）
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--transport" and i + 1 < len(args):
            transport_val = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--auth-verify-url" and i + 1 < len(args):
            auth_verify_url = args[i + 1]
            i += 2
        else:
            i += 1

    # ── HTTP 系模式：sse / http / both ──────────────────────────────
    if transport_val in ("sse", "http", "both"):
        import uvicorn

        from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

        # 自动设置默认远程校验地址（从 config.ini 读取 ops_url，已包含 /api 前缀）
        if not auth_verify_url:
            try:
                ops_base = get_ops_url().rstrip("/")
                auth_verify_url = f"{ops_base}/v1/mcp/verify-key"
            except Exception as exc:
                _logger.warning("无法从 config.ini 读取 ops_url: %s", exc)

        # 多用户模式：使用远程校验；单用户模式：使用固定 API Key
        if auth_verify_url:
            api_key = None
            _print_http_startup_banner(
                host, port, mode=transport_val,
                auth_verify_url=auth_verify_url,
            )
        else:
            api_key = _load_or_create_api_key()
            _print_http_startup_banner(
                host, port, mode=transport_val,
                api_key=api_key,
            )

        # 自动上报工具清单到后端管理库（守护线程，失败不影响启动）
        from opscli.mcp.tool_catalog import sync_catalog_async

        sync_catalog_async(auth_verify_url=auth_verify_url)

        if transport_val == "both":
            # 同时暴露 /sse（SSE）和 /mcp（Streamable HTTP）
            asgi_app = _build_dual_endpoint_app(
                api_key=api_key,
                auth_verify_url=auth_verify_url,
            )
        else:
            # 单端点模式：sse 或 http（streamable-http）
            # 通过 FastMCP.http_app() 创建子应用后包裹鉴权中间件
            transport_name = "sse" if transport_val == "sse" else "streamable-http"
            path = "/sse" if transport_val == "sse" else "/mcp"
            sub_app = mcp.http_app(path=path, transport=transport_name)
            asgi_app = ApiKeyAuthMiddleware(
                sub_app,
                api_key=api_key,
                auth_verify_url=auth_verify_url,
            )

        async def _serve() -> None:
            config = uvicorn.Config(
                asgi_app,
                host=host,
                port=port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()

        try:
            anyio.run(_serve)
        except KeyboardInterrupt:
            # Ctrl+C 正常停止服务器，静默退出
            pass
        return

    # ── stdio 模式（默认）───────────────────────────────────────────
    try:
        mcp.run(transport=transport_val)  # type: ignore[arg-type]
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
