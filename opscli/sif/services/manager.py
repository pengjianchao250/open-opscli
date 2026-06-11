"""Sif service manager for CLI-compatible MCP orchestration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from opscli.shared.file_uploads import FileUploadClient, FileUploadError
from opscli.shared.integration_accounts import IntegrationAccountClient
from opscli.sif.accounts import SifAccountProvider
from opscli.sif.common import parse_asins, write_json
from opscli.sif.compare.provider import SifCompareProvider
from opscli.sif.config import DEFAULT_FEATURE_OUTPUT_DIRS, SifSettings, default_output_dir_for_feature, load_settings
from opscli.sif.domain.exceptions import SifConfigError
from opscli.sif.domain.models import SifRunRequest
from opscli.sif.sales.models import SifSalesRunRequest
from opscli.sif.sales.provider import SifSalesProvider
from opscli.sif.sites import normalize_site
from opscli.sif.traffic.provider import SifTrafficProvider


FEATURE_SCENARIOS: dict[str, dict[str, Any]] = {
    "查销量": {
        "key": "sales",
        "aliases": ["查销量", "sales"],
        "sections": ["不同变体销量", "同组变体销量"],
        "default_time_piece_type": "latelyDay",
        "default_time_piece_value": "30",
    },
    "查流量": {
        "key": "traffic",
        "aliases": ["查流量", "查流量词", "traffic", "traffic-keywords"],
        "sections": ["流量结构", "反查流量词", "多变体自然位"],
        "default_time_piece_type": "latelyDay",
        "default_time_piece_value": "7",
    },
    "多产品对比": {
        "key": "compare",
        "aliases": ["多产品对比", "compare"],
        "sections": ["对比销量", "对比流量词", "对比流量分", "重点流量词", "重点广告词"],
        "default_time_piece_type": "latelyDay",
        "default_time_piece_value": "7",
    },
}

FEATURE_ALIASES = {
    alias: feature
    for feature, definition in FEATURE_SCENARIOS.items()
    for alias in definition["aliases"]
}


class SifServiceManager:
    """Run Sif providers and expose job/export metadata for MCP clients."""

    def __init__(
        self,
        *,
        settings: SifSettings | None = None,
        account_provider: SifAccountProvider | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id
        self.account_provider = account_provider or SifAccountProvider(
            self.settings,
            integration_client=IntegrationAccountClient(jwt=jwt, session_id=session_id),
        )

    def scenarios(self) -> list[dict[str, Any]]:
        """List supported Sif features and sections."""
        return [
            {
                "feature": feature,
                "provider": "sif",
                "aliases": definition["aliases"],
                "sections": definition["sections"],
                "default_time_piece_type": definition["default_time_piece_type"],
                "default_time_piece_value": definition["default_time_piece_value"],
            }
            for feature, definition in FEATURE_SCENARIOS.items()
        ]

    def accounts(self) -> list[dict[str, Any]]:
        """List Sif account summaries."""
        return self.account_provider.list_public()

    def run(self, request: SifRunRequest | SifSalesRunRequest):
        """Run a Sif feature through the existing provider implementation."""
        canonical_feature = normalize_feature(request.feature)
        feature_key = FEATURE_SCENARIOS[canonical_feature]["key"]
        account_summary = self._inject_account(request)
        warnings: list[dict[str, Any]] = []

        if canonical_feature == "查销量":
            sales_request = _to_sales_request(request, canonical_feature)
            result = SifSalesProvider().run(
                sales_request,
                default_output_dir=default_output_dir_for_feature(feature_key),
            )
        else:
            generic_request = _to_generic_request(request, canonical_feature)
            provider = SifTrafficProvider() if canonical_feature == "查流量" else SifCompareProvider()
            result = provider.run(
                generic_request,
                default_output_dir=default_output_dir_for_feature(feature_key),
            )

        if account_summary:
            result.summary.setdefault("account", account_summary)
        warnings.extend(_upload_exports_if_enabled(
            result=result,
            jwt=self.jwt,
            session_id=self.session_id,
        ))
        if warnings:
            result.warnings.extend(warnings)
            result.summary["warning_count"] = len(result.warnings)
        _persist_result(result)
        return result

    def job_status(self, job_id: str, *, output_dir: str | None = None) -> dict[str, Any]:
        """Read a previously written Sif result.json by job id."""
        result_path = self._find_result_path(job_id, output_dir=output_dir)
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        _ensure_export_urls(payload)
        decorate_download_payload(payload)
        return payload

    def export(self, job_id: str, *, export_key: str | None = None, output_dir: str | None = None) -> dict[str, Any]:
        """Return export metadata for a job."""
        status = self.job_status(job_id, output_dir=output_dir)
        exports = status.get("exports")
        if not isinstance(exports, dict) or not exports:
            raise SifConfigError(f"Sif 任务没有导出文件：{job_id}")
        if export_key:
            export = exports.get(export_key)
            if not isinstance(export, dict):
                raise SifConfigError(f"Sif 任务不存在导出项：{export_key}")
            _ensure_single_export_url(export)
            _decorate_single_export(export_key, export)
            return export
        return {"job_id": job_id, "exports": exports}

    def _find_result_path(self, job_id: str, *, output_dir: str | None = None) -> Path:
        base_dirs = [Path(output_dir).expanduser()] if output_dir else [self.settings.output_dir, *DEFAULT_FEATURE_OUTPUT_DIRS.values()]
        for base_dir in dict.fromkeys(base_dirs):
            if not base_dir.is_absolute():
                base_dir = Path.cwd() / base_dir
            candidate = base_dir / job_id / "result.json"
            if candidate.exists():
                return candidate
        searched = ", ".join(str(path) for path in dict.fromkeys(base_dirs))
        raise SifConfigError(f"Sif 任务不存在：{job_id}；已查找目录：{searched}")

    def _inject_account(self, request: SifRunRequest | SifSalesRunRequest) -> dict[str, Any] | None:
        if request.sif_username and request.sif_password:
            return None
        if self.settings.cookie or self.settings.token:
            return None
        account = self.account_provider.get_default()
        request.sif_username = account.username
        request.sif_password = account.password
        return account.to_public_dict()


def normalize_feature(value: str) -> str:
    """Normalize feature name or alias."""
    text = (value or "").strip()
    normalized = FEATURE_ALIASES.get(text) or FEATURE_ALIASES.get(text.lower())
    if normalized:
        return normalized
    supported = ", ".join(FEATURE_SCENARIOS)
    raise SifConfigError(f"不支持的 Sif 功能：{value}；可用功能：{supported}")


def _to_sales_request(request: SifRunRequest | SifSalesRunRequest, feature: str) -> SifSalesRunRequest:
    if isinstance(request, SifSalesRunRequest):
        request.feature = feature
        request.provider = "sif"
        request.site = normalize_site(request.site)
        if not request.time_piece_value:
            request.time_piece_value = "30"
        return request
    return SifSalesRunRequest(
        feature=feature,
        provider="sif",
        asin=request.asin,
        site=normalize_site(request.site),
        time_piece_type=request.time_piece_type or "latelyDay",
        time_piece_value=str(request.time_piece_value or "30"),
        page_num=request.page_num,
        page_size=request.page_size or 100,
        sections=request.sections,
        output_dir=request.output_dir,
        job_id=request.job_id,
        sif_username=request.sif_username,
        sif_password=request.sif_password,
        timeout=request.timeout,
        params=request.params,
    )


def _to_generic_request(request: SifRunRequest | SifSalesRunRequest, feature: str) -> SifRunRequest:
    if isinstance(request, SifRunRequest):
        request.feature = feature
        request.site = normalize_site(request.site)
        if feature == "多产品对比" and not request.asins:
            request.asins = parse_asins(request.asin)
        return request
    return SifRunRequest(
        feature=feature,
        asin=request.asin,
        site=normalize_site(request.site),
        time_piece_type=request.time_piece_type or "latelyDay",
        time_piece_value=str(request.time_piece_value or "7"),
        sections=request.sections,
        page_num=request.page_num,
        page_size=request.page_size,
        output_dir=request.output_dir,
        job_id=request.job_id,
        sif_username=request.sif_username,
        sif_password=request.sif_password,
        timeout=request.timeout,
        params=request.params,
    )


def _upload_exports_if_enabled(*, result, jwt: str | None, session_id: str | None) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return warnings
    for export_key, export in result.exports.items():
        try:
            upload = client.upload(
                export.path,
                purpose="sif_export",
                folder="sif/exports",
                public="1",
                metadata={
                    "job_id": result.job_id,
                    "feature": result.feature,
                    "provider": "sif",
                    "site": result.site,
                    "export_key": export_key,
                    "filename": export.filename,
                },
            )
            export.url = upload.url
        except FileUploadError as exc:
            warnings.append(
                {
                    "stage": "file_upload",
                    "export_key": export_key,
                    "message": "Sif 导出文件上传失败，已保留服务端本地文件链接",
                    "error": exc.to_dict(),
                }
            )
        except Exception as exc:
            warnings.append(
                {
                    "stage": "file_upload",
                    "export_key": export_key,
                    "message": "Sif 导出文件上传失败，已保留服务端本地文件链接",
                    "error": {"code": type(exc).__name__, "message": str(exc)},
                }
            )
    return warnings


def _persist_result(result) -> None:
    result_path = Path(result.result_path)
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        payload = result.to_dict()
    payload["exports"] = {key: value.to_dict() for key, value in result.exports.items()}
    payload["summary"] = result.summary
    payload["warnings"] = result.warnings
    decorate_download_payload(payload)
    write_json(result_path, payload)


def _ensure_export_urls(payload: dict[str, Any]) -> None:
    exports = payload.get("exports")
    if not isinstance(exports, dict):
        return
    for export in exports.values():
        if isinstance(export, dict):
            _ensure_single_export_url(export)


def _ensure_single_export_url(export: dict[str, Any]) -> None:
    path = export.get("path")
    if path and not export.get("url"):
        export["url"] = Path(str(path)).expanduser().resolve().as_uri()


def decorate_download_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add display-ready download links without changing real download URLs."""
    exports = payload.get("exports")
    links: list[dict[str, Any]] = []
    if not isinstance(exports, dict):
        payload["download_links"] = links
        return payload
    for export_key, export in exports.items():
        if not isinstance(export, dict):
            continue
        _ensure_single_export_url(export)
        link = _decorate_single_export(str(export_key), export)
        if link:
            links.append(link)
    payload["download_links"] = links
    return payload


