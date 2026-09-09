"""预取计划参数、时区和安全边界校验。"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SUPPORTED_SOURCES = frozenset({"keepa", "google_trends", "seller_sprite"})
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "jwt",
        "password",
        "secret",
        "session_id",
        "sessionid",
        "token",
    }
)


def normalize_schedule_request(
    *,
    source_system: str,
    scenario: str,
    params: dict[str, Any] | None,
    site: str,
    period: str,
    page_size: int,
    export_format: str,
) -> tuple[str, str, dict[str, Any]]:
    """校验来源场景并返回不含凭证的稳定执行请求。"""
    source = str(source_system or "").strip().lower().replace("-", "_")
    scenario_id = str(scenario or "").strip().lower()
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"不支持的预取来源：{source_system}")
    if not scenario_id:
        raise ValueError("预取场景不能为空")
    request_params = dict(params or {})
    _reject_sensitive_values(request_params)
    normalized_export = _normalize_export_format(export_format)

    if source == "keepa":
        from opscli.keepa.api.scenarios import get_scenario

        normalized_site = str(site or "US").strip().upper() or "US"
        get_scenario(scenario_id).build_params(
            params=request_params,
            site=normalized_site,
        )
        request = {
            "params": request_params,
            "site": normalized_site,
            "export_format": normalized_export,
        }
    elif source == "google_trends":
        from opscli.google_trends.api.scenarios import get_scenario

        geo = str(site or "US").strip().upper()
        get_scenario(scenario_id).build_params(params=request_params, geo=geo)
        request = {
            "params": request_params,
            "geo": geo,
            "export_format": normalized_export,
        }
    else:
        from opscli.seller_sprite.api.scenarios import get_scenario

        definition = get_scenario(scenario_id)
        if scenario_id == "listing-analysis":
            raise ValueError("listing-analysis 只能由用户显式提交，禁止加入预取计划")
        if not definition.replay_safe:
            raise ValueError(f"场景 {scenario_id} 不允许自动重放，不能加入预取计划")
        normalized_site = str(site or "US").strip().upper() or "US"
        normalized_period = str(period or "30d").strip() or "30d"
        normalized_page_size = max(1, min(int(page_size), 1000))
        definition.build_payload(
            params=request_params,
            site=normalized_site,
            period=normalized_period,
            page_size=normalized_page_size,
        )
        request = {
            "params": request_params,
            "site": normalized_site,
            "period": normalized_period,
            "page_size": normalized_page_size,
            "export_format": normalized_export,
        }
    return source, scenario_id, request


def normalize_timezone_and_time(
    run_time: str,
    timezone_name: str,
) -> tuple[str, str]:
    """校验每日执行时间和 IANA 时区名称。"""
    parsed = _parse_run_time(run_time)
    timezone_value = str(timezone_name or "Asia/Shanghai").strip()
    try:
        ZoneInfo(timezone_value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知时区：{timezone_value}") from exc
    return parsed.strftime("%H:%M:%S"), timezone_value


def next_daily_run(
    run_time: str,
    timezone_name: str,
    *,
    after: datetime | None = None,
) -> datetime:
    """计算严格晚于指定时刻的下一次每日运行 UTC 时间。"""
    current = after or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    zone = ZoneInfo(timezone_name)
    local_now = current.astimezone(zone)
    parsed = _parse_run_time(run_time)
    candidate = datetime.combine(local_now.date(), parsed, tzinfo=zone)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_run_time(value: str) -> time:
    text = str(value or "").strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    raise ValueError("run_time 必须使用 HH:MM 或 HH:MM:SS 格式")


def _normalize_export_format(value: str) -> str:
    normalized = str(value or "json").strip().lower()
    if normalized in {"xls", "xlsx"}:
        return "xls"
    if normalized == "json":
        return normalized
    raise ValueError("export_format 仅支持 json、xls 或 xlsx")


def _reject_sensitive_values(value: Any, path: str = "params") -> None:
    """递归拒绝可能承载凭证的字段，避免秘密进入共享 MySQL。"""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            compact = normalized.replace("_", "")
            if (
                normalized in _SENSITIVE_KEYS
                or compact in _SENSITIVE_KEYS
                or compact.endswith(("apikey", "password", "secret", "sessionid", "token"))
            ):
                raise ValueError(f"计划参数禁止保存凭证字段：{path}.{key}")
            _reject_sensitive_values(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_values(item, f"{path}[{index}]")
