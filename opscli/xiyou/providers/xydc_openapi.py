"""西柚 OpenAPI v2 provider。

该模块是 xydc MCP 工具的替代传输层：工具名称和业务参数保持兼容，
实际请求改为使用西柚 OpenAPI v2 的 API Key 鉴权。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from opscli.api_credentials import ApiCredentialLease, ApiCredentialPool
from opscli.api_credentials.exceptions import ApiCredentialUnavailableError
from opscli.xiyou.operation_metadata import get_operation_metadata

from .xydc_audit import XydcAuditLogger, _sanitize


XYDC_OPENAPI_BASE_URL = "https://openapi.xydc.com"
XYDC_OPENAPI_PROVIDER = "xydc_openapi"
XYDC_OPENAPI_VERSION = "2.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3


@dataclass(frozen=True)
class XydcOpenApiOperation:
    """文档中一个 OpenAPI 操作的稳定目录项。"""

    name: str
    title: str
    endpoint: str
    required_fields: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.name,
            "title": self.title,
            "method": "POST",
            "endpoint": self.endpoint,
            "required_fields": list(self.required_fields),
            "description": self.description,
            **get_operation_metadata(self.name, self.required_fields),
        }


# 该目录与西柚 OpenAPI 文档的公开接口清单保持一一对应。
OPERATIONS: dict[str, XydcOpenApiOperation] = {
    "asin_traffic": XydcOpenApiOperation(
        "asin_traffic", "ASIN 流量得分", "/v1/asins/traffic", ("entities",), "查询 ASIN 近一周流量得分"
    ),
    "asin_info_change_daily": XydcOpenApiOperation(
        "asin_info_change_daily", "ASIN 基础信息变动趋势（天）", "/v1/asins/infoChange/trends/daily", ("country", "asin", "startDate", "endDate"), "查询标题和图片等基础信息变化"
    ),
    "asin_traffic_score_daily": XydcOpenApiOperation(
        "asin_traffic_score_daily", "ASIN 流量得分趋势（天）", "/v1/asins/trafficScore/trend/daily", ("asin", "country", "startDate", "endDate"), "查询每日流量得分趋势；日期使用 YYYY-MM-DD。流量不含最新一天，客户端昨日不保证是供应商可用日期；拒绝范围时核对站点日期和数据就绪情况"
    ),
    "asin_traffic_score_weekly": XydcOpenApiOperation(
        "asin_traffic_score_weekly", "ASIN 流量得分趋势（周）", "/v1/asins/trafficScore/trend/weekly", ("asin", "country", "startWeek", "endWeek"), "查询每周流量得分趋势"
    ),
    "asin_traffic_score_monthly": XydcOpenApiOperation(
        "asin_traffic_score_monthly", "ASIN 流量得分趋势（月）", "/v1/asins/trafficScore/trend/monthly", ("asin", "country", "startMonth", "endMonth"), "查询每月流量得分趋势"
    ),
    "asin_advertising_change_daily": XydcOpenApiOperation(
        "asin_advertising_change_daily", "ASIN 广告信息变动趋势（天）", "/v1/asins/advertisingChange/trends/daily", ("country", "asin", "startDate", "endDate"), "查询广告活动新增和移除变化"
    ),
    "asin_bsr_daily": XydcOpenApiOperation(
        "asin_bsr_daily", "ASIN BSR 排名趋势（天）", "/v1/asins/bsrInfo/trends/daily", ("country", "asin", "startDate", "endDate"), "查询 BSR 类目排名趋势"
    ),
    "asin_orders_trends": XydcOpenApiOperation(
        "asin_orders_trends", "ASIN 订单量趋势（月）", "/v1/asins/orders/trends", ("asin", "country", "startMonth", "endMonth"), "查询 ASIN 月度订单量趋势"
    ),
    "asin_info_trends_daily": XydcOpenApiOperation(
        "asin_info_trends_daily", "ASIN 商品信息趋势图（天）", "/v1/asins/info/trends/daily", ("asin", "country", "startDate", "endDate"), "查询商品信息每日趋势"
    ),
    "asin_research_period": XydcOpenApiOperation(
        "asin_research_period", "ASIN 反查关键词列表（最近天）", "/v1/asins/research/list/period", ("asin", "country", "page", "pageSize", "period"), "查询 ASIN 最近7天反查关键词；period 仅支持 last7days，sort 可选，不支持 startDate/endDate"
    ),
    "asin_research_monthly": XydcOpenApiOperation(
        "asin_research_monthly", "ASIN 反查关键词列表（月）", "/v1/asins/research/list/monthly", ("asin", "country", "page", "pageSize", "startMonth", "endMonth"), "查询 ASIN 月度反查关键词，最长一年，sort 可选"
    ),
    "asin_info": XydcOpenApiOperation(
        "asin_info", "ASIN 商品信息", "/v1/asins/info", ("entities",), "查询标题、价格、评分和主图等商品信息"
    ),
    "asin_orders": XydcOpenApiOperation(
        "asin_orders", "ASIN 近 30 天订单量", "/v1/asins/orders", ("asins", "country"), "查询多个 ASIN 近 30 天订单量"
    ),
    "asin_variations": XydcOpenApiOperation(
        "asin_variations", "ASIN 变体", "/v1/asins/variations", ("asin", "country"), "查询父体和子体 ASIN"
    ),
    "asin_search_terms_traffic_daily": XydcOpenApiOperation(
        "asin_search_terms_traffic_daily", "ASIN 词流量趋势（天）", "/v1/asinSearchTerms/traffic/trend/daily", ("asin", "country", "searchTerm", "startDate", "endDate"), "查询 ASIN 关键词每日流量"
    ),
    "asin_search_terms_rank_daily": XydcOpenApiOperation(
        "asin_search_terms_rank_daily", "ASIN 词排名趋势（天）", "/v1/asinSearchTerms/rank/trends/daily", ("asin", "country", "searchTerm", "startDate", "endDate"), "查询 ASIN 关键词每日排名"
    ),
    "asin_search_terms_rank_hourly": XydcOpenApiOperation(
        "asin_search_terms_rank_hourly", "ASIN 词排名趋势（小时）", "/v1/asinSearchTerms/rank/trends/hourly", ("asin", "country", "searchTerm", "date"), "查询单日 ASIN 关键词小时排名"
    ),
    "search_terms_aba_weekly": XydcOpenApiOperation(
        "search_terms_aba_weekly", "关键词 ABA 数据趋势（周）", "/v1/searchTerms/abaReport/trends/weekly", ("country", "searchTerms", "startWeek", "endWeek"), "查询关键词周度 ABA 指标"
    ),
    "search_terms_info": XydcOpenApiOperation(
        "search_terms_info", "关键词信息（最近一周）", "/v1/searchTerms/info", ("country", "searchTerms", "sort"), "查询搜索量、竞争难度和建议竞价；最多100词，sort 必填"
    ),
    "search_terms_analysis_period": XydcOpenApiOperation(
        "search_terms_analysis_period", "关键词分析列表（最近天）", "/v1/searchTerms/analysis/list/period", ("searchTerm", "country", "page", "pageSize", "period", "sort"), "查询关键词竞争 ASIN 和流量；period 仅支持 last7days，分页和排序必填"
    ),
    "search_terms_analysis_monthly": XydcOpenApiOperation(
        "search_terms_analysis_monthly", "关键词分析列表（月）", "/v1/searchTerms/analysis/list/monthly", ("searchTerm", "country", "page", "pageSize", "startMonth", "endMonth", "sort"), "查询月度关键词竞争 ASIN 和流量，分页和排序必填"
    ),
    "client_quota": XydcOpenApiOperation(
        "client_quota", "客户端额度", "/v1/client/quota", (), "查询当前 API 客户端额度（文档标注仅适用于 v1）"
    ),
}

PUBLIC_OPERATION_NAMES = tuple(name for name in OPERATIONS if name != "client_quota")

LEGACY_OPERATION_ALIASES = {
    "get_asin_info": "asin_info",
    "get_asin_traffic": "asin_traffic",
    "get_keyword_info": "search_terms_info",
    "get_keyword_asin_analysis": "search_terms_analysis_period",
}


class XydcOpenApiError(RuntimeError):
    """西柚 OpenAPI 调用错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
        trace_id: str | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.payload = payload
        self.trace_id = trace_id
        self.retry_after = retry_after

    def to_dict(self) -> dict[str, Any]:
        result = {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "trace_id": self.trace_id,
            "retry_after": self.retry_after,
            "details": self.payload,
        }
        # 日期语法合法也可能越过供应商数据边界；补充提示但不猜测或改写请求日期。
        if self.code == "InvalidTrendsRange" and self.status_code == 400:
            result["hint"] = (
                "查询范围被供应商拒绝。请核对当前 operation 的周期字段、日期格式与起止顺序，"
                "并区分客户端日期、站点日期和供应商最新可用数据日；流量不含最新一天且每天更新。"
                "客户端昨日可能仍是站点当天，具体截止时区和发布时间需确认。"
                "保留原始区间和 trace_id，不自动重放相同参数或更换 ASIN；"
                "仅在任务允许且有可用日期依据时显式调整一次，否则报告数据未取得。"
            )
        return result


