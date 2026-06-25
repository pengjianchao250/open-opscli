"""Keepa 远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class KeepaRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 命令映射到远端 Keepa MCP tools。"""

    def scenarios(self) -> dict[str, Any]:
        """读取远端 Keepa 场景列表。"""
        return self.call_tool("keepa_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        site: str,
        params: dict[str, Any],
        job_id: str | None,
        export_format: str,
        reserve_tokens: int | None,
        force: bool,
        wait: bool,
    ) -> dict[str, Any]:
        """执行远端 Keepa 场景。"""
        return self.call_tool(
            "keepa_run",
            {
                "scenario": scenario,
                "site": site,
                "params": params,
                "job_id": job_id,
                "export_format": export_format,
                "reserve_tokens": reserve_tokens,
                "force": force,
                "wait": wait,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取远端 Keepa 任务结果。"""
        return self.call_tool("keepa_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        """读取远端 Keepa 导出文件信息。"""
        return self.call_tool("keepa_export", {"job_id": job_id})
