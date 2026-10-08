"""鹰眼 PND 正式 CLI 的远端 MCP 适配层。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opscli.mcp_client import McpConfigClient, RemoteMcpClient
from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class YingyanRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 动作映射到远端鹰眼 PND MCP Tools。"""

    def __init__(
        self,
        config_client: McpConfigClient | None = None,
        remote_client_factory: Callable[[str], RemoteMcpClient] | None = None,
    ) -> None:
        super().__init__(
            config_client=config_client,
            remote_client_factory=remote_client_factory,
            preferred_name="BI运营系统",
            require_preferred=True,
        )

    def list_available_datasets(self) -> dict[str, Any]:
        """读取当前用户可访问的鹰眼数据集目录。"""
        return self.call_tool("ext_pnd_list_available_datasets", {})

    def execute_readonly_sql(self, sql: str) -> dict[str, Any]:
        """执行一条由目录约束且已收窄的只读 SQL。"""
        return self.call_tool("ext_pnd_execute_readonly_sql", {"sql": sql})

    def search_similar_terms(
        self,
        *,
        search_term: str,
        site: str | None = None,
        top: int | None = None,
    ) -> dict[str, Any]:
        """按站点和种子词查询相似搜索词。"""
        return self.call_tool(
            "ext_pnd_search_similar_terms",
            {
                "search_term": search_term,
                "site": site,
                "top": top,
            },
        )

    def report_task_status(self, task_id: str) -> dict[str, Any]:
        """查询已有鹰眼报告任务状态。"""
        return self.call_tool("ext_pnd_get_report_task_status", {"task_id": task_id})
