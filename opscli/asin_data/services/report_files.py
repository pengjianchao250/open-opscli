"""Client for ASIN report file lookup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import parse_remote_response


DEFAULT_REPORT_FILES_ENDPOINT = "/dataMetrics/v1/asin-report-files"
DEFAULT_ABTEST_DATA_ENDPOINT = "/dataMetrics/v1/asin-report-files/abtest-data"
DEFAULT_TIMEOUT = 20


class AsinReportFileError(RemoteError):
    """ASIN report file lookup error."""

    code = "ASIN_REPORT_FILE_ERROR"


class AsinReportFileHttpError(AsinReportFileError):
    """HTTP error from ASIN report file lookup."""

    code = "ASIN_REPORT_FILE_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class AsinReportFileBusinessError(AsinReportFileError):
    """Business error from ASIN report file lookup."""

    code = "ASIN_REPORT_FILE_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["business_code"] = self.business_code
        return payload


class AsinReportFileBadJsonError(AsinReportFileError):
    """Invalid JSON returned by ASIN report file lookup."""

    code = "ASIN_REPORT_FILE_BAD_JSON"


class AsinReportFileNotFoundError(AsinReportFileError):
    """Required ASIN report file URL was not returned."""

    code = "ASIN_REPORT_FILE_NOT_FOUND"

    def __init__(self, *, asin: str, site: str, message: str | None = None):
        super().__init__(message or f"取数服务异常：未找到 ASIN 报告地址（ASIN={asin}，站点={site}）")
        self.asin = asin
        self.site = site

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["asin"] = self.asin
        payload["site"] = self.site
        return payload


@dataclass(frozen=True)
class AsinReportFile:
    asin: str
    site: str
    url: str | None
    record: dict[str, Any] | None
    raw: dict[str, Any]


class AsinReportFileClient:
    """Fetch latest ASIN report file URL from the ops data-metrics service."""

    def __init__(
        self,
        *,
        auth_client: AuthClient | None = None,
        endpoint: str = DEFAULT_REPORT_FILES_ENDPOINT,
        abtest_endpoint: str = DEFAULT_ABTEST_DATA_ENDPOINT,
        http_get: Callable[..., httpx.Response] | None = None,
        http_post: Callable[..., httpx.Response] | None = None,
        ops_url: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.endpoint = endpoint
        self.abtest_endpoint = abtest_endpoint
        self.http_get = http_get or httpx.get
        self.http_post = http_post or httpx.post
        self.ops_url = _report_files_base_url(ops_url or OPS_URL)

    def fetch(self, *, asin: str, site: str, report_type: str | None = None) -> AsinReportFile:
        normalized_asin = asin.strip().upper()
        normalized_site = site.strip().upper()
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        params: dict[str, str] = {"asin": normalized_asin, "site": normalized_site}
        if report_type:
            params["report_type"] = report_type
        response = self.http_get(
            self._resolve_endpoint(),
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=AsinReportFileHttpError,
            business_error_cls=AsinReportFileBusinessError,
            bad_json_error_cls=AsinReportFileBadJsonError,
        )
        data = payload.get("data")
        record = _select_record(data if data is not None else payload, asin=normalized_asin, site=normalized_site)
        return AsinReportFile(
            asin=normalized_asin,
            site=normalized_site,
            url=_extract_report_url(record),
            record=record if isinstance(record, dict) else None,
            raw=payload,
        )

    def fetch_file(self, *, asin: str, site: str, report_type: str) -> AsinReportFile:
        """Fetch a single per-file ASIN data record by report_type.

        Thin wrapper around :meth:`fetch` that always passes ``report_type``,
        used by the per-file delivery flow (e.g. asin_data_basic_xlsx).
        """
        return self.fetch(asin=asin, site=site, report_type=report_type)

    def fetch_file_list(self, *, asin: str, site: str) -> list[AsinReportFile]:
        """List all per-file records for an ASIN (any asin_data_*_xlsx / *_md report_type)."""
        normalized_asin = asin.strip().upper()
        normalized_site = site.strip().upper()
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = self.http_get(
            self._resolve_endpoint(),
            params={"asin": normalized_asin, "site": normalized_site},
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=AsinReportFileHttpError,
            business_error_cls=AsinReportFileBusinessError,
            bad_json_error_cls=AsinReportFileBadJsonError,
        )
        data = payload.get("data") if isinstance(payload, dict) else payload
        records = _collect_records(data)
        results: list[AsinReportFile] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            rt = str(record.get("report_type") or "")
            # only keep per-file split package records (exclude the whole zip / merged txt)
            if not (rt.startswith("asin_data_") and (rt.endswith("_xlsx") or rt.endswith("_md"))):
                continue
            results.append(
                AsinReportFile(
                    asin=normalized_asin,
                    site=normalized_site,
                    url=_extract_report_url(record),
                    record=record,
                    raw=payload,
                )
            )
        return results

    def fetch_split_files(self, *, asin: str, site: str) -> dict[str, Any]:
        """Fetch the per-file split record for an ASIN and return URLs by file_key.

        Queries the latest record for the ASIN (regardless of report_type) and
        extracts per-file URLs from the dedicated columns
        (basic_data_url / bi_data_url / ...). Works whether the URLs were written
        onto a ``asin_data_split_package_zip`` record (UPDATE backfill) or a
        ``asin_data_split_package_files`` record (INSERT new).
        """
        normalized_asin = asin.strip().upper()
        normalized_site = site.strip().upper()
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = self.http_get(
            self._resolve_endpoint(),
            params={"asin": normalized_asin, "site": normalized_site},
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=AsinReportFileHttpError,
            business_error_cls=AsinReportFileBusinessError,
            bad_json_error_cls=AsinReportFileBadJsonError,
        )
        data = payload.get("data") if isinstance(payload, dict) else payload
        records = _collect_records(data)
        # pick the record that actually carries per-file URLs (newest first)
        record: dict[str, Any] = {}
        for candidate in records:
            if not isinstance(candidate, dict):
                continue
            if _extract_split_file_urls(candidate):
                record = candidate
                break
        if not record and records:
            record = records[0] if isinstance(records[0], dict) else {}
        files = _extract_split_file_urls(record)
        return {
            "asin": normalized_asin,
            "site": normalized_site,
            "record": record,
            "raw": payload,
            "files": files,
        }

    def fetch_abtest(self, *, asin: str, site: str, data_type: str = "file") -> AsinReportFile:
        """Fetch ABTest report data via /dataMetrics/v1/asin-report-files/abtest-data.

        Args:
            asin: 目标 ASIN。
            site: 站点（如 US）。
            data_type: 返回数据类型，默认 "file" 表示取报告文件地址。
        """
        normalized_asin = asin.strip().upper()
        normalized_site = site.strip().upper()
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        response = self.http_get(
            self._resolve_endpoint(self.abtest_endpoint),
            params={
                "asin": normalized_asin,
                "site": normalized_site,
                "data_type": data_type,
            },
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=AsinReportFileHttpError,
            business_error_cls=AsinReportFileBusinessError,
            bad_json_error_cls=AsinReportFileBadJsonError,
        )
        data = payload.get("data")
        record = _select_record(data if data is not None else payload, asin=normalized_asin, site=normalized_site)
        return AsinReportFile(
            asin=normalized_asin,
            site=normalized_site,
            url=_extract_report_url(record),
            record=record if isinstance(record, dict) else None,
            raw=payload,
        )

    def upsert(
        self,
        *,
        items: list[dict[str, Any]],
        request_id: str | None = None,
        source: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit ASIN report file records to the ops data-metrics service."""
        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        headers.setdefault("Content-Type", "application/json")
        body: dict[str, Any] = {"items": items}
        if request_id:
            body["request_id"] = request_id
        if source:
            body["source"] = source
        if idempotency_key:
            body["idempotency_key"] = idempotency_key

        response = self.http_post(
            self._resolve_endpoint(),
            json=body,
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )
        return parse_remote_response(
            response,
            http_error_cls=AsinReportFileHttpError,
            business_error_cls=AsinReportFileBusinessError,
            bad_json_error_cls=AsinReportFileBadJsonError,
        )

    def _resolve_endpoint(self, endpoint: str | None = None) -> str:
        text = (endpoint or self.endpoint).strip()
        if text.startswith(("http://", "https://")):
            return text
        if not text.startswith("/"):
            text = f"/{text}"
        return f"{self.ops_url}{text}"


