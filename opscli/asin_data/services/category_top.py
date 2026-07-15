"""内部类目 Top ASIN 取数与单文件交付服务。

本模块只编排类目 Top 接口、刊登基础数据接口、爬虫详情接口和 OSS
上传，不复用完整 ASIN 巡检流水线，避免引入卖家精灵、Rufus、拆包 ZIP
等慢步骤。
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.asin_data.services.ai_response import (
    DEPRECATED_FIELDS,
    PREFERRED_FIELDS,
    PROTOCOL,
    PROTOCOL_VERSION,
    diagnostic,
)
from opscli.asin_data.services.bi_report_data import (
    AsinBiReportDataClient,
    extract_rows,
    _normalize_site_code,
    normalize_asin,
    normalize_asins,
    rows_for_asin,
)
from opscli.asin_data.services.report_files import _report_files_base_url
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.file_uploads import FileUploadClient
from opscli.shared.http import parse_remote_response


DEFAULT_INTERNAL_CATEGORY_TOP_ENDPOINT = "/dataMetrics/v1/asin-report-files/internal-category-top10"
DEFAULT_TIMEOUT = 20
CATEGORY_TOP_DATA_SCOPE = "internal_category_top"
CATEGORY_TOP_FILE_KEY = "category_top_json"
ENRICH_SOURCE_KEYS = ("listing_basic", "crawler_details")
DATASET_PREVIEW_LIMITS = {
    "category_top": 10,
    "listing_basic": 3,
    "crawler_details": 5,
}


class AsinCategoryTopError(RemoteError):
    """内部类目 Top ASIN 取数错误。"""

    code = "ASIN_CATEGORY_TOP_ERROR"


class AsinCategoryTopHttpError(AsinCategoryTopError):
    """内部类目 Top ASIN 取数 HTTP 错误。"""

    code = "ASIN_CATEGORY_TOP_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class AsinCategoryTopBusinessError(AsinCategoryTopError):
    """内部类目 Top ASIN 取数业务错误。"""

    code = "ASIN_CATEGORY_TOP_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class AsinCategoryTopBadJsonError(AsinCategoryTopError):
    """内部类目 Top ASIN 取数响应 JSON 错误。"""

    code = "ASIN_CATEGORY_TOP_BAD_JSON"


class AsinCategoryTopClient:
    """调用 OPS 内部类目 Top ASIN 接口的轻量客户端。"""

    def __init__(
        self,
        *,
        auth_client: AuthClient | None = None,
        endpoint: str = DEFAULT_INTERNAL_CATEGORY_TOP_ENDPOINT,
        http_get: Callable[..., httpx.Response] | None = None,
        ops_url: str | None = None,
    ) -> None:
        """创建客户端。

        Args:
            auth_client: 复用现有 OPS 登录态的认证客户端。
            endpoint: 内部类目 Top ASIN 接口路径。
            http_get: 测试注入用 HTTP GET 函数。
            ops_url: OPS 服务根地址。
        """
        self.auth_client = auth_client or AuthClient()
        self.endpoint = endpoint
        self.http_get = http_get or httpx.get
        self.ops_url = _report_files_base_url(ops_url or OPS_URL)

    def fetch(
        self,
        *,
        category: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """查询指定平台类目的 Top ASIN 数据。"""
        normalized_category = category.strip()
        if not normalized_category:
            raise ValueError("category 不能为空")
        _validate_limit(limit)
        _validate_date_range(date_from=date_from, date_to=date_to)

        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        params: dict[str, Any] = {"category": normalized_category, "limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        response = self.http_get(
            self._resolve_endpoint(),
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=AsinCategoryTopHttpError,
            business_error_cls=AsinCategoryTopBusinessError,
            bad_json_error_cls=AsinCategoryTopBadJsonError,
        )
        rows = extract_rows(payload.get("data") if isinstance(payload, dict) and "data" in payload else payload)
        return {
            "status": "success",
            "endpoint": self.endpoint,
            "params": params,
            "row_count": len(rows),
            "rows": rows,
            "raw": payload,
        }

    def _resolve_endpoint(self) -> str:
        """把相对路径转换为完整 OPS URL。"""
        text = self.endpoint.strip()
        if text.startswith(("http://", "https://")):
            return text
        if not text.startswith("/"):
            text = f"/{text}"
        return f"{self.ops_url}{text}"


class AsinCategoryTopService:
    """类目 Top ASIN 单文件取数服务，供 CLI 和 MCP 共用。"""

    def __init__(
        self,
        *,
        top_client: Any | None = None,
        bi_report_data_client_factory: Callable[[], Any] | None = None,
        file_upload_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        """创建服务编排器。"""
        self._top_client = top_client or AsinCategoryTopClient()
        self._bi_report_data_client_factory = bi_report_data_client_factory or AsinBiReportDataClient
        self._file_upload_client_factory = file_upload_client_factory or FileUploadClient

    def run(
        self,
        *,
        category: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        site: str = "US",
        output_dir: str = "output/asin-data",
        run_id: str | None = None,
        upload: bool = True,
        enrich: bool = True,
        return_content: bool = False,
    ) -> dict[str, Any]:
        """查询类目 Top ASIN 并生成一个可上传到 OSS 的 JSON 文件。"""
        started_at = time.perf_counter()
        normalized_category = category.strip()
        normalized_site = _normalize_site(site)
        normalized_run_id = run_id or _default_run_id(normalized_category)

        top_result = self._top_client.fetch(
            category=normalized_category,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        top_rows = top_result.get("rows") if isinstance(top_result.get("rows"), list) else []
        asins = _top_asins(top_rows)
        site_by_asin = _site_by_asin(top_rows, default_site=normalized_site)
        enrichment = (
            self._fetch_enrichment(
                asins=asins,
                date_from=date_from,
                date_to=date_to,
                site_by_asin=site_by_asin,
                default_site=normalized_site,
            )
            if enrich and asins
            else _empty_enrichment(asins)
        )

        output_path = _document_path(output_dir=output_dir, run_id=normalized_run_id)
        file_info: dict[str, Any] = {
            "file_path": output_path.as_posix(),
            "file_name": output_path.name,
        }
        response = _build_ai_ready_document(
            category=normalized_category,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            site=normalized_site,
            run_id=normalized_run_id,
            enrichment=enrichment,
            top_rows=top_rows,
            asins=asins,
            site_by_asin=site_by_asin,
            file_info=file_info,
            elapsed_seconds=time.perf_counter() - started_at,
        )
        _write_document(response, path=output_path)
        if upload:
            upload_result = self._file_upload_client_factory().upload(
                output_path,
                purpose="asin_data_category_top_json",
                folder="asin-data",
                public="1",
                filename=output_path.name,
                metadata={
                    "run_id": normalized_run_id,
                    "category": normalized_category,
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": limit,
                    "source": "asin-data category-top",
                },
            )
            file_info["file_url"] = upload_result.url
            file_info["upload"] = {"url": upload_result.url, "raw": upload_result.raw}
            _attach_file_url(response, file_info)

        response["summary"]["file_url"] = file_info.get("file_url")
        return response if return_content else _compact_response(response)

    def _fetch_enrichment(
        self,
        *,
        asins: Sequence[str],
        date_from: str | None,
        date_to: str | None,
        site_by_asin: Mapping[str, str],
        default_site: str,
    ) -> dict[str, dict[str, Any]]:
        """并发查询刊登基础数据和爬虫详情数据。"""
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                key: executor.submit(
                    self._fetch_one_source,
                    source_key=key,
                    asins=asins,
                    date_from=date_from,
                    date_to=date_to,
                    site_by_asin=site_by_asin,
                    default_site=default_site,
                )
                for key in ENRICH_SOURCE_KEYS
            }
            return {key: futures[key].result() for key in ENRICH_SOURCE_KEYS}

    def _fetch_one_source(
        self,
        *,
        source_key: str,
        asins: Sequence[str],
        date_from: str | None,
        date_to: str | None,
        site_by_asin: Mapping[str, str],
        default_site: str,
    ) -> dict[str, Any]:
        """查询单个补充数据源，失败时返回结构化 source 错误而不中断整体文件生成。"""
        try:
            return self._bi_report_data_client_factory().fetch(
                asins=asins,
                start_date=date_from,
                end_date=date_to,
                source_keys=(source_key,),
                site_by_asin=site_by_asin,
                default_site=default_site,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "asins": list(asins),
                "count": len(asins),
                "sources": {
                    source_key: {
                        "key": source_key,
                        "status": "failed",
                        "row_count": 0,
                        "rows": [],
                        "raw": None,
                        "error": _error_dict(exc),
                        "error_message": str(exc),
                    }
                },
            }


def _build_ai_ready_document(
    *,
    category: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    site: str,
    run_id: str,
    enrichment: Mapping[str, dict[str, Any]],
    top_rows: Sequence[dict[str, Any]],
    asins: Sequence[str],
    site_by_asin: Mapping[str, str],
    file_info: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """构造与 live-data ai_ready 对齐的返回文档。"""
    artifact = _artifact(file_info=file_info)
    items = [
        _build_item(
            top_row=row,
            enrichment=enrichment,
            default_site=site,
            site_by_asin=site_by_asin,
            artifact=artifact,
        )
        for row in top_rows
        if _row_asin(row)
    ]
    diagnostics = _global_diagnostics(items=items, date_from=date_from, date_to=date_to)
    failed_asins = [str(item.get("asin")) for item in items if item.get("status") != "success"]
    return {
        "success": True,
        "metadata": {
            "protocol": PROTOCOL,
            "protocol_version": PROTOCOL_VERSION,
            "tool": "asin_data_category_top",
            "data_scope": CATEGORY_TOP_DATA_SCOPE,
            "site": site,
            "request": {
                "category": category,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
                "site": site,
                "run_id": run_id,
            },
        },
        "run": {
            "run_id": run_id,
            "output_dir": str(Path(str(file_info.get("file_path") or "")).parent),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "cache_hit": False,
        },
        "summary": {
            "status": _summary_status(top_count=len(top_rows), failed_asins=failed_asins),
            "category": category,
            "input_count": len(asins),
            "asin_count": len(asins),
            "top_count": len(top_rows),
            "source_error_count": _source_error_count(enrichment),
            "failed_asin_count": len(failed_asins),
            "failed_asins": failed_asins,
            "artifact_count": 1 if file_info.get("file_path") else 0,
        },
        "items": items,
        "diagnostics": diagnostics,
        "deprecated_fields": DEPRECATED_FIELDS,
        "preferred_fields": PREFERRED_FIELDS,
    }


def _build_item(
    *,
    top_row: dict[str, Any],
    enrichment: Mapping[str, dict[str, Any]],
    default_site: str,
    site_by_asin: Mapping[str, str],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    """把 Top 行与同 ASIN 的补充数据转换为 AI Ready item。"""
    asin = _row_asin(top_row)
    listing_rows = _rows_for_source(enrichment, "listing_basic", asin)
    crawler_rows = _rows_for_source(enrichment, "crawler_details", asin)
    datasets = [
        _dataset(
            asin=asin,
            source_key="category_top",
            rows=[top_row],
            artifact_id=str(artifact.get("artifact_id") or ""),
        ),
        _dataset(
            asin=asin,
            source_key="listing_basic",
            rows=listing_rows,
            artifact_id=str(artifact.get("artifact_id") or ""),
            source_error=_source_error_message(enrichment, "listing_basic"),
        ),
        _dataset(
            asin=asin,
            source_key="crawler_details",
            rows=crawler_rows,
            artifact_id=str(artifact.get("artifact_id") or ""),
            source_error=_source_error_message(enrichment, "crawler_details"),
        ),
    ]
    item_diagnostics = _collect_dataset_diagnostics(datasets)
    return {
        "asin": asin,
        "site": site_by_asin.get(asin) or default_site,
        "status": "success" if not _has_error(item_diagnostics) else "failed",
        "rank": _first_present(top_row, "排名", "sales_rank", "rank"),
        "artifacts": [dict(artifact)],
        "datasets": datasets,
        "diagnostics": item_diagnostics,
    }


def _artifact(*, file_info: Mapping[str, Any]) -> dict[str, Any]:
    """构造与 live-data artifacts 对齐的单文件索引。"""
    local_path = str(file_info.get("file_path") or "")
    path = Path(local_path) if local_path else None
    return {
        "artifact_id": "internal_category_top_json",
        "file_key": CATEGORY_TOP_FILE_KEY,
        "type": "json",
        "uri": file_info.get("file_url"),
        "local_path": path.as_posix() if path else "",
        "complete": bool(path),
        "source_filename": path.name if path else "",
        "report_filename": path.name if path else "internal-category-top-asin-data.json",
    }


def _dataset(
    *,
    asin: str,
    source_key: str,
    rows: Sequence[dict[str, Any]],
    artifact_id: str,
    source_error: str | None = None,
) -> dict[str, Any]:
    """构造与 live-data datasets 对齐的数据集描述。"""
    row_list = [dict(row) for row in rows if isinstance(row, dict)]
    columns = _columns(row_list)
    preview_limit = DATASET_PREVIEW_LIMITS.get(source_key, 5)
    dataset_diagnostics: list[dict[str, Any]] = []
    if source_error:
        dataset_diagnostics.append(
            diagnostic(
                "error",
                "SOURCE_ERROR",
                source_error,
                source_key=source_key,
                action="check_auth_or_backend_endpoint",
            )
        )
    elif not row_list:
        dataset_diagnostics.append(
            diagnostic(
                "warning",
                "EMPTY_DATASET",
                f"{source_key} has no data rows.",
                source_key=source_key,
                action="check_source_or_date_range",
            )
        )
    return {
        "dataset_id": f"{asin}_{source_key}",
        "source_key": source_key,
        "semantic_type": source_key,
        "artifact_id": artifact_id,
        "row_count": len(row_list),
        "column_count": len(columns),
        "columns": columns,
        "preview_rows": row_list[:preview_limit],
        "rows": row_list,
        "quality": {
            "empty": len(row_list) == 0,
            "large_sheet": len(row_list) > 500,
            "encoding_ok": True,
            "encoding_suspected": False,
            "has_warnings": bool(dataset_diagnostics),
        },
        "diagnostics": dataset_diagnostics,
    }


def _rows_for_source(enrichment: Mapping[str, dict[str, Any]], source_key: str, asin: str) -> list[dict[str, Any]]:
    """按 ASIN 从补充数据源中筛出对应行。"""
    bundle = enrichment.get(source_key) if isinstance(enrichment.get(source_key), dict) else {}
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    source = sources.get(source_key) if isinstance(sources.get(source_key), dict) else {}
    rows = source.get("rows") if isinstance(source.get("rows"), list) else []
    return rows_for_asin(rows, asin)


def _source_error_message(enrichment: Mapping[str, dict[str, Any]], source_key: str) -> str | None:
    """读取补充数据源错误信息。"""
    bundle = enrichment.get(source_key) if isinstance(enrichment.get(source_key), dict) else {}
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    source = sources.get(source_key) if isinstance(sources.get(source_key), dict) else {}
    if source.get("status") != "failed":
        return None
    return str(source.get("error_message") or source.get("reason") or f"{source_key} source failed")


def _columns(rows: Sequence[dict[str, Any]]) -> list[str]:
    """按首次出现顺序汇总数据集列名。"""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    return columns


def _collect_dataset_diagnostics(datasets: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """汇总 item 下所有 dataset 诊断。"""
    diagnostics: list[dict[str, Any]] = []
    for dataset in datasets:
        values = dataset.get("diagnostics") if isinstance(dataset.get("diagnostics"), list) else []
        diagnostics.extend(values)
    return diagnostics


def _global_diagnostics(
    *,
    items: Sequence[dict[str, Any]],
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    """构造全局诊断信息。"""
    diagnostics: list[dict[str, Any]] = []
    if not date_from or not date_to:
        diagnostics.append(
            diagnostic(
                "warning",
                "DATE_RANGE_DEFAULTED",
                "date_from/date_to 未完整传入，内部类目 Top 接口将使用后端默认日期范围。",
                action="pass_date_from_and_date_to",
            )
        )
    for item in items:
        values = item.get("diagnostics") if isinstance(item.get("diagnostics"), list) else []
        diagnostics.extend(values)
    return diagnostics


def _summary_status(*, top_count: int, failed_asins: Sequence[str]) -> str:
    """根据 Top 行和失败 ASIN 汇总状态。"""
    if top_count == 0:
        return "empty"
    if not failed_asins:
        return "success"
    if len(failed_asins) < top_count:
        return "partial"
    return "failed"


def _source_error_count(enrichment: Mapping[str, dict[str, Any]]) -> int:
    """统计失败的补充数据源数量。"""
    count = 0
    for source_key in ENRICH_SOURCE_KEYS:
        if _source_error_message(enrichment, source_key):
            count += 1
    return count


def _has_error(diagnostics: Sequence[dict[str, Any]]) -> bool:
    """判断诊断列表中是否存在错误级别。"""
    return any(item.get("level") == "error" for item in diagnostics)


def _document_path(*, output_dir: str, run_id: str) -> Path:
    """生成合并 JSON 文件路径。"""
    return Path(output_dir) / run_id / "internal-category-top-asin-data.json"


def _write_document(document: dict[str, Any], *, path: Path) -> None:
    """将合并后的 JSON 文档写入本地文件。"""
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def _attach_file_url(response: dict[str, Any], file_info: Mapping[str, Any]) -> None:
    """把上传后的 OSS URL 写回返回响应中的 artifact。"""
    for item in response.get("items", []):
        if not isinstance(item, dict):
            continue
        for artifact in item.get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("file_key") == CATEGORY_TOP_FILE_KEY:
                artifact["uri"] = file_info.get("file_url")
                artifact["upload"] = file_info.get("upload")


def _compact_response(response: dict[str, Any]) -> dict[str, Any]:
    """默认工具响应移除完整 rows，仅保留 preview_rows 和 artifact 索引。"""
    compact = json.loads(json.dumps(response, ensure_ascii=False))
    for item in compact.get("items", []):
        if not isinstance(item, dict):
            continue
        for dataset in item.get("datasets", []):
            if isinstance(dataset, dict):
                dataset.pop("rows", None)
    return compact


def _top_asins(rows: Sequence[dict[str, Any]]) -> list[str]:
    """从 Top 行中按顺序提取 ASIN 并去重。"""
    return normalize_asins([_row_asin(row) for row in rows])


def _site_by_asin(rows: Sequence[dict[str, Any]], *, default_site: str) -> dict[str, str]:
    """根据 Top 行中的渠道字段推断每个 ASIN 的站点。"""
    result: dict[str, str] = {}
    for row in rows:
        asin = _row_asin(row)
        if not asin:
            continue
        result[asin] = _infer_site(row, default_site=default_site)
    return result


def _row_asin(row: Mapping[str, Any]) -> str:
    """兼容中英文字段名提取 ASIN。"""
    return normalize_asin(_first_present(row, "ASIN", "asin", "f_asin", "amazon_asin"))


def _infer_site(row: Mapping[str, Any], *, default_site: str) -> str:
    """从渠道或站点字段推断站点代码，无法推断时使用默认站点。"""
    explicit = _first_present(row, "站点", "site", "site_code", "country_iso_code")
    if explicit:
        return _normalize_site(str(explicit))
    channel = str(_first_present(row, "渠道", "channel", "channel_name") or "").strip()
    if "-" in channel:
        candidate = channel.rsplit("-", 1)[-1]
        if candidate:
            return _normalize_site(candidate)
    return default_site


def _default_run_id(category: str) -> str:
    """生成默认运行 ID，避免中文类目直接进入目录名。"""
    slug = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-") or "category"
    return f"asin-data-category-top-{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _empty_enrichment(asins: Sequence[str]) -> dict[str, dict[str, Any]]:
    """构造未启用补充查询时的空数据源结构。"""
    return {
        key: {
            "status": "skipped",
            "asins": list(asins),
            "count": len(asins),
            "sources": {
                key: {
                    "key": key,
                    "status": "skipped",
                    "row_count": 0,
                    "rows": [],
                }
            },
        }
        for key in ENRICH_SOURCE_KEYS
    }


def _validate_limit(limit: int) -> None:
    """校验 Top 数量范围。"""
    if limit < 1 or limit > 100:
        raise ValueError("limit 必须在 1-100 之间")


def _validate_date_range(*, date_from: str | None, date_to: str | None) -> None:
    """校验日期范围，缺省日期由后端处理。"""
    if not date_from or not date_to:
        return
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if start > end:
        raise ValueError("date_from 不能大于 date_to")


def _normalize_site(value: str) -> str:
    """规范化站点代码。"""
    return _normalize_site_code(value)


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    """按字段优先级取第一个非空值。"""
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return ""


def _error_dict(exc: Exception) -> dict[str, Any]:
    """将异常转换为统一错误字典。"""
    if hasattr(exc, "to_dict"):
        return exc.to_dict()  # type: ignore[no-any-return, call-arg]
    return {"code": type(exc).__name__, "message": str(exc)}