class XydcOpenApiProvider:
    """使用 API 凭据池调用西柚 OpenAPI v2。"""

    def __init__(
        self,
        credential_pool: ApiCredentialPool | None = None,
        *,
        client_factory=httpx.AsyncClient,
        audit_logger: XydcAuditLogger | None = None,
        base_url: str = XYDC_OPENAPI_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._credential_pool = credential_pool
        self._client_factory = client_factory
        self._audit = audit_logger or XydcAuditLogger()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def call(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """调用清单中的任一 OpenAPI 接口。"""
        requested_operation = str(operation or "").strip()
        normalized_operation = LEGACY_OPERATION_ALIASES.get(requested_operation, requested_operation)
        spec = OPERATIONS.get(normalized_operation)
        if spec is None:
            raise XydcOpenApiError("XYDC_OPENAPI_UNKNOWN_OPERATION", f"不支持的西柚 OpenAPI 操作：{operation}")
        body = _normalize_legacy_payload(requested_operation, dict(payload))
        missing = [field for field in spec.required_fields if field not in body or body[field] in (None, "", [])]
        if missing:
            raise XydcOpenApiError("XYDC_OPENAPI_INVALID_PARAMS", f"缺少必填参数：{', '.join(missing)}")

        tried: set[int] = set()
        last_error: XydcOpenApiError | None = None
        for _ in range(3):
            try:
                lease = self._pool().acquire(XYDC_OPENAPI_PROVIDER, exclude_account_ids=tried)
            except ApiCredentialUnavailableError as exc:
                raise XydcOpenApiError(
                    "XYDC_OPENAPI_CREDENTIAL_UNAVAILABLE",
                    "西柚 OpenAPI 没有可用凭据",
                ) from exc
            tried.add(lease.account_id)
            try:
                result = await self._call_with_lease(spec, body, lease)
                self._report_success(lease, result)
                return result
            except XydcOpenApiError as exc:
                last_error = exc
                if not _should_rotate_credential(exc):
                    self._report_failure(lease, exc)
                    raise
                self._report_failure(lease, exc, disable=exc.status_code in {401, 404}, exhausted=exc.status_code == 403)
                if len(tried) >= 3:
                    raise
        if last_error:
            raise last_error
        raise XydcOpenApiError("XYDC_OPENAPI_CREDENTIAL_UNAVAILABLE", "西柚 OpenAPI 没有可用凭据")

    async def _call_with_lease(
        self,
        spec: XydcOpenApiOperation,
        payload: dict[str, Any],
        lease: ApiCredentialLease,
    ) -> dict[str, Any]:
        started = time.monotonic()
        attempts: list[dict[str, Any]] = []
        url = f"{self.base_url}{spec.endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Version": XYDC_OPENAPI_VERSION,
            "X-Api-Key": lease.secret,
        }
        try:
            async with self._client_factory(timeout=self.timeout, follow_redirects=False) as client:
                response = await self._request_with_retries(client, spec, url, headers, payload, attempts)
        except XydcOpenApiError as exc:
            self._audit.write_failure(
                operation=spec.name,
                endpoint=spec.endpoint,
                payload=payload,
                error=exc.to_dict(),
                attempts=attempts,
                duration_ms=int((time.monotonic() - started) * 1000),
                credential=lease,
            )
            raise
        except Exception as exc:
            error = XydcOpenApiError("XYDC_OPENAPI_TRANSPORT_ERROR", f"西柚 OpenAPI 网络请求失败：{type(exc).__name__}")
            self._audit.write_failure(
                operation=spec.name,
                endpoint=spec.endpoint,
                payload=payload,
                error=error.to_dict(),
                attempts=attempts,
                duration_ms=int((time.monotonic() - started) * 1000),
                credential=lease,
            )
            raise error from exc

        result = response
        self._audit.write_success(
            operation=spec.name,
            endpoint=spec.endpoint,
            payload=payload,
            result=result,
            attempts=attempts,
            duration_ms=int((time.monotonic() - started) * 1000),
            credential=lease,
        )
        return result

    async def _request_with_retries(self, client, spec, url, headers, payload, attempts):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                attempts.append({"attempt": attempt, "status_code": None, "error": type(exc).__name__})
                if attempt == MAX_RETRIES:
                    raise XydcOpenApiError("XYDC_OPENAPI_TRANSPORT_ERROR", f"网络请求失败：{type(exc).__name__}") from exc
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            trace_id = response.headers.get("X-Trace-Id")
            cost = response.headers.get("X-Cost-Credits")
            attempts.append({
                "attempt": attempt,
                "status_code": response.status_code,
                "trace_id": trace_id,
                "cost_credits": cost,
            })
            if response.status_code == 429 and attempt < MAX_RETRIES:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep(_retry_delay(retry_after, attempt))
                continue
            if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            try:
                body = response.json()
            except (ValueError, json.JSONDecodeError):
                body = {"message": response.text[:1000]}
            # REST 和 MCP 都会返回该结果；供应商回显的密钥必须在共享出口脱敏。
            body = _sanitize(body, headers["X-Api-Key"])
            trace_id = _sanitize(trace_id, headers["X-Api-Key"])
            if response.status_code >= 400:
                code = _error_code(response.status_code, body)
                raise XydcOpenApiError(
                    code,
                    _error_message(body, response.status_code),
                    status_code=response.status_code,
                    payload=body,
                    trace_id=trace_id,
                    retry_after=_sanitize(response.headers.get("Retry-After"), headers["X-Api-Key"]),
                )
            return {
                "success": True,
                "data": body,
                "error": None,
                "source": "xydc_openapi",
                "operation": spec.name,
                "endpoint": spec.endpoint,
                "provider_status": response.status_code,
                "trace_id": trace_id,
                "cost_credits": _number_or_text(cost),
            }
        raise XydcOpenApiError("XYDC_OPENAPI_REQUEST_FAILED", "西柚 OpenAPI 请求失败")

    def _pool(self) -> ApiCredentialPool:
        if self._credential_pool is None:
            self._credential_pool = ApiCredentialPool()
        return self._credential_pool

    def _report_success(self, lease: ApiCredentialLease, result: dict[str, Any]) -> None:
        try:
            self._pool().report_success(lease, runtime={"provider_metadata": {"last_cost_credits": result.get("cost_credits")}})
        except Exception:
            pass

    def _report_failure(self, lease: ApiCredentialLease, exc: XydcOpenApiError, *, disable=False, exhausted=False) -> None:
        try:
            self._pool().report_failure(
                lease,
                error_code=exc.code,
                message=exc.message[:500],
                disable=disable,
                exhausted=exhausted,
                runtime={"provider_metadata": {"last_trace_id": exc.trace_id} if exc.trace_id else {}},
            )
        except Exception:
            pass


def list_operations(*, include_internal: bool = False) -> list[dict[str, Any]]:
    """返回操作目录；默认只返回允许暴露给用户的公共操作。"""
    operations = (
        OPERATIONS.values()
        if include_internal
        else (OPERATIONS[name] for name in PUBLIC_OPERATION_NAMES)
    )
    return [item.to_dict() for item in operations]


def _normalize_legacy_payload(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """将四个旧 xydc MCP 工具的参数转换为 OpenAPI 文档 body。"""
    if operation in {"get_asin_info", "get_asin_traffic"}:
        asins = payload.pop("asins", [])
        if isinstance(asins, str):
            try:
                asins = json.loads(asins)
            except json.JSONDecodeError:
                asins = [item.strip() for item in asins.split(",") if item.strip()]
        country = payload.pop("country", "US")
        return {"entities": [{"country": country, "asin": asin} for asin in asins]}
    if operation == "get_keyword_info":
        keywords = payload.pop("keywords", [])
        if isinstance(keywords, str):
            try:
                keywords = json.loads(keywords)
            except json.JSONDecodeError:
                keywords = [item.strip() for item in keywords.split(",") if item.strip()]
        return {
            "country": payload.pop("country", "US"),
            "searchTerms": keywords,
            "sort": {"field": "weeklySearchVolume", "order": "desc"},
        }
    if operation == "get_keyword_asin_analysis":
        page = max(int(payload.pop("page", 1)) - 1, 0)
        page_size = int(payload.pop("page_size", 20))
        return {
            "searchTerm": payload.pop("keyword", ""),
            "country": payload.pop("country", "US"),
            "page": page,
            "pageSize": page_size,
            "period": "last7days",
            "sort": {
                "field": payload.pop("sort_field", "traffic"),
                "order": payload.pop("sort_order", "desc"),
            },
        }
    return payload


def _should_rotate_credential(exc: XydcOpenApiError) -> bool:
    if exc.status_code in {401, 404}:
        return True
    if exc.status_code == 403:
        # 两种错误体均由共享解析归一为业务码，继续使用既有额度轮换白名单。
        return exc.code in {"CreditBalanceInsufficient", "CreditAccountUnavailable", "APICredentialNotFound"}
    return False


def _error_code(status_code: int, body: Any) -> str:
    if isinstance(body, dict) and body.get("reason"):
        return str(body["reason"])
    # 业务接口实际也返回 code/msg；数字 code 是 HTTP 状态，不能当成业务分类。
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(code, str) and code.strip() and not code.strip().isdecimal():
        return code.strip()
    return f"HTTP_{status_code}"


def _error_message(body: Any, status_code: int) -> str:
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    if isinstance(body, dict) and body.get("msg"):
        return str(body["msg"])
    return f"西柚 OpenAPI 返回 HTTP {status_code}"


def _retry_delay(value: str | None, attempt: int) -> float:
    try:
        return min(max(float(value or 0), 0.0), 30.0)
    except ValueError:
        return float(2 ** (attempt - 1))


def _number_or_text(value: str | None) -> int | float | str | None:
    if value is None:
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except ValueError:
        return value
