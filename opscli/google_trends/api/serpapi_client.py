"""SerpApi Google Trends HTTP 客户端。

客户端在每次搜索前通过免费 Account API 核对额度，并在确认 Key 耗尽时
写入 SQLite 状态后自动轮换。所有异常和返回结构都会移除 API Key。
"""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

import httpx

from opscli.google_trends.api.key_store import SerpApiKeyRecord, SerpApiKeyStore
from opscli.google_trends.domain.exceptions import (
    GoogleTrendsApiError,
    GoogleTrendsApiKeysExhaustedError,
    GoogleTrendsConfigError,
)


SERPAPI_SEARCH_URL = "https://serpapi.com/search"
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
DEFAULT_TIMEOUT_SECONDS = 10.0
SCENARIO_ENGINES = {
    "trends": "google_trends",
    "autocomplete": "google_trends_autocomplete",
    "trending-now": "google_trends_trending_now",
}
_SECRET_FIELDS = frozenset({"api_key", "authorization", "token"})
_KEY_LOCKS: dict[str, threading.Lock] = {}
_KEY_LOCKS_GUARD = threading.Lock()


class SerpApiGoogleTrendsClient:
    """使用 SQLite 多 Key 池调用 SerpApi Google Trends 接口。"""

    def __init__(
        self,
        *,
        key_store: SerpApiKeyStore | None = None,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """初始化客户端。

        Args:
            key_store: SerpApi Key 仓储；为空时使用默认配置目录。
            http_client: 可注入的同步 HTTP 客户端，主要用于测试。
            timeout_seconds: 默认 HTTP 超时秒数。
        """
        self.key_store = key_store or SerpApiKeyStore()
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None

    def close(self) -> None:
        """关闭由本实例创建的 HTTP 客户端。"""
        if self._owns_client:
            self._client.close()

    def check_account(self, key_id: str) -> dict[str, Any]:
        """检查指定 Key 的账户额度，并返回不含明文凭证的摘要。"""
        key = self.key_store.get(key_id)
        if key is None:
            raise GoogleTrendsConfigError(f"SerpApi API Key 不存在：{key_id}")
        with _lock_for_key(key.key_id):
            # Account API 免费且不发起搜索；无论当前状态如何都允许人工执行检查。
            current = self.key_store.get(key.key_id)
            if current is None:
                raise GoogleTrendsConfigError(f"SerpApi API Key 不存在：{key_id}")
            try:
                self._check_account(current)
            except GoogleTrendsApiError as account_error:
                self.key_store.record_error(current.key_id, reason=str(account_error))
                raise
            checked = self.key_store.get(current.key_id)
            if checked is None:
                raise GoogleTrendsConfigError(f"SerpApi API Key 不存在：{key_id}")
            return checked.to_public_dict()

    def run(self, scenario: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行一个 SerpApi 场景，Key 耗尽时自动轮换。"""
        engine = SCENARIO_ENGINES.get(scenario)
        if engine is None:
            raise GoogleTrendsConfigError(f"未知 Google Trends 场景：{scenario}")
        forbidden = _SECRET_FIELDS.intersection(_normalized_keys(params))
        if forbidden or "engine" in _normalized_keys(params):
            field = sorted(forbidden or {"engine"})[0]
            raise GoogleTrendsConfigError(f"参数不允许覆盖：{field}")

        attempted: set[str] = set()
        while True:
            key = self.key_store.next_active_key(exclude_key_ids=attempted)
            if key is None:
                raise GoogleTrendsApiKeysExhaustedError(
                    "没有可用的 SerpApi API Key；请检查 SQLite Key 状态和剩余额度"
                )
            attempted.add(key.key_id)
            with _lock_for_key(key.key_id):
                # 获取锁后重新读取，防止同进程其他请求已将该 Key 标记为耗尽。
                current = self.key_store.get(key.key_id)
                if current is None or current.status != "active":
                    continue
                try:
                    account_available = self._check_account(current)
                except GoogleTrendsApiError as account_error:
                    self.key_store.record_error(current.key_id, reason=str(account_error))
                    raise
                if not account_available:
                    continue
                # 搜索一旦发起即视为使用，避免失败请求让同一 Key 持续处于轮换首位。
                self.key_store.mark_used(current.key_id)
                try:
                    payload = self._search(current, engine=engine, params=params)
                except GoogleTrendsApiError as search_error:
                    # 仅在 Account API 明确确认额度归零后轮换；其他错误直接保留。
                    if self._confirm_exhausted_after_error(current, search_error):
                        continue
                    raise
                return payload

    def _check_account(self, key: SerpApiKeyRecord) -> bool:
        """同步账户额度；返回 False 表示该 Key 已确认耗尽。"""
        payload = self._request_json(
            SERPAPI_ACCOUNT_URL,
            params={"api_key": key.api_key},
            api_key=key.api_key,
            operation="SerpApi Account API",
        )
        record = self.key_store.update_account_snapshot(key.key_id, payload)
        if record.total_searches_left is not None and record.total_searches_left <= 0:
            self.key_store.mark_exhausted(key.key_id, reason="SerpApi Account API 确认剩余额度为 0")
            return False
        return True

    def _search(
        self,
        key: SerpApiKeyRecord,
        *,
        engine: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """执行单次 SerpApi Search 请求并返回脱敏 JSON。"""
        request_params = {
            **params,
            "engine": engine,
            "api_key": key.api_key,
            "output": "json",
        }
        return self._request_json(
            SERPAPI_SEARCH_URL,
            params=request_params,
            api_key=key.api_key,
            operation="SerpApi Google Trends API",
        )

    def _confirm_exhausted_after_error(
        self,
        key: SerpApiKeyRecord,
        search_error: GoogleTrendsApiError,
    ) -> bool:
        """搜索失败后复查额度，仅在明确归零时标记 exhausted。"""
        try:
            payload = self._request_json(
                SERPAPI_ACCOUNT_URL,
                params={"api_key": key.api_key},
                api_key=key.api_key,
                operation="SerpApi Account API",
            )
        except GoogleTrendsApiError:
            self.key_store.record_error(key.key_id, reason=str(search_error))
            return False

        record = self.key_store.update_account_snapshot(key.key_id, payload)
        if record.total_searches_left is not None and record.total_searches_left <= 0:
            self.key_store.mark_exhausted(key.key_id, reason="SerpApi 搜索失败后确认剩余额度为 0")
            return True
        self.key_store.record_error(key.key_id, reason=str(search_error))
        return False

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        api_key: str,
        operation: str,
    ) -> dict[str, Any]:
        """执行 GET、校验业务状态，并全面脱敏响应和异常。"""
        try:
            response = self._client.get(url, params=_clean_params(params))
        except httpx.HTTPError as exc:
            safe_message = _sanitize_text(str(exc), api_key)
            raise GoogleTrendsApiError(f"{operation} 请求失败：{safe_message}") from None

        try:
            raw_payload = response.json()
        except ValueError:
            excerpt = _sanitize_text(response.text[:1000], api_key)
            raise GoogleTrendsApiError(
                f"{operation} 返回非 JSON",
                status_code=response.status_code,
                response_excerpt=excerpt,
            ) from None
        if not isinstance(raw_payload, dict):
            raise GoogleTrendsApiError(
                f"{operation} 返回结构不是 JSON 对象",
                status_code=response.status_code,
            )

        payload = _sanitize_value(raw_payload, api_key)
        error = payload.get("error")
        metadata = payload.get("search_metadata")
        metadata_status = str(metadata.get("status") or "") if isinstance(metadata, dict) else ""
        if response.status_code >= 400 or error or metadata_status.lower() == "error":
            message = _extract_error_message(payload) or f"{operation} 请求失败，HTTP {response.status_code}"
            excerpt = json.dumps(payload, ensure_ascii=False)[:1000]
            raise GoogleTrendsApiError(
                message,
                status_code=response.status_code,
                response_excerpt=excerpt,
                response_payload=payload,
            )
        return payload


def _lock_for_key(key_id: str) -> threading.Lock:
    """返回单个 Key 的进程内互斥锁。"""
    with _KEY_LOCKS_GUARD:
        lock = _KEY_LOCKS.get(key_id)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key_id] = lock
        return lock


def _clean_params(params: dict[str, Any]) -> dict[str, str]:
    """将 SerpApi 查询参数转换为稳定字符串。"""
    clean: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            clean[str(key)] = "true" if value else "false"
        else:
            clean[str(key)] = str(value)
    return clean


def _normalized_keys(params: dict[str, Any]) -> set[str]:
    """返回统一下划线形式的参数名集合。"""
    return {str(key).replace("-", "_").lower() for key in params}


def _sanitize_value(value: Any, api_key: str) -> Any:
    """递归移除敏感字段并替换所有明文 Key。"""
    if isinstance(value, list):
        return [_sanitize_value(item, api_key) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SECRET_FIELDS:
                continue
            result[str(key)] = _sanitize_value(item, api_key)
        return result
    if isinstance(value, str):
        return _sanitize_text(value, api_key)
    return value


def _sanitize_text(text: str, api_key: str) -> str:
    """从文本和 URL 查询参数中移除 API Key。"""
    redacted = str(text).replace(api_key, "***") if api_key else str(text)
    try:
        parts = urlsplit(redacted)
    except ValueError:
        return redacted
    if not parts.query:
        return redacted
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        safe_value = "***" if key.replace("-", "_").lower() in _SECRET_FIELDS else value
        query.append(f"{quote_plus(key)}={quote_plus(safe_value)}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query), parts.fragment))


def _extract_error_message(payload: dict[str, Any]) -> str | None:
    """从 SerpApi 错误结构提取用户可读消息。"""
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        for field in ("message", "error", "msg"):
            value = error.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
