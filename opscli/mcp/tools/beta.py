"""Beta MCP 工具模块。

测试阶段的小模块命名为 beta，当前封装 Canopy REST API 的 Amazon 只读查询能力。
仅当用户明确提到 beta、Canopy 或测试服务时才应调用本模块工具。
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

from mcp.types import ToolAnnotations

from opscli.beta.canopy import config as canopy_config
from opscli.beta.canopy.config import (
    CANOPY_API_KEY_PLACEHOLDER,
    CANOPY_BASE_URL,
)
from opscli.beta.canopy.domain.exceptions import CanopyConfigError
from opscli.beta.canopy.domain.models import CanopyScenarioRequest
from opscli.beta.canopy.services import CanopyApiManager
from opscli.beta.canopy.services.api_manager import request_canopy_api

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg


DEFAULT_TIMEOUT_SECONDS = 60
MAX_PUBLIC_DATA_PREVIEW_ROWS = 20
SUPPORTED_DOMAINS = {"US", "UK", "CA", "DE", "FR", "IT", "ES", "AU", "IN", "MX", "BR", "JP", "PL"}


CANOPY_SCENARIOS: dict[str, dict[str, Any]] = {
    "product": {
        "title": "Amazon 商品详情",
        "method": "GET",
        "path": "/api/amazon/product",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": [],
        "description": "获取商品标题、价格、评分、图片、卖家等基础信息。",
    },
    "product-gtin-from-asin": {
        "title": "ASIN 转 GTIN",
        "method": "GET",
        "path": "/api/amazon/product/gtin-from-asin",
        "required_params": ["asin"],
        "optional_params": [],
        "description": "根据 ASIN 获取 GTIN。",
    },
    "product-asin-from-gtin": {
        "title": "GTIN 转 ASIN",
        "method": "GET",
        "path": "/api/amazon/product/asin-from-gtin",
        "required_params": ["gtin"],
        "optional_params": [],
        "description": "根据 GTIN 获取 ASIN。",
    },
    "product-variants": {
        "title": "Amazon 商品变体",
        "method": "GET",
        "path": "/api/amazon/product/variants",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": [],
        "description": "获取父子体、颜色、尺寸等变体信息。",
    },
    "product-stock": {
        "title": "Amazon 库存估算",
        "method": "GET",
        "path": "/api/amazon/product/stock",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": [],
        "description": "获取商品库存估算。",
    },
    "product-sales": {
        "title": "Amazon 销量估算",
        "method": "GET",
        "path": "/api/amazon/product/sales",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": [],
        "description": "获取商品销量估算。",
    },
    "product-reviews": {
        "title": "Amazon 商品评论",
        "method": "GET",
        "path": "/api/amazon/product/reviews",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": ["page", "rating", "onlyVerifiedReviews", "search"],
        "description": "获取商品评论，支持星级、已验证购买和评论内容筛选。",
    },
    "product-offers": {
        "title": "Amazon 商品报价",
        "method": "GET",
        "path": "/api/amazon/product/offers",
        "required_any": [["asin", "url", "gtin"]],
        "optional_params": ["page"],
        "description": "获取商品 offer、卖家报价和 Buy Box 相关信息。",
    },
    "search": {
        "title": "Amazon 商品搜索",
        "method": "GET",
        "path": "/api/amazon/search",
        "required_params": ["searchTerm"],
        "optional_params": ["page", "limit", "categoryId", "sort"],
        "description": "按关键词搜索 Amazon 商品。",
    },
    "autocomplete": {
        "title": "Amazon 搜索自动补全",
        "method": "GET",
        "path": "/api/amazon/autocomplete",
        "required_params": ["searchTerm"],
        "optional_params": ["category"],
        "description": "获取 Amazon 搜索建议。",
    },
    "categories": {
        "title": "Amazon 类目树",
        "method": "GET",
        "path": "/api/amazon/categories",
        "required_params": [],
        "optional_params": [],
        "description": "获取 Amazon 商品类目 taxonomy。",
    },
    "category": {
        "title": "Amazon 类目详情",
        "method": "GET",
        "path": "/api/amazon/category",
        "required_params": ["categoryId"],
        "optional_params": ["page", "sort"],
        "description": "获取指定类目信息和类目商品。",
    },
    "seller": {
        "title": "Amazon 卖家信息",
        "method": "GET",
        "path": "/api/amazon/seller",
        "required_params": ["sellerId"],
        "optional_params": ["page"],
        "description": "获取卖家信息和卖家商品。",
    },
    "author": {
        "title": "Amazon 作者信息",
        "method": "GET",
        "path": "/api/amazon/author",
        "required_params": ["asin"],
        "optional_params": ["page"],
        "description": "获取作者信息和图书列表。",
    },
    "deals": {
        "title": "Amazon Deals",
        "method": "GET",
        "path": "/api/amazon/deals",
        "required_params": [],
        "optional_params": ["page", "limit", "categoryIds"],
        "description": "获取 Amazon 优惠商品。",
    },
    "bestsellers": {
        "title": "Amazon Best Sellers",
        "method": "GET",
        "path": "/api/amazon/bestsellers",
        "required_any": [["categoryId", "url"]],
        "optional_params": ["page", "limit"],
        "description": "获取 Amazon Best Sellers 榜单商品。",
    },
    "bestseller-categories": {
        "title": "Amazon Best Seller 类目",
        "method": "GET",
        "path": "/api/amazon/bestseller-categories",
        "required_params": [],
        "optional_params": [],
        "description": "获取 Amazon Best Seller 类目入口。",
    },
}


async def beta_spec_must_read() -> dict:
    """仅当用户明确提到 beta/Canopy/测试服务时，读取 beta MCP 使用规范。"""
    spec_path = Path(__file__).resolve().parents[1] / "references" / "beta" / "SKILL_MCP.md"
    if not spec_path.exists():
        return _err(
            FileNotFoundError(f"beta MCP 规范文档不存在：{spec_path}。请检查 opscli 安装是否完整。"),
            tool="MCP → beta_spec_must_read()",
        )
    try:
        return _ok({"spec": spec_path.read_text(encoding="utf-8"), "source": str(spec_path)})
    except Exception as exc:
        return _err(exc, tool="MCP → beta_spec_must_read()")


async def beta_canopy_scenarios() -> dict:
    """仅当用户明确提到 beta/Canopy/测试服务时，列出 Canopy API 场景。"""
    try:
        scenarios = []
        for scenario_id, meta in CANOPY_SCENARIOS.items():
            scenarios.append({"scenario_id": scenario_id, **meta})
        return _ok(scenarios)
    except Exception as exc:
        return _err(exc, tool="MCP → beta_canopy_scenarios()")


async def beta_canopy_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    domain: str = "US",
    api_key: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """仅当用户明确提到 beta/Canopy/测试服务时，按场景调用 Canopy REST API 并导出 xls。

    Args:
        scenario: Canopy 场景 ID，例如 product、search、product-reviews。
        params: Canopy query 参数，支持 dict 或 JSON 字符串。
        domain: Amazon 站点代码，默认 US；请求时作为 Canopy 的 domain 参数发送。
        api_key: 内部调试参数；不传时读取项目内本地 key 文件，仍为空则使用占位符。
        timeout_seconds: HTTP 请求超时时间，默认 30 秒。
        export_format: 用户可见导出格式；当前仅允许 xls，内部生成 Excel 兼容 .xlsx。
        output_dir: 可选任务输出根目录；默认写入 beta Canopy 模块目录。
        job_id: 可选任务 ID；不传则自动生成。
        session_id: 可选 OPS 会话 ID，用于导出文件上传；不传则读取当前 MCP 凭证。
        jwt: 可选 OPS JWT，用于导出文件上传；不传则读取当前 MCP 凭证。

    Returns:
        统一 MCP 响应结构，成功时 data 包含 job_id、row_count、request、export 和 data_preview。
    """
    normalized_scenario = str(scenario or "").strip()
    normalized_domain = str(domain or "US").strip().upper()
    call_params = {
        "scenario": normalized_scenario,
        "domain": normalized_domain,
        "timeout_seconds": timeout_seconds,
        "export_format": export_format,
        "job_id": job_id,
    }

    try:
        public_export_format = _normalize_mcp_export_format(export_format)
        call_params["export_format"] = public_export_format
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        meta = _get_scenario(normalized_scenario)
        _validate_domain(normalized_domain)
        query_params = _parse_json_arg(params, dict) or {}
        query_params = _normalize_scenario_params(normalized_scenario, query_params)
        call_params["params"] = query_params
        _validate_required_params(normalized_scenario, meta, query_params)
        sid, jw = _get_auth_pair("ops", session_id, jwt)

        resolved_api_key = _resolve_api_key(api_key)
        request = CanopyScenarioRequest(
            scenario=normalized_scenario,
            domain=normalized_domain,
            params=query_params,
            path=meta["path"],
            method=meta["method"],
            title=meta["title"],
            api_key=resolved_api_key,
            api_key_placeholder_used=resolved_api_key == CANOPY_API_KEY_PLACEHOLDER,
            timeout_seconds=timeout_seconds,
            output_dir=output_dir,
            job_id=job_id,
            export_format=public_export_format,
        )
        result = await CanopyApiManager(jwt=jw, session_id=sid).run(request)
        return _ok(_public_result(result.to_dict()))
    except CanopyConfigError as exc:
        return _err(exc, tool="MCP → beta_canopy_run(...)", call_params=call_params, auto_feedback=False)
    except ValueError as exc:
        return _err(exc, tool="MCP → beta_canopy_run(...)", call_params=call_params, auto_feedback=False)
    except Exception as exc:
        return _err(exc, tool="MCP → beta_canopy_run(...)", call_params=call_params)


async def beta_canopy_job_status(job_id: str) -> dict:
    """仅当用户明确提到 beta/Canopy/测试服务时，读取 Canopy 任务结果。"""
    try:
        return _ok(_public_result(CanopyApiManager().job_status(job_id)))
    except Exception as exc:
        return _err(exc, tool="MCP → beta_canopy_job_status(...)", call_params={"job_id": job_id})


async def beta_canopy_export(job_id: str) -> dict:
    """仅当用户明确提到 beta/Canopy/测试服务时，读取 Canopy 任务导出文件信息。"""
    try:
        status = CanopyApiManager().job_status(job_id)
        export = _public_export_payload(status.get("export"))
        if not export.get("url"):
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → beta_canopy_export(...)", call_params={"job_id": job_id})


async def _request_canopy_api(
    *,
    path: str,
    params: dict[str, Any],
    api_key: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """兼容测试入口：执行 Canopy REST 请求，并要求响应为 JSON 对象。"""
    return await request_canopy_api(path=path, params=params, api_key=api_key, timeout_seconds=timeout_seconds)


def _get_scenario(scenario: str) -> dict[str, Any]:
    """读取场景元数据，未命中时返回清晰错误。"""
    meta = CANOPY_SCENARIOS.get(scenario)
    if not meta:
        supported = ", ".join(CANOPY_SCENARIOS)
        raise ValueError(f"不支持的 beta Canopy 场景：{scenario}。支持场景：{supported}")
    return meta


def _validate_domain(domain: str) -> None:
    """校验 Canopy domain，避免把中文站点或 country 参数误传给官方 API。"""
    if domain not in SUPPORTED_DOMAINS:
        supported = ", ".join(sorted(SUPPORTED_DOMAINS))
        raise ValueError(f"不支持的 Canopy domain：{domain}。支持值：{supported}")


def _normalize_scenario_params(scenario: str, params: dict[str, Any]) -> dict[str, Any]:
    """按场景补充轻量参数归一化，结构化入参始终优先。"""
    normalized = dict(params)
    if scenario == "product-reviews":
        _apply_product_reviews_aliases(normalized)
    return normalized


def _apply_product_reviews_aliases(params: dict[str, Any]) -> None:
    """从自然语言字段推断评论筛选参数，不覆盖显式结构化参数。"""
    if _is_blank(params.get("page")):
        params["page"] = 1

    text = _collect_natural_language_text(params)
    if not text:
        return

    if _is_blank(params.get("rating")):
        rating = _infer_review_rating(text)
        if rating:
            params["rating"] = rating

    if _is_blank(params.get("onlyVerifiedReviews")) and _mentions_verified_reviews(text):
        params["onlyVerifiedReviews"] = True


def _collect_natural_language_text(params: dict[str, Any]) -> str:
    """收集调用方放入 params 的自然语言提示字段。"""
    names = ("query", "text", "natural_language", "naturalLanguage", "user_input", "userInput")
    values = []
    for name in names:
        value = params.get(name)
        if not _is_blank(value):
            values.append(str(value))
    return "\n".join(values)


def _infer_review_rating(text: str) -> str | None:
    """根据明确星级/评价别名推断 Canopy rating 枚举。"""
    alias_groups = (
        ("ONE_STAR", ("差评", "一星", "1星", "1 星", "one star", "1-star", "1 star")),
        ("TWO_STAR", ("二星", "2星", "2 星", "two star", "2-star", "2 star")),
        ("THREE_STAR", ("三星", "3星", "3 星", "three star", "3-star", "3 star")),
        ("FOUR_STAR", ("四星", "4星", "4 星", "four star", "4-star", "4 star")),
        ("FIVE_STAR", ("五星", "5星", "5 星", "five star", "5-star", "5 star", "好评")),
    )
    for rating, aliases in alias_groups:
        if _contains_any_alias(text, aliases):
            return rating
    return None


def _mentions_verified_reviews(text: str) -> bool:
    """识别已验证购买评论的正向表达。"""
    negative_aliases = (
        "不要已验证",
        "不看已验证",
        "不限已验证",
        "不只看已验证",
        "not only verified",
        "not verified only",
    )
    if _contains_any_alias(text, negative_aliases):
        return False
    return _contains_any_alias(
        text,
        ("已验证购买", "验证购买", "verified purchase", "verified reviews", "only verified"),
    )


def _contains_any_alias(text: str, aliases: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    compact_text = "".join(lower_text.split())
    for alias in aliases:
        lower_alias = alias.lower()
        compact_alias = "".join(lower_alias.split())
        if lower_alias in lower_text or compact_alias in compact_text:
            return True
    return False


def _validate_required_params(scenario: str, meta: dict[str, Any], params: dict[str, Any]) -> None:
    """校验场景必填参数，支持普通必填和多选一必填。"""
    missing = [name for name in meta.get("required_params", []) if _is_blank(params.get(name))]
    if missing:
        raise ValueError(f"场景 {scenario} 缺少必填参数：{', '.join(missing)}")

    for group in meta.get("required_any", []):
        if all(_is_blank(params.get(name)) for name in group):
            raise ValueError(f"场景 {scenario} 至少需要提供以下参数之一：{', '.join(group)}")


def _is_blank(value: Any) -> bool:
    """判断参数是否为空；0 和 False 属于有效值。"""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _resolve_api_key(api_key: str | None) -> str:
    """解析 Canopy API key，测试阶段默认读取项目内本地文件。"""
    for candidate in (
        api_key,
        canopy_config.load_local_api_key(),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return CANOPY_API_KEY_PLACEHOLDER


def _normalize_mcp_export_format(value: str) -> str:
    """校验 MCP 对外导出格式；beta 当前只允许 xls。"""
    text = (value or "").strip().lower()
    if text in {"", "xls"}:
        return "xls"
    raise ValueError(f"不支持的导出格式：{value}。beta Canopy 当前仅支持 xls 表格导出。")


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return MCP-safe beta task data without local paths or secrets."""
    public = _strip_sensitive(payload)
    if isinstance(public, dict):
        public.pop("root_dir", None)
        public.pop("params_path", None)
        public.pop("raw_path", None)
        public.pop("result_path", None)
        public.pop("response", None)
        _strip_public_debug_fields(public.get("request"))
        _sanitize_public_export(public)
        _compact_public_data(public)
        public["warnings"] = _public_warnings(public.get("warnings"))
    return public


