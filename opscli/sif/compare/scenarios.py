"""Sif compare download scenarios."""

from __future__ import annotations

from typing import Any


COMPARE_SALES_PATH = "/api/updown/boughtByAsin/download"
COMPARE_SUMMARY_PATH = "/api/compare/summary/multiAsin/download"
COMPARE_MY_KEYWORDS_PATH = "/api/compare/compareMyKeywords/download"

DEFAULT_COMPARE_SECTIONS = ["sales", "traffic_words", "traffic_score", "my_traffic_keywords", "my_ad_keywords"]
COMPARE_SECTION_ALIASES = {
    "sales": "sales",
    "对比销量": "sales",
    "traffic-structure": "traffic_words",
    "对比流量结构": "traffic_words",
    "traffic_words": "traffic_words",
    "流量词": "traffic_words",
    "对比流量词": "traffic_words",
    "对比流量词结构": "traffic_words",
    "traffic_score": "traffic_score",
    "traffic-score": "traffic_score",
    "流量分": "traffic_score",
    "对比流量分": "traffic_score",
    "traffic-keywords": "my_traffic_keywords",
    "my_traffic_keywords": "my_traffic_keywords",
    "重点流量词": "my_traffic_keywords",
    "my_ad_keywords": "my_ad_keywords",
    "重点广告词": "my_ad_keywords",
}


def compare_sales_payload(
    *,
    asins: list[str],
    time_piece_type: str,
    time_piece_value: str,
    page_num: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return {
        "pageNum": page_num,
        "pageSize": page_size,
        "sortBy": "",
        "desc": True,
        "asins": asins,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
    }


def compare_summary_payload(
    *,
    asins: list[str],
    time_piece_type: str,
    time_piece_value: str,
    show_type: int,
) -> dict[str, Any]:
    return {
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
        "type": 1,
        "sortBy": "",
        "desc": True,
        "searchValue": ",".join(asins),
        "showType": show_type,
    }


def compare_my_keywords_payload(
    *,
    asins: list[str],
    time_piece_type: str,
    time_piece_value: str,
    list_type: int,
    page_num: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    return {
        "isMine": False,
        "vipModule": False,
        "asins": asins,
        "sortBy": "",
        "desc": True,
        "strategy": "legacyForSales_exact",
        "granularity": "week",
        "myPageNum": page_num,
        "myPageSize": page_size,
        "listType": list_type,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
        "myCompareField": "",
    }
