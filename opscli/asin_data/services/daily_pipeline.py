"""Stage-based daily ASIN data collection pipeline.

This module keeps the existing ``asin-data collect`` contract intact while
allowing unattended daily jobs to collect independent sources separately and
merge them into the same final package.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from opscli.amazon_rufus.services.batch_backend import BatchGetBackendOptions, RufusBatchBackendRunner
from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.asin_data.services.bi_report_data import (
    build_bi_report_data_placeholder,
    summarize_bi_report_data,
)
from opscli.asin_data.services.collector import AsinDataCollector, DirectOpsRunner
from opscli.asin_data.services.split_package_builder import build_split_package


STAGE_QUERY = "query"
STAGE_BI = "bi"
STAGE_BASIC = "basic"
STAGE_SELLER_KEYWORD_REVERSE = "seller-keyword-reverse"
STAGE_SELLER_KEYWORD_MINER = "seller-keyword-miner"
STAGE_SELLER_LISTING_ANALYSIS = "seller-listing-analysis"
STAGE_RUFUS = "rufus"

STAGES = {
    STAGE_QUERY,
    STAGE_BI,
    STAGE_BASIC,
    STAGE_SELLER_KEYWORD_REVERSE,
    STAGE_SELLER_KEYWORD_MINER,
    STAGE_SELLER_LISTING_ANALYSIS,
    STAGE_RUFUS,
}


@dataclass(frozen=True)
class DailyStagePaths:
    output_root: Path
    stages_dir: Path

    def path_for(self, stage: str) -> Path:
        mapping = {
            STAGE_QUERY: "query.json",
            STAGE_BI: "bi-report-data.json",
            STAGE_BASIC: "basic.jsonl",
            STAGE_SELLER_KEYWORD_REVERSE: "seller-keyword-reverse.jsonl",
            STAGE_SELLER_KEYWORD_MINER: "seller-keyword-miner.jsonl",
            STAGE_SELLER_LISTING_ANALYSIS: "seller-listing-analysis.jsonl",
            STAGE_RUFUS: "rufus.json",
        }
        return self.stages_dir / mapping[stage]


class DailyAsinDataPipeline:
    """Collect, cache, merge, and package daily ASIN data stages."""

    def __init__(
        self,
        *,
        collector: AsinDataCollector | None = None,
        rufus_batch_runner: RufusBatchBackendRunner | None = None,
    ) -> None:
        self.collector = collector or AsinDataCollector()
        self.legacy = self.collector.legacy
        self.runner: DirectOpsRunner = self.collector.runner
        self.rufus_batch_runner = rufus_batch_runner or RufusBatchBackendRunner()

    def run_stage(self, stage: str, **kwargs: Any) -> dict[str, Any]:
        stage = self._normalize_stage(stage)
        args, paths, records, input_errors = self._prepare_run(**kwargs)
        paths.stages_dir.mkdir(parents=True, exist_ok=True)
        self._write_input_manifest(paths, records, input_errors)

        command_log = self.legacy.JsonlWriter(paths.output_root / "commands.jsonl")
        error_log = self.legacy.JsonlWriter(paths.output_root / "errors.jsonl")
        started_at = datetime.now().isoformat(timespec="seconds")

        if stage == STAGE_QUERY:
            payload = self._run_query_stage(args, records, paths, command_log, error_log)
        elif stage == STAGE_BI:
            payload = self._run_bi_stage(args, records)
        elif stage == STAGE_BASIC:
            payload = self._run_basic_stage(args, records, paths, command_log, error_log)
        elif stage == STAGE_SELLER_KEYWORD_REVERSE:
            payload = self._run_keyword_reverse_stage(args, records, paths, command_log, error_log)
        elif stage == STAGE_SELLER_KEYWORD_MINER:
            payload = self._run_keyword_miner_stage(args, records, paths, command_log, error_log)
        elif stage == STAGE_SELLER_LISTING_ANALYSIS:
            payload = self._run_listing_analysis_stage(args, records, paths, command_log, error_log)
        elif stage == STAGE_RUFUS:
            payload = self._run_rufus_stage(args, records, paths)
        else:  # pragma: no cover - protected by _normalize_stage
            raise ValueError(f"Unsupported daily ASIN data stage: {stage}")

        stage_path = paths.path_for(stage)
        self._write_stage_payload(stage_path, payload)
        summary = {
            "success": True,
            "command": "asin-data stage-collect",
            "data": {
                "stage": stage,
                "run_id": paths.output_root.name,
                "output_dir": paths.output_root.as_posix(),
                "stage_path": stage_path.as_posix(),
                "asin_count": len(records),
                "input_error_count": len(input_errors),
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "status": self._stage_status(payload),
            },
            "error": None,
        }
        self.legacy.write_json(paths.stages_dir / f"{stage}-summary.json", summary)
        return summary

    def run_all(self, **kwargs: Any) -> dict[str, Any]:
        """Run the recommended single-process order, then merge.

        Daily automation should prefer separate OS-level jobs for long-running
        stages. This method is intentionally conservative and useful for manual
        verification.
        """
        stages = [
            STAGE_QUERY,
            STAGE_BI,
            STAGE_BASIC,
            STAGE_SELLER_KEYWORD_REVERSE,
            STAGE_SELLER_KEYWORD_MINER,
            STAGE_SELLER_LISTING_ANALYSIS,
            STAGE_RUFUS,
        ]
        stage_results = [self.run_stage(stage, **kwargs) for stage in stages]
        merged = self.merge(**kwargs)
        merged["stage_results"] = stage_results
        return merged

    def merge(self, **kwargs: Any) -> dict[str, Any]:
        args, paths, records, input_errors = self._prepare_run(**kwargs)
        paths.output_root.mkdir(parents=True, exist_ok=True)
        paths.stages_dir.mkdir(parents=True, exist_ok=True)
        self._write_input_manifest(paths, records, input_errors)

        command_log = self.legacy.JsonlWriter(paths.output_root / "commands.jsonl")
        error_log = self.legacy.JsonlWriter(paths.output_root / "errors.jsonl")
        result_log = self.legacy.JsonlWriter(paths.output_root / "asin-data.jsonl")
        started_at = datetime.now().isoformat(timespec="seconds")

        for error in input_errors:
            error_log.write({"source": "input", **error})

        query_bundle = self._read_json(paths.path_for(STAGE_QUERY), default={})
        basic_by_asin = self._read_jsonl_by_asin(paths.path_for(STAGE_BASIC))
        reverse_by_asin = self._read_jsonl_by_asin(paths.path_for(STAGE_SELLER_KEYWORD_REVERSE))
        miner_by_asin = self._read_jsonl_by_asin(paths.path_for(STAGE_SELLER_KEYWORD_MINER))
        listing_by_asin = self._read_jsonl_by_asin(paths.path_for(STAGE_SELLER_LISTING_ANALYSIS))
        rufus_by_asin = self._rufus_by_asin(paths.path_for(STAGE_RUFUS))
        bi_report_data = self._read_json(paths.path_for(STAGE_BI), default=None)

        asin_results: list[dict[str, Any]] = []
        for record in records:
            asin = str(record.get("asin") or "").strip().upper()
            result = self._base_result(record, query_bundle)
            result["amazon"]["scrape"] = self._source_or_skipped(
                basic_by_asin.get(asin, {}).get("amazon_scrape"),
                "basic stage missing",
            )
            result["seller_sprite"]["keyword_reverse"] = self._source_or_skipped(
                reverse_by_asin.get(asin, {}).get("keyword_reverse"),
                "keyword reverse stage missing",
            )
            result["seller_sprite"]["keyword_miner"] = self._source_or_skipped(
                miner_by_asin.get(asin, {}).get("keyword_miner"),
                "keyword miner stage missing",
            )
            miner_input = miner_by_asin.get(asin, {}).get("input")
            if isinstance(miner_input, dict) and miner_input.get("keywords"):
                result["input"].update(miner_input)
            result["seller_sprite"]["listing_analysis"] = self._source_or_skipped(
                listing_by_asin.get(asin, {}).get("listing_analysis"),
                "listing analysis stage missing",
            )
            result["rufus"] = self._source_or_skipped(
                rufus_by_asin.get(asin),
                "rufus stage missing",
            )
            self._collect_result_errors(result)
            result["frontend_data"] = self.legacy.build_frontend_record(result)
            asin_results.append(result)

        if bi_report_data is None:
            bi_report_data = build_bi_report_data_placeholder(
                asins=[record["asin"] for record in records],
                status="skipped",
                reason="bi stage missing",
            )
        self.collector._attach_bi_report_data(asin_results, bi_report_data, error_log)

        if args.fetch_report_files and not args.dry_run:
            report_files = self.collector._fetch_report_files(records, asin_results, error_log)
        else:
            report_files = None

        for asin_result in asin_results:
            result_log.write(asin_result)

        summary = self.legacy.build_summary(records, asin_results, input_errors, paths.output_root, started_at, args)
        summary["options"]["daily_stage_pipeline"] = True
        summary["options"]["fetch_report_files"] = args.fetch_report_files
        summary["options"]["skip_bi_report_data"] = args.skip_bi_report_data
        summary["stages"] = self._stage_file_summary(paths)
        summary["bi_report_data"] = summarize_bi_report_data(bi_report_data)
        if report_files is not None:
            summary["report_files"] = report_files

        frontend_bundle = self.legacy.build_frontend_bundle(summary, asin_results)
        frontend_json_path = paths.output_root / "frontend-data.json"
        frontend_markdown_path = paths.output_root / "frontend-data.md"
        frontend_html_path = paths.output_root / "frontend-data.html"
        report_txt_path = self.collector._write_report_txt(paths.output_root, frontend_bundle, records, summary, asin_results)
        self.legacy.write_json(frontend_json_path, frontend_bundle)
        self.legacy.write_text(frontend_markdown_path, self.legacy.render_frontend_markdown(frontend_bundle))
        self.legacy.write_text(frontend_html_path, self.collector._render_frontend_html(frontend_bundle))
        summary["files"]["frontend_html"] = frontend_html_path.as_posix()
        summary["files"]["asin_report_txt"] = report_txt_path.as_posix()

        split_package = build_split_package(output_root=paths.output_root, asin_results=asin_results, summary=summary)
        summary["files"]["asin_data_package_dir"] = split_package["package_dir"]
        summary["files"]["asin_data_package_zip"] = split_package["zip_path"]
        summary["asin_data_package"] = split_package

        upload = None
        if args.upload:
            upload = self.collector._upload_split_package(
                Path(split_package["zip_path"]),
                run_id=paths.output_root.name,
                records=records,
                summary=summary,
            )
            upload = self.collector._normalize_upload_paths(upload)
            summary["files"]["asin_data_package_upload_url"] = upload["url"]
            summary["files"]["asin_report_upload_url"] = upload["url"]
            summary["upload"] = upload
            file_uploads = self.collector._upload_split_package_files(
                split_package,
                run_id=paths.output_root.name,
                records=records,
            )
            summary["files"]["asin_data_file_urls"] = file_uploads
            summary["asin_data_files"] = file_uploads

        self.legacy.write_json(paths.output_root / "asin-data-summary.json", summary)
        self.legacy.write_json(paths.output_root / "manifest.json", summary)

        report_file_url = self.collector._single_report_file_url(summary.get("report_files"))
        return {
            "success": True,
            "output_dir": paths.output_root.as_posix(),
            "summary": summary["summary"],
            "manifest": summary,
            "upload": upload,
            "report_files": summary.get("report_files"),
            "report_file_url": report_file_url,
            "aliyun_url": report_file_url or (upload["url"] if upload else None),
            "asin_data_files": summary.get("asin_data_files"),
        }

    def _prepare_run(self, **kwargs: Any) -> tuple[Any, DailyStagePaths, list[dict[str, Any]], list[dict[str, Any]]]:
        run_id = kwargs.get("run_id") or f"asin-data-daily-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        kwargs = {**kwargs, "run_id": run_id}
        args = self.collector._build_args(**kwargs)
        args.rufus_batch_mode = kwargs.get("rufus_batch_mode", "balanced")
        args.rufus_asin_concurrency = kwargs.get("rufus_asin_concurrency")
        args.rufus_resume = kwargs.get("rufus_resume", True)
        paths = DailyStagePaths(
            output_root=Path(args.output_dir).expanduser() / run_id,
            stages_dir=Path(args.output_dir).expanduser() / run_id / "stages",
        )
        records, input_errors = self.collector._load_records(args)
        if not records:
            raise ValueError("No valid ASIN records found.")
        return args, paths, records, input_errors

    def _run_query_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths, command_log: Any, error_log: Any) -> dict[str, Any]:
        original_run_or_plan = self.legacy.run_or_plan
        self.legacy.run_or_plan = self.runner.run_or_plan
        try:
            return self.legacy.collect_query_sources(args, records, paths.output_root, command_log, error_log)
        finally:
            self.legacy.run_or_plan = original_run_or_plan

    def _run_bi_stage(self, args: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
        asins = [str(record.get("asin") or "").strip().upper() for record in records if record.get("asin")]
        if args.skip_bi_report_data:
            return build_bi_report_data_placeholder(
                asins=asins,
                status="skipped",
                reason="BI report data skipped by --skip-bi-report-data",
                source_keys=args.bi_report_source_keys,
            )
        if args.dry_run:
            return build_bi_report_data_placeholder(
                asins=asins,
                status="planned",
                reason="BI report data endpoints will be fetched during execution",
                source_keys=args.bi_report_source_keys,
            )
        bundles = {}
        for asin in asins:
            bundles[asin] = self.collector.bi_report_data_client.fetch(
                asins=[asin],
                start_date=args.sales_start,
                end_date=args.sales_end,
                source_keys=args.bi_report_source_keys,
            )
        return self.collector._merge_per_asin_bi_report_data(bundles, asins=asins)

    def _run_basic_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths, command_log: Any, error_log: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in records:
            asin = record["asin"]
            asin_dir = paths.output_root / "asins" / asin
            asin_dir.mkdir(parents=True, exist_ok=True)
            if args.skip_amazon:
                compact = {"status": "skipped", "reason": "amazon skipped"}
            else:
                raw = self.runner.run_or_plan(
                    source="amazon.scrape",
                    command=[args.opscli_bin, "amazon", "scrape", "--asin", asin],
                    dry_run=args.dry_run,
                    command_log=command_log,
                    error_log=error_log,
                    asin=asin,
                    raw_output_path=asin_dir / "amazon-scrape.json",
                )
                compact = self.legacy.compact_amazon_result(raw)
            rows.append({"asin": asin, "site": record.get("site"), "amazon_scrape": compact})
        return rows

    def _run_keyword_reverse_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths, command_log: Any, error_log: Any) -> list[dict[str, Any]]:
        rows = []
        for record in records:
            asin = record["asin"]
            site = record["site"]
            asin_dir = paths.output_root / "asins" / asin
            seller_dir = paths.output_root / "seller-sprite" / asin
            asin_dir.mkdir(parents=True, exist_ok=True)
            seller_dir.mkdir(parents=True, exist_ok=True)
            if args.skip_seller_sprite:
                raw = {"status": "skipped", "reason": "seller sprite skipped"}
            else:
                raw = self.runner.run_or_plan(
                    source="seller_sprite.keyword_reverse",
                    command=[
                        args.opscli_bin,
                        "seller-sprite",
                        "run",
                        "keyword-reverse",
                        "--site",
                        site,
                        "--period",
                        args.seller_sprite_period,
                        "--params",
                        json.dumps({"asin": asin}, ensure_ascii=False),
                        "--page-size",
                        str(args.seller_sprite_page_size),
                        "--export-format",
                        self.legacy.KEYWORD_SELLER_SPRITE_EXPORT_FORMAT,
                        "--output-dir",
                        str(seller_dir),
                    ],
                    dry_run=args.dry_run,
                    command_log=command_log,
                    error_log=error_log,
                    asin=asin,
                    raw_output_path=asin_dir / "seller-sprite-keyword-reverse.json",
                )
            rows.append(
                {
                    "asin": asin,
                    "site": site,
                    "keyword_reverse": self.legacy.compact_seller_sprite_result(
                        raw,
                        inline_rows=self.legacy.KEYWORD_SELLER_SPRITE_INLINE_ROWS,
                    ),
                    "raw_result": raw,
                }
            )
        return rows

    def _run_keyword_miner_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths, command_log: Any, error_log: Any) -> list[dict[str, Any]]:
        reverse_by_asin = self._read_jsonl_by_asin(paths.path_for(STAGE_SELLER_KEYWORD_REVERSE))
        rows = []
        for record in records:
            asin = record["asin"]
            site = record["site"]
            record_keywords = self.legacy.normalize_keywords(record.get("keywords") or record.get("keyword") or "")
            keywords = list(record_keywords)
            reverse_raw = reverse_by_asin.get(asin, {}).get("raw_result")
            if not keywords and args.keyword_source == "reverse_top":
                keywords = self._derive_keywords_from_stage_reverse(reverse_by_asin.get(asin), max_count=args.max_miner_keywords)
            asin_dir = paths.output_root / "asins" / asin
            seller_dir = paths.output_root / "seller-sprite" / asin
            asin_dir.mkdir(parents=True, exist_ok=True)
            seller_dir.mkdir(parents=True, exist_ok=True)

            if args.skip_seller_sprite or args.skip_keyword_miner:
                compact = {"status": "skipped", "reason": "keyword miner skipped"}
            elif not keywords or args.keyword_source == "skip":
                compact = {"status": "skipped", "reason": "keyword is missing"}
            else:
                jobs = []
                seed_keywords = keywords[: max(args.max_miner_keywords, 1)]
                for seed in seed_keywords:
                    raw = self.runner.run_or_plan(
                        source="seller_sprite.keyword_miner",
                        command=[
                            args.opscli_bin,
                            "seller-sprite",
                            "run",
                            "keyword-miner",
                            "--site",
                            site,
                            "--period",
                            args.seller_sprite_period,
                            "--params",
                            json.dumps({"keyword": seed}, ensure_ascii=False),
                            "--page-size",
                            str(args.seller_sprite_page_size),
                            "--export-format",
                            self.legacy.KEYWORD_SELLER_SPRITE_EXPORT_FORMAT,
                            "--output-dir",
                            str(seller_dir),
                        ],
                        dry_run=args.dry_run,
                        command_log=command_log,
                        error_log=error_log,
                        asin=asin,
                        raw_output_path=asin_dir / f"seller-sprite-keyword-miner-{self.legacy.safe_name(seed)}.json",
                    )
                    jobs.append(raw)
                compact = {
                    "status": self.legacy.aggregate_status(jobs),
                    "seed_keywords": seed_keywords,
                    "jobs": [
                        self.legacy.compact_seller_sprite_result(
                            job,
                            inline_rows=self.legacy.KEYWORD_SELLER_SPRITE_INLINE_ROWS,
                        )
                        for job in jobs
                    ],
                }
            input_payload = {
                "keyword": keywords[0] if keywords else (record_keywords[0] if record_keywords else ""),
                "keywords": keywords or record_keywords,
                "keyword_count": len(keywords or record_keywords),
                "keyword_source": "input" if record_keywords else ("reverse_top" if keywords and reverse_raw else ""),
            }
            rows.append({"asin": asin, "site": site, "input": input_payload, "keyword_miner": compact})
        return rows

    def _run_listing_analysis_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths, command_log: Any, error_log: Any) -> list[dict[str, Any]]:
        rows = []
        for record in records:
            asin = record["asin"]
            site = record["site"]
            asin_dir = paths.output_root / "asins" / asin
            seller_dir = paths.output_root / "seller-sprite" / asin
            asin_dir.mkdir(parents=True, exist_ok=True)
            seller_dir.mkdir(parents=True, exist_ok=True)
            if args.skip_seller_sprite:
                compact = self.legacy.compact_listing_analysis_result({"status": "skipped", "reason": "seller sprite skipped"})
            elif args.skip_listing_analysis:
                compact = {"status": "skipped", "reason": "listing analysis skipped", "content": None}
            else:
                listing_params: dict[str, Any] = {"asin": asin, "station": args.listing_analysis_station}
                if args.listing_analysis_poll_attempts is not None:
                    listing_params["pollAttempts"] = args.listing_analysis_poll_attempts
                if args.listing_analysis_poll_interval_seconds is not None:
                    listing_params["pollIntervalSeconds"] = args.listing_analysis_poll_interval_seconds
                raw = self.runner.run_or_plan(
                    source="seller_sprite.listing_analysis",
                    command=[
                        args.opscli_bin,
                        "seller-sprite",
                        "run",
                        "listing-analysis",
                        "--site",
                        site,
                        "--period",
                        args.seller_sprite_period,
                        "--params",
                        json.dumps(listing_params, ensure_ascii=False),
                        "--page-size",
                        str(args.seller_sprite_page_size),
                        "--export-format",
                        "json",
                        "--output-dir",
                        str(seller_dir),
                    ],
                    dry_run=args.dry_run,
                    command_log=command_log,
                    error_log=error_log,
                    asin=asin,
                    raw_output_path=asin_dir / "seller-sprite-listing-analysis.json",
                )
                compact = self.legacy.compact_listing_analysis_result(raw)
            rows.append({"asin": asin, "site": site, "listing_analysis": compact})
        return rows

    def _run_rufus_stage(self, args: Any, records: list[dict[str, Any]], paths: DailyStagePaths) -> dict[str, Any]:
        asins = [record["asin"] for record in records]
        country = str(args.rufus_country or (records[0].get("site") if records else "US") or "US").strip().upper()
        question_templates = self._rufus_question_templates(args)
        if args.skip_rufus or args.dry_run:
            results = [
                {
                    "asin": record["asin"],
                    "status": "planned" if args.dry_run else "skipped",
                    "reason": "rufus planned by --dry-run" if args.dry_run else "rufus skipped",
                    "report_path": None,
                }
                for record in records
            ]
            batch_summary = {
                "success": True,
                "command": "amazon-rufus batch-get-backend",
                "data": {
                    "country": country,
                    "asin_count": len(asins),
                    "question_count": len(question_templates),
                    "results": results,
                },
                "error": None,
            }
        else:
            batch_summary = self.rufus_batch_runner.run(
                BatchGetBackendOptions(
                    asins=asins,
                    country=country,
                    questions=question_templates,
                    skills_dir=args.rufus_skills_dir,
                    mode=getattr(args, "rufus_batch_mode", "balanced"),
                    asin_concurrency=getattr(args, "rufus_asin_concurrency", None),
                    question_parallel=args.rufus_parallel if args.rufus_parallel else None,
                    question_concurrency=args.rufus_concurrency,
                    timeout_seconds=args.rufus_timeout_seconds,
                    retry=args.rufus_retry,
                    strict_answer=True if args.rufus_strict_answer else True,
                    resume=getattr(args, "rufus_resume", True),
                    fallback_serial=True,
                    validate_report=True,
                    output_dir=paths.output_root / "rufus",
                )
            )
        compact_results = []
        batch_results = (((batch_summary.get("data") or {}).get("results")) if isinstance(batch_summary, dict) else []) or []
        by_asin = {
            str(item.get("asin") or "").strip().upper(): item
            for item in batch_results
            if isinstance(item, dict)
        }
        for record in records:
            asin = record["asin"]
            site = record["site"]
            item = by_asin.get(asin, {})
            compact_results.append(
                self._compact_batch_rufus_result(
                    item,
                    asin=asin,
                    country=str(args.rufus_country or site or country).strip().upper(),
                    questions=[self._render_asin_placeholder(question, asin) for question in question_templates],
                )
            )
        return {
            "batch_summary": batch_summary,
            "results": compact_results,
        }

    def _base_result(self, record: dict[str, Any], query_bundle: dict[str, Any]) -> dict[str, Any]:
        asin = record["asin"]
        record_keywords = self.legacy.normalize_keywords(record.get("keywords") or record.get("keyword") or "")
        crawler_rows = self.legacy.localize_crawler_source_rows(self.legacy.rows_for_asin(query_bundle.get("crawler_listing"), asin))
        return {
            "asin": asin,
            "site": record["site"],
            "input": {
                "keyword": record_keywords[0] if record_keywords else "",
                "keywords": record_keywords,
                "keyword_count": len(record_keywords),
                "keyword_source": "input" if record_keywords else "",
                "row_index": record.get("row_index"),
                "source_file": record.get("source_file"),
            },
            "seller_sprite": {},
            "amazon": {},
            "rufus": {},
            "query": {
                "sales": self.legacy.rows_for_asin(query_bundle.get("sales"), asin),
                "crawler_listing": crawler_rows,
            },
            "errors": [],
        }

    def _collect_result_errors(self, result: dict[str, Any]) -> None:
        errors = result.setdefault("errors", [])
        for source_name in ("keyword_reverse", "keyword_miner", "listing_analysis"):
            self.legacy.collect_status_errors("seller_sprite", source_name, result["seller_sprite"].get(source_name), errors)
        self.legacy.collect_status_errors("rufus", "qa", result.get("rufus"), errors)
        self.legacy.collect_status_errors("query", "sales", result["query"].get("sales"), errors)
        self.legacy.collect_status_errors("query", "crawler_listing", result["query"].get("crawler_listing"), errors)

    def _derive_keywords_from_stage_reverse(self, row: dict[str, Any] | None, *, max_count: int) -> list[str]:
        if not isinstance(row, dict):
            return []
        raw = row.get("raw_result")
        if isinstance(raw, dict):
            keywords = self.legacy.derive_keywords_from_reverse(raw, max_count=max_count)
            if keywords:
                return keywords
        compact = row.get("keyword_reverse")
        rows = compact.get("rows") if isinstance(compact, dict) and isinstance(compact.get("rows"), list) else []
        keywords: list[str] = []
        seen: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            for key in ("keyword", "keywords", "word", "query"):
                for value in self.legacy.normalize_keywords(item.get(key)):
                    normalized = str(value).strip()
                    if normalized and normalized.lower() not in seen:
                        seen.add(normalized.lower())
                        keywords.append(normalized)
                    if len(keywords) >= max_count:
                        return keywords
        return keywords

    def _compact_batch_rufus_result(self, item: dict[str, Any], *, asin: str, country: str, questions: list[str]) -> dict[str, Any]:
        status = str(item.get("status") or "failed").strip().lower()
        report_path = item.get("report_path") if isinstance(item.get("report_path"), str) else None
        answers = self.legacy.parse_rufus_report(report_path)
        if not answers and report_path:
            answers = self._section_answers_from_markdown(report_path, questions)
        final_status = "success" if status in {"success", "skipped"} and report_path else status
        compact: dict[str, Any] = {
            "status": final_status,
            "batch_status": status,
            "asin": asin,
            "country": country,
            "questions": questions,
            "question_count": len(questions),
            "answer_count": len(answers),
            "answers": answers,
            "report_path": report_path,
            "validation": item.get("validation"),
            "attempts": item.get("attempts"),
            "duration_seconds": item.get("duration_seconds"),
        }
        if item.get("reason"):
            compact["reason"] = item.get("reason")
        if item.get("error_message"):
            compact["error_message"] = item.get("error_message")
        return compact

    def _section_answers_from_markdown(self, report_path: str, questions: list[str]) -> list[dict[str, Any]]:
        path = Path(report_path)
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:
            return []
        matches = list(re.finditer(r"(?m)^##\s+(\d+)\.\s+(.+?)\s*$", text))
        answers: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            section_index = int(match.group(1))
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            question = questions[section_index - 1] if section_index - 1 < len(questions) else match.group(2)
            answers.append(
                {
                    "index": section_index,
                    "question": question,
                    "related_products": [],
                    "answer": body,
                    "recommended_asins": [],
                    "summary": "",
                }
            )
        return answers

    def _rufus_question_templates(self, args: Any) -> list[str]:
        provided = [str(item).strip() for item in (getattr(args, "rufus_questions", None) or []) if str(item).strip()]
        if provided:
            return provided
        templates = QuestionBankService(skills_dir=args.rufus_skills_dir).load_templates()
        return [question.text for template in templates for question in template.questions if question.text]

    @staticmethod
    def _render_asin_placeholder(question: str, asin: str) -> str:
        return str(question).replace("{{asin}}", asin).replace("{asin}", asin)

    def _write_input_manifest(self, paths: DailyStagePaths, records: list[dict[str, Any]], input_errors: list[dict[str, Any]]) -> None:
        self.legacy.write_json(
            paths.stages_dir / "input-records.json",
            {
                "records": records,
                "input_errors": input_errors,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

    def _write_stage_payload(self, path: Path, payload: Any) -> None:
        if isinstance(payload, list):
            self._write_jsonl(path, payload)
        else:
            self.legacy.write_json(path, payload)

    @staticmethod
    def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _read_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    @classmethod
    def _read_jsonl_by_asin(cls, path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            asin = str(item.get("asin") or "").strip().upper()
            if asin:
                rows[asin] = item
        return rows

    @staticmethod
    def _source_or_skipped(value: Any, reason: str) -> Any:
        if isinstance(value, dict) and value:
            return value
        return {"status": "skipped", "reason": reason}

    def _rufus_by_asin(self, path: Path) -> dict[str, dict[str, Any]]:
        payload = self._read_json(path, default={})
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return {}
        return {
            str(item.get("asin") or "").strip().upper(): item
            for item in results
            if isinstance(item, dict) and str(item.get("asin") or "").strip()
        }

    def _stage_file_summary(self, paths: DailyStagePaths) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for stage in sorted(STAGES):
            path = paths.path_for(stage)
            summary[stage] = {
                "path": path.as_posix(),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
        return summary

    @staticmethod
    def _stage_status(payload: Any) -> str:
        if isinstance(payload, dict):
            if isinstance(payload.get("status"), str):
                return payload["status"]
            if isinstance(payload.get("batch_summary"), dict):
                summary = payload["batch_summary"]
                results = ((summary.get("data") or {}).get("results")) if isinstance(summary.get("data"), dict) else []
                if isinstance(results, list) and results and all(isinstance(item, dict) and item.get("status") == "planned" for item in results):
                    return "planned"
                if summary.get("success") is True:
                    return "success"
                return "failed"
        if isinstance(payload, list):
            statuses = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                for key in ("amazon_scrape", "keyword_reverse", "keyword_miner", "listing_analysis"):
                    value = item.get(key)
                    if isinstance(value, dict):
                        statuses.append(value.get("status"))
            if not statuses:
                return "success"
            if all(status == "planned" for status in statuses):
                return "planned"
            if all(status == "success" for status in statuses):
                return "success"
            if any(status == "success" for status in statuses):
                return "partial"
            if any(status == "planned" for status in statuses):
                return "partial"
            if all(status == "skipped" for status in statuses):
                return "skipped"
            return "failed"
        return "success"

    @staticmethod
    def _normalize_stage(stage: str) -> str:
        normalized = str(stage or "").strip().lower().replace("_", "-")
        aliases = {
            "seller-reverse": STAGE_SELLER_KEYWORD_REVERSE,
            "keyword-reverse": STAGE_SELLER_KEYWORD_REVERSE,
            "seller-miner": STAGE_SELLER_KEYWORD_MINER,
            "keyword-miner": STAGE_SELLER_KEYWORD_MINER,
            "listing-analysis": STAGE_SELLER_LISTING_ANALYSIS,
            "seller-listing": STAGE_SELLER_LISTING_ANALYSIS,
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in STAGES:
            raise ValueError(f"Unsupported stage: {stage}. Expected one of: {', '.join(sorted(STAGES))}")
        return normalized