def _decorate_single_export(export_key: str, export: dict[str, Any]) -> dict[str, Any] | None:
    filename = _display_filename(export)
    url = str(export.get("url") or "").strip()
    if filename:
        export["display_filename"] = filename
        export["download_label"] = filename
    if not url:
        return None
    if filename:
        markdown = f"[{_escape_markdown_link_label(filename)}]({url})"
        export["download_markdown"] = markdown
    else:
        markdown = url
    export["download_url"] = url
    return {
        "key": export_key,
        "filename": filename or "download.xlsx",
        "url": url,
        "markdown": markdown,
        "format": export.get("format"),
        "mime_type": export.get("mime_type"),
    }


def _display_filename(export: dict[str, Any]) -> str:
    filename = str(export.get("filename") or "").strip()
    if not filename:
        filename = _filename_from_url(str(export.get("url") or ""))
    if not filename and export.get("path"):
        filename = Path(str(export["path"])).name
    return _strip_leading_upload_timestamp(filename)


def _filename_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return unquote(Path(parsed.path).name)


def _strip_leading_upload_timestamp(filename: str) -> str:
    text = filename.strip()
    if not text:
        return ""
    for pattern in (
        r"^\d{10,17}[_\-\s]+",
        r"^\d{8,14}[_\-\s]+",
        r"^\d{4}-\d{2}-\d{2}[_\-\s]+\d{2}[_\-\s]?\d{2}[_\-\s]?\d{2}[_\-\s]+",
    ):
        text = re.sub(pattern, "", text)
    return text


def _escape_markdown_link_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
