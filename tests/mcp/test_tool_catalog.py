"""MCP 工具清单采集与同步测试。"""

import httpx
import pytest
import respx

from opscli.mcp import tool_catalog
from opscli.mcp.tool_catalog import ToolCatalog, _do_sync, extract_description, get_catalog


def test_extract_description_prefers_kwargs():
    """注册参数显式传入 description 时优先于 docstring。"""

    def fn():
        """docstring 首行。"""

    assert extract_description(fn, {"description": "显式描述"}) == "显式描述"


def test_extract_description_falls_back_to_docstring_first_line():
    """无 description 参数时取 docstring 首行。"""

    def fn():
        """工具摘要在首行。

        第二段详细说明不应被采集。
        """

    assert extract_description(fn, {}) == "工具摘要在首行。"


def test_isolated_catalog_rejects_duplicate_tool_name():
    catalog = ToolCatalog()
    catalog.record(name="demo_tool", module="demo", description="演示")

    with pytest.raises(ValueError, match="工具名重复"):
        catalog.record(name="demo_tool", module="other", description="重复")


def test_extract_description_handles_missing_doc():
    """无 docstring 时返回 None。"""

    def fn():
        pass

    assert extract_description(fn, {}) is None


def test_server_registration_populates_catalog():
    """导入 server 后清单应包含全部注册工具，且模块归属精确。"""
    import opscli.mcp.server  # noqa: F401  导入即触发注册与采集

    catalog = {t["name"]: t for t in get_catalog()}

    # chatgpt 模块工具名无前缀，模块归属必须来自 __module__ 而非前缀切分
    assert catalog["fetch"]["module"] == "chatgpt"
    assert catalog["search"]["module"] == "chatgpt"
    # 多段前缀模块不能被切分成 "seller"
    assert catalog["seller_sprite_run"]["module"] == "seller_sprite"
    # 描述来自 docstring 首行，非空
    assert catalog["query_simple"]["description"]


@respx.mock
def test_do_sync_posts_catalog(monkeypatch):
    """同步请求携带工具清单，200 响应正常解析。"""
    monkeypatch.setattr(tool_catalog, "_CATALOG", [
        {"name": "demo_tool", "module": "demo", "description": "演示"},
    ])
    route = respx.post("https://ops.example.com/api/v1/mcp/sync-tools").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "created_modules": 1, "created_tools": 1, "updated_tools": 0},
        )
    )

    _do_sync("https://ops.example.com/api/v1/mcp/sync-tools")

    assert route.calls.call_count == 1
    body = route.calls[0].request.content
    assert b"demo_tool" in body


@respx.mock
def test_do_sync_tolerates_404_and_network_error(monkeypatch):
    """旧后端 404 与网络异常均不抛出（不影响服务启动）。"""
    monkeypatch.setattr(tool_catalog, "_CATALOG", [
        {"name": "demo_tool", "module": "demo", "description": ""},
    ])
    respx.post("https://ops.example.com/api/v1/mcp/sync-tools").mock(
        return_value=httpx.Response(404)
    )
    _do_sync("https://ops.example.com/api/v1/mcp/sync-tools")  # 不应抛异常

    respx.post("https://ops.example.com/api/v1/mcp/sync-tools").mock(
        side_effect=httpx.ConnectError("refused")
    )
    _do_sync("https://ops.example.com/api/v1/mcp/sync-tools")  # 不应抛异常
