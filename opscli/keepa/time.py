"""Keepa time minutes conversion helpers.

Keepa stores many timestamps as minutes since its own epoch. Convert them to
UTC Unix epoch values with:

seconds = (keepa_time + 21564000) * 60
milliseconds = (keepa_time + 21564000) * 60000
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


KEEPA_TIME_OFFSET_MINUTES = 21_564_000

_SKIP_TIME_KEYS = {
    "timestamp",
    "requesttime",
    "processingtimeinms",
    "refillin",
    "refillrate",
    "tokensleft",
    "tokensconsumed",
}

_EXACT_TIME_KEYS = {
    "lastupdate",
    "lastpricechange",
    "lastratingupdate",
    "laststockupdate",
    "lastoffersupdate",
    "tracking since",
    "trackingsince",
    "listedsince",
    "lastseen",
}


def keepa_minutes_to_unix_seconds(keepa_time: int | float | str) -> int:
    """Convert Keepa time minutes to a UTC Unix timestamp in seconds."""
    return int((_parse_keepa_time(keepa_time) + KEEPA_TIME_OFFSET_MINUTES) * 60)


def keepa_minutes_to_unix_milliseconds(keepa_time: int | float | str) -> int:
    """Convert Keepa time minutes to a UTC Unix timestamp in milliseconds."""
    return int((_parse_keepa_time(keepa_time) + KEEPA_TIME_OFFSET_MINUTES) * 60000)


def keepa_minutes_to_utc_iso(keepa_time: int | float | str) -> str:
    """Convert Keepa time minutes to an ISO-8601 UTC string."""
    seconds = keepa_minutes_to_unix_seconds(keepa_time)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def add_keepa_time_conversions(value: Any) -> Any:
    """Return a copy with derived UTC fields for common Keepa time values.

    The original values are preserved. Raw Keepa payloads should remain stored
    separately for exact backend comparison.
    """
    if isinstance(value, list):
        return [add_keepa_time_conversions(item) for item in value]
    if not isinstance(value, dict):
        return value

    converted: dict[str, Any] = {}
    for key, item in value.items():
        converted[key] = add_keepa_time_conversions(item)
        if _should_convert_scalar_key(key, item):
            converted[f"{key}UnixSeconds"] = keepa_minutes_to_unix_seconds(item)
            converted[f"{key}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(item)
            converted[f"{key}Utc"] = keepa_minutes_to_utc_iso(item)
        elif key == "csv" and _looks_like_csv(item):
            converted["csvUnixSeconds"] = [_convert_pair_series(series) for series in item]
    return converted


def _parse_keepa_time(value: int | float | str) -> float:
    if isinstance(value, bool):
        raise ValueError("Keepa time cannot be a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        raise ValueError("Keepa time cannot be empty")
    return float(text)


def _should_convert_scalar_key(key: str, value: Any) -> bool:
    if not _is_keepa_minute_value(value):
        return False
    normalized = key.replace("_", "").replace("-", "").lower()
    if normalized in _SKIP_TIME_KEYS:
        return False
    if normalized in _EXACT_TIME_KEYS:
        return True
    return normalized.endswith("lastseen") or normalized.endswith("lastupdate")


def _is_keepa_minute_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = _parse_keepa_time(value)
    except (TypeError, ValueError):
        return False
    return 0 <= parsed <= 20_000_000


def _looks_like_csv(value: Any) -> bool:
    return isinstance(value, list) and any(_looks_like_pair_series(item) for item in value)


def _looks_like_pair_series(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 2 and len(value) % 2 == 0 and _is_keepa_minute_value(value[0])


def _convert_pair_series(series: Any) -> Any:
    if not _looks_like_pair_series(series):
        return series
    converted: list[Any] = []
    for index, item in enumerate(series):
        if index % 2 == 0 and _is_keepa_minute_value(item):
            converted.append(keepa_minutes_to_unix_seconds(item))
        else:
            converted.append(item)
    return converted
