"""Keepa Response Object 格式化共用函数。"""

from __future__ import annotations

from typing import Any

from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
    keepa_minutes_to_utc_iso,
)

# Keepa domain 对应币种及最小货币单位小数位，依据官方 locale 定义。
DOMAIN_CURRENCY_INFO: dict[int, tuple[str, int]] = {
    1: ("USD", 2),
    2: ("GBP", 2),
    3: ("EUR", 2),
    4: ("EUR", 2),
    5: ("JPY", 0),
    6: ("CAD", 2),
    8: ("EUR", 2),
    9: ("EUR", 2),
    10: ("INR", 2),
    11: ("MXN", 2),
    12: ("BRL", 2),
}

# 用户站点别名到 Keepa domain id 的映射。
SITE_DOMAIN = {
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

# Keepa domain 对应 Amazon 前台域名，用于生成可点击的类目链接。
AMAZON_HOST = {
    1: "www.amazon.com",
    2: "www.amazon.co.uk",
    3: "www.amazon.de",
    4: "www.amazon.fr",
    5: "www.amazon.co.jp",
    6: "www.amazon.ca",
    8: "www.amazon.it",
    9: "www.amazon.es",
    10: "www.amazon.in",
    11: "www.amazon.com.mx",
    12: "www.amazon.com.br",
}

# Keepa 图片文件名使用的 Amazon CDN 固定前缀。
IMAGE_BASE_URL = "https://m.media-amazon.com/images/I"


def domain_number(*, site: str, domain_id: Any = None) -> int:
    """解析 Keepa domain id。

    参数：site 为站点代码，domain_id 为响应或请求中的可选 domain。
    返回：整数 domain id；解析失败时按 site 映射，最终回退到 US。
    """
    try:
        return int(domain_id)
    except (TypeError, ValueError):
        return SITE_DOMAIN.get(str(site or "US").upper(), 1)


def currency_info(*, site: str, domain_id: Any = None) -> tuple[str, int]:
    """返回指定站点的币种代码和最小货币单位小数位数。"""
    return DOMAIN_CURRENCY_INFO.get(
        domain_number(site=site, domain_id=domain_id), ("USD", 2)
    )


def money_amount(value: Any, *, decimals: int) -> float | int | None:
    """把 Keepa 最小货币单位转换为可读金额，缺失哨兵值返回空。"""
    if value in (None, -1, -2):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if decimals == 0:
        return int(number)
    return round(number / (10**decimals), decimals)


def add_time_fields(row: dict[str, Any], field: str) -> None:
    """原地为合法 Keepa Time 字段追加 UTC 和 Unix 时间。"""
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return
    row[f"{field}Utc"] = keepa_minutes_to_utc_iso(value)
    row[f"{field}UnixSeconds"] = keepa_minutes_to_unix_seconds(value)
    row[f"{field}UnixMilliseconds"] = keepa_minutes_to_unix_milliseconds(value)


def image_url(value: Any) -> str | None:
    """把 Keepa 图片文件名转换为 Amazon CDN URL，无有效值时返回空。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return text
    return f"{IMAGE_BASE_URL}/{text.lstrip('/')}"


def category_url(category_id: Any, *, site: str, domain_id: Any = None) -> str | None:
    """按类目 ID 和站点生成 Amazon 类目浏览 URL。"""
    if category_id in (None, ""):
        return None
    domain = domain_number(site=site, domain_id=domain_id)
    return f"https://{AMAZON_HOST.get(domain, AMAZON_HOST[1])}/s?node={category_id}"


def string_id(value: Any) -> str | None:
    """把可能超过 Excel 精确整数范围的 ID 固定为字符串。"""
    return None if value in (None, "") else str(value)
