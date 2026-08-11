"""SerpApi Google Trends HTTP 客户端。

客户端在每次搜索前通过免费 Account API 核对额度，并在确认 Key 耗尽时
写入统一 MySQL 账号状态后自动轮换。所有异常和返回结构都会移除 API Key。
"""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

import httpx

from opscli.google_trends.api.key_store import SerpApiKeyRecord, SerpApiKeyStore
from opscli.google_trends.api.mysql_key_store import MySqlSerpApiKeyStore
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
    """使用统一 MySQL 多账号池调用 SerpApi Google Trends 接口。"""

    def __init__(
        self,
        *,
        key_store: SerpApiKeyStore | MySqlSerpApiKeyStore | None = None,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """初始化客户端。

        Args:
            key_store: SerpApi Key 仓储；为空时使用默认配置目录。
            http_client: 可注入的同步 HTTP 客户端，主要用于测试。
            timeout_seconds: 默认 HTTP 超时秒数。
        """
        self.key_store = key_store or MySqlSerpApiKeyStore()
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
        """执行一个 SerpApi 场景，账号级错误发生时自动故障转移。"""
        engine = SCENARIO_ENGINES.get(scenario)
        if engine is None:
            raise GoogleTrendsConfigError(f"未知 Google Trends 场景：{scenario}")
        forbidden = _SECRET_FIELDS.intersection(_normalized_keys(params))
        if forbidden or "engine" in _normalized_keys(params):
            field = sorted(forbidden or {"engine"})[0]
            raise GoogleTrendsConfigError(f"参数不允许覆盖：{field}")

        attempted: set[str] = set()
        while True:
            # 续期日已到的耗尽账号优先复查，使恢复的额度可立即服务当前请求。
            renewal_key = self.key_store.next_due_exhausted_key(exclude_key_ids=attempted)
            key = renewal_key or self.key_store.next_active_key(exclude_key_ids=attempted)
            if key is None:
                raise GoogleTrendsApiKeysExhaustedError(
                    "没有可用的 SerpApi API 账号；请检查 MySQL 账号状态和剩余额度"
                )
            attempted.add(key.key_id)
            with _lock_for_key(key.key_id):
                # 获取锁后重新读取，防止同进程其他请求已修改该 Key 状态。
                current = self.key_store.get(key.key_id)
                if current is None or current.status == "disabled":
                    continue

                account_checked = False
                if current.status == "exhausted":
                    if renewal_key is None:
                        continue
                    try:
                        account_available = self._restore_after_renewal(current)
                    except GoogleTrendsApiError as account_error:
                        self._handle_renewal_check_error(current, account_error)
                        continue
                    if not account_available:
                        continue
                    account_checked = True
                    refreshed = self.key_store.get(current.key_id)
                    if refreshed is None or refreshed.status != "active":
                        continue
                    current = refreshed
                elif current.status != "active":
                    continue

                if not account_checked:
                    try:
                        account_available = self._check_account(current)
                    except GoogleTrendsApiError as account_error:
                        # 账号级错误允许本轮故障转移；参数或服务端错误不能靠换 Key 解决。
                        if self._handle_key_error(current, account_error, confirm_account=False):
                            continue
                        raise
                    if not account_available:
                        continue

                # 搜索一旦发起即视为使用，避免失败请求让同一 Key 持续处于轮换首位。
                self.key_store.mark_used(current.key_id)
                try:
                    payload = self._search(current, engine=engine, params=params)
                except GoogleTrendsApiError as search_error:
                    if self._handle_key_error(current, search_error, confirm_account=True):
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

    def _restore_after_renewal(self, key: SerpApiKeyRecord) -> bool:
        """复查已到续期日的耗尽账号，有新额度时恢复为 active。"""
        payload = self._request_json(
            SERPAPI_ACCOUNT_URL,
            params={"api_key": key.api_key},
            api_key=key.api_key,
            operation="SerpApi Account API",
        )
        try:
            remaining = int(payload.get("total_searches_left"))
        except (TypeError, ValueError):
            remaining = None
        record = self.key_store.update_account_snapshot(
            key.key_id,
            payload,
            # 尚未恢复额度时保留已到期日期，使账号在冷却结束后还能继续复查。
            preserve_plan_renewal_date=remaining is None or remaining <= 0,
        )
        if record.total_searches_left is not None and record.total_searches_left > 0:
            self.key_store.restore_active(key.key_id)
            return True
        if record.total_searches_left is not None:
            self.key_store.mark_exhausted(
                key.key_id,
                reason="SerpApi 续期日复查后剩余额度仍为 0",
            )
        else:
            self.key_store.record_account_check_error(
                key.key_id,
                reason="SerpApi Account API 未返回剩余额度",
            )
        return False

    def _handle_renewal_check_error(
        self,
        key: SerpApiKeyRecord,
        error: GoogleTrendsApiError,
    ) -> None:
        """处理耗尽账号续期复查错误，不阻断其他账号继续服务。"""
        self.key_store.record_account_check_error(key.key_id, reason=str(error))
        if error.status_code in {401, 403}:
            # 续期不会修复无效 Key 或已删除账号，必须转为 disabled 等待人工处理。
            self.key_store.set_status(key.key_id, "disabled")

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

    def _handle_key_error(
        self,
        key: SerpApiKeyRecord,
        error: GoogleTrendsApiError,
        *,
        confirm_account: bool,
    ) -> bool:
        """处理账号级错误；返回 True 表示当前请求应切换下一个 Key。"""
        if error.status_code in {401, 403}:
            # 无效 Key 或已删除账号无法自行恢复，禁用后避免后续请求反复命中。
            self.key_store.record_error(key.key_id, reason=str(error))
            self.key_store.set_status(key.key_id, "disabled")
            return True

        quota_error = _is_quota_exhausted_error(error)
        if error.status_code != 429 and not quota_error:
            self.key_store.record_error(key.key_id, reason=str(error))
            return False

        if confirm_account:
            try:
                payload = self._request_json(
                    SERPAPI_ACCOUNT_URL,
                    params={"api_key": key.api_key},
                    api_key=key.api_key,
                    operation="SerpApi Account API",
                )
            except GoogleTrendsApiError:
                # 复查失败时只信任明确的额度耗尽文案，避免把临时限流永久标为耗尽。
                if quota_error:
                    self.key_store.mark_exhausted(
                        key.key_id,
                        reason="SerpApi 搜索错误明确表示额度已耗尽",
                    )
                else:
                    self.key_store.record_error(key.key_id, reason=str(error))
                return True

            record = self.key_store.update_account_snapshot(key.key_id, payload)
            if record.total_searches_left is not None:
                if record.total_searches_left <= 0:
                    self.key_store.mark_exhausted(
                        key.key_id,
                        reason="SerpApi 搜索失败后确认剩余额度为 0",
                    )
                else:
                    # Account API 确认仍有额度时，429 只代表当前 Key 的吞吐限流。
                    self.key_store.record_error(key.key_id, reason=str(error))
                return True

        if quota_error:
            self.key_store.mark_exhausted(
                key.key_id,
                reason="SerpApi 错误明确表示额度已耗尽",
            )
        else:
            # 有剩余额度的 429 属于吞吐限流，仅跳过本轮，不永久停用账号。
            self.key_store.record_error(key.key_id, reason=str(error))
        return True

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
        normalized_status = metadata_status.strip().lower()
        # SerpApi 会在搜索成功但无结果时同时返回 status=Success 和顶层 error。
        # 因此只有 HTTP 失败、明确的 Error 状态，或缺少搜索状态的 error 才是请求失败。
        request_failed = (
            response.status_code >= 400
            or normalized_status == "error"
            or (bool(error) and normalized_status != "success")
        )
        if request_failed:
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


def _is_quota_exhausted_error(error: GoogleTrendsApiError) -> bool:
    """判断错误文案是否明确表示 SerpApi 搜索额度已耗尽。"""
    message = str(error).strip().lower()
    exhaustion_markers = (
        "searches are exhausted",
        "searches for this month are exhausted",
        "search credits are exhausted",
        "run out of searches",
        "no searches left",
    )
    return any(marker in message for marker in exhaustion_markers)
