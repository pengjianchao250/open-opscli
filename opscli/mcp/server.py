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
    opscli-mcp
    opscli-mcp --transport sse --port 8765
"""

from __future__ import annotations

import secrets
import stat
import string
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

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


# ── API Key 管理（仅 SSE 模式使用）──────────────────────────────────

def _generate_api_key() -> str:
    """生成固定格式的高熵 API Key。

    格式：opscli-mcp-<32位随机字母数字>

    Returns:
        高熵 API Key 字符串
    """
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(32))
    return "opscli-mcp-" + random_part


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


# ── 启动入口 ─────────────────────────────────────────────────────────

def run() -> None:
    """MCP Server 启动入口，由 pyproject.toml scripts 注册为 opscli-mcp。

    支持命令行参数：
        --transport stdio|sse   传输协议（默认 stdio）
        --port <int>            SSE 模式监听端口
        --host <str>            SSE 模式监听地址
    """
    transport_val: str | None = None
    kwargs: dict[str, Any] = {}

    # 手动解析命令行参数（避免引入额外依赖）
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
        from starlette.middleware import Middleware

        from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

        # 不使用 FastMCP 内置 AuthProvider，统一由自定义中间件处理
        # 同时支持 Header (Authorization: Bearer) 和 Query Param (?api_key=)
        kwargs["middleware"] = [
            Middleware(ApiKeyAuthMiddleware, api_key=api_key),
        ]
        print(f"\n[opscli-mcp] SSE 服务已启用 API Key 鉴权")
        print(f"[opscli-mcp] API Key: {api_key}\n")
        print("支持两种方式传入 API Key：")
        print("  1. HTTP Header: Authorization: Bearer <api_key>")
        print("  2. URL Query:   ?api_key=<api_key>\n")

    try:
        mcp.run(transport=transport_val, **kwargs)  # type: ignore[arg-type]
    except KeyboardInterrupt:
        # Ctrl+C 是服务器的正常停止方式，asyncio runner 会将任务取消转为
        # KeyboardInterrupt 向上抛出，这里捕获后静默退出即可
        pass


if __name__ == "__main__":
    run()
