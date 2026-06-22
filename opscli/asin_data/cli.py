"""ASIN batch data collection CLI."""

from __future__ import annotations

import json
from enum import Enum

import typer

from opscli.asin_data.services.collector import (
    DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS,
    DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS,
    AsinDataCollector,
)
from opscli.asin_data.services.daily_pipeline import DailyAsinDataPipeline
from opscli.asin_data.services.report_file_submitter import (
    DEFAULT_REPORT_TYPE,
    DEFAULT_SOURCE,
    AsinReportFileSubmitter,
)
from opscli.asin_data.services.report_files import AsinReportFileClient, AsinReportFileNotFoundError


class KeywordSource(str, Enum):
    input_only = "input_only"
    reverse_top = "reverse_top"
    skip = "skip"


class FieldMode(str, Enum):
    full = "full"
    compatible = "compatible"


class DailyStage(str, Enum):
    query = "query"
    bi = "bi"
    basic = "basic"
    seller_keyword_reverse = "seller-keyword-reverse"
    seller_keyword_miner = "seller-keyword-miner"
    seller_listing_analysis = "seller-listing-analysis"
    rufus = "rufus"


class RufusBatchMode(str, Enum):
    fast = "fast"
    balanced = "balanced"
    safe = "safe"


app = typer.Typer(help="ASIN 批量取数服务")


@app.callback()
def main() -> None:
    """ASIN 批量取数命令组入口。"""


def _emit(payload: dict, pretty: bool) -> None:
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _error_payload(command: str, exc: Exception) -> dict:
    if hasattr(exc, "to_dict"):
        error = exc.to_dict()  # type: ignore[call-arg]
    else:
        error = {"code": "ASIN_DATA_ERROR", "message": str(exc)}
    return {"success": False, "command": command, "data": None, "error": error}


