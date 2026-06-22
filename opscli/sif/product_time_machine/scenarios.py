"""Sif product time machine scenarios."""

from __future__ import annotations

from typing import Any


PRODUCT_TIME_MACHINE_LIST_PATH = "/api/search/bought/keyword"
PRODUCT_TIME_MACHINE_DOWNLOAD_PATH = "/api/updown/boughtByKeyword/download"

DEFAULT_PRODUCT_TIME_MACHINE_SECTIONS = ["product_time_machine"]
PRODUCT_TIME_MACHINE_SECTION_ALIASES = {
    "product-time-machine": "product_time_machine",
    "product_time_machine": "product_time_machine",
    "产品时光机": "product_time_machine",
    "关键词产品时光机": "product_time_machine",
}


def product_time_machine_list_payload(
    *,
    keyword: str,
    time_piece_type: str = "latelyDay",
    time_piece_value: str = "7",
    page_num: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return {
        "pageNum": page_num,
        "pageSize": page_size,
        "sortBy": "",
        "desc": True,
        "keyword": keyword,
        "timePieceType": time_piece_type,
        "timePieceValue": str(time_piece_value),
    }


def product_time_machine_download_payload(
    *,
    keyword: str,
    time_piece_type: str = "latelyDay",
    time_piece_value: str = "7",
) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "sortBy": "",
        "desc": True,
        "timePieceValue": str(time_piece_value),
        "timePieceType": time_piece_type,
    }
