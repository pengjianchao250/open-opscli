"""Render single-ASIN data packages as merged operator reports."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


BI_REPORT_SOURCE_ORDER = (
    ("sales_traffic", "销售/库存/广告/流量数据"),
    ("sp_search_term", "SP广告搜索词数据"),
    ("deals", "活动数据"),
    ("turnover_inventory", "物控版库存数据"),
)

BI_REPORT_TABLE_COLUMNS = {
    "sales_traffic": (
        "ASIN",
        "公司SKU",
        "渠道SKU",
        "产品名称",
        "渠道",
        "销售",
        "订单销量",
        "销售额",
        "毛利",
        "毛利率",
        "可售周转",
        "总库存",
        "平台库存",
        "海外仓库存",
        "在途库存",
        "广告费",
        "广告销量",
        "广告销售额",
        "点击量",
        "曝光量",
        "点击率",
        "CPC转化率",
        "ACOS",
        "平均CPC",
        "流量",
        "浏览量",
        "转化率",
    ),
    "sp_search_term": (
        "渠道",
        "ASIN组",
        "广告活动",
        "广告组",
        "关键投放词",
        "搜索词",
        "搜索词类型",
        "匹配投放类型",
        "曝光量",
        "点击量",
        "点击率",
        "花费",
        "平均CPC",
        "广告订单量",
        "广告销售额",
        "ROAS",
        "ACOS",
        "转化率",
        "广告直接订单量",
        "广告直接销售额",
        "广告直接销量",
        "广告间接订单量",
        "广告间接销售额",
        "广告间接销量",
        "广告销量",
    ),
    "deals": (
        "ASIN",
        "公司SKU",
        "渠道SKU",
        "产品名称",
        "活动名称",
        "活动类型",
        "活动状态",
        "开始时间",
        "结束时间",
        "报名价格",
        "活动价格",
        "销量",
        "销售额",
        "费用",
    ),
    "turnover_inventory": (
        "快照日期",
        "物控编码",
        "公司SKU",
        "产品名称",
        "采购周期",
        "FBA可售库存",
        "FBA不可售库存",
        "walmart可售库存",
        "wayfair可售库存",
        "小平台可售库存",
        "二程在途库存",
        "海外仓库存",
        "头程空运在途库存",
        "头程海运在途库存",
        "国内中转仓库存",
        "采购订单在途库存",
        "24小时销量",
        "7天销量",
        "30天销量",
        "90天销量",
        "180天销量",
        "365天销量",
        "平均日销量",
        "平台周转天数",
        "海外周转天数",
        "库存周转天数",
        "采购在途周转天数",
        "总周转天数_含采购",
    ),
}


def render_merged_report_text(
    asin_result: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
    output_root: Path | None = None,
) -> str:
    """Render the single-ASIN report format used by ops_asin_data_report_files."""
    record = build_merged_report_record(asin_result, summary=summary, output_root=output_root)
    return build_report_text(record)


def build_merged_report_record(
    asin_result: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    summary = summary or {}
    asin = normalize_asin(asin_result.get("asin"))
    site = normalize_site(asin_result.get("site"))
    query = asin_result.get("query") if isinstance(asin_result.get("query"), dict) else {}
    seller_sprite = (
        asin_result.get("seller_sprite")
        if isinstance(asin_result.get("seller_sprite"), dict)
        else {}
    )
    rufus = asin_result.get("rufus") if isinstance(asin_result.get("rufus"), dict) else {}
    bi_report_data = (
        asin_result.get("bi_report_data")
        if isinstance(asin_result.get("bi_report_data"), dict)
        else {}
    )
    bi_report_sources = normalized_bi_report_sources(bi_report_data)

    sales_section = query.get("sales") if isinstance(query.get("sales"), dict) else {}
    crawler_section = (
        query.get("crawler_listing") if isinstance(query.get("crawler_listing"), dict) else {}
    )
    sales_row = first_row(sales_section)
    sales_traffic_section = (
        bi_report_sources.get("sales_traffic")
        if isinstance(bi_report_sources.get("sales_traffic"), dict)
        else {}
    )
    crawler_details_section = (
        bi_report_sources.get("crawler_details")
        if isinstance(bi_report_sources.get("crawler_details"), dict)
        else {}
    )
    listing_basic_section = (
        bi_report_sources.get("listing_basic")
        if isinstance(bi_report_sources.get("listing_basic"), dict)
        else {}
    )
    sales_traffic_row = first_row(sales_traffic_section)
    bi_sales_row = sales_traffic_row or sales_row
    crawler_details_row = first_row(crawler_details_section)
    crawler_row = crawler_details_row or first_row(crawler_section)
    listing_basic_row = first_row(listing_basic_section)
    product_details = crawler_row.get("产品详情") if isinstance(crawler_row.get("产品详情"), dict) else {}

    keyword_miner = (
        seller_sprite.get("keyword_miner")
        if isinstance(seller_sprite.get("keyword_miner"), dict)
        else {}
    )
    listing_analysis = (
        seller_sprite.get("listing_analysis")
        if isinstance(seller_sprite.get("listing_analysis"), dict)
        else {}
    )
    keyword_raw_results = load_seller_sprite_run_results(
        output_root=output_root,
        asin=asin,
        pattern="seller-sprite-keyword-miner-*.json",
    )

    keyword_rows: list[dict[str, Any]] = []
    keyword_excel_url = None
    keyword_excel_path = None
    keyword_full_result = (
        keyword_miner.get("full_result")
        if isinstance(keyword_miner.get("full_result"), dict)
        else None
    )
    if keyword_full_result:
        rows = keyword_full_result.get("data")
        if isinstance(rows, list):
            keyword_rows.extend(row for row in rows if isinstance(row, dict))
        export = (
            keyword_full_result.get("export")
            if isinstance(keyword_full_result.get("export"), dict)
            else {}
        )
        keyword_excel_url = keyword_excel_url or export.get("url")
        keyword_excel_path = keyword_excel_path or export.get("path")
    for result in keyword_raw_results:
        rows = result.get("data")
        if isinstance(rows, list):
            keyword_rows.extend(row for row in rows if isinstance(row, dict))
        export = result.get("export") if isinstance(result.get("export"), dict) else {}
        keyword_excel_url = keyword_excel_url or export.get("url")
        keyword_excel_path = keyword_excel_path or export.get("path")

    keyword_jobs = keyword_miner.get("jobs") if isinstance(keyword_miner.get("jobs"), list) else []
    for job in keyword_jobs:
        if not isinstance(job, dict):
            continue
        keyword_rows.extend(row for row in job.get("rows") or [] if isinstance(row, dict))
        keyword_excel_url = keyword_excel_url or job.get("export_url")
        keyword_excel_path = keyword_excel_path or job.get("export_path")

    generated_at = (
        summary.get("finished_at")
        or summary.get("generated_at")
        or datetime.now().isoformat(timespec="seconds")
    )
    files = summary.get("files") if isinstance(summary.get("files"), dict) else {}

    return {
        "asin": asin,
        "site": site,
        "generated_at": generated_at,
        "run_id": summary.get("run_id") or "",
        "query_run_id": summary.get("query_run_id") or summary.get("run_id") or "",
        "bi_sales": {
            "status": first_status(sales_traffic_section, sales_section),
            "row_count": first_count(sales_traffic_section, sales_section),
            "product_name": first_value(bi_sales_row, "f_product_name", "product_name", "productName", "产品名称", "品名"),
            "order_qty": first_value(bi_sales_row, "f_order_qty", "order_qty", "orderQty", "sales_qty", "salesQty", "订单量", "销量"),
            "orders": first_value(bi_sales_row, "f_orders", "orders", "order_count", "orderCount", "订单数"),
            "sessions": first_value(bi_sales_row, "f_sessions", "sessions", "Sessions", "session", "流量"),
            "page_views": first_value(bi_sales_row, "f_page_views", "page_views", "pageViews", "Page Views", "浏览量"),
            "original_price": first_value(bi_sales_row, "f_original_price", "original_price", "originalPrice", "原价销售额"),
            "sales_amount": first_value(bi_sales_row, "f_sales_amount", "sales_amount", "salesAmount", "amount", "销售额"),
            "advertising_fee": first_value(bi_sales_row, "f_advertising_fee", "advertising_fee", "advertisingFee", "ad_cost", "adCost", "spend", "广告费", "广告花费"),
            "ads_sales_cny": first_value(bi_sales_row, "f_ads_sales_cny", "ads_sales_cny", "adsSalesCny", "ad_sales", "adSales", "广告销售额(CNY)", "广告销售额"),
            "ads_clicks": first_value(bi_sales_row, "f_ads_clicks", "ads_clicks", "adsClicks", "clicks", "广告点击量", "广告点击"),
            "ads_impressions": first_value(bi_sales_row, "f_ads_impressions", "ads_impressions", "adsImpressions", "impressions", "广告曝光量", "广告曝光"),
            "refund": first_value(bi_sales_row, "f_refund", "refund", "refund_amount", "refundAmount", "退款金额"),
            "raw_row": bi_sales_row,
            "legacy_raw_row": sales_row if sales_traffic_row else None,
        },
        "bi_report_sources": bi_report_sources,
        "listing_basic": {
            "status": listing_basic_section.get("status"),
            "row_count": listing_basic_section.get("row_count"),
            "row": listing_basic_row,
            "channel": first_value(listing_basic_row, "渠道"),
            "platform_sku": first_value(listing_basic_row, "平台SKU"),
            "company_sku": first_value(listing_basic_row, "公司SKU"),
            "amazon_status": first_value(listing_basic_row, "亚马逊状态"),
            "fulfillment": first_value(listing_basic_row, "发货方式"),
            "category": first_value(listing_basic_row, "类目"),
            "title": first_value(listing_basic_row, "商品标题"),
            "brand": first_value(listing_basic_row, "品牌"),
            "main_image": first_value(listing_basic_row, "主图链接"),
            "other_images": as_list(first_value(listing_basic_row, "其他附图链接")),
            "bullets": as_list(first_value(listing_basic_row, "五点描述")),
            "search_terms": first_value(listing_basic_row, "关键词搜索", "generic_keyword.value"),
            "listid": first_value(listing_basic_row, "listid"),
        },
        "crawler_basic": {
            "status": first_status(crawler_details_section, crawler_section),
            "row_count": first_count(crawler_details_section, crawler_section),
            "date": first_value(crawler_row, "日期", "date_id", "f_date_id"),
            "title": first_value(crawler_row, "商品标题", "listing", "f_listing", "title", "productTitle", "itemTitle", "标题"),
            "brand": first_value(product_details, "Brand", "Brand Name", "品牌")
            or first_value(crawler_row, "品牌", "brand", "f_brand"),
            "categories": as_list(first_value(crawler_row, "类目", "categories", "f_categories")),
            "main_image": first_value(crawler_row, "主图", "image", "f_image", "main_image", "mainImage", "image_url", "imageUrl"),
            "subplot": as_list(first_value(crawler_row, "副图", "subplot", "f_subplot")),
            "price_list": as_list(first_value(crawler_row, "价格列表", "price_list", "f_price_list", "price", "salePrice", "selling_price")),
            "five_point_description": as_list(
                first_value(crawler_row, "五点描述", "five_point_description", "f_five_point_description", "bullet_points", "bulletPoints", "features", "五点")
            ),
            "description": first_value(crawler_row, "商品描述", "description", "f_description", "product_description", "productDescription") or "",
            "a_image": as_list(first_value(crawler_row, "A+图片", "a_image", "f_a_image", "a_plus_images", "aplus_images")),
            "a_description": as_list(first_value(crawler_row, "A+文案", "a_description", "f_a_description", "a_plus_description", "aplus_description")),
            "qa": as_list(first_value(crawler_row, "QA", "qa", "f_qa", "qa_list", "questions_answers")),
            "review_list": as_list(first_value(crawler_row, "评论列表", "review_list", "f_review_list", "reviews", "reviewList")),
            "product_details": product_details,
            "rating": first_value(crawler_row, "星级评分", "rating", "f_rating"),
            "rating_count": first_value(crawler_row, "评分数量", "rating_count", "f_rating_count"),
            "review_count": first_value(crawler_row, "评论数量", "review_count", "f_review_count"),
            "bullet_count": first_value(
                crawler_row,
                "五点描述数量",
                "five_point_description_count",
                "f_five_point_description_count",
            ),
            "subplot_count": first_value(crawler_row, "副图数量", "subplot_count", "f_subplot_count"),
            "video_count": first_value(crawler_row, "视频数量", "video_count", "f_video_count"),
            "a_image_count": first_value(crawler_row, "A+图片数量", "a_image_count", "f_a_image_count"),
            "variant_count": first_value(crawler_row, "变体数量", "variant_count", "f_variant_count"),
            "major_rank": first_value(crawler_row, "大类排名", "major_rank", "f_major_rank"),
            "subclass_rank": first_value(crawler_row, "小类排名", "subclass_rank", "f_subclass_rank"),
            "country": first_value(crawler_row, "国家", "country", "f_country"),
            "currency": first_value(crawler_row, "币种", "currency", "f_currency"),
            "link": first_value(crawler_row, "商品链接", "link", "f_link"),
            "raw_row": crawler_row,
        },
        "seller_sprite_keyword_miner": {
            "status": keyword_miner.get("status") or "skipped",
            "seed_keyword": first_seed_keyword(keyword_miner),
            "row_count": keyword_row_count(keyword_miner, keyword_raw_results, keyword_rows),
            "excel_path": safe_path(keyword_excel_path),
            "excel_url": keyword_excel_url,
            "top_keywords": top_keywords(keyword_rows, 10),
            "full_result": full_keyword_result(keyword_miner, keyword_raw_results),
        },
        "seller_sprite_listing_analysis": listing_analysis_summary(listing_analysis),
        "rufus": rufus_summary(rufus),
        "source_files": {
            "query_asin_data_jsonl": files.get("results"),
            "query_frontend_json": files.get("frontend_data"),
            "asin_report_txt": files.get("asin_report_txt"),
            "asin_report_upload_url": files.get("asin_report_upload_url"),
            "keyword_miner_excel_url": keyword_excel_url,
        },
    }


def build_report_text(record: dict[str, Any]) -> str:
    sales = record["bi_sales"]
    listing_basic = record.get("listing_basic") if isinstance(record.get("listing_basic"), dict) else {}
    crawler = record["crawler_basic"]
    keyword = record["seller_sprite_keyword_miner"]
    listing = record["seller_sprite_listing_analysis"]
    rufus = record["rufus"]
    source_files = record["source_files"]
    bi_sources = record.get("bi_report_sources") if isinstance(record.get("bi_report_sources"), dict) else {}

    lines: list[str] = []
    lines.append(f"# ASIN 取数汇总报告 - {record['asin']}")
    lines.append("")
    lines.append(f"- 站点: {record['site']}")
    lines.append(f"- 汇总运行ID: {record.get('run_id') or ''}")
    lines.append(f"- Query运行ID: {record.get('query_run_id') or ''}")
    lines.append(f"- 生成时间: {record['generated_at']}")
    lines.append("")
    lines.append("## BI 数据")
    lines.append("")
    lines.append(f"- 状态: {sales.get('status')}")
    lines.append(f"- 行数: {sales.get('row_count')}")
    lines.append(f"- 产品名称: {fmt(sales.get('product_name'))}")
    lines.append(f"- 订单量: {fmt(sales.get('order_qty'))}")
    lines.append(f"- 订单数: {fmt(sales.get('orders'))}")
    lines.append(f"- Sessions: {fmt(sales.get('sessions'))}")
    lines.append(f"- Page Views: {fmt(sales.get('page_views'))}")
    lines.append(f"- 销售额: {fmt(sales.get('sales_amount'))}")
    lines.append(f"- 原价销售额: {fmt(sales.get('original_price'))}")
    lines.append(f"- 广告花费: {fmt(sales.get('advertising_fee'))}")
    lines.append(f"- 广告销售额(CNY): {fmt(sales.get('ads_sales_cny'))}")
    lines.append(f"- 广告点击: {fmt(sales.get('ads_clicks'))}")
    lines.append(f"- 广告曝光: {fmt(sales.get('ads_impressions'))}")
    lines.append(f"- 退款金额: {fmt(sales.get('refund'))}")
    lines.append("")
    for key, label in BI_REPORT_SOURCE_ORDER:
        source = bi_sources.get(key)
        if not isinstance(source, dict):
            source = {"key": key, "label": label, "status": "skipped", "row_count": 0, "rows": []}
        append_bi_source_section(lines, source, default_label=label)
        lines.append("")
    lines.append("## 刊登基础数据")
    lines.append("")
    lines.append(f"- 状态: {listing_basic.get('status')}")
    lines.append(f"- 行数: {fmt(listing_basic.get('row_count'))}")
    lines.append(f"- listid: {fmt(listing_basic.get('listid'))}")
    lines.append(f"- 渠道: {fmt(listing_basic.get('channel'))}")
    lines.append(f"- 平台SKU: {fmt(listing_basic.get('platform_sku'))}")
    lines.append(f"- 公司SKU: {fmt(listing_basic.get('company_sku'))}")
    lines.append(f"- 亚马逊状态: {fmt(listing_basic.get('amazon_status'))}")
    lines.append(f"- 发货方式: {fmt(listing_basic.get('fulfillment'))}")
    lines.append(f"- 类目: {fmt(listing_basic.get('category'))}")
    lines.append(f"- 商品标题: {fmt(listing_basic.get('title'))}")
    lines.append(f"- 品牌: {fmt(listing_basic.get('brand'))}")
    lines.append(f"- 主图链接: {fmt(listing_basic.get('main_image'))}")
    lines.append(f"- 关键词搜索: {fmt(listing_basic.get('search_terms'))}")
    lines.append("")
    lines.append("### 刊登五点描述")
    lines.append("")
    append_numbered(lines, listing_basic.get("bullets"))
    lines.append("")
    lines.append("### 刊登基础数据完整 JSON（压缩格式）")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(listing_basic.get("row") or {}, ensure_ascii=False, separators=(",", ":"), default=str))
    lines.append("```")
    lines.append("")
    lines.append("## 爬虫基础数据")
    lines.append("")
    lines.append(f"- 状态: {crawler.get('status')}")
    lines.append(f"- 最新日期: {fmt(crawler.get('date'))}")
    lines.append(f"- 标题: {fmt(crawler.get('title'))}")
    lines.append(f"- 品牌: {fmt(crawler.get('brand'))}")
    lines.append(f"- 类目: {' > '.join(map(str, crawler.get('categories') or []))}")
    lines.append(f"- 价格列表: {', '.join(map(str, crawler.get('price_list') or []))}")
    lines.append(f"- 星级评分: {fmt(crawler.get('rating'))}")
    lines.append(f"- 评分数量: {fmt(crawler.get('rating_count'))}")
    lines.append(f"- 评论数量: {fmt(crawler.get('review_count'))}")
    lines.append(f"- 五点数量: {fmt(crawler.get('bullet_count'))}")
    lines.append(f"- 副图数量: {fmt(crawler.get('subplot_count'))}")
    lines.append(f"- A+图片数量: {fmt(crawler.get('a_image_count'))}")
    lines.append(f"- 大类排名: {fmt(crawler.get('major_rank'))}")
    lines.append(f"- 小类排名: {fmt(crawler.get('subclass_rank'))}")
    lines.append(f"- 商品链接: {fmt(crawler.get('link'))}")
    lines.append("")
    lines.append("### 五点描述")
    lines.append("")
    append_numbered(lines, crawler.get("five_point_description"))
    lines.append("")
    lines.append("### 商品描述")
    lines.append("")
    lines.append(fmt(crawler.get("description")) or "无")
    lines.append("")
    lines.append("### A+图片链接")
    lines.append("")
    append_numbered(lines, crawler.get("a_image"))
    lines.append("")
    lines.append("### A+文案")
    lines.append("")
    append_numbered(lines, crawler.get("a_description"))
    lines.append("")
    lines.append("### QA 完整 JSON")
    lines.append("")
    append_json_block(lines, crawler.get("qa"))
    lines.append("")
    lines.append("### 评论列表完整 JSON")
    lines.append("")
    append_json_block(lines, crawler.get("review_list"))
    lines.append("")
    lines.append("### 爬虫完整 JSON（压缩格式）")
    lines.append("")
    append_json_block(lines, crawler.get("raw_row"))
    lines.append("")
    lines.append("## 卖家精灵关键词挖掘")
    lines.append("")
    lines.append(f"- 状态: {keyword.get('status')}")
    lines.append(f"- 种子词: {fmt(keyword.get('seed_keyword'))}")
    lines.append(f"- 行数: {fmt(keyword.get('row_count'))}")
    lines.append(f"- Excel阿里云链接: {fmt(keyword.get('excel_url'))}")
    lines.append("")
    lines.append("| 关键词 | 中文 | 搜索量 | 购买量 | 购买率 | 商品数 | 供需比 | 均价 | 标题密度 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for item in keyword.get("top_keywords") or []:
        lines.append(
            "| {keyword} | {keyword_cn} | {searches} | {purchases} | {purchase_rate} | {products} | {supply_demand_ratio} | {avg_price} | {title_density} |".format(
                keyword=fmt(item.get("keyword")),
                keyword_cn=fmt(item.get("keyword_cn")),
                searches=fmt(item.get("searches")),
                purchases=fmt(item.get("purchases")),
                purchase_rate=fmt(item.get("purchase_rate")),
                products=fmt(item.get("products")),
                supply_demand_ratio=fmt(item.get("supply_demand_ratio")),
                avg_price=fmt(item.get("avg_price")),
                title_density=fmt(item.get("title_density")),
            )
        )
    lines.append("")
    lines.append("### 关键词挖掘完整 JSON（压缩格式）")
    lines.append("")
    append_json_block(lines, keyword.get("full_result"))
    lines.append("")
    lines.append("## 卖家精灵 AI 全景分析")
    lines.append("")
    lines.append(f"- 状态: {listing.get('status')}")
    lines.append(f"- 副标题: {fmt(listing.get('subtitle'))}")
    lines.append(f"- 产品定位: {fmt(listing.get('product_identity'))}")
    lines.append(f"- 目标用户: {fmt(listing.get('target_user'))}")
    lines.append(f"- 主要场景: {fmt(listing.get('primary_scene'))}")
    lines.append(f"- 总结: {fmt(listing.get('overall_summary'))}")
    lines.append("")
    lines.append("### 主要优势")
    append_bullets(lines, listing.get("key_strengths"))
    lines.append("")
    lines.append("### 潜在问题")
    append_bullets(lines, listing.get("potential_weaknesses"))
    lines.append("")
    lines.append("### AI 全景分析完整 JSON（压缩格式）")
    lines.append("")
    append_json_block(lines, listing.get("full_content"))
    lines.append("")
    lines.append("## Rufus 数据")
    lines.append("")
    lines.append(f"- 状态: {rufus.get('status')}")
    lines.append(f"- 问题数量: {fmt(rufus.get('question_count'))}")
    lines.append(f"- 页面URL: {fmt(rufus.get('page_url'))}")
    lines.append(f"- 报告文件: {fmt(rufus.get('report_path'))}")
    for answer in rufus.get("answers") or []:
        lines.append("")
        lines.append(f"### 第 {answer.get('index')} 题")
        lines.append("")
        lines.append(f"问题: {fmt(answer.get('question'))}")
        lines.append("")
        append_rufus_display_blocks(lines, answer.get("display_blocks"), answer.get("answer"))
        if answer.get("summary"):
            lines.append("")
            lines.append(f"总结: {fmt(answer.get('summary'))}")
    lines.append("")
    lines.append("### Rufus 完整 JSON（压缩格式）")
    lines.append("")
    append_json_block(lines, rufus.get("full_clean_result"))
    lines.append("")
    lines.append("## 数据链接")
    lines.append("")
    lines.append(f"- 关键词挖掘 Excel 阿里云链接: {fmt(keyword.get('excel_url'))}")
    for label, path in source_files.items():
        if label.endswith("_url") and path:
            lines.append(f"- {label}: {fmt(path)}")
    lines.append("")
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def append_json_block(lines: list[str], value: Any) -> None:
    lines.append("```json")
    lines.append(json_dumps(value))
    lines.append("```")


def append_rufus_display_blocks(lines: list[str], blocks: Any, fallback_answer: Any = None) -> None:
    lines.append("#### Rufus 展示内容")
    lines.append("")
    if not isinstance(blocks, list) or not blocks:
        lines.append(fmt(fallback_answer) or "无")
        return

    wrote = False
    index = 0
    while index < len(blocks):
        block = blocks[index]
        index += 1
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "heading":
            text = clean_text(block.get("text"))
            if text:
                if wrote:
                    lines.append("")
                lines.append(f"##### {text}")
                wrote = True
        elif block_type == "paragraph":
            text = clean_text(block.get("text"))
            if text:
                if text in {"•", "-", "*"} and index < len(blocks):
                    next_block = blocks[index]
                    if isinstance(next_block, dict) and next_block.get("type") == "paragraph":
                        next_text = clean_text(next_block.get("text"))
                        if next_text:
                            text = f"- {next_text}"
                            index += 1
                if wrote:
                    lines.append("")
                lines.append(text)
                wrote = True
        elif block_type == "table":
            rows = block.get("rows")
            if isinstance(rows, list) and rows:
                if wrote:
                    lines.append("")
                append_markdown_table(lines, rows)
                wrote = True

    if not wrote:
        lines.append(fmt(fallback_answer) or "无")


def append_markdown_table(lines: list[str], rows: list[Any]) -> None:
    normalized_rows = normalize_table_rows(rows)
    if not normalized_rows:
        lines.append("无")
        return
    header = normalized_rows[0]
    lines.append("| " + " | ".join(markdown_cell(cell) for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")


def normalize_table_rows(rows: list[Any]) -> list[list[Any]]:
    normalized = [row for row in rows if isinstance(row, list) and any(clean_text(cell) for cell in row)]
    if not normalized:
        return []
    width = max(len(row) for row in normalized)
    return [row + [""] * (width - len(row)) for row in normalized]


def markdown_cell(value: Any) -> str:
    text = clean_text(value if not isinstance(value, (dict, list)) else json_dumps(value))
    return text.replace("\\", "\\\\").replace("|", "\\|")


def append_bi_source_section(lines: list[str], source: dict[str, Any], *, default_label: str) -> None:
    safe_source = report_safe_bi_source(source)
    label = fmt(safe_source.get("label") or default_label)
    rows = safe_source.get("rows") if isinstance(safe_source.get("rows"), list) else []
    lines.append(f"### {label}")
    lines.append("")
    lines.append(f"- 状态: {fmt(safe_source.get('status'))}")
    lines.append(f"- 行数: {fmt(safe_source.get('row_count'))}")
    source_row_count = safe_source.get("source_row_count")
    if source_row_count not in (None, safe_source.get("row_count")):
        lines.append(f"- 原始行数: {fmt(source_row_count)}")
    if safe_source.get("reason"):
        lines.append(f"- 原因: {fmt(safe_source.get('reason'))}")
    if safe_source.get("error_message"):
        lines.append(f"- 错误: {fmt(safe_source.get('error_message'))}")
    lines.append("")
    lines.append("#### 数据表")
    lines.append("")
    append_bi_rows_table(lines, str(safe_source.get("key") or ""), rows)
    lines.append("")
    lines.append("#### 完整 JSON（压缩格式）")
    lines.append("")
    append_json_block(lines, safe_source)


def append_bi_rows_table(lines: list[str], source_key: str, rows: list[Any]) -> None:
    normalized_rows = [row for row in rows if isinstance(row, dict)]
    if not normalized_rows:
        lines.append("无")
        return
    columns = bi_table_columns(source_key, normalized_rows)
    if not columns:
        lines.append("无")
        return
    lines.append("| " + " | ".join(markdown_cell(column) for column in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in normalized_rows:
        lines.append("| " + " | ".join(markdown_cell(row.get(column)) for column in columns) + " |")


def bi_table_columns(source_key: str, rows: list[dict[str, Any]]) -> list[str]:
    available_keys: list[str] = []
    for row in rows:
        for key, value in row.items():
            if key in {"endpoint", "raw"}:
                continue
            if key not in available_keys and has_display_value(value):
                available_keys.append(str(key))
    preferred = BI_REPORT_TABLE_COLUMNS.get(source_key, ())
    columns = [key for key in preferred if key in available_keys]
    columns.extend(key for key in available_keys if key not in columns)
    return columns


def has_display_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return any(has_display_value(item) for item in value)
    if isinstance(value, dict):
        return any(has_display_value(item) for item in value.values())
    return True


def report_safe_bi_source(value: Any) -> Any:
    hidden_keys = {
        "endpoint",
        "request_endpoint",
        "requestEndpoint",
        "request_url",
        "requestUrl",
        "api_endpoint",
        "apiEndpoint",
    }
    if isinstance(value, dict):
        return {
            key: report_safe_bi_source(item)
            for key, item in value.items()
            if str(key) not in hidden_keys
        }
    if isinstance(value, list):
        return [report_safe_bi_source(item) for item in value]
    return value


def append_numbered(lines: list[str], values: Any) -> None:
    items = as_list(values)
    if not items:
        lines.append("无")
        return
    for index, value in enumerate(items, start=1):
        lines.append(f"{index}. {fmt(value)}")


def append_bullets(lines: list[str], values: Any) -> None:
    if not isinstance(values, list) or not values:
        lines.append("- 无")
        return
    for item in values:
        if isinstance(item, dict):
            title = fmt(item.get("title"))
            description = fmt(item.get("description"))
            lines.append(f"- {title}: {description}" if title or description else "- 无")
        else:
            lines.append(f"- {fmt(item)}")


def first_row(section: dict[str, Any]) -> dict[str, Any]:
    rows = section.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def normalized_bi_report_sources(bi_report_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_sources = bi_report_data.get("sources") if isinstance(bi_report_data.get("sources"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for key, label in BI_REPORT_SOURCE_ORDER:
        source = raw_sources.get(key)
        if isinstance(source, dict):
            normalized = dict(source)
            normalized.setdefault("key", key)
            normalized.setdefault("label", label)
            normalized.setdefault("status", "skipped")
            normalized.setdefault("row_count", len(normalized.get("rows") or []))
            normalized.setdefault("rows", [])
        else:
            normalized = {
                "key": key,
                "label": label,
                "status": "skipped",
                "row_count": 0,
                "rows": [],
                "raw": None,
            }
        result[key] = normalized
    for key, source in raw_sources.items():
        if key not in result and isinstance(source, dict):
            result[str(key)] = dict(source)
    return result


def first_status(*sections: dict[str, Any]) -> str:
    fallback = None
    for section in sections:
        if isinstance(section, dict):
            status = section.get("status")
            if status:
                status_text = str(status)
                if status_text not in {"skipped", "planned"}:
                    return status_text
                fallback = fallback or status_text
    return fallback or "skipped"


def first_count(*sections: dict[str, Any]) -> int | Any:
    for section in sections:
        if not isinstance(section, dict):
            continue
        status = str(section.get("status") or "")
        if status in {"skipped", "planned"} and not section.get("row_count"):
            continue
        if section.get("row_count") is not None:
            return section.get("row_count")
        rows = section.get("rows")
        if isinstance(rows, list):
            return len(rows)
    return 0


def first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return None


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def normalize_asin(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_site(value: Any) -> str:
    return str(value or "US").strip().upper()


def safe_path(value: Any) -> str | None:
    if value is None:
        return None
    return Path(str(value)).as_posix()


def load_seller_sprite_run_results(
    *,
    output_root: Path | None,
    asin: str,
    pattern: str,
) -> list[dict[str, Any]]:
    if output_root is None or not asin:
        return []
    asin_dir = output_root / "asins" / asin
    if not asin_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(asin_dir.glob(pattern)):
        outer = read_json(path)
        payload = outer.get("json") if isinstance(outer.get("json"), dict) else outer
        result_path = payload.get("result_path") if isinstance(payload, dict) else None
        result = read_json(Path(result_path)) if result_path else {}
        results.append(result if result else payload)
    return [item for item in results if isinstance(item, dict)]


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def first_seed_keyword(keyword_miner: dict[str, Any]) -> str | None:
    seeds = keyword_miner.get("seed_keywords")
    if isinstance(seeds, list) and seeds:
        return fmt(seeds[0])
    jobs = keyword_miner.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            command = job.get("command") if isinstance(job, dict) else None
            seed = seed_from_command(command)
            if seed:
                return seed
    return None


def seed_from_command(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    for index, token in enumerate(command):
        if token == "--params" and index + 1 < len(command):
            try:
                payload = json.loads(str(command[index + 1]))
            except json.JSONDecodeError:
                return None
            keyword = payload.get("keyword") if isinstance(payload, dict) else None
            return str(keyword) if keyword else None
    return None


def keyword_row_count(
    keyword_miner: dict[str, Any],
    raw_results: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> int | None:
    if raw_results:
        total = 0
        has_count = False
        for result in raw_results:
            value = result.get("row_count")
            if isinstance(value, int):
                total += value
                has_count = True
        if has_count:
            return total
    if rows:
        return len(rows)
    jobs = keyword_miner.get("jobs")
    if isinstance(jobs, list):
        counts = [job.get("row_count") for job in jobs if isinstance(job, dict)]
        if counts:
            return sum(int(value or 0) for value in counts if isinstance(value, int))
    value = keyword_miner.get("row_count")
    return int(value) if isinstance(value, int) else None


def full_keyword_result(keyword_miner: dict[str, Any], raw_results: list[dict[str, Any]]) -> Any:
    full_result = keyword_miner.get("full_result")
    if isinstance(full_result, dict):
        return full_result
    if len(raw_results) == 1:
        return raw_results[0]
    if len(raw_results) > 1:
        return {"jobs": raw_results}
    return keyword_miner


def top_keywords(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> float:
        return as_number(first_value(row, "searches", "搜索量")) or 0

    sorted_rows = sorted(rows, key=sort_key, reverse=True)
    result: list[dict[str, Any]] = []
    for row in sorted_rows[:limit]:
        result.append(
            {
                "keyword": first_value(row, "keyword", "关键词"),
                "keyword_cn": first_value(row, "keywordCn", "keyword_cn", "中文"),
                "searches": first_value(row, "searches", "搜索量"),
                "purchases": first_value(row, "purchases", "购买量"),
                "purchase_rate": first_value(row, "purchaseRate", "purchase_rate", "购买率"),
                "products": first_value(row, "products", "商品数"),
                "supply_demand_ratio": first_value(
                    row,
                    "supplyDemandRatio",
                    "supply_demand_ratio",
                    "供需比",
                ),
                "avg_price": first_value(row, "avgPrice", "avg_price", "均价"),
                "avg_rating": first_value(row, "avgRating", "avg_rating"),
                "title_density": first_value(row, "titleDensity", "title_density", "标题密度"),
                "search_rank": first_value(row, "searchRank", "search_rank"),
            }
        )
    return result


def as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def listing_analysis_summary(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    report = content.get("reportDetails") if isinstance(content.get("reportDetails"), dict) else {}
    strengths = report.get("keyStrengths") if isinstance(report.get("keyStrengths"), list) else []
    weaknesses = (
        report.get("potentialWeaknesses")
        if isinstance(report.get("potentialWeaknesses"), list)
        else []
    )
    return {
        "status": payload.get("status") or "skipped",
        "task_status": payload.get("task_status"),
        "subtitle": report.get("subTitle"),
        "product_identity": report.get("productIdentity"),
        "target_user": report.get("targetUser"),
        "primary_scene": report.get("primaryScene"),
        "overall_summary": report.get("overallSummary"),
        "key_strengths": [
            {"title": item.get("title"), "description": item.get("description")}
            for item in strengths
            if isinstance(item, dict)
        ],
        "potential_weaknesses": [
            {"title": item.get("title"), "description": item.get("description")}
            for item in weaknesses
            if isinstance(item, dict)
        ],
        "full_content": content,
    }


def rufus_summary(payload: dict[str, Any]) -> dict[str, Any]:
    answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
    questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    compact_answers: list[dict[str, Any]] = []
    for index, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            continue
        question = answer.get("question") or (
            questions[index - 1] if index - 1 < len(questions) else None
        )
        compact_answers.append(
            {
                "index": answer.get("index") or index,
                "question": clean_text(question),
                "answer": clean_text(answer.get("text") or answer.get("answer")),
                "summary": clean_text(answer.get("summary") or answer.get("summaryText")),
                "display_blocks": rufus_display_blocks(answer),
            }
        )
    return {
        "status": payload.get("status") or "skipped",
        "page_url": payload.get("page_url"),
        "question_count": payload.get("question_count") or len(questions),
        "questions": [clean_text(question) for question in questions],
        "answers": compact_answers,
        "report_path": safe_path(payload.get("report_path")),
        "full_clean_result": payload,
    }


def rufus_display_blocks(answer: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = answer.get("blocks")
    display_blocks: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            node_type = clean_text(value.get("type")) or "object"
            if node_type == "table":
                rows = rufus_table_rows(value)
                if rows:
                    display_blocks.append({"type": "table", "rows": rows})
                return
            if node_type == "tableRow":
                return
            if node_type in {"text", "link", "heading", "listItem"}:
                text = rufus_text_from_node(value)
                if text:
                    display_blocks.append(
                        {
                            "type": "heading" if is_rufus_heading_node(value) else "paragraph",
                            "text": text,
                        }
                    )
                return
            for child in rufus_child_nodes(value):
                walk(child)
            return
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        content = clean_text(value)
        if content:
            display_blocks.append({"type": "paragraph", "text": content})

    if isinstance(blocks, list) and blocks:
        for block in blocks:
            walk(block)
    elif blocks:
        walk(blocks)
    return display_blocks


def rufus_child_nodes(node: dict[str, Any]) -> list[Any]:
    children: list[Any] = []
    for key in ("children", "items", "rows", "cells"):
        value = node.get(key)
        if isinstance(value, list):
            children.extend(value)
        elif isinstance(value, dict):
            children.append(value)
    return children


def rufus_table_rows(node: dict[str, Any]) -> list[list[str]]:
    raw_rows = node.get("children")
    if not isinstance(raw_rows, list):
        return []
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict) or clean_text(raw_row.get("type")) != "tableRow":
            continue
        raw_cells = raw_row.get("children")
        if not isinstance(raw_cells, list):
            continue
        row = [rufus_text_from_node(cell) for cell in raw_cells]
        if any(row):
            rows.append(row)
    return rows


def is_rufus_heading_node(node: dict[str, Any]) -> bool:
    return (
        clean_text(node.get("accessibilityRole")) == "header"
        or clean_text(node.get("type")) == "heading"
        or (clean_text(node.get("weight")) == "bold" and clean_text(node.get("size")) in {"large", "xlarge"})
    )


def rufus_text_from_node(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return clean_text(value)
    if isinstance(value, list):
        return clean_text(" ".join(rufus_text_from_node(item) for item in value))
    if not isinstance(value, dict):
        return ""

    children = value.get("children")
    if isinstance(children, (str, int, float)):
        return clean_text(children)
    if isinstance(children, list):
        return clean_text(" ".join(rufus_text_from_node(item) for item in children))
    for key in ("text", "label", "title", "value", "name"):
        child_value = value.get(key)
        if isinstance(child_value, (str, int, float)):
            return clean_text(child_value)
    return ""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\r\\n", " ").replace("\\n", " ").replace("\\r", " ")
    text = re.sub(r"[\r\n]+", " ", text)
    return re.sub(r"[ \t\f\v]+", " ", text).strip()
