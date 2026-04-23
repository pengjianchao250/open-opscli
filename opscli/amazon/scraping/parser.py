"""amazon 模块字段标准化工具。"""

from __future__ import annotations

import re


_PRICE_PATTERN = re.compile(r"(\d[\d,]*\.?\d*)")
_RATING_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
_INTEGER_PATTERN = re.compile(r"(\d[\d,]*)")
_LABELED_REVIEW_COUNT_PATTERN = re.compile(r"(\d[\d,]*)\s+(?:ratings?|reviews?)\b", re.IGNORECASE)
_ABBREVIATED_COUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*([KM])\b", re.IGNORECASE)
_ZERO_WIDTH_TRANSLATION = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


def normalize_text(value: str | None) -> str:
    """标准化抓取到的文本。"""
    if not value:
        return ""
    cleaned = str(value).translate(_ZERO_WIDTH_TRANSLATION)
    return " ".join(cleaned.strip().split())


def parse_price(value: str | None) -> tuple[float | None, str | None]:
    """从价格字符串中提取金额和币种。"""
    text = normalize_text(value)
    match = _PRICE_PATTERN.search(text)
    amount = None
    if match:
        amount = float(match.group(1).replace(",", ""))

    currency = None
    if "$" in text:
        currency = "USD"
    return amount, currency


def parse_rating(value: str | None) -> float | None:
    """从评分字符串中提取数值。"""
    text = normalize_text(value)
    match = _RATING_PATTERN.search(text)
    if not match:
        return None
    return float(match.group(1))


def parse_review_count(value: str | None) -> int | None:
    """从评论数字符串中提取数量。"""
    text = normalize_text(value)
    labeled_match = _LABELED_REVIEW_COUNT_PATTERN.search(text)
    if labeled_match:
        return int(labeled_match.group(1).replace(",", ""))

    abbreviated_match = _ABBREVIATED_COUNT_PATTERN.search(text)
    if abbreviated_match:
        amount = float(abbreviated_match.group(1))
        multiplier = 1000 if abbreviated_match.group(2).upper() == "K" else 1000000
        return int(amount * multiplier)

    if "out of" in text.lower() and "star" in text.lower():
        return None

    match = _INTEGER_PATTERN.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))
