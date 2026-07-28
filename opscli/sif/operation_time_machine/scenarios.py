"""Sif operation time machine scenarios."""

from __future__ import annotations

from typing import Any


OPERATION_TIME_MACHINE_LIST_PATH = "/api/search/timeMachine/asinOpTrafficTrend/list"
OPERATION_TIME_MACHINE_DOWNLOAD_PATH = "/api/updown/timeMachine/asinOpTrafficTrend/download"

DEFAULT_OPERATION_TIME_MACHINE_SECTIONS = ["traffic_change"]
OPERATION_TIME_MACHINE_SECTION_ALIASES = {
    "traffic-change": "traffic_change",
    "traffic_change": "traffic_change",
    "流量变化": "traffic_change",
    "运营时光机": "traffic_change",
    "运营流量趋势": "traffic_change",
    "keyword-count-change": "keyword_count_change",
    "keyword_count_change": "keyword_count_change",
    "流量词数量变化": "keyword_count_change",
}

OPERATION_GRANULARITIES = {"day", "week", "month"}
OPERATION_LAST_MONTHS = {3, 6, 12, 24}


def normalize_operation_granularity(value: str | None) -> str:
    granularity = (value or "day").strip().lower()
    if granularity not in OPERATION_GRANULARITIES:
        supported = ", ".join(sorted(OPERATION_GRANULARITIES))
        raise ValueError(f"运营时光机 granularity 仅支持：{supported}")
    return granularity


def normalize_last_months(value: int | None) -> int:
    months = int(value or 6)
    if months not in OPERATION_LAST_MONTHS:
        supported = ", ".join(str(item) for item in sorted(OPERATION_LAST_MONTHS))
        raise ValueError(f"运营时光机 last-months 仅支持：{supported}")
    return months


def operation_time_machine_payload(
    *,
    asin: str,
    granularity: str = "day",
    last_months: int = 6,
    change_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "granularity": granularity,
        "asin": asin,
        "endDay": None,
        "interval": None,
        "listingSearch": False,
        "lastMonths": last_months,
    }
    if change_type:
        payload["type"] = change_type
    return payload


def change_type_for_section(section: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    if section == "keyword_count_change":
        return "all"
    return None
