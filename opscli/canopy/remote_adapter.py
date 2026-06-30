"""Canopy 远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class CanopyRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 命令映射到远端 beta Canopy MCP tools。"""

    def scenarios(self) -> dict[str, Any]:
        """读取远端 Canopy 场景列表。"""
        return self.call_tool("beta_canopy_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        domain: str,
        params: dict[str, Any],
        job_id: str | None,
        export_format: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """执行远端 Canopy 场景。"""
        return self.call_tool(
            "beta_canopy_run",
            {
                "scenario": scenario,
                "domain": domain,
                "params": params,
                "job_id": job_id,
                "export_format": export_format,
                "timeout_seconds": timeout_seconds,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取远端 Canopy 任务结果。"""
        return self.call_tool("beta_canopy_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        """读取远端 Canopy 导出文件信息。"""
        return self.call_tool("beta_canopy_export", {"job_id": job_id})
