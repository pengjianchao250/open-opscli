"""Keepa Best Sellers Object formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)


DOMAIN_INFO: dict[int, tuple[str, str]] = {
    1: ("US", "www.amazon.com"),
    2: ("GB", "www.amazon.co.uk"),
    3: ("DE", "www.amazon.de"),
    4: ("FR", "www.amazon.fr"),
    5: ("JP", "www.amazon.co.jp"),
    6: ("CA", "www.amazon.ca"),
    8: ("IT", "www.amazon.it"),
    9: ("ES", "www.amazon.es"),
    10: ("IN", "www.amazon.in"),
    11: ("MX", "www.amazon.com.mx"),
    12: ("BR", "www.amazon.com.br"),
}

SITE_DOMAIN: dict[str, int] = {
    "US": 1,
    "GB": 2,
    "UK": 2,
    "DE": 3,
    "FR": 4,
    "JP": 5,
    "CA": 6,
    "IT": 8,
    "ES": 9,
    "IN": 10,
    "MX": 11,
    "BR": 12,
}


@dataclass
class FormattedBestSellersExport:
    list_rows: list[dict[str, Any]]
    asin_rows: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        if not self.list_rows:
            return {}
        return {"best_sellers_list": self.list_rows}

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_sellers_list": self.list_rows,
            "best_seller_asins": self.asin_rows,
        }


def format_best_sellers_export(
    best_sellers: Any,
    *,
    site: str = "US",
    domain_id: Any = None,
    category_id: Any = None,
) -> FormattedBestSellersExport | None:
    """Format a Keepa Best Sellers Object into summary and ASIN tables."""
    if not isinstance(best_sellers, dict):
        return None
    list_row = format_best_sellers_object(
        best_sellers,
        site=site,
        domain_id=domain_id,
        category_id=category_id,
    )
    return FormattedBestSellersExport(
        list_rows=[list_row],
        asin_rows=_asin_rows(best_sellers, list_row),
    )


def format_best_sellers_object(
    best_sellers: dict[str, Any],
    *,
    site: str = "US",
    domain_id: Any = None,
    category_id: Any = None,
) -> dict[str, Any]:
    """Return a Best Sellers Object copy with derived summary fields."""
    row = dict(best_sellers)
    domain = _parse_int(best_sellers.get("domainId")) or _parse_int(domain_id) or SITE_DOMAIN.get(str(site).upper(), 1)
    domain_code, host = DOMAIN_INFO.get(domain, (str(site).upper(), "www.amazon.com"))
    category = best_sellers.get("categoryId") or category_id
    asin_list = best_sellers.get("asinList")

    row["rowSource"] = "bestSellersList"
    row["domainId"] = domain
    row["domain"] = domain_code
    row["amazonHost"] = host
    if category is not None:
        row["categoryId"] = str(category)
        row["categoryUrl"] = f"https://{host}/b?node={category}"
    if isinstance(asin_list, list):
        row["asinCount"] = len(asin_list)
        row["asinListJoined"] = ", ".join(str(asin) for asin in asin_list)
    _add_keepa_time_fields(row, "lastUpdate")
    row["bestSellersListRaw"] = best_sellers
    return row


def _asin_rows(best_sellers: dict[str, Any], list_row: dict[str, Any]) -> list[dict[str, Any]]:
    asin_list = best_sellers.get("asinList")
    if not isinstance(asin_list, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, asin in enumerate(asin_list, start=1):
        rows.append(
            {
                "domainId": list_row.get("domainId"),
                "domain": list_row.get("domain"),
                "amazonHost": list_row.get("amazonHost"),
                "categoryId": list_row.get("categoryId"),
                "categoryUrl": list_row.get("categoryUrl"),
                "lastUpdate": list_row.get("lastUpdate"),
                "lastUpdateUtc": list_row.get("lastUpdateUtc"),
                "asinCount": list_row.get("asinCount"),
                "bestSellerRank": index,
                "asin": str(asin),
                "rowSource": "bestSellersList",
            }
        )
    return rows


def _add_keepa_time_fields(row: dict[str, Any], field: str) -> None:
    value = row.get(field)
    if not _is_valid_keepa_time(value):
        return
    row[f"{field}UnixSeconds"] = keepa_minutes_to_unix_seconds(value)
    row[f"{field}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(value)
    row[f"{field}Utc"] = keepa_minutes_to_utc_iso(value)


def _is_valid_keepa_time(value: Any) -> bool:
    number = _parse_number(value)
    return number is not None and number > 0


def _parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_int(value: Any) -> int | None:
    number = _parse_number(value)
    if number is None:
        return None
    return int(number)
