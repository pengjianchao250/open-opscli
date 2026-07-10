"""Scrape.do 远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class ScrapeDoRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 命令映射到远端 Scrape.do MCP tools。"""

    def scenarios(self) -> dict[str, Any]:
        """读取远端 Scrape.do 场景列表。"""
        return self.call_tool("scrape_do_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        site: str,
        params: dict[str, Any],
        job_id: str | None,
        export_format: str,
        timeout_seconds: int | None,
    ) -> dict[str, Any]:
        """执行远端 Scrape.do 场景。"""
        return self.call_tool(
            "scrape_do_run",
            {
                "scenario": scenario,
                "site": site,
                "params": params,
                "job_id": job_id,
                "export_format": export_format,
                "timeout_seconds": timeout_seconds,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取远端 Scrape.do 任务结果。"""
        return self.call_tool("scrape_do_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        """读取远端 Scrape.do 导出文件信息。"""
        return self.call_tool("scrape_do_export", {"job_id": job_id})
