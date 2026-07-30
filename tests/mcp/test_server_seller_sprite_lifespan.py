"""通用 MCP 与卖家精灵 Collector 生命周期边界测试。"""

from starlette.testclient import TestClient


def test_general_mcp_does_not_start_seller_sprite_scheduler(monkeypatch):
    """通用 MCP 只代理卖家精灵，不得启动本地任务调度器。"""
    from opscli.mcp.server import _build_dual_endpoint_app
    from opscli.seller_sprite import services

    def fail_if_called():
        raise AssertionError("通用 MCP 不应创建 SellerSprite scheduler")

    monkeypatch.setattr(services, "get_task_scheduler", fail_if_called)
    app = _build_dual_endpoint_app(api_key="test-api-key")

    with TestClient(app):
        pass


def test_general_mcp_registers_seller_sprite_proxy_tools():
    """通用 MCP 保留同名 Tool，但注册器必须来自代理模块。"""
    from opscli.mcp.server import _REGISTRARS
    from opscli.mcp.tools import seller_sprite_proxy

    assert seller_sprite_proxy.register in _REGISTRARS
    assert all(
        registrar.__module__ != "opscli.mcp.tools.seller_sprite"
        for registrar in _REGISTRARS
    )
