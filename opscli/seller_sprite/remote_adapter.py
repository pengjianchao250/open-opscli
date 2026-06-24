"""卖家精灵正式 CLI 的远端 MCP 适配层。"""

from __future__ import annotations

import asyncio
from typing import Any

from opscli.auth import AuthClient
from opscli.mcp_client import McpConfigClient, RemoteMcpClient


class SellerSpriteRemoteAdapter:
    """将正式 CLI 动作映射到远端卖家精灵 MCP 工具。"""

    def __init__(
        self,
        config_client=None,
        remote_client_factory=None,
        auth_client: AuthClient | None = None,
    ) -> None:
        self.config_client = config_client or McpConfigClient()
        self.remote_client_factory = remote_client_factory or RemoteMcpClient
        self.auth_client = auth_client or getattr(self.config_client, "auth_client", None) or AuthClient()

    def scenarios(self) -> dict[str, Any]:
        return self._call_tool("seller_sprite_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        site: str,
        period: str,
        params: dict[str, Any],
        page_size: int,
        export_format: str,
        output_dir: str | None,
        job_id: str | None,
    ) -> dict[str, Any]:
        session_id = self.auth_client.get_session("ops")
        return self._call_tool(
            "seller_sprite_run",
            {
                "scenario": scenario,
                "site": site,
                "period": period,
                "params": params,
                "page_size": page_size,
                "export_format": export_format,
                "output_dir": output_dir,
                "job_id": job_id,
                "session_id": session_id,
            },
        )

    def quota_status(self) -> dict[str, Any]:
        return self._call_tool("seller_sprite_quota_status", {})

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self._call_tool("seller_sprite_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        return self._call_tool("seller_sprite_export", {"job_id": job_id})

    def _build_remote_client(self) -> RemoteMcpClient:
        payload = self.config_client.fetch_remote_config()
        server = self.config_client.select_server(
            payload,
            transport="http",
            preferred_name="BI运营系统",
        )
        return self.remote_client_factory(server.url)

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        client = self._build_remote_client()
        try:
            return asyncio.run(client.call_tool(tool_name, arguments))
        except PermissionError as exc:
            if "401" not in str(exc):
                raise
        refreshed_client = self._build_remote_client()
        return asyncio.run(refreshed_client.call_tool(tool_name, arguments))