def _strip_public_debug_fields(request: Any) -> None:
    """移除 public MCP 返回中不应暴露的调试字段。"""
    if not isinstance(request, dict):
        return
    request.pop("api_key_placeholder_used", None)


def _sanitize_public_export(public: dict[str, Any]) -> None:
    export = public.get("export")
    if not isinstance(export, dict):
        return
    export.pop("path", None)
    url = export.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        export["url"] = None
        url = None
    if url:
        return

    warnings = public.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(
        {
            "stage": "export_url_unavailable",
            "message": "当前任务导出文件没有可下载地址，请稍后重试或联系管理员检查上传链路。",
        }
    )
    public["warnings"] = warnings


def _public_export_payload(export: Any) -> dict[str, Any]:
    if not isinstance(export, dict):
        raise ValueError("任务无导出文件")
    payload = _strip_sensitive(export)
    if not isinstance(payload, dict):
        raise ValueError("任务导出结构不合法")
    payload.pop("path", None)
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        payload["url"] = None
    return payload


def _compact_public_data(public: dict[str, Any]) -> None:
    data = public.get("data")
    if not isinstance(data, list):
        return
    public["data_preview"] = data[:MAX_PUBLIC_DATA_PREVIEW_ROWS]
    omitted = max(0, len(data) - MAX_PUBLIC_DATA_PREVIEW_ROWS)
    if omitted:
        public["data_omitted"] = omitted
        warnings = public.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            {
                "stage": "mcp_response_compact",
                "message": "返回数据量较大，MCP 响应仅保留摘要和导出文件，请通过导出文件查看完整数据。",
            }
        )
        public["warnings"] = warnings
    public.pop("data", None)


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {
        "api_key",
        "apikey",
        "api-key",
        "token",
        "authorization",
        "headers",
    }
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if normalized in blocked:
            continue
        result[key] = _strip_sensitive(item)
    return result


def _public_warnings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    warnings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        stage = item.get("stage")
        message = item.get("message")
        if message:
            warnings.append({"stage": stage, "message": message})
    return warnings


_NETWORK_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=True,
    destructiveHint=False,
)


_ALL_TOOLS = [
    beta_spec_must_read,
    beta_canopy_scenarios,
    beta_canopy_run,
    beta_canopy_job_status,
    beta_canopy_export,
]


def register(mcp) -> None:
    """向指定 MCP 实例注册 beta 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_READ_ANNOTATIONS)(fn)
