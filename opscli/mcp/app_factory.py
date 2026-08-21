"""MCP 服务实例与传输层共享工厂。"""

from __future__ import annotations

import logging
import stat
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastmcp import FastMCP
from fastmcp.tools import FunctionTool, Tool

from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
from opscli.mcp.tool_catalog import ToolCatalog, extract_description

_logger = logging.getLogger("opscli.mcp.app_factory")
ToolRegistrar = Callable[[Any], None]


class InstrumentedMcpProxy:
    """注册 Tool 时统一叠加限额、遥测和清单采集。"""

    def __init__(
        self,
        real_mcp: FastMCP,
        *,
        catalog: ToolCatalog | None = None,
    ) -> None:
        self._real = real_mcp
        self._catalog = catalog

    def tool(self, *args, **kwargs):
        """代理 FastMCP Tool 装饰器并采集最终工具名。"""
        real_decorator = self._real.tool(*args, **kwargs)

        def wrap(fn):
            name = kwargs.get("name") or fn.__name__
            module = getattr(
                fn,
                "__opscli_catalog_module__",
                fn.__module__.rsplit(".", 1)[-1],
            )
            description = extract_description(fn, kwargs)
            self._record_tool(name=name, module=module, description=description)
            # 代理 Tool 的业务额度由目标 MCP 统一处理，避免跨服务重复扣减。
            instrumented = fn if getattr(fn, "__opscli_skip_quota__", False) else quota_wrap(fn)
            runtime_role = getattr(fn, "__opscli_telemetry_role__", "executor")
            return real_decorator(
                telemetry_wrap(
                    instrumented,
                    module=module,
                    runtime_role=runtime_role,
                )
            )

        return wrap

    def add_tool(self, tool: FunctionTool) -> Tool:
        """注册带冻结 Schema 的动态 Tool，并保持现有治理切面。

        参数:
            tool: 已完成名称、描述和输入 Schema 审批的动态函数工具。

        返回:
            FastMCP 实际注册后的工具对象。

        异常:
            TypeError: 传入对象不是 ``FunctionTool`` 时抛出。
        """
        if not isinstance(tool, FunctionTool):
            raise TypeError("InstrumentedMcpProxy.add_tool 仅接受 FunctionTool")
        fn = tool.fn
        module = getattr(
            fn,
            "__opscli_catalog_module__",
            fn.__module__.rsplit(".", 1)[-1],
        )
        self._record_tool(
            name=tool.name,
            module=module,
            description=tool.description,
        )
        instrumented = fn if getattr(fn, "__opscli_skip_quota__", False) else quota_wrap(fn)
        runtime_role = getattr(fn, "__opscli_telemetry_role__", "executor")
        wrapped_tool = tool.model_copy(
            update={
                "fn": telemetry_wrap(
                    instrumented,
                    module=module,
                    runtime_role=runtime_role,
                )
            }
        )
        return self._real.add_tool(wrapped_tool)

    def _record_tool(self, *, name: str, module: str, description: str | None) -> None:
        """把静态和动态 Tool 写入同一份服务清单。"""
        if self._catalog is None:
            from opscli.mcp.tool_catalog import record_tool

            record_tool(name=name, module=module, description=description)
        else:
            self._catalog.record(name=name, module=module, description=description)

    def __getattr__(self, name: str):
        """其余属性直接转发到真实 FastMCP 实例。"""
        return getattr(self._real, name)


def create_mcp_app(
    *,
    name: str,
    instructions: str,
    registrars: list[ToolRegistrar],
    catalog: ToolCatalog | None = None,
    lifespan=None,
) -> FastMCP:
    """创建完成中间件和显式 Tool 注册的 FastMCP 实例。"""
    mcp = FastMCP(
        name=name,
        instructions=instructions,
        lifespan=lifespan,
    )
    proxy = InstrumentedMcpProxy(mcp, catalog=catalog)
    for register in registrars:
        register(proxy)

    from opscli.mcp.permissions import ToolPermissionMiddleware

    mcp.add_middleware(ToolPermissionMiddleware())
    return mcp


def build_dual_endpoint_app(
    mcp: FastMCP,
    *,
    api_key: str | None = None,
    auth_verify_url: str | None = None,
    app_wrapper: Callable[[Any], Any] | None = None,
) -> Any:
    """构建同时暴露 SSE 与 Streamable HTTP 的鉴权 ASGI 应用。"""
    from starlette.applications import Starlette

    from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

    sse_sub_app = mcp.http_app(path="/sse", transport="sse")
    http_sub_app = mcp.http_app(path="/mcp", transport="streamable-http")
    combined_routes = list(sse_sub_app.routes) + list(http_sub_app.routes)

    @asynccontextmanager
    async def _combined_lifespan(_app: Any):
        async with sse_sub_app.lifespan(sse_sub_app):
            async with http_sub_app.lifespan(http_sub_app):
                yield

    combined = Starlette(routes=combined_routes, lifespan=_combined_lifespan)
    if app_wrapper is not None:
        # 服务可在鉴权中间件外层组装前扩展自身资源生命周期。
        combined = app_wrapper(combined)
    return ApiKeyAuthMiddleware(
        combined,
        api_key=api_key,
        auth_verify_url=auth_verify_url,
    )


