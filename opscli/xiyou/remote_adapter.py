"""西柚正式 CLI 的远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class XiyouRemoteAdapter(RemoteMcpAdapter):
    """复用 Keepa 的配置与传输链路，供应商凭据由远端管理。"""

    def operations(self) -> dict[str, Any]:
        """读取远端西柚操作目录，不调用供应商收费接口。"""
        return self.call_tool("ext_xydc_openapi_operations", {})

    def call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """原样透传业务参数，不转换页码、日期或重新执行失败查询。"""
        return self.call_tool(
            "ext_xydc_openapi_call", {"operation": operation, "payload": payload}
        )
