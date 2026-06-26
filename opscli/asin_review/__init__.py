"""复盘 ASIN 数据查询模块。

提供 CLI 命令和 MCP Tool，用于从运营系统拉取指定 ASIN 的复盘仪表盘数据。
"""

from opscli.asin_review.services.manager import AsinReviewManager

__all__ = ["AsinReviewManager"]
