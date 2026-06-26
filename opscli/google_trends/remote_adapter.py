"""Google Trends 远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class GoogleTrendsRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 命令映射到远端 Google Trends MCP tools。"""

    def scenarios(self) -> dict[str, Any]:
        """读取远端 Google Trends 场景列表。"""
        return self.call_tool("google_trends_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        geo: str,
        params: dict[str, Any],
        job_id: str | None,
        export_format: str,
        hl: str | None,
        tz: int | None,
    ) -> dict[str, Any]:
        """执行远端 Google Trends 场景。"""
        return self.call_tool(
            "google_trends_run",
            {
                "scenario": scenario,
                "geo": geo,
                "params": params,
                "job_id": job_id,
                "export_format": export_format,
                "hl": hl,
                "tz": tz,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """读取远端 Google Trends 任务结果。"""
        return self.call_tool("google_trends_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        """读取远端 Google Trends 导出文件信息。"""
        return self.call_tool("google_trends_export", {"job_id": job_id})
