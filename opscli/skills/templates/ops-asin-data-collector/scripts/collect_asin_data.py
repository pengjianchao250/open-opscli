#!/usr/bin/env python3
"""Collect batch ASIN data through official opscli commands."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_asin_input import load_asin_records, normalize_keywords


DEFAULT_SALES_ALIAS = "ds_d35ac6f3910c"
DEFAULT_CRAWLER_ALIAS = "ds_icw50TLOFu4F"
KEYWORD_SELLER_SPRITE_EXPORT_FORMAT = "xlsx"
KEYWORD_SELLER_SPRITE_INLINE_ROWS = False
DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS = 180
DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS = 2.0
CRAWLER_DATE_FIELDS = ("f_date_id", "date_id")
DEFAULT_RUFUS_QUESTIONS = (
    "标题清晰度：分析 ASIN {{asin}} 的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按：标题｜问题｜依据｜建议改为 输出。",
    "五点优化方向：分析 ASIN {{asin}} 的五点卖点，从消费者决策路径与商品信息表达优化的角度，对该商品进行系统分析。按：五点｜问题｜依据｜建议改为 输出。",
    "图片优化方向：分析 ASIN {{asin}} 的图片是否解决买家购买疑问，从消费者决策路径与商品信息表达优化的角度。按：图片｜问题｜依据｜每张图建议改为 输出。",
    "A+优化方向：分析 ASIN {{asin}} 的 A+ 是否补充了关键信息、增强购买信任。按：A+｜问题｜依据｜每张图建议改为 输出。",
    "评论/星级优化方向：分析 ASIN {{asin}} 的评论中买家最常夸和最常抱怨的点，判断页面是否提前说明。按：评论｜问题｜依据｜建议改为 输出。",
    "整体优化：从标题、五点、图片、A+、评论中，找出 ASIN {{asin}} 最优先修改的一处。按：整体｜问题｜依据｜建议改为 输出。",
)
RUFUS_REPORT_PATH_PATTERN = re.compile(r"Rufus 答案报告已保存：\s*(.+?\.md)")
STATUS_ZH = {
    "success": "成功",
    "skipped": "跳过",
    "failed": "失败",
    "partial": "部分成功",
    "planned": "计划中",
}
KEYWORD_SOURCE_ZH = {
    "input": "输入文件",
    "reverse_top": "卖家精灵关键词反查Top词",
    "skip": "跳过派生",
    "": "未提供",
}
SALES_FIELD_LABELS = {
    "channel_uuid": "渠道UUID",
    "listing_uuid": "Listing UUID",
    "date_id": "日期",
    "dept_id": "部门ID",
    "channel_id": "渠道ID",
    "sell_sku": "销售SKU",
    "dept_name": "部门名称",
    "channel_name": "渠道名称",
    "aukey_account_id": "Aukey账号ID",
    "aukey_account_name": "Aukey账号名称",
    "country_name": "国家",
    "platform_name": "平台",
    "large_team_name": "大团队",
    "team_name": "团队",
    "team_username": "团队负责人",
    "dev_team_name": "开发团队",
    "develop_username": "开发负责人",
    "pmc_code": "PMC编码",
    "upc": "UPC",
    "spu": "SPU",
    "model": "型号",
    "brand_name": "品牌",
    "amazon_cat": "Amazon类目",
    "self_cat": "自定义类目",
    "url": "链接",
    "image_url": "图片链接",
    "rate": "汇率",
    "category": "产品类目",
    "level_name": "等级",
    "product_name": "产品名称",
    "parent_asin": "父ASIN",
    "asin": "ASIN",
    "ed_sku": "ED SKU",
    "platform_name_lower": "平台小写",
    "channel_name_lower": "渠道名称小写",
    "large_team_name_lower": "大团队小写",
    "team_name_lower": "团队小写",
    "dev_team_name_lower": "开发团队小写",
    "asin_lower": "ASIN小写",
    "ed_sku_lower": "ED SKU小写",
    "sell_sku_lower": "销售SKU小写",
    "product_name_lower": "产品名称小写",
    "model_lower": "型号小写",
    "category_lower": "产品类目小写",
    "spu_lower": "SPU小写",
    "brand_name_lower": "品牌小写",
    "amazon_cat_lower": "Amazon类目小写",
    "development_type": "开发类型",
    "sku_type": "SKU类型",
    "pmc_type": "PMC类型",
    "parent_ed_sku": "父ED SKU",
    "style_name": "款式名称",
    "protection_level": "保护等级",
    "star": "星级",
    "reviews_qty": "评论数",
    "sold_days": "售卖天数",
    "platform_qty": "平台库存",
    "total_qty": "总库存",
    "sell_qty_days": "可售天数",
    "orders": "订单量",
    "order_qty": "销量",
    "order_qty_ds": "DS销量",
    "order_qty_dp": "DP销量",
    "sessions": "流量",
    "page_views": "浏览量",
    "convert_percent": "转化率",
    "original_price": "原价销售额",
    "price": "销售额",
    "price_ds": "DS销售额",
    "price_dp": "DP销售额",
    "refund": "退款金额",
    "refund_qty": "退款数量",
    "compensate": "赔偿金额",
    "fee": "平台费用",
    "freight": "运费",
    "freight_ds": "DS运费",
    "freight_dp": "DP运费",
    "freight_inbound_fee": "入库运费",
    "storage_charges": "仓储费",
    "storage_charges_os": "海外仓仓储费",
    "storage_charges_plat": "平台仓储费",
    "storage_charges_plat_lt": "平台长期仓储费",
    "storage_charges_plat_ov": "平台超量仓储费",
    "storage_charges_disposed_fee": "仓储销毁费",
    "storage_charges_return_fee": "仓储退件费",
    "storage_charges_disposed_qty": "仓储销毁数量",
    "storage_charges_return_qty": "仓储退件数量",
    "lightning_deals": "秒杀费",
    "coupons_fee": "优惠券费用",
    "deals_fee": "Deals费用",
    "advertising_fee": "广告费",
    "ads_sales_cny": "广告销售额(CNY)",
    "ads_acos": "ACOS",
    "ads_clicks": "广告点击量",
    "ads_impressions": "广告曝光量",
    "ads_sp": "SP广告费",
    "ads_sd": "SD广告费",
    "ads_sb": "SB广告费",
    "ads_sbv": "SBV广告费",
    "first_leg": "头程费用",
    "first_leg_shipping_fee": "头程运费",
    "first_leg_port_fee": "头程港杂费",
    "first_leg_trailer_fee": "头程拖车费",
    "transport_fee": "配送费",
    "purchase_cost": "采购成本",
    "fixed_cost": "固定成本",
    "evaluation_refund": "测评返款",
    "ams_ads_fee": "AMS广告费",
    "tax_fee": "税费",
    "vat_tax": "VAT税",
    "eu_tax": "EU税",
    "resend": "重发费用",
    "resend_pkg": "重发包裹数",
    "gross_profit": "毛利",
    "fi_freight_inbound_fee": "FI入库运费",
    "fi_first_leg_port_fee": "FI头程港杂费",
    "fi_first_leg_trailer_fee": "FI头程拖车费",
    "fi_eu_tax": "FI EU税",
    "avg_price": "平均售价",
    "avg_price_cny": "平均售价(CNY)",
    "avg_original_price": "平均原价",
    "avg_original_price_cny": "平均原价(CNY)",
    "avg_freight": "平均运费",
    "avg_freight_cny": "平均运费(CNY)",
    "avg_transport_fee": "平均配送费",
    "avg_transport_fee_cny": "平均配送费(CNY)",
    "avg_freight_transport_fee": "平均运费+配送费",
    "avg_freight_transport_fee_cny": "平均运费+配送费(CNY)",
    "avg_lightning_deals": "平均秒杀费",
    "avg_lightning_deals_cny": "平均秒杀费(CNY)",
    "gross_profit_percent": "毛利率",
    "refund_percent": "退款率",
    "purchase_cost_percent": "采购成本占比",
    "first_leg_percent": "头程占比",
    "fee_percent": "平台费用占比",
    "freight_percent": "运费占比",
    "transport_fee_percent": "配送费占比",
    "storage_charges_percent": "仓储费占比",
    "advertising_fee_percent": "广告费占比",
    "ams_ads_fee_percent": "AMS广告费占比",
    "lightning_deals_percent": "秒杀费占比",
    "evaluation_refund_percent": "测评返款占比",
    "tax_fee_percent": "税费占比",
    "compensate_percent": "赔偿占比",
    "fixed_cost_percent": "固定成本占比",
    "resend_percent": "重发费用占比",
    "total_sell_qty": "总销量",
    "sell_avg_qty": "平均销量",
    "storage_charges_os_percent": "海外仓仓储费占比",
    "storage_charges_plat_percent": "平台仓储费占比",
    "storage_charges_plat_lt_percent": "平台长期仓储费占比",
    "storage_charges_plat_ov_percent": "平台超量仓储费占比",
    "storage_charges_disposed_fee_percent": "仓储销毁费占比",
    "storage_charges_return_fee_percent": "仓储退件费占比",
    "resend_pkg_percent": "重发包裹率",
    "ads_sp_percent": "SP广告费占比",
    "ads_sd_percent": "SD广告费占比",
    "ads_sb_percent": "SB广告费占比",
    "ads_sbv_percent": "SBV广告费占比",
    "coupons_fee_percent": "优惠券费用占比",
    "deals_fee_percent": "Deals费用占比",
    "vat_tax_percent": "VAT税占比",
    "eu_tax_percent": "EU税占比",
    "first_leg_shipping_fee_percent": "头程运费占比",
    "sales_amount": "销售额",
}


def main() -> None:
    args = parse_args()
    started_at = datetime.now().isoformat(timespec="seconds")
    run_id = args.run_id or f"asin-data-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    output_root = Path(args.output_dir).expanduser() / run_id
    output_root.mkdir(parents=True, exist_ok=True)

    records, input_errors = load_asin_records(
        args.input,
        asin_column=args.asin_column,
        keyword_column=args.keyword_column,
        site_column=args.site_column,
        default_site=args.site,
    )
    if not records:
        raise SystemExit("No valid ASIN records found.")

    command_log = JsonlWriter(output_root / "commands.jsonl")
    error_log = JsonlWriter(output_root / "errors.jsonl")
    result_log = JsonlWriter(output_root / "asin-data.jsonl")

    for error in input_errors:
        error_log.write({"source": "input", **error})

    query_bundle = {}
    if not args.skip_query:
        query_bundle = collect_query_sources(args, records, output_root, command_log, error_log)

    asin_results: list[dict[str, Any]] = []
    for record in records:
        asin_result = collect_one_asin(args, record, output_root, command_log, error_log, query_bundle)
        asin_results.append(asin_result)
        result_log.write(asin_result)

    summary = build_summary(records, asin_results, input_errors, output_root, started_at, args)
    frontend_bundle = build_frontend_bundle(summary, asin_results)
    write_json(output_root / "frontend-data.json", frontend_bundle)
    write_text(output_root / "frontend-data.md", render_frontend_markdown(frontend_bundle))
    write_json(output_root / "asin-data-summary.json", summary)
    write_json(output_root / "manifest.json", summary)

    print(json.dumps({"success": True, "output_dir": str(output_root), "summary": summary["summary"]}, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch collect ASIN data through opscli.")
    parser.add_argument("--input", required=True, help="CSV/XLSX/JSON/JSONL input file")
    parser.add_argument("--asin-column", default="asin")
    parser.add_argument("--keyword-column", default="keyword")
    parser.add_argument("--site-column", default="site")
    parser.add_argument("--site", default="US")
    parser.add_argument("--output-dir", default="output/asin-data")
    parser.add_argument("--run-id")
    parser.add_argument("--opscli-bin", default="opscli")
    parser.add_argument("--dry-run", action="store_true", help="Plan commands without executing opscli")

    parser.add_argument("--skip-seller-sprite", action="store_true")
    parser.add_argument("--skip-keyword-miner", action="store_true")
    parser.add_argument("--skip-listing-analysis", action="store_true")
    parser.add_argument("--skip-amazon", action="store_true")
    parser.add_argument("--skip-query", action="store_true")
    parser.add_argument("--skip-sales-query", action="store_true")
    parser.add_argument("--skip-crawler-query", action="store_true")
    parser.add_argument("--skip-rufus", action="store_true")

    parser.add_argument("--seller-sprite-period", default="30d")
    parser.add_argument("--seller-sprite-page-size", type=int, default=100)
    parser.add_argument("--keyword-source", choices=["input_only", "reverse_top", "skip"], default="reverse_top")
    parser.add_argument("--max-miner-keywords", type=int, default=1)
    parser.add_argument("--listing-analysis-station", default="GLOBAL")
    parser.add_argument("--listing-analysis-poll-attempts", type=int, default=DEFAULT_LISTING_ANALYSIS_POLL_ATTEMPTS)
    parser.add_argument(
        "--listing-analysis-poll-interval-seconds",
        type=float,
        default=DEFAULT_LISTING_ANALYSIS_POLL_INTERVAL_SECONDS,
    )

    parser.add_argument("--rufus-country", help="Override Rufus country code; default follows each record site")
    parser.add_argument("--rufus-question", action="append", dest="rufus_questions", help="Rufus question; repeat for multiple questions")
    parser.add_argument("--rufus-skills-dir", default=".agents/skills")
    parser.add_argument("--rufus-timeout-seconds", type=int, default=180)
    parser.add_argument("--rufus-login-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--skip-rufus-login-recovery",
        action="store_true",
        help="Do not open watch-login when Rufus backend login state is missing",
    )

    parser.add_argument("--sales-table-id", type=int)
    parser.add_argument("--sales-dataset-alias", default=DEFAULT_SALES_ALIAS)
    parser.add_argument("--sales-field-mode", choices=["full", "compatible"], default="full")
    parser.add_argument("--sales-start")
    parser.add_argument("--sales-end")
    parser.add_argument("--query-chunk-size", type=int, default=100)

    parser.add_argument("--crawler-table-id", type=int)
    parser.add_argument("--crawler-dataset-alias", default=DEFAULT_CRAWLER_ALIAS)
    parser.add_argument("--crawler-field-mode", choices=["full", "compatible"], default="full")

    args = parser.parse_args()
    if args.query_chunk_size < 1:
        parser.error("--query-chunk-size must be >= 1")
    if args.max_miner_keywords < 1:
        parser.error("--max-miner-keywords must be >= 1")
    if args.listing_analysis_poll_attempts is not None and args.listing_analysis_poll_attempts < 1:
        parser.error("--listing-analysis-poll-attempts must be >= 1")
    if args.listing_analysis_poll_interval_seconds is not None and args.listing_analysis_poll_interval_seconds < 0:
        parser.error("--listing-analysis-poll-interval-seconds must be >= 0")
    if args.rufus_timeout_seconds < 1:
        parser.error("--rufus-timeout-seconds must be >= 1")
    if args.rufus_login_timeout_seconds < 1:
        parser.error("--rufus-login-timeout-seconds must be >= 1")
    return args


def collect_query_sources(
    args: argparse.Namespace,
    records: list[dict[str, Any]],
    output_root: Path,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
) -> dict[str, Any]:
    query_dir = output_root / "query"
    query_dir.mkdir(parents=True, exist_ok=True)
    asins = [record["asin"] for record in records]
    bundle = {"sales": {}, "crawler_listing": {}}

    if args.skip_sales_query:
        bundle["sales"] = {"status": "skipped", "reason": "sales query skipped by flag"}
    else:
        sales_table_id = args.sales_table_id
        sales_query_alias = args.sales_dataset_alias
        sales_metadata_result = None
        if not args.dry_run:
            resolved_sales_table_id, resolved_sales_alias, sales_metadata_result = resolve_table_id(
                opscli_bin=args.opscli_bin,
                dataset_alias=args.sales_dataset_alias,
                command_log=command_log,
                error_log=error_log,
                raw_output_path=query_dir / "sales-metadata.json",
            )
            sales_table_id = sales_table_id or resolved_sales_table_id
            sales_query_alias = resolved_sales_alias or sales_query_alias
        if sales_table_id is None and args.dry_run:
            metadata_command = [args.opscli_bin, "query", "metadata", "--dataset", args.sales_dataset_alias]
            sales_metadata_result = run_or_plan(
                source="query.metadata",
                command=metadata_command,
                dry_run=True,
                command_log=command_log,
                error_log=error_log,
                raw_output_path=query_dir / "sales-metadata.json",
            )
            bundle["sales"] = {
                "status": "planned",
                "reason": "sales table_id will be resolved by query.metadata during execution",
                "metadata_status": sales_metadata_result.get("status"),
            }
        elif sales_table_id:
            sales_args = argparse.Namespace(**vars(args))
            sales_args.sales_dataset_alias = sales_query_alias
            bundle["sales"] = run_query_chunks(
                source="query.sales",
                table_id=sales_table_id,
                dataset_alias=sales_query_alias,
                asins=asins,
                payload_builder=build_sales_payload,
                payload_prefix="sales",
                args=sales_args,
                query_dir=query_dir,
                command_log=command_log,
                error_log=error_log,
                metadata_fields=extract_metadata_field_sets(sales_metadata_result),
            )
        else:
            reason = "sales table_id not resolved"
            if sales_metadata_result:
                reason = extract_error_message(sales_metadata_result.get("json"), sales_metadata_result.get("stderr", "")) or reason
            bundle["sales"] = {
                "status": "failed" if sales_metadata_result else "skipped",
                "reason": reason,
                "metadata_status": sales_metadata_result.get("status") if isinstance(sales_metadata_result, dict) else None,
            }

    if args.skip_crawler_query:
        bundle["crawler_listing"] = {"status": "skipped", "reason": "crawler query skipped by flag"}
        return bundle

    crawler_table_id = args.crawler_table_id
    crawler_query_alias = args.crawler_dataset_alias
    metadata_result = None
    if not args.dry_run:
        resolved_crawler_table_id, resolved_crawler_alias, metadata_result = resolve_table_id(
            opscli_bin=args.opscli_bin,
            dataset_alias=args.crawler_dataset_alias,
            command_log=command_log,
            error_log=error_log,
            raw_output_path=query_dir / "crawler-metadata.json",
        )
        crawler_table_id = crawler_table_id or resolved_crawler_table_id
        crawler_query_alias = resolved_crawler_alias or crawler_query_alias
    if crawler_table_id is None and args.dry_run:
        metadata_command = [args.opscli_bin, "query", "metadata", "--dataset", args.crawler_dataset_alias]
        metadata_result = run_or_plan(
            source="query.metadata",
            command=metadata_command,
            dry_run=True,
            command_log=command_log,
            error_log=error_log,
            raw_output_path=query_dir / "crawler-metadata.json",
        )
        bundle["crawler_listing"] = {
            "status": "planned",
            "reason": "crawler table_id will be resolved by query.metadata during execution",
            "metadata_status": metadata_result.get("status"),
        }
        return bundle

    if crawler_table_id:
        crawler_args = argparse.Namespace(**vars(args))
        crawler_args.crawler_dataset_alias = crawler_query_alias
        crawler_args.crawler_sites = sorted({str(record.get("site") or "").upper() for record in records if record.get("site")})
        crawler_result = run_query_chunks(
            source="query.crawler_listing",
            table_id=crawler_table_id,
            dataset_alias=crawler_query_alias,
            asins=asins,
            payload_builder=build_crawler_payload,
            payload_prefix="crawler-listing",
            args=crawler_args,
            query_dir=query_dir,
            command_log=command_log,
            error_log=error_log,
            metadata_fields=extract_metadata_field_sets(metadata_result),
        )
        bundle["crawler_listing"] = keep_latest_date_per_asin(crawler_result)
    else:
        reason = "crawler table_id not resolved"
        if metadata_result:
            reason = extract_error_message(metadata_result.get("json"), metadata_result.get("stderr", "")) or reason
        bundle["crawler_listing"] = {
            "status": "failed" if metadata_result else "skipped",
            "reason": reason,
            "metadata_status": metadata_result.get("status") if isinstance(metadata_result, dict) else None,
        }

    return bundle


def collect_one_asin(
    args: argparse.Namespace,
    record: dict[str, Any],
    output_root: Path,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
    query_bundle: dict[str, Any],
) -> dict[str, Any]:
    asin = record["asin"]
    site = record["site"]
    record_keywords = normalize_keywords(record.get("keywords") or record.get("keyword") or "")
    asin_dir = output_root / "asins" / asin
    asin_dir.mkdir(parents=True, exist_ok=True)

    errors: list[dict[str, Any]] = []
    result = {
        "asin": asin,
        "site": site,
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
            "sales": rows_for_asin(query_bundle.get("sales"), asin),
            "crawler_listing": rows_for_asin(query_bundle.get("crawler_listing"), asin),
        },
        "errors": errors,
    }

    reverse_result = {"status": "skipped", "reason": "seller sprite skipped"}
    if not args.skip_seller_sprite:
        seller_dir = output_root / "seller-sprite" / asin
        seller_dir.mkdir(parents=True, exist_ok=True)
        reverse_params = json.dumps({"asin": asin}, ensure_ascii=False)
        reverse_command = [
            args.opscli_bin,
            "seller-sprite",
            "run",
            "keyword-reverse",
            "--site",
            site,
            "--period",
            args.seller_sprite_period,
            "--params",
            reverse_params,
            "--page-size",
            str(args.seller_sprite_page_size),
            "--export-format",
            KEYWORD_SELLER_SPRITE_EXPORT_FORMAT,
            "--output-dir",
            str(seller_dir),
        ]
        reverse_result = run_or_plan(
            source="seller_sprite.keyword_reverse",
            command=reverse_command,
            dry_run=args.dry_run,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "seller-sprite-keyword-reverse.json",
        )
    result["seller_sprite"]["keyword_reverse"] = compact_seller_sprite_result(
        reverse_result,
        inline_rows=KEYWORD_SELLER_SPRITE_INLINE_ROWS,
    )

    keywords = list(record_keywords)
    if not keywords and args.keyword_source == "reverse_top":
        keywords = derive_keywords_from_reverse(reverse_result, max_count=args.max_miner_keywords)
        if keywords:
            result["input"]["keyword"] = keywords[0]
            result["input"]["keywords"] = keywords
            result["input"]["keyword_count"] = len(keywords)
            result["input"]["keyword_source"] = "reverse_top"

    miner_jobs = []
    if args.skip_seller_sprite or args.skip_keyword_miner:
        result["seller_sprite"]["keyword_miner"] = {"status": "skipped", "reason": "keyword miner skipped"}
    elif not keywords or args.keyword_source == "skip":
        result["seller_sprite"]["keyword_miner"] = {"status": "skipped", "reason": "keyword is missing"}
    else:
        seller_dir = output_root / "seller-sprite" / asin
        miner_keywords = keywords[: max(args.max_miner_keywords, 1)]
        for seed in miner_keywords:
            miner_params = json.dumps({"keyword": seed}, ensure_ascii=False)
            miner_command = [
                args.opscli_bin,
                "seller-sprite",
                "run",
                "keyword-miner",
                "--site",
                site,
                "--period",
                args.seller_sprite_period,
                "--params",
                miner_params,
                "--page-size",
                str(args.seller_sprite_page_size),
                "--export-format",
                KEYWORD_SELLER_SPRITE_EXPORT_FORMAT,
                "--output-dir",
                str(seller_dir),
            ]
            miner_jobs.append(
                run_or_plan(
                    source="seller_sprite.keyword_miner",
                    command=miner_command,
                    dry_run=args.dry_run,
                    command_log=command_log,
                    error_log=error_log,
                    asin=asin,
                    raw_output_path=asin_dir / f"seller-sprite-keyword-miner-{safe_name(seed)}.json",
                )
            )
        result["seller_sprite"]["keyword_miner"] = {
            "status": aggregate_status(miner_jobs),
            "seed_keywords": miner_keywords,
            "jobs": [
                compact_seller_sprite_result(job, inline_rows=KEYWORD_SELLER_SPRITE_INLINE_ROWS)
                for job in miner_jobs
            ],
        }

    listing_result = {"status": "skipped", "reason": "seller sprite skipped"}
    if args.skip_seller_sprite:
        result["seller_sprite"]["listing_analysis"] = compact_listing_analysis_result(listing_result)
    elif args.skip_listing_analysis:
        result["seller_sprite"]["listing_analysis"] = {
            "status": "skipped",
            "reason": "listing analysis skipped",
            "content": None,
        }
    else:
        seller_dir = output_root / "seller-sprite" / asin
        seller_dir.mkdir(parents=True, exist_ok=True)
        listing_params: dict[str, Any] = {
            "asin": asin,
            "station": args.listing_analysis_station,
        }
        if args.listing_analysis_poll_attempts is not None:
            listing_params["pollAttempts"] = args.listing_analysis_poll_attempts
        if args.listing_analysis_poll_interval_seconds is not None:
            listing_params["pollIntervalSeconds"] = args.listing_analysis_poll_interval_seconds
        listing_command = [
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
        ]
        listing_result = run_or_plan(
            source="seller_sprite.listing_analysis",
            command=listing_command,
            dry_run=args.dry_run,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "seller-sprite-listing-analysis.json",
        )
        result["seller_sprite"]["listing_analysis"] = compact_listing_analysis_result(listing_result)

    if args.skip_amazon:
        result["amazon"]["scrape"] = {"status": "skipped", "reason": "amazon skipped"}
    else:
        amazon_command = [args.opscli_bin, "amazon", "scrape", "--asin", asin]
        amazon_result = run_or_plan(
            source="amazon.scrape",
            command=amazon_command,
            dry_run=args.dry_run,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "amazon-scrape.json",
        )
        result["amazon"]["scrape"] = compact_amazon_result(amazon_result)

    result["rufus"] = collect_rufus_data(args, asin, site, asin_dir, command_log, error_log)

    for source_name in ("keyword_reverse", "keyword_miner", "listing_analysis"):
        collect_status_errors("seller_sprite", source_name, result["seller_sprite"].get(source_name), errors)
    collect_status_errors("rufus", "qa", result.get("rufus"), errors)
    collect_status_errors("query", "sales", result["query"].get("sales"), errors)
    collect_status_errors("query", "crawler_listing", result["query"].get("crawler_listing"), errors)
    result["frontend_data"] = build_frontend_record(result)
    return result


def collect_rufus_data(
    args: argparse.Namespace,
    asin: str,
    site: str,
    asin_dir: Path,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
) -> dict[str, Any]:
    questions = rufus_questions(args, asin=asin)
    country = rufus_country(args, site)
    if getattr(args, "skip_rufus", True):
        return {
            "status": "skipped",
            "reason": "rufus skipped",
            "country": country,
            "questions": questions,
            "answers": [],
        }

    remote_result = run_or_plan(
        source="rufus.remote_consent",
        command=[args.opscli_bin, "amazon-rufus", "remote-consent", "status", country, "--pretty"],
        dry_run=args.dry_run,
        command_log=command_log,
        error_log=error_log,
        asin=asin,
        raw_output_path=asin_dir / "rufus-remote-consent.json",
    )
    login_result = run_or_plan(
        source="rufus.login_status",
        command=[args.opscli_bin, "amazon-rufus", "login-status", country, "--pretty"],
        dry_run=args.dry_run,
        command_log=command_log,
        error_log=error_log,
        asin=asin,
        raw_output_path=asin_dir / "rufus-login-status.json",
    )

    if args.dry_run:
        get_result = run_or_plan(
            source="rufus.get_backend",
            command=build_rufus_get_backend_command(args, asin, country, questions),
            dry_run=True,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "rufus-get-backend.json",
        )
        return compact_rufus_result(
            get_result,
            asin=asin,
            country=country,
            questions=questions,
            remote_consent=compact_json_command_result(remote_result),
            login_status=compact_json_command_result(login_result),
        )

    remote_consent = compact_json_command_result(remote_result)
    if remote_result.get("status") != "success":
        return failed_rufus_result(
            asin=asin,
            country=country,
            questions=questions,
            reason=extract_error_message(remote_result.get("json"), remote_result.get("stderr", "")) or "rufus remote consent failed",
            remote_consent=remote_consent,
        )

    consent_status = str(((remote_result.get("json") or {}).get("data") or {}).get("status") or "").strip().lower()
    if consent_status in {"", "unknown", "invalid"}:
        return failed_rufus_result(
            asin=asin,
            country=country,
            questions=questions,
            reason="Rufus remote consent is not configured; run opscli amazon-rufus remote-consent set first",
            remote_consent=remote_consent,
            login_status=compact_json_command_result(login_result),
        )

    login_status = compact_json_command_result(login_result)
    if login_result.get("status") != "success":
        return failed_rufus_result(
            asin=asin,
            country=country,
            questions=questions,
            reason=extract_error_message(login_result.get("json"), login_result.get("stderr", "")) or "rufus login status failed",
            remote_consent=remote_consent,
            login_status=login_status,
        )

    if not rufus_can_get_backend(login_result):
        if getattr(args, "skip_rufus_login_recovery", False):
            return failed_rufus_result(
                asin=asin,
                country=country,
                questions=questions,
                reason="Rufus login state is not ready and login recovery is disabled",
                remote_consent=remote_consent,
                login_status=login_status,
            )
        watch_result = run_or_plan(
            source="rufus.watch_login",
            command=[
                args.opscli_bin,
                "amazon-rufus",
                "watch-login",
                asin,
                country,
                "--launch-if-needed",
                "--close-browser",
                "--timeout",
                str(args.rufus_login_timeout_seconds),
                "--pretty",
            ],
            dry_run=False,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "rufus-watch-login.json",
        )
        watch_login = compact_json_command_result(watch_result)
        if watch_result.get("status") != "success":
            return failed_rufus_result(
                asin=asin,
                country=country,
                questions=questions,
                reason=extract_error_message(watch_result.get("json"), watch_result.get("stderr", "")) or "rufus watch-login failed",
                remote_consent=remote_consent,
                login_status=login_status,
                watch_login=watch_login,
            )
        login_result = run_or_plan(
            source="rufus.login_status",
            command=[args.opscli_bin, "amazon-rufus", "login-status", country, "--pretty"],
            dry_run=False,
            command_log=command_log,
            error_log=error_log,
            asin=asin,
            raw_output_path=asin_dir / "rufus-login-status-after-watch.json",
        )
        login_status = compact_json_command_result(login_result)
        if login_result.get("status") != "success" or not rufus_can_get_backend(login_result):
            return failed_rufus_result(
                asin=asin,
                country=country,
                questions=questions,
                reason="Rufus login state is still not ready after watch-login",
                remote_consent=remote_consent,
                login_status=login_status,
                watch_login=watch_login,
            )

    get_result = run_or_plan(
        source="rufus.get_backend",
        command=build_rufus_get_backend_command(args, asin, country, questions),
        dry_run=False,
        command_log=command_log,
        error_log=error_log,
        asin=asin,
        raw_output_path=asin_dir / "rufus-get-backend.json",
    )
    return compact_rufus_result(
        get_result,
        asin=asin,
        country=country,
        questions=questions,
        remote_consent=remote_consent,
        login_status=login_status,
    )


def rufus_questions(args: argparse.Namespace, asin: str | None = None) -> list[str]:
    questions = [str(item).strip() for item in (getattr(args, "rufus_questions", None) or []) if str(item).strip()]
    resolved = questions or list(DEFAULT_RUFUS_QUESTIONS)
    if asin:
        return [render_asin_placeholder(question, asin) for question in resolved]
    return resolved


def render_asin_placeholder(question: str, asin: str) -> str:
    normalized_asin = str(asin or "").strip().upper()
    return str(question).replace("{{asin}}", normalized_asin).replace("{asin}", normalized_asin)


def rufus_country(args: argparse.Namespace, site: str) -> str:
    return str(getattr(args, "rufus_country", None) or site or "US").strip().upper()


def build_rufus_get_backend_command(
    args: argparse.Namespace,
    asin: str,
    country: str,
    questions: list[str],
) -> list[str]:
    command = [
        args.opscli_bin,
        "amazon-rufus",
        "get-backend",
        asin,
        country,
        "--skills-dir",
        str(args.rufus_skills_dir),
        "--timeout",
        str(args.rufus_timeout_seconds),
        "--no-upload-payload",
        "--pretty",
    ]
    for question in questions:
        command.extend(["-q", question])
    return command


def compact_json_command_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result, dict) else None
    compact = {
        "status": result.get("status") if isinstance(result, dict) else "skipped",
        "data": payload.get("data") if isinstance(payload, dict) else None,
    }
    if isinstance(result, dict) and result.get("status") == "failed":
        compact["error_message"] = extract_error_message(payload, result.get("stderr", ""))
    return compact


def rufus_can_get_backend(result: dict[str, Any]) -> bool:
    payload = result.get("json") if isinstance(result, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else {}
    return bool(data.get("can_get_backend")) if isinstance(data, dict) else False


def failed_rufus_result(
    *,
    asin: str,
    country: str,
    questions: list[str],
    reason: str,
    remote_consent: dict[str, Any] | None = None,
    login_status: dict[str, Any] | None = None,
    watch_login: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "failed",
        "asin": asin,
        "country": country,
        "questions": questions,
        "answers": [],
        "answer_count": 0,
        "reason": reason,
    }
    if remote_consent:
        payload["remote_consent"] = remote_consent
    if login_status:
        payload["login_status"] = login_status
    if watch_login:
        payload["watch_login"] = watch_login
    return payload


def build_sales_payload(args: argparse.Namespace, asins: list[str]) -> dict[str, Any]:
    if getattr(args, "sales_field_mode", "full") == "compatible":
        return build_sales_compatible_payload(args, asins)

    filters = [{"field": f"{args.sales_dataset_alias}.asin", "operator": "in", "value": asins}]
    if args.sales_start and args.sales_end:
        filters.append(
            {
                "field": f"{args.sales_dataset_alias}.date_id",
                "operator": "between",
                "value": [args.sales_start, args.sales_end],
            }
        )
    return {
        "dimensions": [
            {"field": f"{args.sales_dataset_alias}.asin", "alias": "f_asin"},
            {"field": f"{args.sales_dataset_alias}.product_name", "alias": "f_product_name"},
        ],
        "metrics": [
            {"field": f"{args.sales_dataset_alias}.order_qty", "aggregation": "SUM", "alias": "f_order_qty"},
            {"field": f"{args.sales_dataset_alias}.orders", "aggregation": "SUM", "alias": "f_orders"},
            {"field": f"{args.sales_dataset_alias}.sessions", "aggregation": "SUM", "alias": "f_sessions"},
            {"field": f"{args.sales_dataset_alias}.page_views", "aggregation": "SUM", "alias": "f_page_views"},
            {"field": f"{args.sales_dataset_alias}.original_price", "aggregation": "SUM", "alias": "f_original_price"},
            {"field": f"{args.sales_dataset_alias}.price", "aggregation": "SUM", "alias": "f_sales_amount"},
            {"field": f"{args.sales_dataset_alias}.advertising_fee", "aggregation": "SUM", "alias": "f_advertising_fee"},
            {"field": f"{args.sales_dataset_alias}.ads_sales_cny", "aggregation": "SUM", "alias": "f_ads_sales_cny"},
            {"field": f"{args.sales_dataset_alias}.ads_clicks", "aggregation": "SUM", "alias": "f_ads_clicks"},
            {"field": f"{args.sales_dataset_alias}.ads_impressions", "aggregation": "SUM", "alias": "f_ads_impressions"},
            {"field": f"{args.sales_dataset_alias}.refund", "aggregation": "SUM", "alias": "f_refund"},
            {"field": f"{args.sales_dataset_alias}.refund_qty", "aggregation": "SUM", "alias": "f_refund_qty"},
        ],
        "filters": filters,
        "limit": max(len(asins), args.query_chunk_size),
        "offset": 0,
    }


def build_sales_compatible_payload(args: argparse.Namespace, asins: list[str]) -> dict[str, Any]:
    filters = [{"field": f"{args.sales_dataset_alias}.asin", "operator": "in", "value": asins}]
    if args.sales_start and args.sales_end:
        filters.append(
            {
                "field": f"{args.sales_dataset_alias}.date_id",
                "operator": "between",
                "value": [args.sales_start, args.sales_end],
            }
        )
    return {
        "dimensions": [
            {"field": f"{args.sales_dataset_alias}.asin", "alias": "f_asin"},
            {"field": f"{args.sales_dataset_alias}.product_name", "alias": "f_product_name"},
        ],
        "metrics": [
            {"field": f"{args.sales_dataset_alias}.order_qty", "aggregation": "SUM", "alias": "f_order_qty"},
            {"field": f"{args.sales_dataset_alias}.orders", "aggregation": "SUM", "alias": "f_orders"},
            {"field": f"{args.sales_dataset_alias}.price", "aggregation": "SUM", "alias": "f_sales_amount"},
        ],
        "filters": filters,
        "limit": max(len(asins), args.query_chunk_size),
        "offset": 0,
    }


def build_crawler_payload(args: argparse.Namespace, asins: list[str]) -> dict[str, Any]:
    if getattr(args, "crawler_field_mode", "full") == "compatible":
        return build_crawler_compatible_payload(args, asins)

    alias = args.crawler_dataset_alias
    filters = build_crawler_filters(args, asins)
    return {
        "dimensions": [
            {"field": f"{alias}.asin", "alias": "f_asin"},
            {"field": f"{alias}.date_id", "alias": "f_date_id"},
            {"field": f"{alias}.country", "alias": "f_country"},
            {"field": f"{alias}.currency", "alias": "f_currency"},
            {"field": f"{alias}.listing", "alias": "f_product_name"},
            {"field": f"{alias}.link", "alias": "f_link"},
            {"field": f"{alias}.image", "alias": "f_image"},
            {"field": f"{alias}.description", "alias": "f_description"},
            {"field": f"{alias}.a_image", "alias": "f_a_image"},
            {"field": f"{alias}.a_description", "alias": "f_a_description"},
            {"field": f"{alias}.product_details", "alias": "f_product_details"},
            {"field": f"{alias}.five_point_description", "alias": "f_five_point_description"},
            {"field": f"{alias}.qa", "alias": "f_qa"},
            {"field": f"{alias}.review_list", "alias": "f_review_list"},
            {"field": f"{alias}.brand", "alias": "f_brand"},
            {"field": f"{alias}.seller_id", "alias": "f_seller_id"},
            {"field": f"{alias}.price_scribe", "alias": "f_price_scribe"},
            {"field": f"{alias}.original_price", "alias": "f_original_price"},
            {"field": f"{alias}.unit_price", "alias": "f_unit_price"},
            {"field": f"{alias}.reduction", "alias": "f_reduction"},
            {"field": f"{alias}.coupon", "alias": "f_coupon"},
            {"field": f"{alias}.promo_code_value", "alias": "f_promo_code_value"},
            {"field": f"{alias}.promo_code", "alias": "f_promo_code"},
            {"field": f"{alias}.deal", "alias": "f_deal"},
            {"field": f"{alias}.major_name", "alias": "f_major_name"},
            {"field": f"{alias}.major_rank", "alias": "f_major_rank"},
            {"field": f"{alias}.subclass_name", "alias": "f_subclass_name"},
            {"field": f"{alias}.subclass_rank", "alias": "f_subclass_rank"},
            {"field": f"{alias}.deal_type", "alias": "f_deal_type"},
        ],
        "metrics": [
            {"field": f"{alias}.price", "aggregation": "AVG", "alias": "f_price"},
            {"field": f"{alias}.rating", "aggregation": "AVG", "alias": "f_rating"},
            {"field": f"{alias}.rating_count", "aggregation": "MAX", "alias": "f_rating_count"},
            {"field": f"{alias}.review_count", "aggregation": "MAX", "alias": "f_review_count"},
            {"field": f"{alias}.stock_qty", "aggregation": "MAX", "alias": "f_stock_qty"},
            {"field": f"{alias}.sales_status", "aggregation": "MAX", "alias": "f_sales_status"},
            {"field": f"{alias}.in_stock", "aggregation": "MAX", "alias": "f_in_stock"},
            {"field": f"{alias}.subplot_count", "aggregation": "MAX", "alias": "f_subplot_count"},
            {"field": f"{alias}.video_count", "aggregation": "MAX", "alias": "f_video_count"},
            {"field": f"{alias}.five_point_description_count", "aggregation": "MAX", "alias": "f_five_point_description_count"},
            {"field": f"{alias}.a_image_count", "aggregation": "MAX", "alias": "f_a_image_count"},
            {"field": f"{alias}.variant_count", "aggregation": "MAX", "alias": "f_variant_count"},
            {"field": f"{alias}.cs_count", "aggregation": "MAX", "alias": "f_cs_count"},
            {"field": f"{alias}.qa_count", "aggregation": "MAX", "alias": "f_qa_count"},
            {"field": f"{alias}.timestamp", "aggregation": "MAX", "alias": "f_timestamp"},
        ],
        "filters": filters,
        "orderBy": [{"field": "f_date_id", "desc": True}],
        "limit": max(len(asins), args.query_chunk_size),
        "offset": 0,
    }


def build_crawler_compatible_payload(args: argparse.Namespace, asins: list[str]) -> dict[str, Any]:
    alias = args.crawler_dataset_alias
    filters = build_crawler_filters(args, asins)
    return {
        "dimensions": [
            {"field": f"{alias}.asin", "alias": "f_asin"},
            {"field": f"{alias}.date_id", "alias": "f_date_id"},
            {"field": f"{alias}.country", "alias": "f_country"},
            {"field": f"{alias}.currency", "alias": "f_currency"},
            {"field": f"{alias}.listing", "alias": "f_product_name"},
            {"field": f"{alias}.link", "alias": "f_link"},
            {"field": f"{alias}.image", "alias": "f_image"},
            {"field": f"{alias}.description", "alias": "f_description"},
            {"field": f"{alias}.brand", "alias": "f_brand"},
            {"field": f"{alias}.seller_id", "alias": "f_seller_id"},
            {"field": f"{alias}.price_scribe", "alias": "f_price_scribe"},
            {"field": f"{alias}.original_price", "alias": "f_original_price"},
            {"field": f"{alias}.unit_price", "alias": "f_unit_price"},
            {"field": f"{alias}.reduction", "alias": "f_reduction"},
            {"field": f"{alias}.coupon", "alias": "f_coupon"},
            {"field": f"{alias}.promo_code_value", "alias": "f_promo_code_value"},
            {"field": f"{alias}.promo_code", "alias": "f_promo_code"},
            {"field": f"{alias}.deal", "alias": "f_deal"},
            {"field": f"{alias}.major_name", "alias": "f_major_name"},
            {"field": f"{alias}.major_rank", "alias": "f_major_rank"},
            {"field": f"{alias}.subclass_name", "alias": "f_subclass_name"},
            {"field": f"{alias}.subclass_rank", "alias": "f_subclass_rank"},
            {"field": f"{alias}.deal_type", "alias": "f_deal_type"},
        ],
        "metrics": [
            {"field": f"{alias}.price", "aggregation": "AVG", "alias": "f_price"},
            {"field": f"{alias}.rating", "aggregation": "AVG", "alias": "f_rating"},
            {"field": f"{alias}.rating_count", "aggregation": "MAX", "alias": "f_rating_count"},
            {"field": f"{alias}.review_count", "aggregation": "MAX", "alias": "f_review_count"},
            {"field": f"{alias}.stock_qty", "aggregation": "MAX", "alias": "f_stock_qty"},
            {"field": f"{alias}.sales_status", "aggregation": "MAX", "alias": "f_sales_status"},
            {"field": f"{alias}.in_stock", "aggregation": "MAX", "alias": "f_in_stock"},
            {"field": f"{alias}.subplot_count", "aggregation": "MAX", "alias": "f_subplot_count"},
            {"field": f"{alias}.video_count", "aggregation": "MAX", "alias": "f_video_count"},
            {"field": f"{alias}.five_point_description_count", "aggregation": "MAX", "alias": "f_five_point_description_count"},
            {"field": f"{alias}.a_image_count", "aggregation": "MAX", "alias": "f_a_image_count"},
            {"field": f"{alias}.variant_count", "aggregation": "MAX", "alias": "f_variant_count"},
            {"field": f"{alias}.cs_count", "aggregation": "MAX", "alias": "f_cs_count"},
            {"field": f"{alias}.qa_count", "aggregation": "MAX", "alias": "f_qa_count"},
            {"field": f"{alias}.timestamp", "aggregation": "MAX", "alias": "f_timestamp"},
        ],
        "filters": filters,
        "orderBy": [{"field": "f_date_id", "desc": True}],
        "limit": max(len(asins), args.query_chunk_size),
        "offset": 0,
    }


def build_crawler_filters(args: argparse.Namespace, asins: list[str]) -> list[dict[str, Any]]:
    alias = args.crawler_dataset_alias
    filters = [{"field": f"{alias}.asin", "operator": "in", "value": asins}]
    sites = [site for site in getattr(args, "crawler_sites", []) if site]
    if sites:
        filters.append({"field": f"{alias}.country", "operator": "in", "value": sites})
    return filters


def extract_metadata_field_sets(metadata_result: dict[str, Any] | None) -> dict[str, set[str]]:
    if not isinstance(metadata_result, dict):
        return {}
    payload = metadata_result.get("json")
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    fields = (data.get("fields") or []) if isinstance(data, dict) else []
    field_sets: dict[str, set[str]] = {"dimension": set(), "metric": set()}
    for item in fields:
        if not isinstance(item, dict):
            continue
        field_name = item.get("field_name")
        field_type = item.get("field_type")
        if isinstance(field_name, str) and field_type in field_sets:
            field_sets[field_type].add(field_name)
    return {key: value for key, value in field_sets.items() if value}


def filter_query_payload_by_metadata(
    payload: dict[str, Any],
    dataset_alias: str,
    metadata_fields: dict[str, set[str]] | None,
) -> tuple[dict[str, Any], list[str]]:
    if not metadata_fields:
        return payload, []

    dimension_fields = metadata_fields.get("dimension", set())
    metric_fields = metadata_fields.get("metric", set())
    all_fields = dimension_fields | metric_fields
    dropped: list[str] = []

    filtered = dict(payload)
    filtered_dimensions = [
        item
        for item in payload.get("dimensions", [])
        if keep_payload_field(item, dataset_alias, dimension_fields, "dimension", dropped)
    ]
    filtered_metrics = [
        item
        for item in payload.get("metrics", [])
        if keep_payload_metric(item, dataset_alias, metric_fields, all_fields, dropped)
    ]
    filtered["dimensions"] = filtered_dimensions
    filtered["metrics"] = filtered_metrics

    aliases = {
        item.get("alias")
        for item in [*filtered_dimensions, *filtered_metrics]
        if isinstance(item, dict) and item.get("alias")
    }
    if "orderBy" in filtered:
        filtered_order_by = []
        for item in filtered.get("orderBy") or []:
            if not isinstance(item, dict):
                filtered_order_by.append(item)
                continue
            field = item.get("field")
            if not isinstance(field, str) or field in aliases or "." in field:
                filtered_order_by.append(item)
            else:
                dropped.append(f"orderBy:{field}")
        filtered["orderBy"] = filtered_order_by

    return filtered, dropped


def keep_payload_field(
    item: Any,
    dataset_alias: str,
    supported_fields: set[str],
    field_type: str,
    dropped: list[str],
) -> bool:
    if not isinstance(item, dict):
        return True
    field_name = payload_field_name(item.get("field"), dataset_alias)
    if field_name and field_name not in supported_fields:
        dropped.append(f"{field_type}:{field_name}")
        return False
    return True


def keep_payload_metric(
    item: Any,
    dataset_alias: str,
    metric_fields: set[str],
    all_fields: set[str],
    dropped: list[str],
) -> bool:
    if not isinstance(item, dict):
        return True
    field_name = payload_field_name(item.get("field"), dataset_alias)
    if field_name and field_name not in metric_fields:
        dropped.append(f"metric:{field_name}")
        return False
    expr = item.get("expr")
    if isinstance(expr, str):
        missing = [name for name in expr_field_names(expr, dataset_alias) if name not in all_fields]
        if missing:
            dropped.extend(f"expr:{name}" for name in missing)
            return False
    return True


def payload_field_name(field: Any, dataset_alias: str) -> str | None:
    if not isinstance(field, str):
        return None
    prefix = f"{dataset_alias}."
    if field.startswith(prefix):
        return field[len(prefix) :]
    return None


def expr_field_names(expr: str, dataset_alias: str) -> list[str]:
    return re.findall(rf"{re.escape(dataset_alias)}\.([A-Za-z_][A-Za-z0-9_]*)", expr)


def run_query_chunks(
    *,
    source: str,
    table_id: int,
    dataset_alias: str,
    asins: list[str],
    payload_builder: Any,
    payload_prefix: str,
    args: argparse.Namespace,
    query_dir: Path,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
    metadata_fields: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    chunks = list(chunk_list(asins, args.query_chunk_size))
    results: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    asin_status: dict[str, str] = {}
    asin_errors: dict[str, str] = {}
    metadata_dropped_fields: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        suffix = "" if len(chunks) == 1 else f"-{index:03d}"
        payload = payload_builder(args, chunk)
        payload, dropped_fields = filter_query_payload_by_metadata(payload, dataset_alias, metadata_fields)
        metadata_dropped_fields.extend(dropped_fields)
        payload_path = query_dir / f"{payload_prefix}-payload{suffix}.json"
        result_path = query_dir / f"{payload_prefix}-result{suffix}.json"
        write_json(payload_path, payload)
        command = [
            args.opscli_bin,
            "query",
            "simple",
            "--table-id",
            str(table_id),
            "--payload",
            str(payload_path),
            "--run",
        ]
        result = run_or_plan(
            source=source,
            command=command,
            dry_run=args.dry_run,
            command_log=command_log,
            error_log=error_log,
            raw_output_path=result_path,
        )
        results.append(result)
        rows.extend(extract_query_rows(result.get("json")))
        for asin in chunk:
            asin_status[asin] = result.get("status") or "skipped"
            if result.get("status") == "failed":
                asin_errors[asin] = extract_error_message(result.get("json"), result.get("stderr", ""))

    return {
        "status": aggregate_status(results),
        "table_id": table_id,
        "dataset_alias": dataset_alias,
        "chunk_count": len(chunks),
        "row_count": len(rows),
        "rows": rows,
        "asin_status": asin_status,
        "asin_errors": asin_errors,
        "chunks": [compact_query_chunk(index, result, len(chunks[index - 1])) for index, result in enumerate(results, start=1)],
        "metadata_dropped_fields": sorted(set(metadata_dropped_fields)),
    }


def chunk_list(items: list[str], size: int) -> list[list[str]]:
    step = max(size, 1)
    return [items[index : index + step] for index in range(0, len(items), step)]


def compact_query_chunk(index: int, result: dict[str, Any], asin_count: int) -> dict[str, Any]:
    payload = {
        "index": index,
        "asin_count": asin_count,
        "status": result.get("status"),
        "command": result.get("command"),
        "row_count": len(extract_query_rows(result.get("json"))),
    }
    if result.get("status") == "failed":
        payload["error_message"] = extract_error_message(result.get("json"), result.get("stderr", ""))
    return payload


def resolve_table_id(
    *,
    opscli_bin: str,
    dataset_alias: str,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
    raw_output_path: Path,
) -> tuple[int | None, str | None, dict[str, Any]]:
    command = [opscli_bin, "query", "metadata", "--dataset", dataset_alias]
    result = run_or_plan(
        source="query.metadata",
        command=command,
        dry_run=False,
        command_log=command_log,
        error_log=error_log,
        raw_output_path=raw_output_path,
    )
    data = result.get("json") or {}
    dataset = (((data.get("data") or {}).get("dataset")) if isinstance(data, dict) else {}) or {}
    table_id = dataset.get("table_id")
    resolved_alias = dataset.get("dataset_alias") if isinstance(dataset, dict) else None
    return (int(table_id) if table_id else None), (str(resolved_alias) if resolved_alias else None), result



def run_or_plan(
    *,
    source: str,
    command: list[str],
    dry_run: bool,
    command_log: "JsonlWriter",
    error_log: "JsonlWriter",
    asin: str | None = None,
    raw_output_path: Path | None = None,
) -> dict[str, Any]:
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "asin": asin,
        "command": command,
        "dry_run": dry_run,
    }
    if dry_run:
        planned = {**entry, "status": "planned", "exit_code": None}
        command_log.write(planned)
        return {"status": "planned", "command": command}

    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = parse_json_output(completed.stdout)
    status = "success" if completed.returncode == 0 and not is_payload_failure(payload) else "failed"
    result = {
        **entry,
        "status": status,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": payload,
    }
    command_log.write(strip_large_output(result))
    if raw_output_path:
        write_json(raw_output_path, result)
    if status == "failed":
        error = {
            "asin": asin,
            "source": source,
            "tool": " ".join(command[:4]),
            "status": "failed",
            "exit_code": completed.returncode,
            "error_message": extract_error_message(payload, completed.stderr),
            "retry_count": 0,
        }
        error_log.write(error)
    return result


def parse_json_output(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char not in "{[":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            return payload
        except Exception:
            continue
    return None


def is_payload_failure(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("success") is False


def extract_error_message(payload: Any, stderr: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return f"{error.get('code') or ''}: {error.get('message') or ''}".strip(": ")
        if error:
            return str(error)
    return stderr.strip()


def strip_large_output(result: dict[str, Any]) -> dict[str, Any]:
    compact = dict(result)
    for key in ("stdout", "stderr"):
        value = compact.get(key) or ""
        if len(value) > 1000:
            compact[key] = value[:1000] + "...<truncated>"
    return compact


def rows_for_asin(source_result: Any, asin: str) -> dict[str, Any]:
    if not isinstance(source_result, dict):
        return {"status": "skipped", "rows": []}
    status = (source_result.get("asin_status") or {}).get(asin) or source_result.get("status")
    if status == "planned":
        return {"status": "planned", "rows": []}
    if status not in {"success", "partial"}:
        payload = {"status": status or "skipped", "rows": []}
        reason = (source_result.get("asin_errors") or {}).get(asin) or source_result.get("reason")
        if reason:
            payload["reason"] = reason
        return payload
    rows = source_result.get("rows")
    if not isinstance(rows, list):
        rows = extract_query_rows(source_result.get("json"))
    matched = [row for row in rows if str(row.get("f_asin") or row.get("asin") or "").upper() == asin]
    return {"status": status, "rows": matched, "row_count": len(matched)}


def keep_latest_date_per_asin(source_result: dict[str, Any]) -> dict[str, Any]:
    rows = source_result.get("rows")
    if not isinstance(rows, list):
        return source_result

    latest_rows = latest_date_rows_per_asin([row for row in rows if isinstance(row, dict)])
    result = dict(source_result)
    result["rows"] = latest_rows
    result["row_count"] = len(latest_rows)
    result["latest_date_only"] = True
    result["latest_dates_by_asin"] = latest_dates_by_asin(latest_rows)
    return result


def latest_date_rows_per_asin(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        asin = str(row.get("f_asin") or row.get("asin") or "").upper()
        grouped.setdefault(asin, []).append(row)

    latest_rows: list[dict[str, Any]] = []
    for asin_rows in grouped.values():
        dated_rows = [
            (row, crawler_date_sort_key(row))
            for row in asin_rows
            if crawler_date_value(row) is not None
        ]
        if not dated_rows:
            latest_rows.extend(asin_rows)
            continue

        latest_key = max(date_key for _, date_key in dated_rows)
        latest_rows.extend(row for row, date_key in dated_rows if date_key == latest_key)

    return latest_rows


def latest_dates_by_asin(rows: list[dict[str, Any]]) -> dict[str, str]:
    latest_dates: dict[str, str] = {}
    for row in rows:
        asin = str(row.get("f_asin") or row.get("asin") or "").upper()
        date_value = crawler_date_value(row)
        if asin and date_value is not None:
            latest_dates[asin] = date_value
    return latest_dates


def crawler_date_value(row: dict[str, Any]) -> str | None:
    for field in CRAWLER_DATE_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def crawler_date_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    value = crawler_date_value(row)
    if value is None:
        return (0, "")

    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return (
            2,
            parsed.year,
            parsed.month,
            parsed.day,
            parsed.hour,
            parsed.minute,
            parsed.second,
            parsed.microsecond,
        )
    except ValueError:
        pass

    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
        try:
            parsed = datetime.strptime(value, fmt)
            return (
                2,
                parsed.year,
                parsed.month,
                parsed.day,
                parsed.hour,
                parsed.minute,
                parsed.second,
                parsed.microsecond,
            )
        except ValueError:
            continue

    return (1, value)


def extract_query_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = [
        (((payload.get("data") or {}).get("result") or {}).get("data")),
        ((payload.get("data") or {}).get("data")),
        payload.get("data"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def seller_sprite_run_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("data")
    if isinstance(nested, dict) and ("job_id" in nested or "export" in nested):
        return nested
    if "job_id" in payload or "export" in payload:
        return payload
    return {}


def seller_sprite_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    run_payload = seller_sprite_run_payload(payload)
    candidates = [
        run_payload.get("data") if run_payload else None,
        run_payload.get("rows") if run_payload else None,
        payload.get("data"),
        payload.get("rows"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def seller_sprite_export_format(export: Any, export_path: str | None) -> str | None:
    if isinstance(export, dict):
        value = export.get("format")
        if isinstance(value, str) and value.strip():
            normalized = value.strip().lower()
            return "xlsx" if normalized == "xls" else normalized
    if export_path:
        suffix = Path(export_path).suffix.lower().lstrip(".")
        if suffix:
            return "xlsx" if suffix == "xls" else suffix
    return None


def compact_seller_sprite_result(result: dict[str, Any], *, inline_rows: bool = True) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result, dict) else None
    data = seller_sprite_run_payload(payload)
    export = data.get("export") if isinstance(data, dict) else {}
    export_path = export.get("path") if isinstance(export, dict) else None
    rows = seller_sprite_rows(payload) or read_export_rows(export_path)
    export_format = seller_sprite_export_format(export, export_path)
    compact = {
        "status": result.get("status", "skipped"),
        "job_id": data.get("job_id") if isinstance(data, dict) else None,
        "row_count": data.get("row_count") if isinstance(data, dict) else None,
        "rows": rows if inline_rows else [],
        "rows_inlined": inline_rows,
        "export_format": export_format,
        "export_path": export_path,
        "export_url": export.get("url") if isinstance(export, dict) else None,
        "command": result.get("command"),
    }
    if result.get("reason"):
        compact["reason"] = result["reason"]
    if result.get("status") == "failed":
        compact["error_message"] = extract_error_message(payload, result.get("stderr", ""))
    return compact


def compact_listing_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = compact_seller_sprite_result(result)
    row = extract_listing_analysis_row(result)
    content = row.get("content") if isinstance(row, dict) else None
    compact.update(
        {
            "task_id": row.get("taskId") or row.get("task_id") if isinstance(row, dict) else None,
            "task_status": row.get("taskStatus") or row.get("task_status") if isinstance(row, dict) else None,
            "completed_time": row.get("completedTime") or row.get("completed_time") if isinstance(row, dict) else None,
            "expired_time": row.get("expiredTime") or row.get("expired_time") if isinstance(row, dict) else None,
            "html_status": row.get("htmlStatus") if isinstance(row, dict) else None,
            "html_content": row.get("htmlContent") if isinstance(row, dict) else None,
            "content": parse_content_payload(content),
        }
    )
    return compact


def extract_listing_analysis_row(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result, dict) else None
    rows = seller_sprite_rows(payload)
    if rows:
        return rows[0]

    run_payload = seller_sprite_run_payload(payload)
    export = run_payload.get("export") if isinstance(run_payload, dict) else {}
    export_path = export.get("path") if isinstance(export, dict) else None
    for row in read_export_rows(export_path):
        return row
    return {}


def read_export_rows(export_path: str | None) -> list[dict[str, Any]]:
    payload = read_export_payload(export_path)
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) and isinstance(payload, dict):
        rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def read_export_payload(export_path: str | None) -> dict[str, Any]:
    if not export_path:
        return {}
    path = Path(export_path).expanduser()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_content_payload(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    value = content.strip()
    if not value:
        return content
    try:
        return json.loads(value)
    except Exception:
        return content


def compact_amazon_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else {}
    snapshot = data if isinstance(data, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("snapshot"), dict):
        snapshot = data["snapshot"]
    compact = {
        "status": result.get("status", "skipped"),
        "product_name": snapshot.get("product_name"),
        "price_amount": snapshot.get("price_amount"),
        "rating_value": snapshot.get("rating_value"),
        "review_count_value": snapshot.get("review_count_value"),
        "valid": snapshot.get("valid"),
        "command": result.get("command"),
    }
    if result.get("reason"):
        compact["reason"] = result["reason"]
    if result.get("status") == "failed":
        compact["error_message"] = extract_error_message(payload, result.get("stderr", ""))
    return compact


def compact_rufus_result(
    result: dict[str, Any],
    *,
    asin: str,
    country: str,
    questions: list[str],
    remote_consent: dict[str, Any] | None = None,
    login_status: dict[str, Any] | None = None,
    watch_login: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = result.get("status", "skipped") if isinstance(result, dict) else "skipped"
    report_path = extract_rufus_report_path(result.get("stdout", "") if isinstance(result, dict) else "")
    answers = parse_rufus_report(report_path)
    compact: dict[str, Any] = {
        "status": status,
        "asin": asin,
        "country": country,
        "questions": questions,
        "question_count": len(questions),
        "answer_count": len(answers),
        "answers": answers,
        "report_path": report_path,
        "command": result.get("command") if isinstance(result, dict) else None,
    }
    if remote_consent:
        compact["remote_consent"] = remote_consent
    if login_status:
        compact["login_status"] = login_status
    if watch_login:
        compact["watch_login"] = watch_login
    if isinstance(result, dict) and result.get("reason"):
        compact["reason"] = result["reason"]
    if status == "failed":
        compact["error_message"] = extract_error_message(result.get("json"), result.get("stderr", ""))
    if status == "success" and not report_path:
        compact["status"] = "failed"
        compact["reason"] = "Rufus report path was not found in CLI output"
    return compact


def extract_rufus_report_path(stdout: str) -> str | None:
    match = RUFUS_REPORT_PATH_PATTERN.search(stdout or "")
    if not match:
        return None
    return match.group(1).strip()


def parse_rufus_report(report_path: str | None) -> list[dict[str, Any]]:
    if not report_path:
        return []
    path = Path(report_path).expanduser()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception:
        return []
    return parse_rufus_report_text(text)


def parse_rufus_report_text(text: str) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_field: str | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        for key, value in list(current.items()):
            if isinstance(value, list) and key not in {"related_products", "recommended_asins"}:
                current[key] = "\n".join(value).strip()
        current["related_products"] = clean_markdown_items(current.get("related_products"))
        current["recommended_asins"] = clean_markdown_items(current.get("recommended_asins"))
        answers.append(current)
        current = None

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        question_match = re.match(r"^##\s+第\s*(\d+)\s*题[:：]\s*(.+?)\s*$", line)
        if question_match:
            flush_current()
            current = {
                "index": int(question_match.group(1)),
                "question": question_match.group(2).strip(),
                "related_products": [],
                "answer": [],
                "recommended_asins": [],
                "summary": [],
            }
            current_field = None
            continue
        if current is None:
            continue
        heading_match = re.match(r"^###\s+(.+?)\s*$", line)
        if heading_match:
            heading = heading_match.group(1).strip()
            current_field = {
                "相关产品": "related_products",
                "答案": "answer",
                "推荐 ASIN": "recommended_asins",
                "推荐ASIN": "recommended_asins",
                "总结": "summary",
            }.get(heading)
            continue
        if not current_field:
            continue
        if current_field in {"related_products", "recommended_asins"}:
            if line.strip():
                current[current_field].append(line.strip())
        else:
            current[current_field].append(line)

    flush_current()
    return answers


def clean_markdown_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        cleaned.append(re.sub(r"^\s*[-*]\s*", "", text).strip())
    return cleaned


def derive_keyword_from_reverse(result: dict[str, Any]) -> str:
    keywords = derive_keywords_from_reverse(result, max_count=1)
    return keywords[0] if keywords else ""


def derive_keywords_from_reverse(result: dict[str, Any], *, max_count: int) -> list[str]:
    payload = result.get("json") if isinstance(result, dict) else None
    rows = seller_sprite_rows(payload)
    keywords: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("keyword", "keywords", "word", "query", "关键词", "搜索词"):
            for value in normalize_keywords(row.get(key)):
                dedupe_key = value.casefold()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                keywords.append(value)
                if len(keywords) >= max(max_count, 1):
                    return keywords
    return keywords


def collect_status_errors(group: str, name: str, payload: Any, errors: list[dict[str, Any]]) -> None:
    if not isinstance(payload, dict):
        return
    if payload.get("status") in {"failed", "partial"}:
        error = {"source": f"{group}.{name}", "status": payload.get("status")}
        if payload.get("reason"):
            error["reason"] = payload["reason"]
        errors.append(error)


def aggregate_status(items: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in items}
    if not items:
        return "skipped"
    if statuses == {"success"}:
        return "success"
    if "success" in statuses:
        return "partial"
    if "planned" in statuses:
        return "planned"
    return "failed"


def build_frontend_record(result: dict[str, Any]) -> dict[str, Any]:
    query = result.get("query") or {}
    seller_sprite = result.get("seller_sprite") or {}
    input_payload = result.get("input") or {}
    rufus = result.get("rufus") or {}
    return {
        "基础数据": {
            "ASIN": result.get("asin"),
            "站点": result.get("site"),
            "输入关键词": input_payload.get("keyword") or "",
            "输入关键词列表": input_payload.get("keywords") or [],
            "关键词数量": input_payload.get("keyword_count") or len(input_payload.get("keywords") or []),
            "关键词来源": keyword_source_zh(input_payload.get("keyword_source")),
            "输入行号": input_payload.get("row_index"),
            "来源文件": input_payload.get("source_file"),
            "BI销售数据": localize_rows_source(query.get("sales"), localize_sales_row),
            "爬虫Listing数据": localize_rows_source(query.get("crawler_listing"), localize_crawler_row),
            "错误列表": localize_errors(result.get("errors") or [], exclude_sources={"amazon.scrape"}),
        },
        "卖家精灵关键词数据": {
            "关键词输入": localize_keyword_input(input_payload),
            "关键词反查": localize_seller_sprite_job(seller_sprite.get("keyword_reverse")),
            "关键词挖掘": localize_keyword_miner(seller_sprite.get("keyword_miner")),
        },
        "卖家精灵AI全景分析数据": localize_listing_analysis(seller_sprite.get("listing_analysis")),
        "Alexa优化建议数据": localize_rufus_data(rufus),
    }


def build_frontend_bundle(summary: dict[str, Any], asin_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "运行信息": {
            "运行ID": summary.get("run_id"),
            "开始时间": summary.get("started_at"),
            "结束时间": summary.get("finished_at"),
            "输出目录": summary.get("output_dir"),
            "是否DryRun": summary.get("dry_run"),
            "ASIN数量": (summary.get("summary") or {}).get("asin_count"),
            "失败ASIN数量": (summary.get("summary") or {}).get("failed_asin_count"),
        },
        "数据": [item.get("frontend_data") or build_frontend_record(item) for item in asin_results],
    }


def render_frontend_markdown(frontend_bundle: dict[str, Any]) -> str:
    info = frontend_bundle.get("运行信息") or {}
    lines = [
        "# ASIN取数完整数据",
        "",
        "## 运行信息",
        "",
        f"- 运行ID：{info.get('运行ID') or ''}",
        f"- 开始时间：{info.get('开始时间') or ''}",
        f"- 结束时间：{info.get('结束时间') or ''}",
        f"- 输出目录：{info.get('输出目录') or ''}",
        f"- ASIN数量：{info.get('ASIN数量') or 0}",
        f"- 失败ASIN数量：{info.get('失败ASIN数量') or 0}",
        "",
        "## 数据结构",
        "",
        "每个 ASIN 固定返回四段：",
        "",
        "- `基础数据`：中文字段，包含输入信息、BI 销售、爬虫 Listing 和错误列表。",
        "- `卖家精灵关键词数据`：关键词反查和关键词挖掘任务信息。",
        "- `卖家精灵AI全景分析数据`：直接返回 SellerSprite AI 全景分析的完整 `content`。",
        "- `Alexa优化建议数据`：Amazon Alexa 问答数据、报告路径和答案明细。",
        "",
        "## ASIN汇总",
        "",
        "| ASIN | 站点 | 输入关键词 | 基础数据 | 关键词数据 | AI全景分析 | Alexa |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    records = frontend_bundle.get("数据") or []
    for item in records:
        base = item.get("基础数据") or {}
        keyword = item.get("卖家精灵关键词数据") or {}
        ai = item.get("卖家精灵AI全景分析数据") or {}
        rufus = item.get("Alexa优化建议数据") or {}
        lines.append(
            "| {asin} | {site} | {input_keywords} | {base_status} | {keyword_status} | {ai_status} | {rufus_status} |".format(
                asin=base.get("ASIN") or "",
                site=base.get("站点") or "",
                input_keywords=", ".join(base.get("输入关键词列表") or []),
                base_status=source_status_zh(base.get("错误列表"), success_text="已返回"),
                keyword_status=status_zh((keyword.get("关键词反查") or {}).get("原始状态")),
                ai_status=ai.get("状态") or "",
                rufus_status=rufus.get("状态") or "",
            )
        )

    for index, item in enumerate(records, start=1):
        base = item.get("基础数据") or {}
        keyword = item.get("卖家精灵关键词数据") or {}
        ai = item.get("卖家精灵AI全景分析数据") or {}
        rufus = item.get("Alexa优化建议数据") or {}
        lines.extend(
            [
                "",
                f"## {index}. ASIN {base.get('ASIN') or ''}",
                "",
                "### 基础数据",
                "",
            ]
        )
        lines.extend(render_key_value_list(base, exclude={"BI销售数据", "爬虫Listing数据", "错误列表"}))
        lines.extend(
            [
                "",
                "#### BI销售数据",
                "",
                json_block(base.get("BI销售数据")),
                "",
                "#### 爬虫Listing数据",
                "",
                json_block(base.get("爬虫Listing数据")),
                "",
                "#### 错误列表",
                "",
                json_block(base.get("错误列表") or []),
                "",
                "### 卖家精灵关键词数据",
                "",
                "#### 关键词反查",
                "",
                json_block(keyword.get("关键词反查")),
                "",
                "#### 关键词挖掘",
                "",
                json_block(keyword.get("关键词挖掘")),
                "",
                "### 卖家精灵AI全景分析数据",
                "",
            ]
        )
        lines.extend(render_key_value_list(ai, exclude={"content", "html内容", "命令"}))
        lines.extend(
            [
                "",
                "#### content",
                "",
                json_block(ai.get("content")),
                "",
                "### Alexa优化建议数据",
                "",
                json_block(rufus),
                "",
            ]
        )

    lines.extend(["", "完整机器可读 JSON 数据见同目录 `frontend-data.json`。", ""])
    return "\n".join(lines)


def render_key_value_list(payload: dict[str, Any], *, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    lines = []
    for key, value in payload.items():
        if key in exclude:
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"- {key}：")
            lines.append(json_block(value))
        else:
            lines.append(f"- {key}：{'' if value is None else value}")
    return lines


def json_block(payload: Any) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"


def localize_seller_sprite_job(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "结果数据": []}
    export_path = payload.get("export_path")
    export_url = payload.get("export_url")
    export_format = str(payload.get("export_format") or "").lower()
    if not export_format and isinstance(export_path, str):
        export_format = Path(export_path).suffix.lower().lstrip(".")
    is_spreadsheet = export_format in {"xls", "xlsx"}
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else read_export_rows(export_path)
    if is_spreadsheet:
        rows = []
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "任务ID": payload.get("job_id"),
        "行数": payload.get("row_count"),
        "结果数据": rows,
    }
    if is_spreadsheet:
        data["导出格式"] = "xlsx"
        data["导出路径"] = export_path
        data["导出URL"] = export_url
        data["数据说明"] = "明细已导出为 Excel，MD 不内嵌完整明细。"
    if payload.get("reason") and payload.get("status") != "success":
        data["原因"] = payload.get("reason")
    if payload.get("error_message") and payload.get("status") != "success":
        data["错误信息"] = payload.get("error_message")
    return data

def localize_keyword_input(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "关键词列表": [], "关键词数量": 0}
    keywords = normalize_keywords(payload.get("keywords") or payload.get("keyword") or "")
    status = "success" if keywords else "skipped"
    return {
        "状态": status_zh(status),
        "原始状态": status,
        "关键词来源": keyword_source_zh(payload.get("keyword_source")),
        "关键词列表": keywords,
        "关键词数量": len(keywords),
    }


def localize_keyword_miner(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "种子关键词": [], "任务列表": []}
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "种子关键词": payload.get("seed_keywords") or [],
        "任务列表": [localize_seller_sprite_job(job) for job in jobs],
    }
    if payload.get("reason") and payload.get("status") != "success":
        data["原因"] = payload.get("reason")
    if payload.get("error_message") and payload.get("status") != "success":
        data["错误信息"] = payload.get("error_message")
    return data


def localize_listing_analysis(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "content": None}
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "任务ID": payload.get("job_id"),
        "报告任务ID": payload.get("task_id"),
        "报告状态": payload.get("task_status"),
        "完成时间": payload.get("completed_time"),
        "过期时间": payload.get("expired_time"),
        "content": payload.get("content"),
        "html状态": payload.get("html_status"),
        "html内容": payload.get("html_content"),
    }
    if payload.get("reason") and payload.get("status") != "success":
        data["原因"] = payload.get("reason")
    if payload.get("error_message") and payload.get("status") != "success":
        data["错误信息"] = payload.get("error_message")
    return data


def localize_rufus_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "接入状态": "已接入", "数据": []}
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "接入状态": "已接入",
        "国家站点": payload.get("country"),
        "问题列表": payload.get("questions") or [],
        "问题数量": payload.get("question_count") or len(payload.get("questions") or []),
        "答案数量": payload.get("answer_count") or len(payload.get("answers") or []),
        "报告路径": payload.get("report_path"),
        "数据": [localize_rufus_answer(answer) for answer in (payload.get("answers") or []) if isinstance(answer, dict)],
    }
    if payload.get("reason") and payload.get("status") != "success":
        data["原因"] = payload.get("reason")
    if payload.get("error_message") and payload.get("status") != "success":
        data["错误信息"] = payload.get("error_message")
    return data


def localize_rufus_answer(answer: dict[str, Any]) -> dict[str, Any]:
    return {
        "题号": answer.get("index"),
        "问题": answer.get("question"),
        "相关产品": answer.get("related_products") or [],
        "答案": answer.get("answer") or "",
        "推荐ASIN": answer.get("recommended_asins") or [],
        "总结": answer.get("summary") or "",
    }


def localize_amazon_scrape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped"}
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "商品名称": payload.get("product_name"),
        "价格": payload.get("price_amount"),
        "评分": payload.get("rating_value"),
        "评论数": payload.get("review_count_value"),
        "是否有效": payload.get("valid"),
        "命令": payload.get("command"),
    }
    if payload.get("reason"):
        data["原因"] = payload.get("reason")
    if payload.get("error_message"):
        data["错误信息"] = payload.get("error_message")
    return data


def localize_rows_source(payload: Any, row_mapper: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"状态": "跳过", "原始状态": "skipped", "行数": 0, "明细": []}
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    data = {
        "状态": status_zh(payload.get("status")),
        "原始状态": payload.get("status"),
        "行数": payload.get("row_count", len(rows)),
        "明细": [row_mapper(row) for row in rows],
    }
    if payload.get("reason"):
        data["原因"] = payload.get("reason")
    return data


def localize_sales_row(row: dict[str, Any]) -> dict[str, Any]:
    localized: dict[str, Any] = {}
    for field_name, label in SALES_FIELD_LABELS.items():
        for key in (field_name, f"f_{field_name}"):
            if key in row:
                localized[label] = row.get(key)
                break
    if "f_sales_amount" in row:
        localized["销售额"] = row.get("f_sales_amount")
    return localized


def localize_crawler_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ASIN": row.get("f_asin") or row.get("asin"),
        "快照日期": row.get("f_date_id") or row.get("date_id"),
        "国家": row.get("f_country") or row.get("country"),
        "币种": row.get("f_currency") or row.get("currency"),
        "产品名称": row.get("f_product_name") or row.get("listing"),
        "商品链接": row.get("f_link") or row.get("link"),
        "主图": row.get("f_image") or row.get("image"),
        "A+图片": row.get("f_a_image") or row.get("a_image"),
        "A+文案": row.get("f_a_description") or row.get("a_description"),
        "产品详情": row.get("f_product_details") or row.get("product_details"),
        "五点描述": row.get("f_five_point_description") or row.get("five_point_description"),
        "QA": row.get("f_qa") or row.get("qa"),
        "评论": row.get("f_review_list") or row.get("review_list"),
        "星级": row.get("f_rating") or row.get("rating"),
        "划线价": row.get("f_original_price") or row.get("original_price"),
        "售价": row.get("f_price") or row.get("price"),
        "折扣百分比": row.get("f_reduction") or row.get("reduction"),
        "评论数": row.get("f_review_count") or row.get("review_count"),
        "描述": row.get("f_description") or row.get("description"),
        "品牌": row.get("f_brand") or row.get("brand"),
        "卖家ID": row.get("f_seller_id") or row.get("seller_id"),
        "到手价文案": row.get("f_price_scribe") or row.get("price_scribe"),
        "单价": row.get("f_unit_price") or row.get("unit_price"),
        "优惠券": row.get("f_coupon") or row.get("coupon"),
        "促销码金额": row.get("f_promo_code_value") or row.get("promo_code_value"),
        "促销码": row.get("f_promo_code") or row.get("promo_code"),
        "Deal": row.get("f_deal") or row.get("deal"),
        "大类名称": row.get("f_major_name") or row.get("major_name"),
        "大类排名": row.get("f_major_rank") or row.get("major_rank"),
        "小类名称": row.get("f_subclass_name") or row.get("subclass_name"),
        "小类排名": row.get("f_subclass_rank") or row.get("subclass_rank"),
        "Deal类型": row.get("f_deal_type") or row.get("deal_type"),
        "评分数": row.get("f_rating_count") or row.get("rating_count"),
        "库存数": row.get("f_stock_qty") or row.get("stock_qty"),
        "销售状态": row.get("f_sales_status") or row.get("sales_status"),
        "是否有库存": row.get("f_in_stock") or row.get("in_stock"),
        "子图数量": row.get("f_subplot_count") or row.get("subplot_count"),
        "视频数量": row.get("f_video_count") or row.get("video_count"),
        "五点描述数量": row.get("f_five_point_description_count") or row.get("five_point_description_count"),
        "A+图片数量": row.get("f_a_image_count") or row.get("a_image_count"),
        "变体数量": row.get("f_variant_count") or row.get("variant_count"),
        "CS数量": row.get("f_cs_count") or row.get("cs_count"),
        "QA数量": row.get("f_qa_count") or row.get("qa_count"),
        "时间戳": row.get("f_timestamp") or row.get("timestamp"),
    }


def localize_errors(errors: list[dict[str, Any]], *, exclude_sources: set[str] | None = None) -> list[dict[str, Any]]:
    exclude_sources = exclude_sources or set()
    localized = []
    for error in errors:
        if error.get("source") in exclude_sources:
            continue
        localized.append(
            {
                "来源": error.get("source"),
                "状态": status_zh(error.get("status")),
                "原始状态": error.get("status"),
                "原因": error.get("reason") or error.get("error_message"),
            }
        )
    return localized


def status_zh(status: Any) -> str:
    return STATUS_ZH.get(str(status or "").strip(), str(status or "未知"))


def keyword_source_zh(source: Any) -> str:
    return KEYWORD_SOURCE_ZH.get(str(source or "").strip(), str(source or "未提供"))


def source_status_zh(errors: Any, *, success_text: str) -> str:
    if isinstance(errors, list) and errors:
        return "有错误"
    return success_text


def build_summary(
    records: list[dict[str, Any]],
    asin_results: list[dict[str, Any]],
    input_errors: list[dict[str, Any]],
    output_root: Path,
    started_at: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    failed_asins = [item["asin"] for item in asin_results if item.get("errors")]
    source_error_count = sum(len(item.get("errors") or []) for item in asin_results)
    return {
        "run_id": output_root.name,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(output_root),
        "dry_run": args.dry_run,
        "summary": {
            "input_count": len(records),
            "asin_count": len(asin_results),
            "input_error_count": len(input_errors),
            "source_error_count": source_error_count,
            "failed_asin_count": len(failed_asins),
            "failed_asins": failed_asins,
        },
        "options": {
            "asin_column": args.asin_column,
            "keyword_column": args.keyword_column,
            "site_column": args.site_column,
            "skip_seller_sprite": args.skip_seller_sprite,
            "skip_keyword_miner": args.skip_keyword_miner,
            "skip_listing_analysis": args.skip_listing_analysis,
            "skip_amazon": args.skip_amazon,
            "skip_query": args.skip_query,
            "skip_sales_query": args.skip_sales_query,
            "skip_crawler_query": args.skip_crawler_query,
            "skip_rufus": args.skip_rufus,
            "seller_sprite_period": args.seller_sprite_period,
            "keyword_source": args.keyword_source,
            "max_miner_keywords": args.max_miner_keywords,
            "listing_analysis_station": args.listing_analysis_station,
            "rufus_country": args.rufus_country,
            "rufus_questions": rufus_questions(args),
            "rufus_skills_dir": args.rufus_skills_dir,
            "rufus_timeout_seconds": args.rufus_timeout_seconds,
            "skip_rufus_login_recovery": args.skip_rufus_login_recovery,
            "sales_start": args.sales_start,
            "sales_end": args.sales_end,
            "query_chunk_size": args.query_chunk_size,
        },
        "files": {
            "manifest": str(output_root / "manifest.json"),
            "results": str(output_root / "asin-data.jsonl"),
            "frontend_data": str(output_root / "frontend-data.json"),
            "frontend_markdown": str(output_root / "frontend-data.md"),
            "summary": str(output_root / "asin-data-summary.json"),
            "commands": str(output_root / "commands.jsonl"),
            "errors": str(output_root / "errors.jsonl"),
        },
    }


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.strip())[:60] or "keyword"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8-sig")


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def write(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
