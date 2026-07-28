"""ASIN Data 精简 CLI 的轻量 JSON 查询服务。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Callable, Sequence

from opscli.asin_data.services.bi_report_data import (
    BASIC_REPORT_SOURCE_KEYS,
    BI_QUERY_SOURCE_KEYS,
    SITE_CODE_ALIASES,
    AsinBiReportDataClient,
)
from opscli.asin_data.services.category_top import AsinCategoryTopClient


BASIC_SOURCE_ALIASES = {
    "listing": "listing_basic",
    "listing_basic": "listing_basic",
    "crawler": "crawler_details",
    "crawler_details": "crawler_details",
}
SUPPORTED_SITE_CODES = frozenset(SITE_CODE_ALIASES.values())
_ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


class AsinDataQueryService:
    """直接返回远端源 JSON，不生成工作簿或上传 OSS。"""

    def __init__(
        self,
        *,
        data_client: Any | None = None,
        top_client: Any | None = None,
        today_factory: Callable[[], date] | None = None,
    ) -> None:
        self._data_client = data_client or AsinBiReportDataClient()
        self._top_client = top_client or AsinCategoryTopClient()
        self._today_factory = today_factory or date.today

    def fetch_basic(
        self,
        *,
        asins: Sequence[str],
        site: str = "US",
        sources: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        normalized_asins = normalize_asins(asins)
        normalized_site = normalize_site(site)
        source_keys = _normalize_basic_sources(sources)
        bundle = self._data_client.fetch(
            asins=normalized_asins,
            source_keys=source_keys,
            site_by_asin={asin: normalized_site for asin in normalized_asins},
            default_site=normalized_site,
        )
        return _data_response(
            bundle=bundle,
            asins=normalized_asins,
            site=normalized_site,
            source_keys=source_keys,
        )

    def fetch_bi(
        self,
        *,
        asins: Sequence[str],
        site: str = "US",
        date_from: str | None = None,
        date_to: str | None = None,
        domains: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        normalized_asins = normalize_asins(asins)
        normalized_site = normalize_site(site)
        normalized_domains = _normalize_bi_domains(domains)
        start, end = _date_range(
            date_from=date_from,
            date_to=date_to,
            default_start=lambda today: today - timedelta(days=29),
            today=self._today_factory(),
        )
        bundle = self._data_client.fetch(
            asins=normalized_asins,
            start_date=start,
            end_date=end,
            source_keys=normalized_domains,
            site_by_asin={asin: normalized_site for asin in normalized_asins},
            default_site=normalized_site,
        )
        response = _data_response(
            bundle=bundle,
            asins=normalized_asins,
            site=normalized_site,
            source_keys=normalized_domains,
        )
        response.update(
            {
                "date_from": start,
                "date_to": end,
                "domains": list(normalized_domains),
            }
        )
        return response

    def fetch_category_top(
        self,
        *,
        category: str | None,
        data_type: str = "asin",
        site: str = "US",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        normalized_data_type = str(data_type).strip().lower()
        if normalized_data_type not in {"asin", "traffic"}:
            raise ValueError("data_type 仅支持 asin 或 traffic")
        normalized_category = str(category or "").strip() or None
        if normalized_data_type == "asin" and not normalized_category:
            raise ValueError("data_type=asin 时必须传入 category")
        start, end = _date_range(
            date_from=date_from,
            date_to=date_to,
            default_start=lambda today: today.replace(day=1),
            today=self._today_factory(),
        )
        if normalized_data_type == "traffic":
            result = self._top_client.fetch_traffic(
                category=normalized_category,
                date_from=start,
                date_to=end,
            )
            rows = result.get("rows") if isinstance(result.get("rows"), list) else []
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            return {
                "data_type": "traffic",
                "category": normalized_category,
                "date_from": start,
                "date_to": end,
                "row_count": len(rows),
                "category_total": metadata.get("category_total"),
                "category_names": metadata.get("category_names", []),
                "ranking_metric": metadata.get("ranking_metric"),
                "top_n": metadata.get("top_n"),
                "category_traffic": rows,
            }

        normalized_site = normalize_site(site)
        result = self._top_client.fetch(
            category=normalized_category,
            site=normalized_site,
            date_from=start,
            date_to=end,
            limit=limit,
        )
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        return {
            "category": normalized_category,
            "site": normalized_site,
            "date_from": start,
            "date_to": end,
            "limit": limit,
            "row_count": len(rows),
            "category_top": rows,
        }

def normalize_asins(asins: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in asins:
        normalized = str(value).strip().upper()
        if not normalized:
            continue
        if not _ASIN_PATTERN.fullmatch(normalized):
            raise ValueError(f"ASIN 格式无效：{value}")
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ValueError("至少需要传入一个 ASIN")
    return result


def normalize_site(site: str) -> str:
    normalized = SITE_CODE_ALIASES.get(str(site).strip()) or SITE_CODE_ALIASES.get(str(site).strip().upper())
    if not normalized or normalized not in SUPPORTED_SITE_CODES:
        allowed = ", ".join(sorted(SUPPORTED_SITE_CODES))
        raise ValueError(f"不支持的站点：{site}，可选值：{allowed}")
    return normalized


def _normalize_basic_sources(sources: Sequence[str] | None) -> tuple[str, ...]:
    if not sources:
        return BASIC_REPORT_SOURCE_KEYS
    result: list[str] = []
    for value in sources:
        key = BASIC_SOURCE_ALIASES.get(str(value).strip().lower())
        if not key:
            raise ValueError(f"不支持的 basic source：{value}，可选值：listing、crawler")
        if key not in result:
            result.append(key)
    return tuple(result)


def _normalize_bi_domains(domains: Sequence[str] | None) -> tuple[str, ...]:
    if not domains:
        return BI_QUERY_SOURCE_KEYS
    allowed = set(BI_QUERY_SOURCE_KEYS)
    result: list[str] = []
    for value in domains:
        key = str(value).strip().lower()
        if key not in allowed:
            raise ValueError(f"不支持的 BI domain：{value}，可选值：{', '.join(BI_QUERY_SOURCE_KEYS)}")
        if key not in result:
            result.append(key)
    return tuple(result)


def _date_range(
    *,
    date_from: str | None,
    date_to: str | None,
    default_start: Callable[[date], date],
    today: date,
) -> tuple[str, str]:
    try:
        start = date.fromisoformat(date_from) if date_from else default_start(today)
        end = date.fromisoformat(date_to) if date_to else today
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("date_from 不能晚于 date_to")
    if end > today:
        raise ValueError("日期范围不允许包含未来日期")
    return start.isoformat(), end.isoformat()


def _data_response(
    *,
    bundle: dict[str, Any],
    asins: list[str],
    site: str,
    source_keys: Sequence[str],
) -> dict[str, Any]:
    all_sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    sources = {key: all_sources.get(key, {}) for key in source_keys}
    return {
        "status": bundle.get("status", "success"),
        "asins": asins,
        "site": site,
        "source_count": len(sources),
        "row_count": sum(
            int(source.get("row_count") or 0)
            for source in sources.values()
            if isinstance(source, dict)
        ),
        "sources": sources,
    }
