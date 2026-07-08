"""In-process ASIN batch data collector.

The historical ASIN collector lives as a Skill script because it started as an
agent-facing wrapper. This module makes it a first-class opscli command while
reusing the existing data contract and frontend output formatting.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

from opscli.asin_data.services.bi_report_data import (
    AsinBiReportDataClient,
    build_bi_report_data_placeholder,
    select_bi_report_data_for_asin,
    summarize_bi_report_data,
)
from opscli.asin_data.services.merged_report_renderer import render_merged_report_text
from opscli.asin_data.services.report_files import AsinReportFileClient, AsinReportFileNotFoundError
from opscli.asin_data.services.split_package_builder import (
    SPLIT_FILE_KEYS,
    build_split_package,
)
from opscli.amazon.services.manager import AmazonManager
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.remote_consent import RemoteConsentStore
from opscli.query.services.manager import QueryManager
from opscli.seller_sprite.domain.models import SellerSpriteScenarioRequest
from opscli.seller_sprite.services import SellerSpriteApiManager
from opscli.shared.file_uploads import FileUploadClient


DEFAULT_LEGACY_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "templates"
    / "ops-asin-data-collector"
    / "scripts"
    / "collect_asin_data.py"
)
DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS = 600
DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS = 2.0
WINDOWS_COMPAT_EXPORT_PATH_LIMIT = 240


class AsinDataCollector:
    """Run the ASIN collector through package APIs instead of CLI subprocesses."""

    def __init__(
        self,
        *,
        query_manager: QueryManager | None = None,
        seller_sprite_manager: SellerSpriteApiManager | None = None,
        rufus_manager: RufusManager | None = None,
        amazon_manager: AmazonManager | None = None,
        remote_consent_store: RemoteConsentStore | None = None,
        report_writer: AnswerReportWriter | None = None,
        file_upload_client: FileUploadClient | None = None,
        report_file_client: AsinReportFileClient | None = None,
        bi_report_data_client: AsinBiReportDataClient | None = None,
        legacy_module: ModuleType | None = None,
    ) -> None:
        self.legacy = legacy_module or load_legacy_collector()
        self.file_upload_client = file_upload_client or FileUploadClient()
        self.report_file_client = report_file_client or AsinReportFileClient()
        self.bi_report_data_client = bi_report_data_client or AsinBiReportDataClient()
        self.runner = DirectOpsRunner(
            self.legacy,
            query_manager=query_manager,
            seller_sprite_manager=seller_sprite_manager,
            rufus_manager=rufus_manager,
            amazon_manager=amazon_manager,
            remote_consent_store=remote_consent_store,
            report_writer=report_writer,
        )

    def collect(self, **kwargs: Any) -> dict[str, Any]:
        """Collect ASIN data and write the standard output package."""
        args = self._build_args(**kwargs)
        started_at = datetime.now().isoformat(timespec="seconds")
        run_id = args.run_id or f"asin-data-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        output_root = Path(args.output_dir).expanduser() / run_id
        output_root.mkdir(parents=True, exist_ok=True)

        records, input_errors = self._load_records(args)
        if not records:
            raise ValueError("No valid ASIN records found.")

        command_log = self.legacy.JsonlWriter(output_root / "commands.jsonl")
        error_log = self.legacy.JsonlWriter(output_root / "errors.jsonl")
        result_log = self.legacy.JsonlWriter(output_root / "asin-data.jsonl")

        for error in input_errors:
            error_log.write({"source": "input", **error})

        original_run_or_plan = self.legacy.run_or_plan
        self.legacy.run_or_plan = self.runner.run_or_plan
        try:
            report_files = None
            if args.fetch_report_files and not args.dry_run:
                report_files = self._fetch_report_files(records, [], error_log, require_all=True)

            query_bundle = {}
            if not args.skip_query:
                query_bundle = self.legacy.collect_query_sources(args, records, output_root, command_log, error_log)

            asin_results: list[dict[str, Any]] = []
            for record in records:
                asin_result = self.legacy.collect_one_asin(args, record, output_root, command_log, error_log, query_bundle)
                asin_results.append(asin_result)

            bi_report_data = self._collect_bi_report_data(records, asin_results, args, error_log)

            if report_files is None and args.fetch_report_files and not args.dry_run:
                report_files = self._fetch_report_files(records, asin_results, error_log)
            elif report_files is not None:
                self._attach_report_files(asin_results, report_files)

            for asin_result in asin_results:
                result_log.write(asin_result)

            summary = self.legacy.build_summary(records, asin_results, input_errors, output_root, started_at, args)
            summary["options"]["fetch_report_files"] = args.fetch_report_files
            summary["options"]["skip_bi_report_data"] = args.skip_bi_report_data
            summary["bi_report_data"] = summarize_bi_report_data(bi_report_data)
            if report_files is not None:
                summary["report_files"] = report_files
            frontend_bundle = self.legacy.build_frontend_bundle(summary, asin_results)
            frontend_json_path = output_root / "frontend-data.json"
            frontend_markdown_path = output_root / "frontend-data.md"
            frontend_html_path = output_root / "frontend-data.html"
            report_txt_path = self._write_report_txt(output_root, frontend_bundle, records, summary, asin_results)
            self.legacy.write_json(frontend_json_path, frontend_bundle)
            self.legacy.write_text(frontend_markdown_path, self.legacy.render_frontend_markdown(frontend_bundle))
            self.legacy.write_text(frontend_html_path, self._render_frontend_html(frontend_bundle))
            summary["files"]["frontend_html"] = frontend_html_path.as_posix()
            summary["files"]["asin_report_txt"] = report_txt_path.as_posix()
            split_package = build_split_package(output_root=output_root, asin_results=asin_results, summary=summary)
            summary["files"]["asin_data_package_dir"] = split_package["package_dir"]
            summary["files"]["asin_data_package_zip"] = split_package["zip_path"]
            summary["asin_data_package"] = split_package
            upload = None
            if args.upload:
                upload = self._upload_split_package(
                    Path(split_package["zip_path"]),
                    run_id=run_id,
                    records=records,
                    summary=summary,
                )
                summary["files"]["asin_data_package_upload_url"] = upload["url"]
                summary["files"]["asin_report_upload_url"] = upload["url"]
                summary["upload"] = upload
                file_uploads = self._upload_split_package_files(
                    split_package,
                    run_id=run_id,
                    records=records,
                )
                summary["files"]["asin_data_file_urls"] = file_uploads
                summary["asin_data_files"] = file_uploads
            self.legacy.write_json(output_root / "asin-data-summary.json", summary)
            self.legacy.write_json(output_root / "manifest.json", summary)
        finally:
            self.legacy.run_or_plan = original_run_or_plan

        if isinstance(upload, dict):
            upload = self._normalize_upload_paths(upload)
            summary["upload"] = upload

        report_file_url = self._single_report_file_url(summary.get("report_files"))
        aliyun_url = report_file_url or (upload["url"] if upload else None)
        return {
            "success": True,
            "output_dir": output_root.as_posix(),
            "summary": summary["summary"],
            "manifest": summary,
            "upload": upload,
            "report_files": summary.get("report_files"),
            "report_file_url": report_file_url,
            "aliyun_url": aliyun_url,
            "asin_data_files": summary.get("asin_data_files"),
        }

    def _build_args(self, **kwargs: Any) -> argparse.Namespace:
        args = argparse.Namespace(
            input=kwargs.get("input"),
            asin=kwargs.get("asin"),
            keywords=kwargs.get("keywords") if kwargs.get("keywords") is not None else kwargs.get("keyword"),
            asin_column=kwargs.get("asin_column", "asin"),
            keyword_column=kwargs.get("keyword_column", "keyword"),
            site_column=kwargs.get("site_column", "site"),
            site=kwargs.get("site", "US"),
            output_dir=kwargs.get("output_dir", "output/asin-data"),
            run_id=kwargs.get("run_id"),
            opscli_bin="__direct__",
            dry_run=kwargs.get("dry_run", False),
            skip_seller_sprite=kwargs.get("skip_seller_sprite", False),
            skip_keyword_miner=kwargs.get("skip_keyword_miner", False),
            skip_listing_analysis=kwargs.get("skip_listing_analysis", False),
            skip_amazon=kwargs.get("skip_amazon", False),
            skip_query=kwargs.get("skip_query", False),
            skip_bi_report_data=kwargs.get("skip_bi_report_data", False),
            skip_sales_query=kwargs.get("skip_sales_query", False),
            skip_crawler_query=kwargs.get("skip_crawler_query", True),
            skip_rufus=kwargs.get("skip_rufus", False),
            seller_sprite_period=kwargs.get("seller_sprite_period", "30d"),
            seller_sprite_page_size=kwargs.get("seller_sprite_page_size", 100),
            keyword_source=kwargs.get("keyword_source", "reverse_top"),
            max_miner_keywords=kwargs.get("max_miner_keywords", 1),
            listing_analysis_station=kwargs.get("listing_analysis_station", "GLOBAL"),
            listing_analysis_poll_attempts=(
                kwargs.get("listing_analysis_poll_attempts")
                if kwargs.get("listing_analysis_poll_attempts") is not None
                else DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS
            ),
            listing_analysis_poll_interval_seconds=(
                kwargs.get("listing_analysis_poll_interval_seconds")
                if kwargs.get("listing_analysis_poll_interval_seconds") is not None
                else DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS
            ),
            rufus_country=kwargs.get("rufus_country"),
            rufus_questions=kwargs.get("rufus_questions"),
            rufus_skills_dir=kwargs.get("rufus_skills_dir", ".agents/skills"),
            rufus_timeout_seconds=kwargs.get("rufus_timeout_seconds", 180),
            rufus_login_timeout_seconds=kwargs.get("rufus_login_timeout_seconds", 180),
            rufus_parallel=kwargs.get("rufus_parallel", False),
            rufus_concurrency=kwargs.get("rufus_concurrency", 3),
            rufus_retry=kwargs.get("rufus_retry", 0),
            rufus_strict_answer=kwargs.get("rufus_strict_answer", False),
            skip_rufus_login_recovery=kwargs.get("skip_rufus_login_recovery", False),
            sales_table_id=kwargs.get("sales_table_id"),
            sales_dataset_alias=kwargs.get("sales_dataset_alias", self.legacy.DEFAULT_SALES_ALIAS),
            sales_field_mode=kwargs.get("sales_field_mode", "full"),
            sales_start=kwargs.get("sales_start"),
            sales_end=kwargs.get("sales_end"),
            bi_report_source_keys=kwargs.get("bi_report_source_keys"),
            query_chunk_size=kwargs.get("query_chunk_size", 100),
            crawler_table_id=kwargs.get("crawler_table_id"),
            crawler_dataset_alias=kwargs.get("crawler_dataset_alias", self.legacy.DEFAULT_CRAWLER_ALIAS),
            crawler_field_mode=kwargs.get("crawler_field_mode", "full"),
            upload=kwargs.get("upload", False),
            fetch_report_files=kwargs.get("fetch_report_files", False),
        )
        self._validate_args(args)
        return args

    def _collect_bi_report_data(
        self,
        records: list[dict[str, Any]],
        asin_results: list[dict[str, Any]],
        args: argparse.Namespace,
        error_log: Any,
    ) -> dict[str, Any]:
        asins = [str(record.get("asin") or "").strip().upper() for record in records if record.get("asin")]
        if args.skip_bi_report_data:
            bundle = build_bi_report_data_placeholder(
                asins=asins,
                status="skipped",
                reason="BI report data skipped by --skip-bi-report-data",
                source_keys=args.bi_report_source_keys,
            )
        elif args.dry_run:
            bundle = build_bi_report_data_placeholder(
                asins=asins,
                status="planned",
                reason="BI report data endpoints will be fetched during execution",
                source_keys=args.bi_report_source_keys,
            )
        else:
            bundles: dict[str, dict[str, Any]] = {}
            for asin_result in asin_results:
                asin = str(asin_result.get("asin") or "").strip().upper()
                if not asin:
                    continue
                asin_bundle = self.bi_report_data_client.fetch(
                    asins=[asin],
                    start_date=args.sales_start,
                    end_date=args.sales_end,
                    source_keys=args.bi_report_source_keys,
                )
                bundles[asin] = asin_bundle
                self._attach_bi_report_data([asin_result], asin_bundle, error_log)
            return self._merge_per_asin_bi_report_data(bundles, asins=asins)

        self._attach_bi_report_data(asin_results, bundle, error_log)
        return bundle

    @classmethod
    def _merge_per_asin_bi_report_data(
        cls,
        bundles: dict[str, dict[str, Any]],
        *,
        asins: list[str],
    ) -> dict[str, Any]:
        if len(bundles) == 1:
            bundle = dict(next(iter(bundles.values())))
            bundle["request_mode"] = "per_asin"
            return bundle
        statuses = [bundle.get("status") for bundle in bundles.values() if isinstance(bundle, dict)]
        return {
            "status": cls._aggregate_bi_report_data_status(statuses),
            "asins": asins,
            "count": len(asins),
            "request_mode": "per_asin",
            "per_asin": bundles,
        }

    @staticmethod
    def _aggregate_bi_report_data_status(statuses: list[Any]) -> str:
        if not statuses:
            return "skipped"
        if all(status == "success" for status in statuses):
            return "success"
        if any(status == "success" for status in statuses):
            return "partial"
        if all(status == "planned" for status in statuses):
            return "planned"
        if all(status == "skipped" for status in statuses):
            return "skipped"
        return "failed"

    def _attach_bi_report_data(
        self,
        asin_results: list[dict[str, Any]],
        bundle: dict[str, Any],
        error_log: Any,
    ) -> None:
        for asin_result in asin_results:
            asin = str(asin_result.get("asin") or "").strip().upper()
            payload = select_bi_report_data_for_asin(bundle, asin=asin)
            asin_result["bi_report_data"] = payload
            self._attach_bi_report_data_to_frontend(asin_result, payload)
            failed_sources = self._failed_bi_report_sources(payload)
            if failed_sources:
                errors = asin_result.setdefault("errors", [])
                if isinstance(errors, list):
                    errors.extend(failed_sources)
        self._write_bi_report_data_errors(bundle, error_log)

    @staticmethod
    def _failed_bi_report_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
        sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
        failed: list[dict[str, Any]] = []
        for key, source in sources.items():
            if not isinstance(source, dict) or source.get("status") != "failed":
                continue
            failed.append(
                {
                    "source": f"bi_report_data.{key}",
                    "status": "failed",
                    "endpoint": source.get("endpoint"),
                    "error_message": source.get("error_message"),
                }
            )
        return failed

    @staticmethod
    def _write_bi_report_data_errors(bundle: dict[str, Any], error_log: Any) -> None:
        sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
        for key, source in sources.items():
            if not isinstance(source, dict) or source.get("status") != "failed":
                continue
            error_log.write(
                {
                    "source": f"bi_report_data.{key}",
                    "status": "failed",
                    "endpoint": source.get("endpoint"),
                    "asins": bundle.get("asins"),
                    "error_message": source.get("error_message"),
                }
            )

    @staticmethod
    def _attach_bi_report_data_to_frontend(asin_result: dict[str, Any], payload: dict[str, Any]) -> None:
        frontend_data = asin_result.get("frontend_data")
        if not isinstance(frontend_data, dict):
            return
        base_section = frontend_data.get("基础数据")
        if not isinstance(base_section, dict):
            base_section = frontend_data.get("鍩虹鏁版嵁")
        if not isinstance(base_section, dict):
            return
        sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
        base_section["BI接口数据"] = {
            "状态": payload.get("status"),
            "数据源": {
                str(source.get("label") or key): {
                    "接口": source.get("endpoint"),
                    "状态": source.get("status"),
                    "行数": source.get("row_count"),
                    "源行数": source.get("source_row_count"),
                    "错误": source.get("error_message"),
                    "数据": source.get("rows"),
                }
                for key, source in sources.items()
                if isinstance(source, dict)
            },
        }

    def _fetch_report_files(
        self,
        records: list[dict[str, Any]],
        asin_results: list[dict[str, Any]],
        error_log: Any,
        *,
        require_all: bool = False,
    ) -> dict[str, Any]:
        by_asin = {item.get("asin"): item for item in asin_results}
        items: list[dict[str, Any]] = []
        for record in records:
            asin = str(record.get("asin") or "").strip().upper()
            site = str(record.get("site") or "US").strip().upper()
            payload: dict[str, Any]
            try:
                report_file = self.report_file_client.fetch(asin=asin, site=site)
                payload = {
                    "asin": asin,
                    "site": site,
                    "status": "success" if report_file.url else "not_found",
                    "url": report_file.url,
                    "record": report_file.record,
                }
                if require_all and not report_file.url:
                    error_log.write(
                        {
                            "asin": asin,
                            "source": "asin_report_files",
                            "status": "not_found",
                            "error_message": "report file url not found",
                        }
                    )
                    raise AsinReportFileNotFoundError(asin=asin, site=site)
            except Exception as exc:
                if require_all:
                    if isinstance(exc, AsinReportFileNotFoundError):
                        raise
                    error_log.write(
                        {
                            "asin": asin,
                            "source": "asin_report_files",
                            "status": "failed",
                            "error_message": str(exc),
                        }
                    )
                    raise AsinReportFileNotFoundError(
                        asin=asin,
                        site=site,
                        message=f"取数服务异常：ASIN 报告地址接口查询失败（ASIN={asin}，站点={site}）：{exc}",
                    ) from exc
                payload = {
                    "asin": asin,
                    "site": site,
                    "status": "failed",
                    "url": None,
                    "error_message": str(exc),
                }
                error_log.write(
                    {
                        "asin": asin,
                        "source": "asin_report_files",
                        "status": "failed",
                        "error_message": str(exc),
                    }
                )
            items.append(payload)
            asin_result = by_asin.get(asin)
            if isinstance(asin_result, dict):
                asin_result["asin_report_file"] = payload
                self._attach_report_file_to_frontend(asin_result, payload)
        success_count = sum(1 for item in items if item.get("url"))
        return {
            "status": "success" if success_count == len(items) else ("partial" if success_count else "failed"),
            "endpoint": "/dataMetrics/v1/asin-report-files",
            "count": len(items),
            "success_count": success_count,
            "items": items,
        }

    def _attach_report_files(self, asin_results: list[dict[str, Any]], report_files: dict[str, Any]) -> None:
        items = report_files.get("items")
        if not isinstance(items, list):
            return
        by_asin = {
            str(item.get("asin") or "").strip().upper(): item
            for item in items
            if isinstance(item, dict)
        }
        for asin_result in asin_results:
            asin = str(asin_result.get("asin") or "").strip().upper()
            payload = by_asin.get(asin)
            if payload:
                asin_result["asin_report_file"] = payload
                self._attach_report_file_to_frontend(asin_result, payload)

    @staticmethod
    def _attach_report_file_to_frontend(asin_result: dict[str, Any], report_file: dict[str, Any]) -> None:
        frontend_data = asin_result.get("frontend_data")
        if not isinstance(frontend_data, dict):
            return
        base_section = frontend_data.get("基础数据")
        if not isinstance(base_section, dict):
            return
        base_section["取数报告地址"] = report_file.get("url")
        base_section["取数报告状态"] = report_file.get("status")

    @staticmethod
    def _single_report_file_url(report_files: Any) -> str | None:
        if not isinstance(report_files, dict):
            return None
        items = report_files.get("items")
        if not isinstance(items, list) or len(items) != 1:
            return None
        url = items[0].get("url") if isinstance(items[0], dict) else None
        return url if isinstance(url, str) and url.strip() else None

    def _upload_split_package(
        self,
        path: Path,
        *,
        run_id: str,
        records: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        upload = self.file_upload_client.upload(
            path,
            purpose="asin_data_split_package_zip",
            folder="asin-data",
            public="1",
            metadata={
                "run_id": run_id,
                "asin_count": len(records),
                "asins": [record.get("asin") for record in records],
                "report_type": "asin_data_split_package_zip",
                "report_filename": path.name,
                "package_filename": path.name,
                "frontend_html": "frontend-data.html",
                "frontend_markdown": "frontend-data.md",
                "source_filename": path.name,
                "upload_filename": path.name,
                "summary": summary.get("summary"),
            },
        )
        self._validate_split_package_upload_url(upload.url, records)
        return {
            "url": upload.url,
            "path": path.as_posix(),
            "upload_path": path.as_posix(),
            "purpose": "asin_data_split_package_zip",
            "folder": "asin-data",
            "raw": upload.raw,
        }

    def _upload_split_package_files(
        self,
        split_package: dict[str, Any],
        *,
        run_id: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Upload each ASIN's 6 split files individually and return per-file URLs.

        This complements :meth:`_upload_split_package` (whole zip) by giving the
        downstream AI a way to fetch one file at a time instead of the whole zip,
        avoiding oversized context windows.
        """
        asin_set = {str(record.get("asin") or "").strip().upper() for record in records}
        items: list[dict[str, Any]] = []
        files_uploaded = 0
        for entry in split_package.get("items", []) or []:
            asin = str(entry.get("asin") or "").strip().upper()
            if not asin or (asin_set and asin not in asin_set):
                continue
            file_paths = entry.get("files") if isinstance(entry.get("files"), dict) else {}
            per_file: dict[str, Any] = {}
            for file_key in SPLIT_FILE_KEYS:
                path_text = file_paths.get(file_key)
                if not isinstance(path_text, str) or not path_text.strip():
                    continue
                file_path = Path(path_text)
                if not file_path.exists():
                    continue
                try:
                    upload = self.file_upload_client.upload(
                        file_path,
                        purpose="asin_data_file",
                        folder="asin-data",
                        public="1",
                        metadata={
                            "run_id": run_id,
                            "asin": asin,
                            "file_key": file_key,
                            "report_filename": file_path.name,
                        },
                    )
                except Exception:
                    continue
                per_file[file_key] = {
                    "url": upload.url,
                    "file_name": file_path.name,
                    "file_path": file_path.as_posix(),
                }
                files_uploaded += 1
            items.append({"asin": asin, "files": per_file})
        return {"files_uploaded": files_uploaded, "items": items}

    @classmethod
    def _validate_split_package_upload_url(cls, url: str, records: list[dict[str, Any]]) -> None:
        asin = cls._single_record_asin(records)
        if not asin:
            return
        pattern = rf"/asin-data/\d{{4}}/\d{{2}}/\d+-{re.escape(asin)}-asin-data-package\.zip(?:\?.*)?$"
        if not re.search(pattern, url):
            raise ValueError(
                "ASIN data package upload URL format mismatch: "
                f"expected /asin-data/YYYY/MM/<number>-{asin}-asin-data-package.zip, got {url}"
            )

    @staticmethod
    def _normalize_upload_paths(upload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(upload)
        for key in ("path", "upload_path"):
            if normalized.get(key):
                normalized[key] = str(normalized[key]).replace("\\", "/")
        return normalized

    def _write_report_txt(
        self,
        output_root: Path,
        frontend_bundle: dict[str, Any],
        records: list[dict[str, Any]],
        summary: dict[str, Any],
        asin_results: list[dict[str, Any]],
    ) -> Path:
        report_path = output_root / self._report_txt_filename(records)
        report_text = self._render_report_txt(
            frontend_bundle,
            records,
            summary=summary,
            asin_results=asin_results,
            output_root=output_root,
        )
        with report_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
            handle.write(report_text)
        return report_path

    def _render_report_txt(
        self,
        frontend_bundle: dict[str, Any],
        records: list[dict[str, Any]],
        *,
        summary: dict[str, Any] | None = None,
        asin_results: list[dict[str, Any]] | None = None,
        output_root: Path | None = None,
    ) -> str:
        if len(records) == 1 and asin_results and len(asin_results) == 1:
            return render_merged_report_text(asin_results[0], summary=summary, output_root=output_root)
        markdown = self.legacy.render_frontend_markdown(frontend_bundle)
        asin = self._single_record_asin(records)
        if asin:
            return markdown.replace("# ASIN取数完整数据", f"# ASIN 取数汇总报告 - {asin}", 1)
        return markdown.replace("# ASIN取数完整数据", "# ASIN 取数汇总报告", 1)

    @classmethod
    def _report_txt_filename(cls, records: list[dict[str, Any]]) -> str:
        asin = cls._single_record_asin(records)
        if asin:
            return f"{asin}-asin-data-report.txt"
        return "asin-data-report.txt"

    @staticmethod
    def _single_record_asin(records: list[dict[str, Any]]) -> str | None:
        if len(records) != 1:
            return None
        asin = str(records[0].get("asin") or "").strip().upper()
        return asin or None

    @staticmethod
    def _render_frontend_html(frontend_bundle: dict[str, Any]) -> str:
        run_info = frontend_bundle.get("运行信息")
        rows = frontend_bundle.get("数据")
        if not isinstance(run_info, dict):
            run_info = {}
        if not isinstance(rows, list):
            rows = []

        def esc(value: Any) -> str:
            return html.escape("" if value is None else str(value), quote=True)

        def json_block(value: Any) -> str:
            return (
                "<pre>"
                + esc(json.dumps(value, ensure_ascii=False, indent=2, default=str))
                + "</pre>"
            )

        def table(payload: dict[str, Any]) -> str:
            body = "\n".join(
                f"<tr><th>{esc(key)}</th><td>{esc(value) if not isinstance(value, (dict, list)) else json_block(value)}</td></tr>"
                for key, value in payload.items()
            )
            return f"<table>{body}</table>"

        cards: list[str] = []
        for index, record in enumerate(rows, start=1):
            if not isinstance(record, dict):
                cards.append(f"<section class=\"asin-card\"><h2>ASIN {index}</h2>{json_block(record)}</section>")
                continue
            base = record.get("基础数据") if isinstance(record.get("基础数据"), dict) else {}
            asin = base.get("ASIN") or f"ASIN {index}" if isinstance(base, dict) else f"ASIN {index}"
            section_html: list[str] = []
            for section_name, section_payload in record.items():
                open_attr = " open" if section_name == "基础数据" else ""
                section_html.append(
                    f"<details{open_attr}><summary>{esc(section_name)}</summary>{json_block(section_payload)}</details>"
                )
            cards.append(
                f"<section class=\"asin-card\" id=\"asin-{esc(asin)}\"><h2>{esc(asin)}</h2>{''.join(section_html)}</section>"
            )

        template = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ASIN Data Package</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f8fb; color: #17202a; }
    header { background: #0f172a; color: #fff; padding: 24px 32px; }
    main { max-width: 1180px; margin: 0 auto; padding: 24px; }
    h1, h2 { margin: 0 0 16px; }
    .panel, .asin-card { background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 20px; margin-bottom: 18px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #e6eaf0; padding: 10px 12px; text-align: left; vertical-align: top; }
    th { width: 220px; color: #475569; background: #f8fafc; }
    details { border: 1px solid #e2e8f0; border-radius: 6px; margin: 10px 0; background: #fbfdff; }
    summary { cursor: pointer; font-weight: 600; padding: 12px 14px; }
    pre { margin: 0; padding: 14px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: #0b1020; color: #d7e0ff; border-radius: 0 0 6px 6px; }
    .panel pre { border-radius: 6px; }
  </style>
</head>
<body>
  <header>
    <h1>ASIN Data Package</h1>
    <div>Generated by opscli asin-data collect</div>
  </header>
      <main>
        <section class="panel">
          <h2>运行信息</h2>
      __RUN_INFO__
    </section>
    __CARDS__
    <section class="panel">
      <h2>完整 JSON</h2>
      __FULL_JSON__
    </section>
  </main>
</body>
</html>
"""
        return (
            template
            .replace("__RUN_INFO__", table(run_info))
            .replace("__CARDS__", "\n".join(cards))
            .replace("__FULL_JSON__", json_block(frontend_bundle))
        )

    def _load_records(self, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if args.input:
            return self.legacy.load_asin_records(
                args.input,
                asin_column=args.asin_column,
                keyword_column=args.keyword_column,
                site_column=args.site_column,
                default_site=args.site,
            )

        asin = str(args.asin or "").strip().upper()
        site = str(args.site or "US").strip().upper()
        keywords = self.legacy.normalize_keywords(args.keywords)
        return [
            {
                "asin": asin,
                "site": site,
                "keyword": keywords[0] if keywords else "",
                "keywords": keywords,
                "row_index": 1,
                "source_file": "--asin",
                "source_row": {
                    "asin": asin,
                    "site": site,
                    "keywords": keywords,
                },
            }
        ], []

    @staticmethod
    def _validate_args(args: argparse.Namespace) -> None:
        input_provided = bool(str(args.input or "").strip())
        asin = str(args.asin or "").strip().upper()
        asin_provided = bool(asin)
        if input_provided == asin_provided:
            raise ValueError("Provide exactly one of --input or --asin")
        if asin_provided and (len(asin) != 10 or not asin.isalnum()):
            raise ValueError("--asin must be a 10-character ASIN")
        if args.query_chunk_size < 1:
            raise ValueError("--query-chunk-size must be >= 1")
        if args.max_miner_keywords < 1:
            raise ValueError("--max-miner-keywords must be >= 1")
        if args.listing_analysis_poll_attempts is not None and args.listing_analysis_poll_attempts < 1:
            raise ValueError("--listing-analysis-poll-attempts must be >= 1")
        if args.listing_analysis_poll_interval_seconds is not None and args.listing_analysis_poll_interval_seconds < 0:
            raise ValueError("--listing-analysis-poll-interval-seconds must be >= 0")
        if args.rufus_timeout_seconds < 1:
            raise ValueError("--rufus-timeout-seconds must be >= 1")
        if args.rufus_login_timeout_seconds < 1:
            raise ValueError("--rufus-login-timeout-seconds must be >= 1")
        if args.rufus_concurrency < 1:
            raise ValueError("--rufus-concurrency must be >= 1")
        if args.rufus_retry < 0:
            raise ValueError("--rufus-retry must be >= 0")


class DirectOpsRunner:
    """Compatibility runner that returns the same shape as the old subprocess path."""

    def __init__(
        self,
        legacy: ModuleType,
        *,
        query_manager: QueryManager | None = None,
        seller_sprite_manager: SellerSpriteApiManager | None = None,
        rufus_manager: RufusManager | None = None,
        amazon_manager: AmazonManager | None = None,
        remote_consent_store: RemoteConsentStore | None = None,
        report_writer: AnswerReportWriter | None = None,
    ) -> None:
        self.legacy = legacy
        self.query_manager = query_manager or QueryManager()
        self.seller_sprite_manager = seller_sprite_manager or SellerSpriteApiManager()
        self.rufus_manager = rufus_manager or RufusManager()
        self.amazon_manager = amazon_manager or AmazonManager()
        self.remote_consent_store = remote_consent_store or RemoteConsentStore()
        self.report_writer = report_writer or AnswerReportWriter()

    def run_or_plan(
        self,
        *,
        source: str,
        command: list[str],
        dry_run: bool,
        command_log: Any,
        error_log: Any,
        asin: str | None = None,
        raw_output_path: Path | None = None,
    ) -> dict[str, Any]:
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "asin": asin,
            "command": command,
            "dry_run": dry_run,
            "execution": "direct",
        }
        if dry_run:
            planned = {**entry, "status": "planned", "exit_code": None}
            _write_log(command_log, planned)
            return {"status": "planned", "command": command}

        stdout = ""
        stderr = ""
        exit_code = 0
        try:
            payload, stdout = self._dispatch(source=source, command=command)
            status = "success" if not self.legacy.is_payload_failure(payload) else "failed"
            if status == "failed":
                exit_code = 1
        except Exception as exc:  # Keep collection resilient per-source.
            payload = _exception_payload(source, exc)
            stderr = str(exc)
            status = "failed"
            exit_code = 1

        result = {
            **entry,
            "status": status,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "json": payload,
        }
        _write_log(command_log, self.legacy.strip_large_output(result))
        if raw_output_path:
            self.legacy.write_json(raw_output_path, result)
        if status == "failed":
            _write_log(
                error_log,
                {
                    "asin": asin,
                    "source": source,
                    "tool": f"direct:{source}",
                    "status": "failed",
                    "exit_code": exit_code,
                    "error_message": self.legacy.extract_error_message(payload, stderr),
                    "retry_count": 0,
                },
            )
        return result

    def _dispatch(self, *, source: str, command: list[str]) -> tuple[Any, str]:
        if source == "query.metadata":
            return self._run_query_metadata(command), ""
        if source == "query.sales":
            return self._run_query_simple(command), ""
        if source == "query.crawler_listing":
            if len(command) > 2 and command[2] == "run":
                return self._run_query_run(command), ""
            return self._run_query_simple(command), ""
        if source.startswith("seller_sprite."):
            return self._run_seller_sprite(command), ""
        if source == "amazon.scrape":
            return self._run_amazon_scrape(command), ""
        if source == "rufus.remote_consent":
            return self._run_rufus_remote_consent(command), ""
        if source == "rufus.login_status":
            return self._run_rufus_login_status(command), ""
        if source == "rufus.watch_login":
            return self._run_rufus_watch_login(command), ""
        if source == "rufus.get_backend":
            payload = self._run_rufus_get_backend(command)
            report_path = self.report_writer.write(payload)
            return payload, f"Rufus 答案报告已保存：{report_path.as_posix()}\n"
        raise ValueError(f"Unsupported ASIN data direct source: {source}")

    def _run_query_metadata(self, command: list[str]) -> dict[str, Any]:
        result = self.query_manager.metadata(
            dataset_alias=_option(command, "--dataset"),
            table_id=_int_option(command, "--table-id"),
        )
        return {"success": True, "command": "query metadata", "data": result.to_dict(), "error": None}

    def _run_query_simple(self, command: list[str]) -> dict[str, Any]:
        payload_path = _required_option(command, "--payload")
        simple_params = json.loads(Path(payload_path).read_text(encoding="utf-8-sig"))
        result = self.query_manager.build_simple_and_run(
            table_id=_required_int_option(command, "--table-id"),
            dataset_alias=None,
            dimensions=simple_params.get("dimensions"),
            metrics=simple_params.get("metrics"),
            filters=simple_params.get("filters"),
            data_comparison=simple_params.get("dataComparison"),
            order_by=simple_params.get("orderBy"),
            limit=int(simple_params.get("limit", 20)),
            offset=int(simple_params.get("offset", 0)),
            dry_run=bool(simple_params.get("dryRun", False)),
            validate_fields=True,
        )
        return {"success": True, "command": "query simple-run", "data": result, "error": None}

    def _run_query_run(self, command: list[str]) -> dict[str, Any]:
        payload_path = _required_option(command, "--payload")
        result = self.query_manager.run(payload_path=payload_path)
        return {"success": True, "command": "query run", "data": result, "error": None}

    def _run_seller_sprite(self, command: list[str]) -> dict[str, Any]:
        scenario = command[3] if len(command) > 3 else ""
        request = SellerSpriteScenarioRequest(
            scenario=scenario,
            site=_option(command, "--site", "US") or "US",
            period=_option(command, "--period", "30d") or "30d",
            params=_json_option(command, "--params", {}),
            page_size=_required_int_option(command, "--page-size", default=100),
            output_dir=_option(command, "--output-dir"),
            export_format=_option(command, "--export-format", "json") or "json",
        )
        try:
            return asyncio.run(self.seller_sprite_manager.run(request)).to_dict()
        except FileNotFoundError as exc:
            recovered = _recover_listing_analysis_from_raw(request, exc)
            if recovered is not None:
                return recovered
            raise

    def _run_amazon_scrape(self, command: list[str]) -> dict[str, Any]:
        result = self.amazon_manager.scrape_product(
            asin=_required_option(command, "--asin"),
            zip_code=_option(command, "--zip-code", "10001") or "10001",
            save_history="--no-save" not in command,
        )
        return {"success": True, "command": "amazon scrape", "data": result.to_dict(include_raw=False), "error": None}

    def _run_rufus_remote_consent(self, command: list[str]) -> dict[str, Any]:
        country = command[4] if len(command) > 4 else ""
        data = self.remote_consent_store.status(country)
        return {"success": True, "command": "amazon-rufus remote-consent status", "data": data, "error": None}

    def _run_rufus_login_status(self, command: list[str]) -> dict[str, Any]:
        country = command[3] if len(command) > 3 else ""
        data = self.rufus_manager.login_status(country=country)
        return {"success": True, "command": "amazon-rufus login-status", "data": data, "error": None}

    def _run_rufus_watch_login(self, command: list[str]) -> dict[str, Any]:
        asin = command[3] if len(command) > 3 else ""
        country = command[4] if len(command) > 4 else ""
        data = self.rufus_manager.watch_login(
            asin=asin,
            country=country,
            timeout_seconds=_required_int_option(command, "--timeout", default=180),
            launch_if_needed="--launch-if-needed" in command,
            close_browser="--close-browser" in command,
        )
        return {"success": True, "command": "amazon-rufus watch-login", "data": data, "error": None}

    def _run_rufus_get_backend(self, command: list[str]) -> dict[str, Any]:
        asin = command[3] if len(command) > 3 else ""
        country = command[4] if len(command) > 4 else ""
        questions = _repeat_options(command, "-q", "--question")
        return self.rufus_manager.get_backend(
            asin=asin,
            country=country,
            questions=questions or None,
            skills_dir=_option(command, "--skills-dir"),
            timeout_seconds=_required_int_option(command, "--timeout", default=180),
            include_upload_payload="--no-upload-payload" not in command,
            submit_upload="--submit-upload" in command,
            parallel="--parallel" in command,
            concurrency=_required_int_option(command, "--concurrency", default=3),
            retry=_required_int_option(command, "--retry", default=0),
            strict_answer="--strict-answer" in command,
        )


def load_legacy_collector(path: Path = DEFAULT_LEGACY_SCRIPT) -> ModuleType:
    spec = importlib.util.spec_from_file_location("opscli_asin_data_legacy_collector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load ASIN collector script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exception_payload(command: str, exc: Exception) -> dict[str, Any]:
    if hasattr(exc, "to_dict"):
        error = exc.to_dict()  # type: ignore[call-arg]
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    return {"success": False, "command": command, "data": None, "error": error}


def _recover_listing_analysis_from_raw(
    request: SellerSpriteScenarioRequest,
    exc: FileNotFoundError,
) -> dict[str, Any] | None:
    if request.scenario != "listing-analysis":
        return None

    missing_path = _missing_file_path(exc)
    raw_path = _listing_analysis_raw_path(request, missing_path)
    if raw_path is None:
        return None

    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None

    rows = _listing_analysis_rows_from_response(raw.get("response"))
    if not rows:
        return None

    root_dir = raw_path.parent
    job_id = str(raw.get("job_id") or root_dir.name)
    result_path = root_dir / "result.json"
    warnings = [item for item in raw.get("warnings", []) if isinstance(item, dict)]
    warnings.append(
        {
            "stage": "direct_runner_recovery",
            "message": "ListingAnalysis export file was missing; recovered from raw response data.",
            "missing_path": str(missing_path) if missing_path else None,
            "raw_path": str(raw_path),
        }
    )

    export = None
    export_path = _recovered_export_path(root_dir=root_dir, job_id=job_id, missing_path=missing_path)
    try:
        _write_json_file(
            export_path,
            {
                "job_id": job_id,
                "scenario": request.scenario,
                "site": request.site,
                "period": request.period,
                "row_count": len(rows),
                "rows": rows,
                "high_frequency_rows": [],
                "warnings": warnings,
            },
        )
        resolved_export_path = export_path.resolve()
        export = {
            "path": str(resolved_export_path),
            "filename": resolved_export_path.name,
            "url": resolved_export_path.as_uri(),
            "format": "json",
            "mime_type": "application/json",
        }
    except Exception as write_exc:
        warnings.append(
            {
                "stage": "direct_runner_recovery_export",
                "message": "Recovered ListingAnalysis data, but could not rewrite the missing export file.",
                "error": {"code": type(write_exc).__name__, "message": str(write_exc)},
            }
        )

    payload = {
        "job_id": job_id,
        "scenario": request.scenario,
        "site": request.site,
        "period": request.period,
        "row_count": len(rows),
        "root_dir": str(root_dir),
        "params_path": str(root_dir / "params.json"),
        "raw_path": str(raw_path),
        "result_path": str(result_path),
        "export": export,
        "data": rows,
        "warnings": warnings,
    }
    try:
        _write_json_file(result_path, payload)
    except Exception:
        pass
    return payload


def _missing_file_path(exc: FileNotFoundError) -> Path | None:
    filename = getattr(exc, "filename", None)
    if not filename:
        return None
    try:
        return Path(filename)
    except TypeError:
        return None


def _listing_analysis_raw_path(
    request: SellerSpriteScenarioRequest,
    missing_path: Path | None,
) -> Path | None:
    if missing_path is not None:
        candidate = missing_path.parent / "raw.json"
        if candidate.exists():
            return candidate

    if not request.output_dir:
        return None
    base_dir = Path(request.output_dir).expanduser()
    if not base_dir.is_absolute():
        base_dir = Path.cwd() / base_dir
    if not base_dir.exists():
        return None

    asin = str((request.params or {}).get("asin") or "").upper()
    candidates = []
    for candidate in base_dir.glob("*/raw.json"):
        parent_name = candidate.parent.name.upper()
        if "LISTINGANALYSIS" not in parent_name:
            continue
        if asin and asin not in parent_name:
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _listing_analysis_rows_from_response(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    has_content = data.get("content") is not None or data.get("htmlContent") is not None
    status = str(data.get("taskStatus") or data.get("status") or "").strip().upper()
    if not has_content and status not in {"COMPLETED", "COMPLETE", "SUCCESS", "SUCCEEDED", "FINISHED", "DONE"}:
        return []
    return [
        {
            "taskId": data.get("taskId"),
            "taskStatus": data.get("taskStatus"),
            "content": data.get("content"),
            "htmlStatus": data.get("htmlStatus"),
            "htmlContent": data.get("htmlContent"),
            "completedTime": data.get("completedTime"),
            "expiredTime": data.get("expiredTime"),
        }
    ]


def _recovered_export_path(*, root_dir: Path, job_id: str, missing_path: Path | None) -> Path:
    candidate = missing_path if missing_path is not None else root_dir / f"{job_id}.json"
    if len(str(candidate)) >= WINDOWS_COMPAT_EXPORT_PATH_LIMIT:
        return root_dir / "export.json"
    return candidate


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_log(writer: Any, payload: dict[str, Any]) -> None:
    if writer is not None:
        writer.write(payload)


def _option(command: list[str], name: str, default: str | None = None) -> str | None:
    try:
        return command[command.index(name) + 1]
    except (ValueError, IndexError):
        return default


def _required_option(command: list[str], name: str) -> str:
    value = _option(command, name)
    if value is None:
        raise ValueError(f"Missing option {name}")
    return value


def _int_option(command: list[str], name: str) -> int | None:
    value = _option(command, name)
    return int(value) if value is not None else None


def _required_int_option(command: list[str], name: str, default: int | None = None) -> int:
    value = _option(command, name)
    if value is None:
        if default is None:
            raise ValueError(f"Missing option {name}")
        return default
    return int(value)


def _json_option(command: list[str], name: str, default: dict[str, Any]) -> dict[str, Any]:
    value = _option(command, name)
    if value is None:
        return default
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    return parsed


def _repeat_options(command: list[str], *names: str) -> list[str]:
    values: list[str] = []
    index = 0
    names_set = set(names)
    while index < len(command):
        if command[index] in names_set and index + 1 < len(command):
            values.append(command[index + 1])
            index += 2
            continue
        index += 1
    return values
