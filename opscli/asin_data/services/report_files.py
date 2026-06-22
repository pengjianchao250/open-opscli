"""Client for ASIN report file lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import parse_remote_response


DEFAULT_REPORT_FILES_ENDPOINT = "/dataMetrics/v1/asin-report-files"
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
        http_get: Callable[..., httpx.Response] | None = None,
        http_post: Callable[..., httpx.Response] | None = None,
        ops_url: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.endpoint = endpoint
        self.http_get = http_get or httpx.get
        self.http_post = http_post or httpx.post
        self.ops_url = _report_files_base_url(ops_url or OPS_URL)

    def fetch(self, *, asin: str, site: str) -> AsinReportFile:
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

    def _resolve_endpoint(self) -> str:
        text = self.endpoint.strip()
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
