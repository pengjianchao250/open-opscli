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


class KeywordSource(str, Enum):
    input_only = "input_only"
    reverse_top = "reverse_top"
    skip = "skip"


class FieldMode(str, Enum):
    full = "full"
    compatible = "compatible"


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
    skip_sales_query: bool = typer.Option(False, "--skip-sales-query", help="跳过销售数据 query"),
    skip_crawler_query: bool = typer.Option(False, "--skip-crawler-query", help="跳过爬虫 Listing query"),
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
    upload: bool = typer.Option(True, "--upload/--no-upload", help="上传 frontend-data.json 并返回阿里云文件地址"),
    url_only: bool = typer.Option(False, "--url-only", help="只输出阿里云文件地址"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
) -> None:
    """执行 ASIN 批量取数，并输出标准前端数据文件。"""
    try:
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
            skip_sales_query=skip_sales_query,
            skip_crawler_query=skip_crawler_query,
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
            upload=upload,
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


__all__ = ["app"]
