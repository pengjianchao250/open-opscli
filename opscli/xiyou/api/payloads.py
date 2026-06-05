"""西柚洞察排行榜 payload 构造。"""

from __future__ import annotations

from typing import Any


def make_ranking_payload(params: dict[str, Any]) -> dict[str, Any]:
    """构造排行榜接口 payload。"""
    return {
        "biz": {
            "country": str(params.get("site") or "US").upper(),
            "filed": params.get("period") or "week",
            "page": int(params.get("page") or 1),
            "pageSize": int(params.get("page_size") or params.get("pageSize") or 50),
            "query": params.get("query") or "",
            "rankPattern": params.get("rank_pattern") or params.get("rankPattern"),
        }
    }