def _select_record(data: Any, *, asin: str, site: str) -> Any:
    if isinstance(data, dict):
        for key in ("record", "report", "file", "latest"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        for key in ("items", "records", "list", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return _select_record(value, asin=asin, site=site)
        return data
    if isinstance(data, list):
        fallback = data[0] if data else None
        for item in data:
            if not isinstance(item, dict):
                continue
            item_asin = str(item.get("asin") or item.get("ASIN") or "").strip().upper()
            item_site = str(item.get("site") or item.get("country") or item.get("站点") or item.get("国家") or "").strip().upper()
            asin_matches = not item_asin or item_asin == asin
            site_matches = not item_site or item_site == site
            if asin_matches and site_matches:
                return item
        return fallback
    return data


def _collect_records(data: Any) -> list[dict[str, Any]]:
    """Flatten any container shape into a flat list of record dicts."""
    records: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("list", "items", "records", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                records.extend(item for item in value if isinstance(item, dict))
                if records:
                    return records
        return [data]
    if isinstance(data, list):
        records.extend(item for item in data if isinstance(item, dict))
    return records


# file_key -> (db_column, is_multi) — mirrors split_package_builder.FILE_FIELD_MAP
_SPLIT_FILE_COLUMNS = {
    "basic": ("basic_data_url", False),
    "bi": ("bi_data_url", False),
    "keyword_reverse": ("keyword_reverse_url", False),
    "keyword_miner": ("keyword_miner_urls", True),
    "competitor": ("competitor_urls", True),
    "rufus": ("rufus_report_url", False),
}


def _extract_split_file_urls(record: dict[str, Any]) -> dict[str, Any]:
    """Extract per-file URLs from a split-files record into {file_key: url|[urls]}."""
    result: dict[str, Any] = {}
    for file_key, (column, is_multi) in _SPLIT_FILE_COLUMNS.items():
        value = record.get(column)
        if value is None or value == "":
            continue
        if is_multi:
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError):
                    parsed = [value]
            else:
                parsed = value
            if isinstance(parsed, list):
                urls = [str(item).strip() for item in parsed if str(item).strip()]
                if urls:
                    result[file_key] = urls
            elif isinstance(parsed, str) and parsed.strip():
                result[file_key] = [parsed.strip()]
        else:
            text = str(value).strip()
            if text:
                result[file_key] = text
    return result


def _report_files_base_url(ops_url: str) -> str:
    base = ops_url.rstrip("/")
    if base.endswith("/api"):
        return base[:-4]
    return base


def _extract_report_url(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in (
        "file_url",
        "fileUrl",
        "url",
        "download_url",
        "downloadUrl",
        "report_url",
        "reportUrl",
        "aliyun_url",
        "aliyunUrl",
    ):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("file", "report", "data"):
        nested = record.get(key)
        url = _extract_report_url(nested)
        if url:
            return url
    return None
