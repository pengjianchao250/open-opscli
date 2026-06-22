"""Sif ranking scenarios."""

from __future__ import annotations

from typing import Any


RANKING_LIST_PATH = "/api/search/subscribe/v2"
RANKING_DOWNLOAD_PATH = "/api/updown/userSubs/download"

DEFAULT_RANKING_SECTIONS = ["daily_ranking"]
RANKING_SECTION_ALIASES = {
    "daily-ranking": "daily_ranking",
    "daily_ranking": "daily_ranking",
    "每日排名": "daily_ranking",
    "查排名": "daily_ranking",
    "推排名": "daily_ranking",
    "查坑位": "daily_ranking",
}

RANKING_GRANULARITIES = {"week", "month"}


def normalize_ranking_granularity(value: str | None) -> str:
    granularity = (value or "week").strip().lower()
    if granularity not in RANKING_GRANULARITIES:
        supported = ", ".join(sorted(RANKING_GRANULARITIES))
        raise ValueError(f"查排名 granularity 仅支持：{supported}")
    return granularity


def ranking_list_payload(
    *,
    asin: str,
    granularity: str = "week",
    page_num: int = 1,
    page_size: int = 200,
) -> dict[str, Any]:
    return {
        "filterAsin": "",
        "granularity": granularity,
        "asin": asin,
        "endDay": None,
        "pageNum": page_num,
        "pageSize": page_size,
        "interval": 7,
        "sortBy": "estSearchesNum",
        "desc": True,
        "isListingSearch": True,
        "isExample": True,
    }


def ranking_download_payload(*, asin: str, granularity: str = "week") -> dict[str, Any]:
    return {
        "isListingSearch": True,
        "asin": asin,
        "granularity": granularity,
        "isExample": True,
    }
