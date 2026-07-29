"""已停用的 pytrends 客户端实现。

正式 Google Trends 执行链已切换到 SerpApi；本文件暂时保留旧代码，仅供历史
排障和回滚参考，不再由场景管理器导入或调用。
"""

from __future__ import annotations

import math
from datetime import date, datetime
from importlib import import_module
from inspect import signature
from typing import Any

from opscli.google_trends.config import GoogleTrendsSettings, load_settings
from opscli.google_trends.domain.exceptions import GoogleTrendsApiError, GoogleTrendsConfigError


UNAVAILABLE_SCENARIOS = {
    "trending-searches": "Google Trends 每日热搜 pytrends 端点当前返回 404，暂不可用。",
    "realtime-trending": "Google Trends 实时热搜 pytrends 端点当前返回 404，暂不可用。",
    "related-topics": "Google Trends 相关主题 pytrends 解析当前返回 list index out of range，暂不可用。",
}


class GoogleTrendsApiClient:
    """使用 pytrends 获取 Google Trends 数据。"""

    def __init__(
        self,
        *,
        settings: GoogleTrendsSettings | None = None,
        hl: str | None = None,
        tz: int | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.hl = hl or self.settings.hl
        self.tz = self.settings.tz if tz is None else tz
        self._client = None

    def run(self, scenario: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行指定场景并返回 JSON-safe 原始结构。"""
        try:
            return self._run(scenario, params)
        except (GoogleTrendsApiError, GoogleTrendsConfigError):
            raise
        except Exception as exc:
            raise _api_error_from_exception(exc) from exc

    def _run(self, scenario: str, params: dict[str, Any]) -> dict[str, Any]:
        if scenario in UNAVAILABLE_SCENARIOS:
            raise GoogleTrendsConfigError(
                f"{UNAVAILABLE_SCENARIOS[scenario]} 可用场景：interest-over-time、"
                "interest-by-region、related-queries、suggestions。"
            )
        if scenario == "interest-over-time":
            self._build_payload(params)
            return {"records": _dataframe_to_records(self._trend_req().interest_over_time(), index_name="date")}
        if scenario == "interest-by-region":
            self._build_payload(params)
            dataframe = self._trend_req().interest_by_region(
                resolution=params.get("resolution", "COUNTRY"),
                inc_low_vol=params.get("inc_low_vol", True),
                inc_geo_code=params.get("inc_geo_code", False),
            )
            return {"records": _dataframe_to_records(dataframe, index_name="geo_name")}
        if scenario == "related-queries":
            self._build_payload(params)
            return _dict_of_dataframes_to_records(self._trend_req().related_queries())
        if scenario == "related-topics":
            self._build_payload(params)
            return _dict_of_dataframes_to_records(self._trend_req().related_topics())
        if scenario == "suggestions":
            return {"records": _to_json_safe(self._trend_req().suggestions(keyword=params["keyword"]))}
        if scenario == "trending-searches":
            dataframe = self._trend_req().trending_searches(pn=params.get("pn", "united_states"))
            return {"records": _dataframe_to_records(dataframe, index_name="rank")}
        if scenario == "realtime-trending":
            dataframe = self._trend_req().realtime_trending_searches(pn=params.get("pn", "US"))
            return {"records": _dataframe_to_records(dataframe, index_name="rank")}
        raise GoogleTrendsConfigError(f"未知 Google Trends 场景：{scenario}")

    def _build_payload(self, params: dict[str, Any]) -> None:
        self._trend_req().build_payload(
            params["kw_list"],
            cat=params.get("cat", 0),
            timeframe=params.get("timeframe", "today 12-m"),
            geo=params.get("geo", "US"),
            gprop=params.get("gprop", ""),
        )

    def _trend_req(self):
        if self._client is not None:
            return self._client
        try:
            _patch_pytrends_retry_compatibility()
            from pytrends.request import TrendReq
        except ModuleNotFoundError as exc:
            raise GoogleTrendsConfigError(
                "缺少 pytrends 依赖，请安装 aukeys-opscli[google-trends] 或 pytrends>=4.9.2"
            ) from exc

        connect_timeout = min(10.0, max(3.0, float(self.settings.timeout_seconds)))
        self._client = TrendReq(
            hl=self.hl,
            tz=self.tz,
            timeout=(connect_timeout, float(self.settings.timeout_seconds)),
            proxies=self.settings.proxies or "",
            retries=self.settings.retries,
            backoff_factor=self.settings.backoff_factor,
            requests_args={"verify": self.settings.requests_verify},
        )
        return self._client


def _patch_pytrends_retry_compatibility() -> None:
    """Patch pytrends for urllib3 2.x Retry keyword compatibility."""
    pytrends_request = import_module("pytrends.request")
    if getattr(pytrends_request, "_opscli_retry_compat_patched", False):
        return

    retry_class = pytrends_request.Retry
    retry_init_params = signature(retry_class.__init__).parameters
    if "method_whitelist" in retry_init_params:
        return

    class RetryCompat(retry_class):
        def __init__(
            self,
            *args: Any,
            method_whitelist: Any = None,
            allowed_methods: Any = None,
            **kwargs: Any,
        ) -> None:
            if allowed_methods is None and method_whitelist is not None:
                allowed_methods = method_whitelist
            super().__init__(*args, allowed_methods=allowed_methods, **kwargs)

    pytrends_request.Retry = RetryCompat
    pytrends_request._opscli_retry_compat_patched = True


def _dict_of_dataframes_to_records(value: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for keyword, groups in (value or {}).items():
        item: dict[str, Any] = {}
        if isinstance(groups, dict):
            for group_name, dataframe in groups.items():
                item[str(group_name)] = _dataframe_to_records(dataframe)
        else:
            item["records"] = _to_json_safe(groups)
        payload[str(keyword)] = item
    return payload


def _dataframe_to_records(dataframe: Any, *, index_name: str | None = None) -> list[dict[str, Any]]:
    if dataframe is None:
        return []
    if hasattr(dataframe, "empty") and dataframe.empty:
        return []
    if not hasattr(dataframe, "reset_index"):
        value = _to_json_safe(dataframe)
        return value if isinstance(value, list) else [{"value": value}]

    frame = dataframe.copy()
    if index_name:
        frame.index.name = frame.index.name or index_name
    frame = frame.reset_index()
    records = frame.to_dict(orient="records")
    return [_to_json_safe(record) for record in records]


def _to_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_to_json_safe(key)): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _to_json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _to_json_safe(value.to_dict())
        except Exception:
            pass
    return str(value)


def _api_error_from_exception(exc: Exception) -> GoogleTrendsApiError:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    text = getattr(response, "text", None)
    message = str(exc) or type(exc).__name__
    lowered = message.lower()
    if status_code == 429 or "429" in lowered or "too many requests" in lowered or "rate" in lowered:
        message = "Google Trends 暂时限流，请稍后重试"
    return GoogleTrendsApiError(
        message,
        status_code=status_code,
        response_excerpt=str(text)[:1000] if text else None,
    )
