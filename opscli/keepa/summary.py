"""Keepa 任务结果的小型公开摘要。"""

from __future__ import annotations

from typing import Any

# MCP 和 result.json 最多保留 5 行摘要，完整记录统一从导出文件读取。
KEEPA_SUMMARY_ROW_LIMIT = 5
# 白名单只包含识别结果所需的标量字段，避免历史、Offer 等嵌套值进入上下文。
KEEPA_SUMMARY_FIELDS = (
    "asin",
    "title",
    "brand",
    "sellerId",
    "sellerName",
    "categoryId",
    "catId",
    "name",
    "dealId",
    "dealState",
    "totalResults",
    "bestSellerRank",
)


def summarize_rows(
    rows: list[Any],
    *,
    limit: int = KEEPA_SUMMARY_ROW_LIMIT,
) -> list[Any]:
    """压缩 Keepa 结果行。

    Args:
        rows: Keepa 主结果行；对象行可能包含大型嵌套字段。
        limit: 最多保留的摘要行数。

    Returns:
        最多 ``limit`` 行的标量白名单摘要；标量结果行保持原值。
    """
    return [_summarize_row(row) for row in rows[:limit]]


def _summarize_row(row: Any) -> Any:
    """为单行保留稳定标识字段，标量列表则保持原值。"""
    if not isinstance(row, dict):
        return row
    return {
        field: row[field]
        for field in KEEPA_SUMMARY_FIELDS
        if field in row and not isinstance(row[field], (dict, list))
    }
