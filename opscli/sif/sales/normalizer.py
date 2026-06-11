"""Sif 查销量响应规范化。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class SifSalesNormalizer:
    """将 Sif 原始响应整理为稳定 JSON。"""

    schema_version = "sif_sales.v1"

    def normalize(
        self,
        *,
        asin: str,
        site: str,
        range_value: str | None,
        time_piece_type: str = "latelyDay",
        time_piece_value: str = "30",
        page_num: int = 1,
        page_size: int = 100,
        listing_history: dict[str, Any],
        group_variants: dict[str, Any],
        exports: dict[str, Any],
    ) -> dict[str, Any]:
        """生成稳定结构，保留原始字段引用。"""
        normalized_asin = asin.strip().upper()
        normalized_site = site.strip().upper()
        return {
            "schema_version": self.schema_version,
            "feature": "查销量",
            "provider": "sif",
            "asin": normalized_asin,
            "site": normalized_site,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "query": {
                "asin": normalized_asin,
                "site": normalized_site,
                "range": range_value,
                "time_piece_type": time_piece_type,
                "time_piece_value": str(time_piece_value),
                "page_num": page_num,
                "page_size": page_size,
            },
            "summary": self._summary(listing_history=listing_history, group_variants=group_variants),
            "listing_history": {
                "variant_sales": self._series(listing_history, ("data", "variantSales")),
                "color_sales": self._series(listing_history, ("data", "colorSales")),
                "size_sales": self._series(listing_history, ("data", "sizeSales")),
            },
            "group_variants": self._group_variants(group_variants),
            "exports": exports,
            "raw_refs": {
                "listing_history": "raw.json#/listing_history_response",
                "group_variants": "raw.json#/group_variants_response",
            },
        }

    def _summary(self, *, listing_history: dict[str, Any], group_variants: dict[str, Any]) -> dict[str, Any]:
        return {
            "listing_history_keys": sorted(list(listing_history.keys())),
            "group_variant_count": len(self._group_variants(group_variants)),
        }

    def _series(self, payload: dict[str, Any], path: tuple[str, ...]) -> list[dict[str, Any]]:
        value: Any = payload
        for key in path:
            if not isinstance(value, dict):
                return []
            value = value.get(key)
        if not isinstance(value, list):
            return []
        return [self._series_item(item) for item in value if isinstance(item, dict)]

    def _series_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "series_key": str(item.get("key") or item.get("asin") or item.get("name") or ""),
            "asin": str(item.get("asin") or ""),
            "label": str(item.get("label") or item.get("name") or ""),
            "color": item.get("color"),
            "size": item.get("size"),
            "points": self._points(item),
            "source_fields": item,
        }

    def _points(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        points = item.get("points") or item.get("data") or item.get("values")
        if not isinstance(points, list):
            return []
        normalized = []
        for point in points:
            if isinstance(point, dict):
                normalized.append(
                    {
                        "date": point.get("date") or point.get("x") or point.get("month"),
                        "sales": point.get("sales") or point.get("value") or point.get("y"),
                        "source_fields": point,
                    }
                )
        return normalized

    def _group_variants(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        items = data.get("asin") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [self._variant_item(item) for item in items if isinstance(item, dict)]

    def _variant_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "asin": str(item.get("asin") or item.get("childAsin") or ""),
            "title": item.get("title") or item.get("name"),
            "price": item.get("price"),
            "color": item.get("color"),
            "size": item.get("size"),
            "recent_30d_sales_text": item.get("recent30dSales") or item.get("salesText"),
            "recent_30d_sales_value": item.get("recent30dSalesValue") or item.get("sales"),
            "trend": item.get("trend") if isinstance(item.get("trend"), list) else [],
            "source_fields": item,
        }

