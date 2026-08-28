"""Keepa Tracking and Notification response formatting helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from opscli.keepa.object_formatting import add_time_fields, currency_info, image_url, money_amount
from opscli.keepa.product_formatter import CSV_SERIES


TRACKING_NOTIFICATION_CHANNELS = (
    "reserved_0",
    "reserved_1",
    "reserved_2",
    "reserved_3",
    "reserved_4",
    "api",
    "reserved_6",
)

# Notification.currentPrices uses the same complete CSV type indexing as Product.
# Keep the source of truth in product_formatter so newly supported CSV types are
# not silently rendered as unknown notification prices.
CURRENT_PRICE_TYPES = {
    index: (
        config.name,
        "money" if config.kind in {"price", "shipping_price"} else config.kind,
    )
    for index, config in CSV_SERIES.items()
}

TRACKING_NOTIFICATION_CAUSES = {
    0: "EXPIRED",
    1: "DESIRED_PRICE",
    3: "PRICE_CHANGE_AFTER_DESIRED_PRICE",
    4: "OUT_STOCK",
    5: "IN_STOCK",
}


@dataclass
class FormattedTrackingExport:
    """Tracking 主表及其规则、通知明细。"""

    trackings: list[dict[str, Any]]
    thresholds: list[dict[str, Any]]
    notify_if: list[dict[str, Any]]
    notification_csv: list[dict[str, Any]]
    nested_values: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: rows
            for name, rows in {
                "tracking_thresholds": self.thresholds,
                "tracking_notify_if": self.notify_if,
                "tracking_notification_csv": self.notification_csv,
                "tracking_nested_values": self.nested_values,
            }.items()
            if rows
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "trackings": self.trackings,
            "tracking_thresholds": self.thresholds,
            "tracking_notify_if": self.notify_if,
            "tracking_notification_csv": self.notification_csv,
            "tracking_nested_values": self.nested_values,
        }


@dataclass
class FormattedNotificationExport:
    """Notification 主表及价格、通知通道明细。"""

    notifications: list[dict[str, Any]]
    current_prices: list[dict[str, Any]]
    sent_via: list[dict[str, Any]]
    nested_values: list[dict[str, Any]]

    def extra_sheets(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: rows
            for name, rows in {
                "notification_current_prices": self.current_prices,
                "notification_sent_via": self.sent_via,
                "notification_nested_values": self.nested_values,
            }.items()
            if rows
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "notifications": self.notifications,
            "notification_current_prices": self.current_prices,
            "notification_sent_via": self.sent_via,
            "notification_nested_values": self.nested_values,
        }


def format_tracking_export(
    rows: list[Any], *, site: str = "US", domain_id: Any = None
) -> FormattedTrackingExport:
    """Format Tracking Objects while preserving all unknown response fields."""
    trackings: list[dict[str, Any]] = []
    thresholds: list[dict[str, Any]] = []
    notify_if: list[dict[str, Any]] = []
    notification_csv: list[dict[str, Any]] = []
    nested_values: list[dict[str, Any]] = []

    for value in rows:
        if not isinstance(value, dict):
            trackings.append({"value": value})
            continue
        tracking_id = value.get("asin")
        detail_fields = {"thresholdValues", "notifyIf", "notificationType", "notificationCSV"}
        row = {key: item for key, item in value.items() if key not in detail_fields}
        _remove_nested_fields(row)
        for field in ("createDate", "lastUpdate", "lastNotification"):
            add_time_fields(row, field)
        row["thresholdCount"] = len(_list(value.get("thresholdValues")))
        row["notifyIfCount"] = len(_list(value.get("notifyIf")))
        channels = _channels(value.get("notificationType"))
        row["notificationTypeJoined"] = ", ".join(channels) if channels else None
        row["trackingRawJson"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        trackings.append(row)

        for index, threshold in enumerate(_list(value.get("thresholdValues"))):
            detail = {
                "asin": tracking_id,
                "trackingListName": value.get("trackingListName"),
                "thresholdIndex": index,
            }
            if isinstance(threshold, dict):
                detail.update(threshold)
                csv = threshold.get("thresholdValueCSV")
                if isinstance(csv, list):
                    base_detail = dict(detail)
                    base_detail["thresholdValueCSVJoined"] = ", ".join(str(item) for item in csv)
                    pairs = list(zip(csv[0::2], csv[1::2]))
                    if not pairs:
                        _stringify_nested_fields(base_detail)
                        thresholds.append(base_detail)
                        continue
                    for history_index, (keepa_time, threshold_value) in enumerate(pairs):
                        history_detail = dict(base_detail)
                        history_detail["thresholdHistoryIndex"] = history_index
                        history_detail["thresholdKeepaTime"] = keepa_time
                        history_detail["thresholdValue"] = threshold_value
                        add_time_fields(history_detail, "thresholdKeepaTime")
                        _stringify_nested_fields(history_detail)
                        thresholds.append(history_detail)
                    continue
            else:
                detail["value"] = threshold
            _stringify_nested_fields(detail)
            thresholds.append(detail)

        for index, rule in enumerate(_list(value.get("notifyIf"))):
            detail = {
                "asin": tracking_id,
                "trackingListName": value.get("trackingListName"),
                "notifyIfIndex": index,
            }
            detail.update(rule if isinstance(rule, dict) else {"value": rule})
            _stringify_nested_fields(detail)
            notify_if.append(detail)

        notification_csv.extend(_tracking_notification_rows(value))
        _append_nested_values(
            nested_values,
            parent_id=tracking_id,
            value=value,
            excluded=detail_fields,
        )

    return FormattedTrackingExport(trackings, thresholds, notify_if, notification_csv, nested_values)


def format_notification_export(
    rows: list[Any], *, site: str = "US", domain_id: Any = None
) -> FormattedNotificationExport:
    """Format Notification Objects into a main table and typed detail tables."""
    notifications: list[dict[str, Any]] = []
    current_prices: list[dict[str, Any]] = []
    sent_via: list[dict[str, Any]] = []
    nested_values: list[dict[str, Any]] = []

    for value in rows:
        if not isinstance(value, dict):
            notifications.append({"value": value})
            continue
        asin = value.get("asin")
        row = {key: item for key, item in value.items() if key not in {"currentPrices", "sentNotificationVia"}}
        _remove_nested_fields(row)
        add_time_fields(row, "createDate")
        row["imageUrl"] = image_url(value.get("image"))
        row["currentPriceCount"] = len(_list(value.get("currentPrices")))
        channels = _channels(value.get("sentNotificationVia"))
        row["sentNotificationViaJoined"] = ", ".join(channels) if channels else None
        row["notificationRawJson"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        notifications.append(row)

        notification_domain = value.get("notificationDomainId", value.get("domainId", domain_id))
        currency_code, decimals = currency_info(site=site, domain_id=notification_domain)
        for index, raw_value in enumerate(_list(value.get("currentPrices"))):
            price_type, value_kind = CURRENT_PRICE_TYPES.get(index, (f"CSV_{index}", "unknown"))
            current_prices.append(_current_price_row(
                asin=asin,
                index=index,
                price_type=price_type,
                value_kind=value_kind,
                raw_value=raw_value,
                currency_code=currency_code,
                decimals=decimals,
            ))
        for index, enabled in enumerate(_list(value.get("sentNotificationVia"))):
            sent_via.append(
                {
                    "asin": asin,
                    "channelIndex": index,
                    "channel": TRACKING_NOTIFICATION_CHANNELS[index]
                    if index < len(TRACKING_NOTIFICATION_CHANNELS)
                    else f"channel_{index}",
                    "enabled": enabled,
                }
            )
        _append_nested_values(
            nested_values,
            parent_id=asin,
            value=value,
            excluded={"currentPrices", "sentNotificationVia"},
        )

    return FormattedNotificationExport(notifications, current_prices, sent_via, nested_values)


def _tracking_notification_rows(value: dict[str, Any]) -> list[dict[str, Any]]:
    csv = value.get("notificationCSV")
    if not isinstance(csv, list):
        return []
    rows: list[dict[str, Any]] = []
    for history_index in range(0, len(csv), 5):
        entry = csv[history_index : history_index + 5]
        row: dict[str, Any] = {
            "asin": value.get("asin"),
            "trackingListName": value.get("trackingListName"),
            "notificationHistoryIndex": history_index // 5,
            "notificationCSVJoined": ", ".join(str(item) for item in entry),
            "rawNotificationCSVJson": json.dumps(entry, ensure_ascii=False, separators=(",", ":")),
        }
        if len(entry) > 0:
            row["notificationDomainId"] = entry[0]
        if len(entry) > 1:
            row["csvType"] = entry[1]
        if len(entry) > 2:
            row["notificationType"] = entry[2]
        if len(entry) > 3:
            row["notificationCause"] = entry[3]
            row["notificationCauseLabel"] = TRACKING_NOTIFICATION_CAUSES.get(entry[3])
        if len(entry) > 4:
            row["notificationKeepaTime"] = entry[4]
            add_time_fields(row, "notificationKeepaTime")
        rows.append(row)
    return rows


def _current_price_row(
    *,
    asin: Any,
    index: int,
    price_type: str,
    value_kind: str,
    raw_value: Any,
    currency_code: str,
    decimals: int,
) -> dict[str, Any]:
    row = {
        "asin": asin,
        "priceTypeIndex": index,
        "priceType": price_type,
        "valueKind": value_kind,
        "rawValue": raw_value,
        "currencyCode": currency_code,
    }
    if value_kind == "money":
        row["amount"] = money_amount(raw_value, decimals=decimals)
    elif value_kind == "rating":
        row["amount"] = _rating_stars(raw_value)
    else:
        row["amount"] = None if raw_value in (-1, -2) else raw_value
    return row


def _rating_stars(value: Any) -> float | None:
    if value in (None, -1, -2):
        return None
    try:
        return float(value) / 10
    except (TypeError, ValueError):
        return None


def _channels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        TRACKING_NOTIFICATION_CHANNELS[index]
        if index < len(TRACKING_NOTIFICATION_CHANNELS)
        else f"channel_{index}"
        for index, enabled in enumerate(value)
        if enabled is True
    ]


def _append_nested_values(
    rows: list[dict[str, Any]], *, parent_id: Any, value: dict[str, Any], excluded: set[str]
) -> None:
    for field, child in value.items():
        if field in excluded or field in {"trackingRaw", "notificationRaw"}:
            continue
        if isinstance(child, (dict, list)):
            _append_leaves(rows, parent_id=parent_id, field=field, path=field, value=child)


def _append_leaves(
    rows: list[dict[str, Any]], *, parent_id: Any, field: str, path: str, value: Any
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _append_leaves(rows, parent_id=parent_id, field=field, path=f"{path}.{key}", value=child)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _append_leaves(rows, parent_id=parent_id, field=field, path=f"{path}[{index}]", value=child)
        return
    rows.append({"id": parent_id, "field": field, "path": path, "value": value})


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _remove_nested_fields(row: dict[str, Any]) -> None:
    for field, value in list(row.items()):
        if isinstance(value, (dict, list)):
            row.pop(field)


def _stringify_nested_fields(row: dict[str, Any]) -> None:
    for field, value in list(row.items()):
        if isinstance(value, (dict, list)):
            row[field] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