def _generate_api_key() -> str:
    """使用现有用户存储实现生成固定格式的高熵 API Key。"""
    from opscli.mcp.user_store import generate_api_key

    return generate_api_key()


def _load_or_create_api_key(filename: str) -> str:
    """从配置目录加载或创建服务固定 API Key。"""
    from opscli.config import CONFIG_DIR

    key_path = Path(CONFIG_DIR) / filename
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()

    api_key = _generate_api_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(api_key, encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return api_key


def _print_http_startup_banner(
    *,
    service_name: str,
    host: str,
    port: int,
    mode: str,
    api_key: str | None,
    auth_verify_url: str | None,
) -> None:
    """打印不包含真实公网地址的 HTTP 启动信息。"""
    local_url = f"http://{host}:{port}"
    print(f"\n[{service_name}] 服务已启动（模式：{mode}）")
    if auth_verify_url:
        print(f"[{service_name}] 远程校验模式：{auth_verify_url}")
    elif api_key:
        print(f"[{service_name}] 固定 API Key: {api_key}")
    if mode in {"sse", "both"}:
        print(f"[{service_name}] SSE: {local_url}/sse")
    if mode in {"http", "both"}:
        print(f"[{service_name}] Streamable HTTP: {local_url}/mcp")


def run_mcp_app(
    mcp: FastMCP,
    *,
    service_name: str,
    catalog: list[dict],
    api_key_filename: str = "mcp_api_key",
    app_wrapper: Callable[[Any], Any] | None = None,
) -> None:
    """按统一参数解析规则运行 MCP 服务。"""
    from opscli.auth.config import get_ops_url

    transport_val: str | None = None
    host = "0.0.0.0"
    port = 8765
    auth_verify_url: str | None = None
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        if args[index] == "--transport" and index + 1 < len(args):
            transport_val = args[index + 1]
            index += 2
        elif args[index] == "--port" and index + 1 < len(args):
            port = int(args[index + 1])
            index += 2
        elif args[index] == "--host" and index + 1 < len(args):
            host = args[index + 1]
            index += 2
        elif args[index] == "--auth-verify-url" and index + 1 < len(args):
            auth_verify_url = args[index + 1]
            index += 2
        else:
            index += 1

    if transport_val not in {"sse", "http", "both"}:
        try:
            mcp.run(transport=transport_val)  # type: ignore[arg-type]
        except KeyboardInterrupt:
            pass
        return

    import uvicorn

    from opscli.mcp.auth_middleware import ApiKeyAuthMiddleware

    if not auth_verify_url:
        try:
            auth_verify_url = f"{get_ops_url().rstrip('/')}/v1/mcp/verify-key"
        except Exception as exc:
            _logger.warning("无法从 config.ini 读取 ops_url: %s", exc)

    api_key = None if auth_verify_url else _load_or_create_api_key(api_key_filename)
    _print_http_startup_banner(
        service_name=service_name,
        host=host,
        port=port,
        mode=transport_val,
        api_key=api_key,
        auth_verify_url=auth_verify_url,
    )

    from opscli.mcp.tool_catalog import sync_catalog_async

    sync_catalog_async(auth_verify_url=auth_verify_url, catalog=catalog)
    if transport_val == "both":
        asgi_app = build_dual_endpoint_app(
            mcp,
            api_key=api_key,
            auth_verify_url=auth_verify_url,
            app_wrapper=app_wrapper,
        )
    else:
        transport_name = "sse" if transport_val == "sse" else "streamable-http"
        path = "/sse" if transport_val == "sse" else "/mcp"
        sub_app = mcp.http_app(path=path, transport=transport_name)
        if app_wrapper is not None:
            sub_app = app_wrapper(sub_app)
        asgi_app = ApiKeyAuthMiddleware(
            sub_app,
            api_key=api_key,
            auth_verify_url=auth_verify_url,
        )

    async def _serve() -> None:
        config = uvicorn.Config(asgi_app, host=host, port=port, log_level="info")
        await uvicorn.Server(config).serve()

    try:
        anyio.run(_serve)
    except KeyboardInterrupt:
        pass