@app.command("report-url")
def report_url(
    asin: str = typer.Option(..., "--asin", help="ASIN"),
    site: str = typer.Option("US", "--site", help="站点"),
    url_only: bool = typer.Option(False, "--url-only", help="只输出报告文件地址"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
) -> None:
    """只查询 ASIN 报告文件接口并返回报告地址。"""
    normalized_asin = asin.strip().upper()
    normalized_site = site.strip().upper()
    try:
        report_file = AsinReportFileClient().fetch(asin=normalized_asin, site=normalized_site)
        if not report_file.url:
            raise AsinReportFileNotFoundError(asin=normalized_asin, site=normalized_site)
    except Exception as exc:
        _emit(_error_payload("asin-data report-url", exc), pretty)
        raise typer.Exit(1)

    if url_only:
        typer.echo(report_file.url)
        return

    _emit(
        {
            "success": True,
            "command": "asin-data report-url",
            "data": {
                "asin": report_file.asin,
                "site": report_file.site,
                "report_file_url": report_file.url,
                "record": report_file.record,
                "raw": report_file.raw,
            },
            "error": None,
        },
        pretty,
    )


@app.command("collect")
def collect(
    input_path: str | None = typer.Option(None, "--input", "-i", help="CSV/XLSX/JSON/JSONL 输入文件"),
    asin: str | None = typer.Option(None, "--asin", help="单个 ASIN；与 --input 二选一"),
    keywords: list[str] | None = typer.Option(None, "--keyword", help="单个 ASIN 的关键词，可重复传入"),
    asin_column: str = typer.Option("asin", "--asin-column", help="ASIN 列名"),
    keyword_column: str = typer.Option("keyword", "--keyword-column", help="关键词列名"),
    site_column: str = typer.Option("site", "--site-column", help="站点列名"),
    site: str = typer.Option("US", "--site", help="默认站点"),
    output_dir: str = typer.Option("output/asin-data", "--output-dir", help="输出目录"),
    run_id: str | None = typer.Option(None, "--run-id", help="本次运行 ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只生成计划与前端文件，不执行远程取数"),
    skip_seller_sprite: bool = typer.Option(False, "--skip-seller-sprite", help="跳过卖家精灵数据"),
    skip_keyword_miner: bool = typer.Option(False, "--skip-keyword-miner", help="跳过关键词挖掘"),
    skip_listing_analysis: bool = typer.Option(False, "--skip-listing-analysis", help="跳过卖家精灵 AI 全景分析"),
    skip_amazon: bool = typer.Option(False, "--skip-amazon", help="跳过 Amazon 页面抓取"),
    skip_query: bool = typer.Option(False, "--skip-query", help="跳过 BI query 取数"),
    skip_bi_report_data: bool = typer.Option(False, "--skip-bi-report-data", help="跳过 ASIN 报告 BI 接口取数"),
    skip_sales_query: bool = typer.Option(False, "--skip-sales-query", help="跳过销售数据 query"),
    skip_crawler_query: bool = typer.Option(False, "--skip-crawler-query", help="跳过旧爬虫 Listing query；默认已跳过，爬虫详情改走 crawler-details 接口"),
    legacy_crawler_query: bool = typer.Option(False, "--legacy-crawler-query", help="兼容旧逻辑：启用旧爬虫 Listing query"),
    skip_rufus: bool = typer.Option(False, "--skip-rufus", help="跳过 Rufus 优化建议"),
    seller_sprite_period: str = typer.Option("30d", "--seller-sprite-period", help="卖家精灵周期"),
    seller_sprite_page_size: int = typer.Option(100, "--seller-sprite-page-size", min=1, help="卖家精灵分页大小"),
    keyword_source: KeywordSource = typer.Option(KeywordSource.reverse_top, "--keyword-source", help="关键词来源策略"),
    max_miner_keywords: int = typer.Option(1, "--max-miner-keywords", min=1, help="最多挖掘关键词数量"),
    listing_analysis_station: str = typer.Option("GLOBAL", "--listing-analysis-station", help="AI 全景分析站点参数"),
    listing_analysis_poll_attempts: int | None = typer.Option(
        DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS,
        "--listing-analysis-poll-attempts",
        min=1,
        help="AI 全景分析轮询次数",
    ),
    listing_analysis_poll_interval_seconds: float | None = typer.Option(
        DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS,
        "--listing-analysis-poll-interval-seconds",
        min=0,
        help="AI 全景分析轮询间隔秒数",
    ),
    rufus_country: str | None = typer.Option(None, "--rufus-country", help="覆盖 Rufus 国家站点；默认跟随输入站点"),
    rufus_questions: list[str] | None = typer.Option(
        None,
        "--rufus-question",
        help="Rufus 问题，可重复传入；支持 {{asin}} 占位符",
    ),
    rufus_skills_dir: str = typer.Option(".agents/skills", "--rufus-skills-dir", help="Rufus Skill 根目录"),
    rufus_timeout_seconds: int = typer.Option(180, "--rufus-timeout-seconds", min=1, help="Rufus 单题超时秒数"),
    rufus_login_timeout_seconds: int = typer.Option(180, "--rufus-login-timeout-seconds", min=1, help="Rufus 登录恢复超时秒数"),
    rufus_parallel: bool = typer.Option(False, "--rufus-parallel", help="Rufus 多题并发获取"),
    rufus_concurrency: int = typer.Option(3, "--rufus-concurrency", min=1, help="Rufus 并发数，仅 --rufus-parallel 生效"),
    rufus_retry: int = typer.Option(0, "--rufus-retry", min=0, help="Rufus 单题无效回答重试次数"),
    rufus_strict_answer: bool = typer.Option(False, "--rufus-strict-answer", help="Rufus 无效回答重试后仍失败时中止"),
    skip_rufus_login_recovery: bool = typer.Option(False, "--skip-rufus-login-recovery", help="登录态不可用时不自动恢复"),
    sales_table_id: int | None = typer.Option(None, "--sales-table-id", help="BI 销售数据 table_id"),
    sales_dataset_alias: str = typer.Option("ds_d35ac6f3910c", "--sales-dataset-alias", help="BI 销售数据 dataset alias"),
    sales_field_mode: FieldMode = typer.Option(FieldMode.full, "--sales-field-mode", help="销售字段模式"),
    sales_start: str | None = typer.Option(None, "--sales-start", help="销售开始日期"),
    sales_end: str | None = typer.Option(None, "--sales-end", help="销售结束日期"),
    query_chunk_size: int = typer.Option(100, "--query-chunk-size", min=1, help="query 每批 ASIN 数量"),
    crawler_table_id: int | None = typer.Option(None, "--crawler-table-id", help="爬虫 Listing table_id"),
    crawler_dataset_alias: str = typer.Option("ds_icw50TLOFu4F", "--crawler-dataset-alias", help="爬虫 Listing dataset alias"),
    crawler_field_mode: FieldMode = typer.Option(FieldMode.full, "--crawler-field-mode", help="爬虫 Listing 字段模式"),
    fetch_report_files: bool = typer.Option(
        True,
        "--fetch-report-files/--no-fetch-report-files",
        help="从 ASIN 报告文件接口获取报告地址",
    ),
    upload: bool = typer.Option(True, "--upload/--no-upload", help="上传 ASIN 拆分数据包 zip 并返回阿里云文件地址"),
    submit_report_files: bool = typer.Option(False, "--submit-report-files/--no-submit-report-files", help="采集完成后提交报告文件记录到 /dataMetrics/v1/asin-report-files"),
    report_date: str | None = typer.Option(None, "--report-date", help="报告日期，默认当天"),
    report_type: str = typer.Option(DEFAULT_REPORT_TYPE, "--report-type", help="报告类型"),
    report_source: str = typer.Option(DEFAULT_SOURCE, "--report-source", help="报告记录来源"),
    register_endpoint: str | None = typer.Option(None, "--register-endpoint", help="报告文件保存接口地址"),
    include_report_content: bool = typer.Option(False, "--include-report-content/--no-include-report-content", help="提交时是否包含报告 txt 内容和明细 JSON"),
    url_only: bool = typer.Option(False, "--url-only", help="只输出报告文件地址"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
) -> None:
    """执行 ASIN 批量取数，并输出标准前端数据文件。"""
    try:
        effective_fetch_report_files = False if submit_report_files else fetch_report_files
        result = AsinDataCollector().collect(
            input=input_path,
            asin=asin,
            keywords=keywords,
            asin_column=asin_column,
            keyword_column=keyword_column,
            site_column=site_column,
            site=site,
            output_dir=output_dir,
            run_id=run_id,
            dry_run=dry_run,
            skip_seller_sprite=skip_seller_sprite,
            skip_keyword_miner=skip_keyword_miner,
            skip_listing_analysis=skip_listing_analysis,
            skip_amazon=skip_amazon,
            skip_query=skip_query,
            skip_bi_report_data=skip_bi_report_data,
            skip_sales_query=skip_sales_query,
            skip_crawler_query=(skip_crawler_query or not legacy_crawler_query),
            skip_rufus=skip_rufus,
            seller_sprite_period=seller_sprite_period,
            seller_sprite_page_size=seller_sprite_page_size,
            keyword_source=keyword_source.value,
            max_miner_keywords=max_miner_keywords,
            listing_analysis_station=listing_analysis_station,
            listing_analysis_poll_attempts=listing_analysis_poll_attempts,
            listing_analysis_poll_interval_seconds=listing_analysis_poll_interval_seconds,
            rufus_country=rufus_country,
            rufus_questions=rufus_questions,
            rufus_skills_dir=rufus_skills_dir,
            rufus_timeout_seconds=rufus_timeout_seconds,
            rufus_login_timeout_seconds=rufus_login_timeout_seconds,
            rufus_parallel=rufus_parallel,
            rufus_concurrency=rufus_concurrency,
            rufus_retry=rufus_retry,
            rufus_strict_answer=rufus_strict_answer,
            skip_rufus_login_recovery=skip_rufus_login_recovery,
            sales_table_id=sales_table_id,
            sales_dataset_alias=sales_dataset_alias,
            sales_field_mode=sales_field_mode.value,
            sales_start=sales_start,
            sales_end=sales_end,
            query_chunk_size=query_chunk_size,
            crawler_table_id=crawler_table_id,
            crawler_dataset_alias=crawler_dataset_alias,
            crawler_field_mode=crawler_field_mode.value,
            fetch_report_files=effective_fetch_report_files,
            upload=upload,
        )
        if submit_report_files:
            if dry_run:
                result["report_file_submit"] = {
                    "submitted": False,
                    "reason": "dry_run",
                }
            else:
                client = AsinReportFileClient(endpoint=register_endpoint) if register_endpoint else AsinReportFileClient()
                result["report_file_submit"] = AsinReportFileSubmitter(client=client).submit(
                    result,
                    report_date=report_date,
                    report_type=report_type,
                    source=report_source,
                    include_content=include_report_content,
                )
    except Exception as exc:
        _emit(_error_payload("asin-data collect", exc), pretty)
        raise typer.Exit(1)

    if url_only:
        url = result.get("aliyun_url")
        if not url:
            _emit(_error_payload("asin-data collect", ValueError("No Aliyun file URL returned. Use --upload or check upload configuration.")), pretty)
            raise typer.Exit(1)
        typer.echo(url)
        return

    _emit({"success": True, "command": "asin-data collect", "data": result, "error": None}, pretty)


def _daily_pipeline_kwargs(
    *,
    input_path: str | None,
    asin: str | None,
    keywords: list[str] | None,
    asin_column: str,
    keyword_column: str,
    site_column: str,
    site: str,
    output_dir: str,
    run_id: str | None,
    dry_run: bool,
    sales_start: str | None,
    sales_end: str | None,
    seller_sprite_period: str,
    seller_sprite_page_size: int,
    keyword_source: KeywordSource,
    max_miner_keywords: int,
    listing_analysis_station: str,
    rufus_country: str | None,
    rufus_questions: list[str] | None,
    rufus_skills_dir: str,
    rufus_batch_mode: RufusBatchMode,
    rufus_asin_concurrency: int | None,
    rufus_timeout_seconds: int,
    rufus_concurrency: int,
    rufus_retry: int,
    rufus_resume: bool,
    legacy_crawler_query: bool,
    upload: bool,
    fetch_report_files: bool,
) -> dict:
    return {
        "input": input_path,
        "asin": asin,
        "keywords": keywords,
        "asin_column": asin_column,
        "keyword_column": keyword_column,
        "site_column": site_column,
        "site": site,
        "output_dir": output_dir,
        "run_id": run_id,
        "dry_run": dry_run,
        "seller_sprite_period": seller_sprite_period,
        "seller_sprite_page_size": seller_sprite_page_size,
        "keyword_source": keyword_source.value,
        "max_miner_keywords": max_miner_keywords,
        "listing_analysis_station": listing_analysis_station,
        "rufus_country": rufus_country,
        "rufus_questions": rufus_questions,
        "rufus_skills_dir": rufus_skills_dir,
        "rufus_batch_mode": rufus_batch_mode.value,
        "rufus_asin_concurrency": rufus_asin_concurrency,
        "rufus_timeout_seconds": rufus_timeout_seconds,
        "rufus_parallel": False,
        "rufus_concurrency": rufus_concurrency,
        "rufus_retry": rufus_retry,
        "rufus_strict_answer": True,
        "rufus_resume": rufus_resume,
        "sales_start": sales_start,
        "sales_end": sales_end,
        "skip_crawler_query": not legacy_crawler_query,
        "fetch_report_files": fetch_report_files,
        "upload": upload,
    }


@app.command("stage-collect")
def stage_collect(
    stage: DailyStage = typer.Option(..., "--stage", help="Daily stage to run"),
    input_path: str | None = typer.Option(None, "--input", "-i", help="CSV/XLSX/JSON/JSONL input file"),
    asin: str | None = typer.Option(None, "--asin", help="Single ASIN; mutually exclusive with --input"),
    keywords: list[str] | None = typer.Option(None, "--keyword", help="Keyword for single ASIN; repeatable"),
    asin_column: str = typer.Option("asin", "--asin-column"),
    keyword_column: str = typer.Option("keyword", "--keyword-column"),
    site_column: str = typer.Option("site", "--site-column"),
    site: str = typer.Option("US", "--site"),
    output_dir: str = typer.Option("output/asin-data", "--output-dir"),
    run_id: str | None = typer.Option(None, "--run-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    sales_start: str | None = typer.Option(None, "--sales-start"),
    sales_end: str | None = typer.Option(None, "--sales-end"),
    seller_sprite_period: str = typer.Option("30d", "--seller-sprite-period"),
    seller_sprite_page_size: int = typer.Option(100, "--seller-sprite-page-size", min=1),
    keyword_source: KeywordSource = typer.Option(KeywordSource.reverse_top, "--keyword-source"),
    max_miner_keywords: int = typer.Option(1, "--max-miner-keywords", min=1),
    listing_analysis_station: str = typer.Option("GLOBAL", "--listing-analysis-station"),
    rufus_country: str | None = typer.Option(None, "--rufus-country"),
    rufus_questions: list[str] | None = typer.Option(None, "--rufus-question"),
    rufus_skills_dir: str = typer.Option(".agents/skills", "--rufus-skills-dir"),
    rufus_batch_mode: RufusBatchMode = typer.Option(RufusBatchMode.balanced, "--rufus-batch-mode"),
    rufus_asin_concurrency: int | None = typer.Option(2, "--rufus-asin-concurrency", min=1),
    rufus_timeout_seconds: int = typer.Option(240, "--rufus-timeout-seconds", min=1),
    rufus_concurrency: int = typer.Option(2, "--rufus-concurrency", min=1),
    rufus_retry: int = typer.Option(1, "--rufus-retry", min=0),
    rufus_resume: bool = typer.Option(True, "--rufus-resume/--no-rufus-resume"),
    legacy_crawler_query: bool = typer.Option(False, "--legacy-crawler-query"),
    pretty: bool = typer.Option(False, "--pretty"),
) -> None:
    """Run one stage and write it under output/asin-data/<run-id>/stages."""
    try:
        result = DailyAsinDataPipeline().run_stage(
            stage.value,
            **_daily_pipeline_kwargs(
                input_path=input_path,
                asin=asin,
                keywords=keywords,
                asin_column=asin_column,
                keyword_column=keyword_column,
                site_column=site_column,
                site=site,
                output_dir=output_dir,
                run_id=run_id,
                dry_run=dry_run,
                sales_start=sales_start,
                sales_end=sales_end,
                seller_sprite_period=seller_sprite_period,
                seller_sprite_page_size=seller_sprite_page_size,
                keyword_source=keyword_source,
                max_miner_keywords=max_miner_keywords,
                listing_analysis_station=listing_analysis_station,
                rufus_country=rufus_country,
                rufus_questions=rufus_questions,
                rufus_skills_dir=rufus_skills_dir,
                rufus_batch_mode=rufus_batch_mode,
                rufus_asin_concurrency=rufus_asin_concurrency,
                rufus_timeout_seconds=rufus_timeout_seconds,
                rufus_concurrency=rufus_concurrency,
                rufus_retry=rufus_retry,
                rufus_resume=rufus_resume,
                legacy_crawler_query=legacy_crawler_query,
                upload=False,
                fetch_report_files=False,
            ),
        )
    except Exception as exc:
        _emit(_error_payload("asin-data stage-collect", exc), pretty)
        raise typer.Exit(1)
    _emit(result, pretty)


@app.command("merge-stages")
def merge_stages(
    input_path: str | None = typer.Option(None, "--input", "-i", help="CSV/XLSX/JSON/JSONL input file"),
    asin: str | None = typer.Option(None, "--asin", help="Single ASIN; mutually exclusive with --input"),
    keywords: list[str] | None = typer.Option(None, "--keyword", help="Keyword for single ASIN; repeatable"),
    asin_column: str = typer.Option("asin", "--asin-column"),
    keyword_column: str = typer.Option("keyword", "--keyword-column"),
    site_column: str = typer.Option("site", "--site-column"),
    site: str = typer.Option("US", "--site"),
    output_dir: str = typer.Option("output/asin-data", "--output-dir"),
    run_id: str = typer.Option(..., "--run-id"),
    upload: bool = typer.Option(True, "--upload/--no-upload"),
    fetch_report_files: bool = typer.Option(False, "--fetch-report-files/--no-fetch-report-files"),
    url_only: bool = typer.Option(False, "--url-only"),
    pretty: bool = typer.Option(False, "--pretty"),
) -> None:
    """Merge cached stages, build frontend files, split package, and optional upload."""
    try:
        result = DailyAsinDataPipeline().merge(
            input=input_path,
            asin=asin,
            keywords=keywords,
            asin_column=asin_column,
            keyword_column=keyword_column,
            site_column=site_column,
            site=site,
            output_dir=output_dir,
            run_id=run_id,
            upload=upload,
            fetch_report_files=fetch_report_files,
        )
    except Exception as exc:
        _emit(_error_payload("asin-data merge-stages", exc), pretty)
        raise typer.Exit(1)

    if url_only:
        url = result.get("aliyun_url")
        if not url:
            _emit(_error_payload("asin-data merge-stages", ValueError("No Aliyun file URL returned. Use --upload or check upload configuration.")), pretty)
            raise typer.Exit(1)
        typer.echo(url)
        return
    _emit({"success": True, "command": "asin-data merge-stages", "data": result, "error": None}, pretty)


@app.command("daily-collect")
def daily_collect(
    input_path: str | None = typer.Option(None, "--input", "-i", help="CSV/XLSX/JSON/JSONL input file"),
    asin: str | None = typer.Option(None, "--asin", help="Single ASIN; mutually exclusive with --input"),
    keywords: list[str] | None = typer.Option(None, "--keyword", help="Keyword for single ASIN; repeatable"),
    asin_column: str = typer.Option("asin", "--asin-column"),
    keyword_column: str = typer.Option("keyword", "--keyword-column"),
    site_column: str = typer.Option("site", "--site-column"),
    site: str = typer.Option("US", "--site"),
    output_dir: str = typer.Option("output/asin-data", "--output-dir"),
    run_id: str | None = typer.Option(None, "--run-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    sales_start: str | None = typer.Option(None, "--sales-start"),
    sales_end: str | None = typer.Option(None, "--sales-end"),
    upload: bool = typer.Option(True, "--upload/--no-upload"),
    pretty: bool = typer.Option(False, "--pretty"),
) -> None:
    """Run all daily stages in a conservative sequence, then merge."""
    try:
        result = DailyAsinDataPipeline().run_all(
            input=input_path,
            asin=asin,
            keywords=keywords,
            asin_column=asin_column,
            keyword_column=keyword_column,
            site_column=site_column,
            site=site,
            output_dir=output_dir,
            run_id=run_id,
            dry_run=dry_run,
            sales_start=sales_start,
            sales_end=sales_end,
            rufus_batch_mode="balanced",
            rufus_asin_concurrency=2,
            rufus_timeout_seconds=240,
            rufus_concurrency=2,
            rufus_retry=1,
            rufus_strict_answer=True,
            rufus_resume=True,
            upload=upload,
            fetch_report_files=False,
        )
    except Exception as exc:
        _emit(_error_payload("asin-data daily-collect", exc), pretty)
        raise typer.Exit(1)
    _emit({"success": True, "command": "asin-data daily-collect", "data": result, "error": None}, pretty)


__all__ = ["app"]
