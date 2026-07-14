"""asin-data yicopy 销词引擎核心流程。

本模块从 ASIN 或 Amazon URL 中提取 ASIN，无登录采集商品页标题与五点描述，
再基于标题 2 词滑窗请求 Amazon 自动补全，最终输出关键词反查与词频结构。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

import httpx


ASIN_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{10})(?![A-Z0-9])", re.IGNORECASE)
ASIN_URL_PATTERN = re.compile(
    r"/(?:dp|gp/product|product)/([A-Z0-9]{10})(?:[/?#]|$)",
    re.IGNORECASE,
)
NON_WORD_SPACE_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(slots=True)
class ProductInfo:
    """保存单个 ASIN 的标题和前 5 条五点描述。"""

    asin: str
    title: str
    bullet_points: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, object]:
        """转换为 productList 输出结构。"""

        return {
            "asin": self.asin,
            "title": self.title,
            "bulletPoints": list(self.bullet_points[:5]),
        }


@dataclass(slots=True)
class PrefixKeywordResult:
    """保存单个标题前缀对应的 Amazon 自动补全关键词。"""

    asin: str
    prefix: str
    keywords: list[str] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, object]:
        """转换为 allKeywords 输出结构。"""

        return {
            "asin": self.asin,
            "prefix": self.prefix,
            "keywords": list(self.keywords),
        }


@dataclass(slots=True)
class KeywordFrequency:
    """保存关键词在标题、五点和总文本中的词频。"""

    search_term: str
    title_frequency: int
    bullets_frequency: int
    total_frequency: int

    def to_camel_dict(self) -> dict[str, object]:
        """转换为完整结果使用的 keywordReverse 字段结构。"""

        return {
            "searchTerm": self.search_term,
            "titleFrequency": self.title_frequency,
            "bulletsFrequency": self.bullets_frequency,
            "totalFrequency": self.total_frequency,
        }

    def to_export_dict(self) -> dict[str, object]:
        """转换为示例文件一致的纯销词结果行。"""

        return {
            "keyword": self.search_term,
            "titleFrequency": self.title_frequency,
            "bulletsFrequency": self.bullets_frequency,
            "totalFrequency": self.total_frequency,
        }


@dataclass(slots=True)
class YicopyRunOptions:
    """保存销词引擎运行参数。"""

    site: str = "US"
    locale: str = "en_US"
    timeout_seconds: float = 30.0
    request_delay_seconds: float = 0.0
    max_asins: int | None = None
    max_prefixes_per_asin: int | None = None
    completion_limit: int = 11


@dataclass(frozen=True, slots=True)
class _AmazonSiteConfig:
    """保存 Amazon 站点访问配置。"""

    domain: str
    completion_host: str
    mid: str


SITE_CONFIGS: dict[str, _AmazonSiteConfig] = {
    "US": _AmazonSiteConfig("amazon.com", "completion.amazon.com", "ATVPDKIKX0DER"),
}
YICOPY_PROTOCOL = "asin_data_ai_response"
YICOPY_PROTOCOL_VERSION = "1.0"
YICOPY_DATA_SCOPE = "yicopy_keyword_reverse"
YICOPY_SOURCE_KEY = "yicopy_keyword_reverse"
YICOPY_PREVIEW_LIMIT = 20
YICOPY_COLUMNS = ["keyword", "titleFrequency", "bulletsFrequency", "totalFrequency"]


class _ProductDetailParser(HTMLParser):
    """按 span#productTitle 和 div#feature-bullets .a-list-item 解析商品页。"""

    def __init__(self) -> None:
        """初始化 HTML 解析状态。"""

        super().__init__(convert_charrefs=True)
        self.title_chunks: list[str] = []
        self.bullets: list[str] = []
        self._title_depth: int | None = None
        self._feature_depth: int | None = None
        self._bullet_depth: int | None = None
        self._bullet_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """进入标签时识别标题、五点容器和五点文本节点。"""

        attr_map = _attrs_to_dict(attrs)
        normalized_tag = tag.lower()

        if self._title_depth is not None:
            self._title_depth += 1
        elif normalized_tag == "span" and attr_map.get("id") == "productTitle":
            self._title_depth = 1

        if self._feature_depth is not None:
            self._feature_depth += 1
        elif normalized_tag == "div" and attr_map.get("id") == "feature-bullets":
            self._feature_depth = 1

        if self._bullet_depth is not None:
            self._bullet_depth += 1
        elif self._feature_depth is not None and _has_class(attr_map, "a-list-item"):
            self._bullet_depth = 1
            self._bullet_chunks = []

    def handle_endtag(self, tag: str) -> None:
        """离开标签时结束对应采集区间。"""

        _ = tag
        if self._bullet_depth is not None:
            self._bullet_depth -= 1
            if self._bullet_depth <= 0:
                bullet = _clean_text(" ".join(self._bullet_chunks))
                if bullet:
                    self.bullets.append(bullet)
                self._bullet_depth = None
                self._bullet_chunks = []

        if self._feature_depth is not None:
            self._feature_depth -= 1
            if self._feature_depth <= 0:
                self._feature_depth = None

        if self._title_depth is not None:
            self._title_depth -= 1
            if self._title_depth <= 0:
                self._title_depth = None

    def handle_data(self, data: str) -> None:
        """采集标题和五点文本。"""

        if self._title_depth is not None:
            self.title_chunks.append(data)
        if self._bullet_depth is not None:
            self._bullet_chunks.append(data)


