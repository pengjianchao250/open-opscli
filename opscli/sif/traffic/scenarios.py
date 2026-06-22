"""Sif traffic download scenarios."""

from __future__ import annotations

from typing import Any


TRAFFIC_STRUCTURE_PATH = "/api/struct/listingscore/chart/download"
TRAFFIC_KEYWORDS_PATH = "/api/updown/asinKeywordList/download"
TRAFFIC_MULTI_NF_PATH = "/api/updown/asinMultiNf/keywordList/download"

DEFAULT_TRAFFIC_SECTIONS = ["structure", "keywords", "multi_nf"]
TRAFFIC_SECTION_ALIASES = {
    "流量结构": "structure",
    "查流量结构": "structure",
    "structure": "structure",
    "keywords": "keywords",
    "反查流量词": "keywords",
    "流量词": "keywords",
    "查流量词": "keywords",
    "multi-nf": "multi_nf",
    "multi_nf": "multi_nf",
    "多变体自然位": "multi_nf",
    "查多变体自然位": "multi_nf",
}


def listing_score_chart_query(*, asin: str, country: str, time_piece_type: str, time_piece_value: str) -> dict[str, Any]:
    return {
        "country": country,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
        "asin": asin,
        "dimension": "asin",
        "desc": True,
    }


def asin_keyword_list_payload(
    *,
    asin: str,
    time_piece_type: str,
    time_piece_value: str,
    page_num: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    return {
        "pageSize": page_size,
        "pageNum": page_num,
        "sort": "scoreInfo.scoreRatio",
        "desc": True,
        "conditions": ["totalPeriod.total"],
        "keyword": "",
        "asin": asin,
        "listingSearch": False,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
        "keywordSearch": "",
    }


def asin_multi_nf_payload(
    *,
    asin: str,
    time_piece_type: str,
    time_piece_value: str,
    page_num: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return {
        "searchKeyword": "",
        "pageNum": page_num,
        "pageSize": page_size,
        "searchAsin": "",
        "sortBy": "nfScore",
        "desc": True,
        "asin": asin,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
    }


def traffic_referer(*, asin: str, country: str, time_piece_type: str, time_piece_value: str) -> str:
    return (
        "https://www.sif.com/Traffic"
        f"?country={country}&asin={asin}&timePieceType={time_piece_type}&timePieceValue={time_piece_value}"
    )
