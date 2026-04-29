"""opscli MCP Server 入口。

基于 fastmcp 将 opscli 核心能力暴露为 MCP Tools。
**无状态设计**：服务器不保存任何用户 OAuth 凭证，所有认证信息由调用方传入。

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
    opscli-mcp --transport both --port 8765       # /sse + /mcp 双端点（推荐远程部署）

传输协议说明：
    - sse:   旧式 SSE 传输，在 GET /sse 建立事件流，POST /messages/ 投递消息
             兼容 Cursor、Claude Desktop、Cherry Studio 等客户端
    - http:  Streamable HTTP 传输，所有请求走 POST /mcp
             为 ChatGPT / OpenAI Apps SDK 等推荐协议
    - both:  同时暴露 /sse（SSE）和 /mcp（Streamable HTTP），推荐远程部署使用
"""

from __future__ import annotations

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
        "Aukeys 运营 CLI 工具集 MCP 接口（无状态模式）。\n"
        "服务器不保存用户凭证，所有认证信息（session_id / jwt）由调用方传入。\n"
        "典型流程：auth_login_start → 浏览器授权 → auth_login_poll → "
        "保存返回的 session_id → 后续 tool 调用传入 session_id（和可选的 jwt）。"
    ),
)

# ── 工具注册（按领域分模块，各模块暴露 register(mcp) 函数）─────────
from opscli.mcp.tools import auth as _auth_tools
from opscli.mcp.tools import chatgpt as _chatgpt_tools
from opscli.mcp.tools import query as _query_tools
from opscli.mcp.tools import skills as _skills_tools

_auth_tools.register(mcp)
_chatgpt_tools.register(mcp)
_query_tools.register(mcp)
_skills_tools.register(mcp)

# amazon 工具依赖可选扩展 playwright，未安装时跳过注册不影响其他工具
try:
    from opscli.mcp.tools import amazon as _amazon_tools

    _amazon_tools.register(mcp)
except (ImportError, ModuleNotFoundError):
    # playwright 或 opscli[amazon] 未安装，amazon_* 工具不可用
    _logger.info("amazon 工具未加载：缺少 playwright 依赖，安装命令：pip install opscli[amazon] && playwright install chromium")


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


# ── 双端点组合应用构建 ───────────────────────────────────────────────

def _build_dual_endpoint_app(api_key: str) -> Any:
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
        api_key: 鉴权用的 API Key，中间件会同时检查 Header 和 Query Param。

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
    return ApiKeyAuthMiddleware(combined, api_key=api_key)


def _print_http_startup_banner(api_key: str, host: str, port: int, mode: str) -> None:
    """打印 HTTP 模式启动信息。

    Args:
        api_key: 当前使用的 API Key
        host:    监听地址
        port:    监听端口
        mode:    "sse" | "http" | "both"
    """
    base_url = f"https://<your-domain>"  # 实际部署时替换为公网域名
    local_url = f"http://{host}:{port}"

    print(f"\n[opscli-mcp] 服务已启动（模式：{mode}）")
    print(f"[opscli-mcp] API Key: {api_key}")
    print()
    print("鉴权方式（选其一）：")
    print(f"  Authorization: Bearer {api_key}")
    print(f"  ?api_key={api_key}")
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

    transport 取值说明：
        stdio  — 标准输入输出（本地 AI 工具集成，默认值）
        sse    — 仅 /sse 端点（SSE 传输，兼容旧客户端）
        http   — 仅 /mcp 端点（Streamable HTTP，ChatGPT 推荐）
        both   — /sse + /mcp 双端点（推荐远程部署方式）
    """
    transport_val: str | None = None
    host = "0.0.0.0"
    port = 8765

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
        else:
            i += 1

    # ── HTTP 系模式：sse / http / both ──────────────────────────────
    if transport_val in ("sse", "http", "both"):
        import uvicorn

        from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

        api_key = _load_or_create_api_key()
        _print_http_startup_banner(api_key, host, port, mode=transport_val)

        if transport_val == "both":
            # 同时暴露 /sse（SSE）和 /mcp（Streamable HTTP）
            asgi_app = _build_dual_endpoint_app(api_key)
        else:
            # 单端点模式：sse 或 http（streamable-http）
            # 通过 FastMCP.http_app() 创建子应用后包裹鉴权中间件
            transport_name = "sse" if transport_val == "sse" else "streamable-http"
            path = "/sse" if transport_val == "sse" else "/mcp"
            sub_app = mcp.http_app(path=path, transport=transport_name)
            asgi_app = ApiKeyAuthMiddleware(sub_app, api_key=api_key)

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
