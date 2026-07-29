"""MCP 工具清单采集与后端自动同步。

工具注册时由 server.py 的注册代理调用 record_tool() 采集元数据
（工具名、所属模块、描述），HTTP/SSE 模式启动时自动上报后端
POST /v1/mcp/sync-tools，使新增工具无需人工在管理后台录入。

同步语义（与后端 McpToolSyncController 约定一致）：
- 只增不删：新模块/新工具自动入库并启用；代码中已移除的工具不会被自动停用
  （某台服务器可能缺少可选依赖如 playwright，按单台上报停用会误伤其他部署）
- 已有工具仅刷新 description（以代码 docstring 为准）；label、is_active 等
  人工维护字段不被覆盖
- stdio 本地模式不上报（团队后台清单由统一部署的 HTTP 服务维护）
"""

from __future__ import annotations

import logging
import threading

from opscli.config import __version__

_logger = logging.getLogger("opscli.mcp.tool_catalog")

# 通用 MCP 的进程内默认工具清单，保留供现有调用方兼容访问。
_CATALOG: list[dict] = []


class ToolCatalog:
    """隔离保存单个 MCP 服务已注册的工具清单。"""

    def __init__(self) -> None:
        self._items: list[dict] = []
        self._names: set[str] = set()

    def record(self, *, name: str, module: str, description: str | None) -> None:
        """记录工具元数据，重复工具名直接失败关闭。"""
        if name in self._names:
            raise ValueError(f"MCP 工具名重复：{name}")
        self._names.add(name)
        self._items.append(_build_catalog_item(name, module, description))

    def get_catalog(self) -> list[dict]:
        """返回当前服务工具清单的副本。"""
        return list(self._items)


def _build_catalog_item(name: str, module: str, description: str | None) -> dict:
    """构造后端工具清单使用的稳定元数据。"""
    return {
        "name": name,
        "module": module,
        # 后端 description 字段上限 255，超长截断
        "description": (description or "").strip()[:255],
    }


def record_tool(*, name: str, module: str, description: str | None) -> None:
    """记录通用 MCP 工具元数据，保留原有全局接口和注册语义。"""
    _CATALOG.append(_build_catalog_item(name, module, description))


def get_catalog() -> list[dict]:
    """返回通用 MCP 已采集的工具清单（副本）。"""
    return list(_CATALOG)


def extract_description(fn, kwargs: dict) -> str | None:
    """从注册参数或函数 docstring 提取工具描述。

    优先级：注册时显式传入的 description 参数 > docstring 首行。
    """
    desc = kwargs.get("description")
    if desc:
        return str(desc)
    doc = getattr(fn, "__doc__", None)
    if doc:
        # docstring 首行通常是一句中文摘要，适合作为管理后台的说明
        first_line = doc.strip().splitlines()[0].strip()
        return first_line or None
    return None


def _do_sync(sync_url: str, catalog: list[dict] | None = None) -> None:
    """同步执行清单上报（在守护线程中调用，失败仅记日志不影响服务启动）。"""
    tools = list(_CATALOG if catalog is None else catalog)
    try:
        import httpx

        resp = httpx.post(
            sync_url,
            json={"tools": tools, "opscli_version": __version__},
            headers={"X-Opscli-Version": __version__},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _logger.info(
                "MCP 工具清单已同步：新增模块 %s 个，新增工具 %s 个，更新描述 %s 个",
                data.get("created_modules", 0),
                data.get("created_tools", 0),
                data.get("updated_tools", 0),
            )
        elif resp.status_code == 404:
            # 旧后端未部署同步端点，静默跳过（灰度兼容）
            _logger.info("后端暂未部署 /v1/mcp/sync-tools，跳过工具清单同步")
        else:
            _logger.warning("MCP 工具清单同步失败：HTTP %s", resp.status_code)
    except Exception as exc:
        # 同步失败不能影响 MCP 服务启动
        _logger.warning("MCP 工具清单同步异常: %s", exc)


def sync_catalog_async(
    auth_verify_url: str | None = None,
    *,
    catalog: list[dict] | None = None,
) -> None:
    """启动守护线程上报指定服务工具清单。"""
    tools = list(_CATALOG if catalog is None else catalog)
    if not tools:
        return
    try:
        if auth_verify_url and auth_verify_url.endswith("/verify-key"):
            # 与远程校验同一后端：.../v1/mcp/verify-key → .../v1/mcp/sync-tools
            sync_url = auth_verify_url[: -len("/verify-key")] + "/sync-tools"
        else:
            from opscli.auth.config import get_ops_url

            sync_url = f"{get_ops_url().rstrip('/')}/v1/mcp/sync-tools"
    except Exception as exc:
        _logger.warning("无法推导工具清单同步地址: %s", exc)
        return

    threading.Thread(
        target=_do_sync,
        args=(sync_url, tools),
        daemon=True,
        name="mcp-tool-sync",
    ).start()
