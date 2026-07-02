"""Build and submit ASIN report file records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from opscli.asin_data.services.report_files import DEFAULT_REPORT_FILES_ENDPOINT, AsinReportFileClient
from opscli.asin_data.services.split_package_builder import (
    FILE_FIELD_MAP,
    SPLIT_FILE_KEYS,
)


DEFAULT_REPORT_TYPE = "asin_data_split_package_zip"
DEFAULT_SOURCE = "asin_data_collect"


class AsinReportFileSubmitter:
    """Submit collected ASIN report data to the report-files endpoint."""

    def __init__(self, *, client: AsinReportFileClient | None = None) -> None:
        self.client = client or AsinReportFileClient()

    def submit(
        self,
        collect_result: dict[str, Any],
        *,
        report_date: str | None = None,
        report_type: str = DEFAULT_REPORT_TYPE,
        source: str = DEFAULT_SOURCE,
        include_content: bool = False,
        idempotency_key: str | None = None,
        file_mode: bool = False,
    ) -> dict[str, Any]:
        if file_mode:
            items = self.build_file_items(
                collect_result,
                report_date=report_date,
                source=source,
            )
        else:
            items = self.build_items(
                collect_result,
                report_date=report_date,
                report_type=report_type,
                source=source,
                include_content=include_content,
            )
        request_id = _run_id(collect_result) or idempotency_key
        response = self.client.upsert(
            items=items,
            request_id=request_id,
            source=source,
            idempotency_key=idempotency_key or request_id,
        )
        return _summarize_submit_response(response, items=items, endpoint=self.client.endpoint)

    def build_items(
        self,
        collect_result: dict[str, Any],
        *,
        report_date: str | None = None,
        report_type: str = DEFAULT_REPORT_TYPE,
        source: str = DEFAULT_SOURCE,
        include_content: bool = False,
    ) -> list[dict[str, Any]]:
        output_dir = _output_dir(collect_result)
        manifest = _manifest(collect_result, output_dir)
        frontend_bundle = _read_json(output_dir / "frontend-data.json")
        raw_records = _read_jsonl(output_dir / "asin-data.jsonl")
        errors = _read_jsonl(output_dir / "errors.jsonl")
        report_path = _report_path(manifest, output_dir)
        report_text = _read_text(report_path) if include_content and _is_text_file(report_path) else None
        report_bytes = _read_bytes(report_path)
        report_hash = hashlib.sha256(report_bytes).hexdigest() if report_bytes is not None else None
        file_url = _file_url(collect_result, manifest)
        normalized_report_date = report_date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        frontend_by_asin = _frontend_by_asin(frontend_bundle)

        items: list[dict[str, Any]] = []
        for raw_record in raw_records:
            asin = _normalize_asin(raw_record.get("asin"))
            if not asin:
                continue
            site = _normalize_site(raw_record.get("site"))
            related_errors = _related_errors(errors, asin=asin)
            item = {
                "report_uuid": str(uuid5(NAMESPACE_URL, f"{asin}:{site}:{report_type}:{normalized_report_date}")),
                "run_id": manifest.get("run_id") or _run_id(collect_result),
                "asin": asin,
                "site": site,
                "report_type": report_type,
                "source": source,
                "status": _status(raw_record, related_errors),
                "report_date": normalized_report_date,
                "file_name": report_path.name if report_path else None,
                "file_ext": report_path.suffix.lstrip(".") if report_path and report_path.suffix else "txt",
                "mime_type": _mime_type(report_path),
                "file_path": report_path.as_posix() if report_path else None,
                "file_url": file_url,
                "content_text": report_text,
                "content_hash": report_hash,
                "file_size_bytes": len(report_bytes) if report_bytes is not None else None,
                "meta_json": _meta_json(manifest, content_hash=report_hash),
                "frontend_json": frontend_by_asin.get(asin) if include_content else None,
                "raw_record_json": raw_record if include_content else None,
                "error_message": _error_message(related_errors),
            }
            items.append(item)
        if not items:
            raise ValueError("No ASIN report file records were generated for submit.")
        return items

    def build_file_items(
        self,
        collect_result: dict[str, Any],
        *,
        report_date: str | None = None,
        source: str = DEFAULT_SOURCE,
    ) -> list[dict[str, Any]]:
        """Build one record per ASIN with per-file OSS URLs in dedicated columns.

        Unlike :meth:`build_items` (one record pointing at the whole zip), this
        writes each split file's OSS URL into its own column on a single per-ASIN
        record: ``basic_data_url`` / ``bi_data_url`` / ``keyword_reverse_url`` /
        ``keyword_miner_urls`` (json array) / ``competitor_urls`` (json array) /
        ``rufus_report_url``. The downstream AI can then fetch one file at a time
        without loading the whole package.
        """
        manifest = _manifest(collect_result, _output_dir(collect_result))
        run_id = manifest.get("run_id") or _run_id(collect_result)
        normalized_report_date = report_date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        file_uploads = collect_result.get("asin_data_files") or {}
        items_by_asin = {
            str(entry.get("asin") or "").strip().upper(): entry
            for entry in (file_uploads.get("items") or [])
            if isinstance(entry, dict)
        }

        items: list[dict[str, Any]] = []
        for asin, entry in items_by_asin.items():
            if not asin:
                continue
            site = _normalize_site(_site_for_asin(manifest, asin))
            per_files = entry.get("files") if isinstance(entry.get("files"), dict) else {}

            # group URLs by db column; multi-file keys accumulate into a list
            column_values: dict[str, Any] = {}
            column_meta: dict[str, Any] = {}
            for file_key in SPLIT_FILE_KEYS:
                mapping = FILE_FIELD_MAP.get(file_key)
                if not mapping:
                    continue
                db_column, is_multi = mapping
                file_info = per_files.get(file_key) if isinstance(per_files.get(file_key), dict) else {}
                file_url = file_info.get("url") if isinstance(file_info.get("url"), str) else None
                if not file_url:
                    continue
                if is_multi:
                    column_values.setdefault(db_column, []).append(file_url)
                else:
                    column_values[db_column] = file_url
                column_meta[file_key] = {
                    "url": file_url,
                    "file_name": file_info.get("file_name"),
                }
            if not column_values:
                continue

            # serialize multi-file columns as JSON arrays
            extra_fields: dict[str, Any] = {}
            for file_key in SPLIT_FILE_KEYS:
                mapping = FILE_FIELD_MAP.get(file_key)
                if not mapping:
                    continue
                db_column, is_multi = mapping
                value = column_values.get(db_column)
                if value is None:
                    continue
                if is_multi:
                    extra_fields[db_column] = json.dumps(value, ensure_ascii=False)
                else:
                    extra_fields[db_column] = value

            report_type = "asin_data_split_package_files"
            item = {
                "report_uuid": str(
                    uuid5(NAMESPACE_URL, f"{asin}:{site}:{report_type}:{normalized_report_date}")
                ),
                "run_id": run_id,
                "asin": asin,
                "site": site,
                "report_type": report_type,
                "source": source,
                "status": "success",
                "report_date": normalized_report_date,
                "meta_json": {
                    "run_id": run_id,
                    "files": column_meta,
                },
                "error_message": None,
            }
            item.update(extra_fields)
            items.append(item)
        if not items:
            raise ValueError("No per-file ASIN report records were generated for submit.")
        return items


def _output_dir(collect_result: dict[str, Any]) -> Path:
    output_dir = collect_result.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ValueError("collect result is missing output_dir")
    return Path(output_dir)


def _manifest(collect_result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    manifest = collect_result.get("manifest")
    if isinstance(manifest, dict):
        return manifest
    return _read_json(output_dir / "manifest.json")


def _report_path(manifest: dict[str, Any], output_dir: Path) -> Path | None:
    files = manifest.get("files")
    path_text = None
    if isinstance(files, dict):
        path_text = files.get("asin_data_package_zip") or files.get("asin_report_txt")
    if not isinstance(path_text, str) or not path_text.strip():
        package_candidates = list(output_dir.glob("*-asin-data-package.zip")) or list(output_dir.glob("asin-data-packages.zip"))
        if package_candidates:
            return package_candidates[0]
        candidates = list(output_dir.glob("*-asin-data-report.txt")) or list(output_dir.glob("asin-data-report.txt"))
        return candidates[0] if candidates else None
    path = Path(path_text)
    if path.exists():
        return path
    fallback = output_dir / path.name
    return fallback if fallback.exists() else path


def _file_url(collect_result: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    upload = collect_result.get("upload")
    if isinstance(upload, dict) and isinstance(upload.get("url"), str):
        return upload["url"]
    files = manifest.get("files")
    if isinstance(files, dict):
        for key in ("asin_data_package_upload_url", "asin_report_upload_url", "frontend_upload_url"):
            value = files.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    value = collect_result.get("aliyun_url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _meta_json(manifest: dict[str, Any], *, content_hash: str | None) -> dict[str, Any]:
    meta = dict(manifest)
    if content_hash:
        meta["content_hash"] = content_hash
    files = manifest.get("files")
    if isinstance(files, dict):
        meta["source_files"] = {
            "query_frontend_json": files.get("frontend_data"),
            "query_asin_data_jsonl": files.get("results"),
            "asin_report_txt": files.get("asin_report_txt"),
            "asin_data_package_zip": files.get("asin_data_package_zip"),
        }
    return meta


def _mime_type(path: Path | None) -> str:
    if path is not None and path.suffix.lower() == ".zip":
        return "application/zip"
    return "text/plain; charset=utf-8"


def _is_text_file(path: Path | None) -> bool:
    return path is not None and path.suffix.lower() in {".txt", ".md", ".json"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _read_text(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8-sig")


def _read_bytes(path: Path | None) -> bytes | None:
    if path is None or not path.exists():
        return None
    return path.read_bytes()


def _frontend_by_asin(frontend_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = frontend_bundle.get("数据")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        base = row.get("基础数据")
        asin = _normalize_asin(base.get("ASIN") if isinstance(base, dict) else None)
        if asin:
            result[asin] = row
    return result


def _related_errors(errors: list[dict[str, Any]], *, asin: str) -> list[dict[str, Any]]:
    related = []
    for error in errors:
        error_asin = _normalize_asin(error.get("asin"))
        if not error_asin or error_asin == asin:
            related.append(error)
    return related


def _status(raw_record: dict[str, Any], errors: list[dict[str, Any]]) -> str:
    raw_status = str(raw_record.get("status") or "").strip().lower()
    if raw_status in {"failed", "error"}:
        return "failed"
    return "partial" if errors else "success"


def _error_message(errors: list[dict[str, Any]]) -> str | None:
    messages = []
    for error in errors:
        message = error.get("error_message") or error.get("message") or error.get("error")
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    return "; ".join(messages) if messages else None


def _run_id(collect_result: dict[str, Any]) -> str | None:
    manifest = collect_result.get("manifest")
    if isinstance(manifest, dict) and isinstance(manifest.get("run_id"), str):
        return manifest["run_id"]
    return None


def _normalize_asin(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_site(value: Any) -> str:
    return str(value or "US").strip().upper()


def _site_for_asin(manifest: dict[str, Any], asin: str) -> str:
    """Best-effort site lookup for an ASIN from manifest summary/records."""
    records = manifest.get("records")
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and _normalize_asin(record.get("asin")) == asin:
                site = record.get("site")
                if site:
                    return str(site)
    return "US"


def _file_ext(file_name: str | None) -> str:
    if not isinstance(file_name, str) or not file_name.strip():
        return "txt"
    suffix = Path(file_name).suffix.lstrip(".")
    return suffix or "txt"


def _mime_type_for_name(file_name: str | None) -> str:
    if not isinstance(file_name, str):
        return "application/octet-stream"
    suffix = Path(file_name).suffix.lower()
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".zip":
        return "application/zip"
    return "text/plain; charset=utf-8"


def _summarize_submit_response(response: dict[str, Any], *, items: list[dict[str, Any]], endpoint: str) -> dict[str, Any]:
    data = response.get("data")
    data = data if isinstance(data, dict) else {}
    return {
        "endpoint": endpoint or DEFAULT_REPORT_FILES_ENDPOINT,
        "submitted": True,
        "count": len(items),
        "inserted": data.get("inserted"),
        "updated": data.get("updated"),
        "failed": data.get("failed"),
        "items": data.get("items"),
        "raw": response,
    }