class YicopyKeywordEngine:
    """执行 yicopy 销词引擎完整流程。"""

    async def run(
        self,
        sources: list[str],
        options: YicopyRunOptions | None = None,
    ) -> dict[str, Any]:
        """接收 ASIN/URL 输入并返回包含全链路证据的完整 JSON。"""

        run_options = options or YicopyRunOptions()
        asins = extract_asins_from_inputs(sources)
        if run_options.max_asins is not None:
            asins = asins[: run_options.max_asins]
        if not asins:
            raise ValueError("请传入至少一个有效 ASIN 或包含 ASIN 的 Amazon URL。")

        errors: list[dict[str, str]] = []
        timeout = httpx.Timeout(run_options.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            products = await self._fetch_products(client, asins, run_options, errors)
            if not products:
                raise ValueError(f"未能成功采集任何商品详情页：{_format_error_messages(errors)}")
            all_keywords = await self._fetch_all_completion_keywords(
                client,
                products,
                run_options,
                errors,
            )
            completion_keywords = dedupe_preserve_order(
                keyword
                for prefix_result in all_keywords
                for keyword in prefix_result.keywords
            )
            keyword_reverse = build_reference_keyword_rows(completion_keywords)

        return {
            "status": "succeeded" if not errors else "partial_failed",
            "asins": asins,
            "productList": [product.to_public_dict() for product in products],
            "allKeywords": [item.to_public_dict() for item in all_keywords],
            "completionKeywords": completion_keywords,
            "keywordReverse": [item.to_camel_dict() for item in keyword_reverse],
            "keywordRows": [item.to_export_dict() for item in keyword_reverse],
            "errors": errors,
            "summary": {
                "asinCount": len(asins),
                "productCount": len(products),
                "prefixCount": len(all_keywords),
                "completionKeywordCount": len(completion_keywords),
                "keywordReverseCount": len(keyword_reverse),
                "errorCount": len(errors),
                "analysisMode": "frontend",
                "loginRequired": False,
            },
        }

    async def _fetch_products(
        self,
        client: httpx.AsyncClient,
        asins: list[str],
        options: YicopyRunOptions,
        errors: list[dict[str, str]],
    ) -> list[ProductInfo]:
        """逐个访问 Amazon 商品详情页并解析标题和五点。"""

        products: list[ProductInfo] = []
        for asin in asins:
            try:
                html_text = await self._fetch_product_html(client, asin, options)
                products.append(parse_product_detail_html(asin, html_text))
            except (ValueError, httpx.HTTPError) as exc:
                errors.append({"stage": "product_detail", "asin": asin, "message": str(exc)})
        return products

    async def _fetch_all_completion_keywords(
        self,
        client: httpx.AsyncClient,
        products: list[ProductInfo],
        options: YicopyRunOptions,
        errors: list[dict[str, str]],
    ) -> list[PrefixKeywordResult]:
        """按每个商品标题的 2 词滑动窗口逐个查询自动补全。"""

        all_keywords: list[PrefixKeywordResult] = []
        for product in products:
            prefixes = generate_title_prefixes(product.title)
            if options.max_prefixes_per_asin is not None:
                prefixes = prefixes[: options.max_prefixes_per_asin]
            for prefix in prefixes:
                try:
                    keywords = await self._fetch_completion_keywords(client, prefix, options)
                except httpx.HTTPError as exc:
                    errors.append(
                        {
                            "stage": "completion",
                            "asin": product.asin,
                            "prefix": prefix,
                            "message": str(exc),
                        }
                    )
                    keywords = []
                all_keywords.append(
                    PrefixKeywordResult(asin=product.asin, prefix=prefix, keywords=keywords)
                )
                if options.request_delay_seconds > 0:
                    await asyncio.sleep(options.request_delay_seconds)
        return all_keywords

    async def _fetch_product_html(
        self,
        client: httpx.AsyncClient,
        asin: str,
        options: YicopyRunOptions,
    ) -> str:
        """无登录访问 Amazon 商品详情页，多入口兜底后返回 HTML。"""

        config = _site_config(options.site)
        diagnostics: list[str] = []
        for url in _product_detail_urls(config, asin, options.locale):
            try:
                response = await client.get(url, headers=_amazon_page_headers(options.locale))
                response.raise_for_status()
            except httpx.HTTPError as exc:
                diagnostics.append(f"{url} -> {exc}")
                continue
            html_text = response.text
            if _looks_like_product_detail_html(html_text):
                return html_text
            diagnostics.append(f"{url} -> {_describe_non_product_html(html_text)}")
        raise ValueError(f"无法采集 ASIN {asin} 商品详情页：{'；'.join(diagnostics)}")

    async def _fetch_completion_keywords(
        self,
        client: httpx.AsyncClient,
        prefix: str,
        options: YicopyRunOptions,
    ) -> list[str]:
        """调用 Amazon completion API 并提取 suggestions[].value。"""

        config = _site_config(options.site)
        response = await client.get(
            f"https://{config.completion_host}/api/2017/suggestions",
            params=_build_completion_params(prefix, options, config),
            headers=_amazon_completion_headers(options.locale),
        )
        response.raise_for_status()
        data = response.json()
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            return []
        return [
            value.strip()
            for item in suggestions
            if isinstance(item, dict)
            and isinstance(value := item.get("value"), str)
            and value.strip()
        ]


def extract_asins_from_inputs(sources: list[str]) -> list[str]:
    """从 ASIN、Amazon URL 或混合文本中提取去重后的 ASIN。"""

    result: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if not source:
            continue
        text = str(source)
        matches = [match.group(1).upper() for match in ASIN_URL_PATTERN.finditer(text)]
        matches.extend(match.group(1).upper() for match in ASIN_PATTERN.finditer(text))
        for asin in matches:
            if asin in seen:
                continue
            seen.add(asin)
            result.append(asin)
    return result


def parse_product_detail_html(asin: str, html_text: str) -> ProductInfo:
    """从商品详情 HTML 中解析 asin、标题和前 5 个五点。"""

    parser = _ProductDetailParser()
    parser.feed(html_text)
    title = _clean_text(" ".join(parser.title_chunks))
    if not title:
        raise ValueError(f"无法从 ASIN {asin} 的商品页 HTML 中解析标题：{_describe_non_product_html(html_text)}")
    return ProductInfo(
        asin=asin.upper(),
        title=title,
        bullet_points=[bullet for bullet in parser.bullets if bullet][:5],
    )


def generate_title_prefixes(title: str) -> list[str]:
    """按 JS 规则 replace(/[^\\w\\s]/g, '') 后生成 2 词滑动窗口。"""

    normalized = NON_WORD_SPACE_PATTERN.sub("", title)
    words = [word for word in WHITESPACE_PATTERN.split(normalized.strip()) if word]
    return [" ".join(words[index : index + 2]) for index in range(0, max(0, len(words) - 1))]


def dedupe_preserve_order(values: Iterable[object]) -> list[str]:
    """对关键词忽略大小写去重，并保留首次出现顺序。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = _clean_text(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def build_reference_keyword_rows(completion_keywords: list[str]) -> list[KeywordFrequency]:
    """按参考前端导出逻辑生成词频行，三个频次字段固定为 0。"""

    return [
        KeywordFrequency(
            search_term=keyword,
            title_frequency=0,
            bullets_frequency=0,
            total_frequency=0,
        )
        for keyword in completion_keywords
    ]


def format_keyword_reverse_export(result: dict[str, Any]) -> list[dict[str, object]]:
    """把完整结果转换为示例文件一致的纯数组输出。"""

    rows = result.get("keywordRows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    keyword_reverse = result.get("keywordReverse")
    if not isinstance(keyword_reverse, list):
        return []
    export_rows: list[dict[str, object]] = []
    for row in keyword_reverse:
        if not isinstance(row, dict):
            continue
        export_rows.append(
            {
                "keyword": str(row.get("keyword") or row.get("searchTerm") or ""),
                "titleFrequency": _to_int(row.get("titleFrequency", 0)),
                "bulletsFrequency": _to_int(row.get("bulletsFrequency", 0)),
                "totalFrequency": _to_int(row.get("totalFrequency", 0)),
            }
        )
    return export_rows


def load_source_tokens_from_file(path: Path) -> list[str]:
    """从 JSON 或普通文本输入文件中读取 ASIN/URL 原始输入。"""

    content = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return [content]
    tokens: list[str] = []
    _collect_source_tokens(parsed, tokens)
    return tokens


def render_yicopy_result(result: dict[str, Any], result_format: str) -> object:
    """按输出格式渲染 yicopy 结果。"""

    if result_format == "full":
        return result
    return format_keyword_reverse_export(result)


def normalize_yicopy_result_format(value: str) -> str:
    """校验并归一化 yicopy 输出格式。"""

    normalized = value.strip().lower()
    if normalized not in {"keyword-reverse", "full"}:
        raise ValueError("result-format 只能是 keyword-reverse 或 full。")
    return normalized


def build_yicopy_ai_ready_response(
    *,
    tool_name: str,
    request: dict[str, Any],
    result: dict[str, Any],
    rendered_result: object,
    result_format: str,
    site: str,
    output_file: str | None = None,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    """把 yicopy 结果转换为 asin-data 统一 AI Ready 返回协议。"""

    rows = _yicopy_keyword_rows(rendered_result, result)
    asins = [str(item).strip().upper() for item in result.get("asins", []) if str(item).strip()]
    if not asins:
        requested = request.get("asin")
        if isinstance(requested, list):
            asins = extract_asins_from_inputs([str(item) for item in requested])
        elif requested:
            asins = extract_asins_from_inputs([str(requested)])
    if not asins:
        asins = ["UNKNOWN"]

    artifacts = _yicopy_artifacts(asins[0], output_file)
    dataset = _yicopy_dataset(asins[0], rows, artifacts)
    diagnostics = _yicopy_diagnostics(result)
    item_status = "success" if result.get("status") == "succeeded" and not diagnostics else "partial_failed"
    output_dir = Path(output_file).parent.as_posix() if output_file else ""

    response = {
        "status": result.get("status"),
        "result_format": result_format,
        "result": rendered_result,
        "output_file": output_file,
        "row_count": len(rows),
        "metadata": {
            "protocol": YICOPY_PROTOCOL,
            "protocol_version": YICOPY_PROTOCOL_VERSION,
            "tool": tool_name,
            "data_scope": YICOPY_DATA_SCOPE,
            "site": site,
            "request": _sanitize_yicopy_request(request),
        },
        "run": {
            "run_id": "",
            "output_dir": output_dir,
            "elapsed_seconds": round(elapsed_seconds, 3) if elapsed_seconds is not None else None,
            "cache_hit": False,
        },
        "summary": _yicopy_summary(result, rows, asins, diagnostics),
        "items": [
            {
                "asin": asin,
                "site": site,
                "status": item_status,
                "artifacts": artifacts,
                "datasets": [dataset],
                "diagnostics": diagnostics,
            }
            for asin in asins
        ],
        "diagnostics": diagnostics,
        "deprecated_fields": [],
        "preferred_fields": ["items[].artifacts", "items[].datasets", "items[].diagnostics"],
    }
    return response


def _yicopy_keyword_rows(rendered_result: object, result: dict[str, Any]) -> list[dict[str, object]]:
    """提取标准 keyword-reverse 行，full 模式也从完整结果中抽取关键词表。"""

    if isinstance(rendered_result, list):
        return [row for row in rendered_result if isinstance(row, dict)]
    return format_keyword_reverse_export(result)


def _yicopy_artifacts(asin: str, output_file: str | None) -> list[dict[str, Any]]:
    """构建 yicopy JSON 文件索引。"""

    if not output_file:
        return []
    path = Path(output_file)
    return [
        {
            "artifact_id": f"{asin}_{YICOPY_SOURCE_KEY}_json",
            "file_key": YICOPY_SOURCE_KEY,
            "type": "json",
            "uri": None,
            "local_path": path.as_posix(),
            "complete": path.exists(),
            "source_filename": path.name,
            "report_filename": path.name,
        }
    ]


def _yicopy_dataset(
    asin: str,
    rows: list[dict[str, object]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建 yicopy keyword-reverse 数据集索引。"""

    artifact_id = str(artifacts[0].get("artifact_id")) if artifacts else ""
    empty = not rows
    diagnostics = []
    if empty:
        diagnostics.append(
            {
                "level": "warning",
                "code": "EMPTY_DATASET",
                "message": "yicopy keyword reverse has no data rows.",
                "source_key": YICOPY_SOURCE_KEY,
                "action": "rerun_yicopy_keyword_engine",
            }
        )
    return {
        "dataset_id": f"{asin}_{YICOPY_SOURCE_KEY}",
        "source_key": YICOPY_SOURCE_KEY,
        "semantic_type": "keyword_reverse",
        "sheet_name": "",
        "artifact_id": artifact_id,
        "row_count": len(rows),
        "column_count": len(YICOPY_COLUMNS),
        "columns": list(YICOPY_COLUMNS),
        "preview_rows": rows[:YICOPY_PREVIEW_LIMIT],
        "quality": {
            "empty": empty,
            "large_sheet": len(rows) > 500,
            "encoding_ok": True,
            "encoding_suspected": False,
            "has_warnings": bool(diagnostics),
        },
        "diagnostics": diagnostics,
    }


def _yicopy_diagnostics(result: dict[str, Any]) -> list[dict[str, Any]]:
    """把 yicopy 内部 errors 转换为统一诊断对象。"""

    diagnostics: list[dict[str, Any]] = []
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    for error in errors:
        if not isinstance(error, dict):
            continue
        diagnostics.append(
            {
                "level": "error",
                "code": "SOURCE_ERROR",
                "message": str(error.get("message") or ""),
                "source_key": YICOPY_SOURCE_KEY,
                "stage": error.get("stage"),
                "asin": error.get("asin"),
                "action": "rerun_yicopy_keyword_engine",
            }
        )
    return diagnostics


def _yicopy_summary(
    result: dict[str, Any],
    rows: list[dict[str, object]],
    asins: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """合并 yicopy 原始 summary 与 AI Ready 通用摘要字段。"""

    original = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    failed_asins = asins if diagnostics else []
    return {
        **original,
        "input_count": original.get("asinCount", len(asins)),
        "asin_count": original.get("asinCount", len(asins)),
        "dataset_count": len(asins),
        "artifact_count": 1 if rows else 0,
        "keyword_reverse_count": len(rows),
        "source_error_count": original.get("errorCount", len(diagnostics)),
        "failed_asin_count": len(failed_asins),
        "failed_asins": failed_asins,
    }


def _sanitize_yicopy_request(request: dict[str, Any]) -> dict[str, Any]:
    """过滤请求快照中的敏感字段。"""

    blocked_keys = {"jwt", "session_id", "authorization", "cookie", "password", "token"}
    return {key: value for key, value in request.items() if key.lower() not in blocked_keys}


def _collect_source_tokens(value: Any, tokens: list[str]) -> None:
    """递归收集 JSON 输入中的字符串值。"""

    if isinstance(value, str):
        tokens.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_source_tokens(item, tokens)
        return
    if isinstance(value, dict):
        for key in ("asin", "asins", "url", "urls", "source", "sources"):
            if key in value:
                _collect_source_tokens(value[key], tokens)


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    """将 HTML 属性列表转换为小写 key 字典。"""

    return {key.lower(): value or "" for key, value in attrs}


def _has_class(attr_map: dict[str, str], class_name: str) -> bool:
    """判断 class 属性是否包含目标类名。"""

    return class_name in {item.strip() for item in attr_map.get("class", "").split()}


def _clean_text(value: str) -> str:
    """压缩空白并去掉首尾空白。"""

    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _site_config(site: str) -> _AmazonSiteConfig:
    """获取 Amazon 站点配置，未知站点默认美国站。"""

    return SITE_CONFIGS.get(site.upper(), SITE_CONFIGS["US"])


def _product_detail_urls(
    config: _AmazonSiteConfig,
    asin: str,
    locale: str,
) -> list[str]:
    """生成无登录采集商品详情页的候选 URL，后置入口用于绕过普通 /dp 反爬页。"""

    language = locale.replace("_", "-")
    return [
        f"https://{config.domain}/dp/{asin}",
        f"https://www.{config.domain}/dp/{asin}?th=1&psc=1&language={locale}",
        f"https://www.{config.domain}/gp/product/{asin}?th=1&psc=1&language={locale}",
        f"https://www.{config.domain}/-/dp/{asin}?th=1&psc=1&language={locale}",
        f"https://www.{config.domain}/-/dp/{asin}?th=1&psc=1&language={language}",
    ]


def _looks_like_product_detail_html(html_text: str) -> bool:
    """判断 HTML 是否包含商品详情页核心节点。"""

    return 'id="productTitle"' in html_text or "id='productTitle'" in html_text


def _describe_non_product_html(html_text: str) -> str:
    """给非商品详情 HTML 生成可读诊断信息。"""

    lowered = html_text.lower()
    if "captcha" in lowered:
        return "Amazon 返回 captcha/反自动化页面"
    if "robot check" in lowered:
        return "Amazon 返回 Robot Check 页面"
    if "dogs of amazon" in lowered:
        return "Amazon 返回 Dogs of Amazon 错误页"
    title_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = _clean_text(re.sub(r"<.*?>", "", title_match.group(1)))
        return f"非商品详情页，title={title}"
    return f"非商品详情页，HTML 长度={len(html_text)}"


def _format_error_messages(errors: list[dict[str, str]]) -> str:
    """把内部错误列表整理成命令行可读文本。"""

    if not errors:
        return "未记录具体错误。"
    messages: list[str] = []
    for error in errors:
        asin = error.get("asin", "unknown")
        stage = error.get("stage", "unknown")
        message = error.get("message", "")
        messages.append(f"{asin}/{stage}: {message}")
    return "；".join(messages)


def _amazon_page_headers(locale: str) -> dict[str, str]:
    """生成商品详情页请求头，不携带登录态。"""

    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": locale.replace("_", "-"),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }


def _amazon_completion_headers(locale: str) -> dict[str, str]:
    """生成 completion API 请求头，不携带登录态。"""

    return {
        "Accept": "application/json",
        "Accept-Language": locale.replace("_", "-"),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }


def _build_completion_params(
    prefix: str,
    options: YicopyRunOptions,
    config: _AmazonSiteConfig,
) -> list[tuple[str, str]]:
    """按参考前端销词引擎参数构造 Amazon 自动补全查询。"""

    params = [
        ("limit", str(options.completion_limit)),
        ("prefix", prefix),
        ("suggestion-type", "KEYWORD"),
    ]
    params.extend(
        [
            ("page-type", "Gateway"),
            ("alias", "aps"),
            ("site-variant", "desktop"),
            ("version", "3"),
            ("event", "onkeypress"),
            ("wc", ""),
            ("lop", options.locale),
            ("last-prefix", prefix),
            ("avg-ks-time", "500"),
            ("fb", "1"),
            ("mid", config.mid),
            ("plain-mid", "1"),
            ("client-info", "search-ui"),
        ]
    )
    return params


def _to_int(value: Any) -> int:
    """安全转换数字字段。"""

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
