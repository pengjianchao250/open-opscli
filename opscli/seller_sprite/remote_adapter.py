"""卖家精灵正式 CLI 的远端 MCP 适配层。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opscli.auth import AuthClient
from opscli.mcp_client import McpConfigClient, RemoteMcpClient
from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


OPS_REMOTE_MCP_SERVER_NAME = "BI运营系统"


class SellerSpriteRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 动作映射到远端卖家精灵 MCP 工具。"""

    def __init__(
        self,
        config_client: McpConfigClient | None = None,
        remote_client_factory: Callable[[str], RemoteMcpClient] | None = None,
        auth_client: AuthClient | None = None,
    ) -> None:
        """初始化正式 CLI 的 SellerSprite 远端适配器。

        Args:
            config_client: 获取当前用户远端 MCP 配置的客户端；默认自动创建。
            remote_client_factory: 根据 MCP URL 创建远端客户端的工厂；默认使用正式实现。
            auth_client: 旧调用方注入的本地认证客户端。仅保留构造与属性兼容，
                不再从中读取或向 SellerSprite Tool 传递 Session/JWT。
        """
        super().__init__(
            config_client=config_client,
            remote_client_factory=remote_client_factory,
            preferred_name=OPS_REMOTE_MCP_SERVER_NAME,
            require_preferred=True,
        )
        self.auth_client = (
            auth_client
            or getattr(self.config_client, "auth_client", None)
            or AuthClient()
        )

    def scenarios(self) -> dict[str, Any]:
        """获取卖家精灵远端可用场景列表。"""
        return self.call_tool("seller_sprite_scenarios", {})

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
        """执行卖家精灵远端任务，认证由 MCP API Key 对应的隔离凭证提供。"""
        return self.call_tool(
            "seller_sprite_run",
            {
                "scenario": scenario,
                "site": site,
                "period": period,
                "params": params,
                "page_size": page_size,
                "export_format": export_format,
                "job_id": job_id,
            },
        )

    def quota_status(self) -> dict[str, Any]:
        """查询卖家精灵远端额度状态。"""
        return self.call_tool("seller_sprite_quota_status", {})

    def listing_analysis_submit(
        self,
        *,
        asin: str,
        station: str,
        site: str,
        export_format: str,
        output_dir: str | None,
        job_id: str | None,
    ) -> dict[str, Any]:
        """提交 Listing Analysis 远端异步任务。"""
        return self.call_tool(
            "seller_sprite_listing_analysis_submit",
            {
                "asin": asin,
                "station": station,
                "site": site,
                "export_format": export_format,
                "job_id": job_id,
            },
        )

    def listing_analysis_status(self, job_id: str) -> dict[str, Any]:
        """查询 Listing Analysis 远端任务状态。"""
        return self.call_tool("seller_sprite_listing_analysis_status", {"job_id": job_id})

    def listing_analysis_result(self, job_id: str, *, export_format: str) -> dict[str, Any]:
        """读取 Listing Analysis 远端任务结果。"""
        return self.call_tool(
            "seller_sprite_listing_analysis_result",
            {"job_id": job_id, "export_format": export_format},
        )

    def job_status(self, job_id: str, wait_seconds: int = 0) -> dict[str, Any]:
        """查询单个卖家精灵远端任务状态。"""
        return self.call_tool(
            "seller_sprite_job_status",
            {"job_id": job_id, "wait_seconds": wait_seconds},
        )

    def jobs_status(self, job_ids: list[str], wait_seconds: int = 0) -> dict[str, Any]:
        """按输入顺序批量查询卖家精灵远端任务状态。"""
        return self.call_tool(
            "seller_sprite_jobs_status",
            {"job_ids": job_ids, "wait_seconds": wait_seconds},
        )

    def export(self, job_id: str) -> dict[str, Any]:
        """读取卖家精灵远端任务导出信息。"""
        return self.call_tool("seller_sprite_export", {"job_id": job_id})
