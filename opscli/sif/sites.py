"""Sif marketplace normalization."""

from __future__ import annotations

from opscli.sif.domain.exceptions import SifError


class SifSiteNotSupportedError(SifError):
    """Unsupported Sif marketplace."""

    code = "SIF_SITE_NOT_SUPPORTED"


SITE_ALIASES = {
    "US": "US",
    "USA": "US",
    "美国": "US",
    "美国站": "US",
    "UK": "UK",
    "GB": "UK",
    "英国": "UK",
    "英国站": "UK",
    "CA": "CA",
    "加拿大": "CA",
    "加拿大站": "CA",
    "FR": "FR",
    "法国": "FR",
    "法国站": "FR",
    "ES": "ES",
    "西班牙": "ES",
    "西班牙站": "ES",
    "IT": "IT",
    "意大利": "IT",
    "意大利站": "IT",
    "AU": "AU",
    "澳大利亚": "AU",
    "澳大利亚站": "AU",
    "MX": "MX",
    "墨西哥": "MX",
    "墨西哥站": "MX",
    "AE": "AE",
    "阿联酋": "AE",
    "阿联酋站": "AE",
    "BR": "BR",
    "巴西": "BR",
    "巴西站": "BR",
    "SA": "SA",
    "沙特": "SA",
    "沙特站": "SA",
    "JP": "JP",
    "日本": "JP",
    "日本站": "JP",
    "DE": "DE",
    "德国": "DE",
    "德国站": "DE",
}


def normalize_site(value: str | None) -> str:
    key = (value or "US").strip()
    normalized = SITE_ALIASES.get(key) or SITE_ALIASES.get(key.upper())
    if normalized:
        return normalized
    supported = ", ".join(sorted({code for code in SITE_ALIASES.values()}))
    raise SifSiteNotSupportedError(f"不支持的 Sif 站点：{value}，可用站点编码：{supported}")
