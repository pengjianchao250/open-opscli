"""Build a deterministic optimization brief from stored Sorftime responses."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def text_result(path: Path) -> str:
    if not path.exists():
        return ""
    result = json.loads(path.read_text(encoding="utf-8"))
    return "".join(block.get("text", "") for block in result.get("content", []) if block.get("type") == "text")


def json_result(path: Path) -> Any:
    text = text_result(path)
    if not path.exists():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def trend_result(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for part in text_result(path).split(","):
        if "=" not in part:
            continue
        key, value = part.rsplit("=", 1)
        try:
            values[key] = float(value)
        except ValueError:
            continue
    return values


def build_report(run_dir: Path) -> dict[str, Any]:
    raw = run_dir / "raw"
    detail = json_result(raw / "product_detail.json") or {}
    product = detail.get("data", {}) if isinstance(detail, dict) else {}
    traffic = (json_result(raw / "product_traffic_terms.json") or {}).get("data", [])
    competitor = (json_result(raw / "competitor_product_keywords.json") or {}).get("data", [])
    category = (json_result(raw / "category_keywords.json") or {}).get("data", [])
    extensions = []
    for path in sorted(raw.glob("keyword_extends_*.json")):
        extensions.extend((json_result(path) or {}).get("data", []))
    reviews_payload = json_result(raw / "product_reviews_both.json") or {}
    reviews = reviews_payload.get("data", []) if isinstance(reviews_payload, dict) else []
    negative_text = text_result(raw / "product_reviews_negative.json") if (raw / "product_reviews_negative.json").exists() else ""
    customers = (json_result(raw / "product_customers_say.json") or {}).get("data", {})
    sales_trend = trend_result(raw / "product_trend_sales_volume.json")
    price_trend = trend_result(raw / "product_trend_price.json")

    keywords = {}
    for row in traffic + competitor + category + extensions:
        keyword = str(row.get("keyword", "")).strip().lower()
        if keyword:
            keywords[keyword] = row
    review_counts = Counter(float(row.get("star_rating", 0)) for row in reviews)
    top_traffic = sorted(traffic, key=lambda row: float(row.get("monthly_search_volume", 0) or 0), reverse=True)
    top_competitor = sorted(competitor, key=lambda row: float(row.get("monthly_search_volume", 0) or 0), reverse=True)
    latest_sales = next(reversed(sales_trend.values()), None) if sales_trend else None
    previous_sales = list(sales_trend.values())[-4:-1] if len(sales_trend) >= 4 else []
    avg_recent_sales = sum(previous_sales) / len(previous_sales) if previous_sales else None
    manifest_path = run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    no_data_tasks = manifest.get("no_data_tasks", [])
    no_data_tools = {row.get("tool") for row in no_data_tasks if isinstance(row, dict)}
    limitations = [
        "缺失或超时的 MCP 接口不会被推断为接口正常返回零条数据。",
        "product_reviews(review_type=Negative) returned 'No reviews found';评论样本不能代表完整评论总体。",
    ]
    for row in no_data_tasks:
        limitations.append(
            f"{row.get('tool')} 多次等待约 5 分钟仍无响应，已标记为 no_data_after_timeout；"
            "本报告按暂无可用数据处理，并保留超时证据。"
        )
    result = {
        "asin": product.get("asin"),
        "site": manifest.get("site", product.get("site", "US")),
        "run_dir": str(run_dir),
        "product": {key: product.get(key) for key in ("title", "brand", "price", "star_rating", "review_count", "category", "node_id", "monthly_sales_volume", "monthly_sales_amount", "delivery_type", "subcategory", "a_plus", "gross_profit", "gross_profit_rate")},
        "reviews": {"sample_count": len(reviews), "star_counts": {str(k): v for k, v in sorted(review_counts.items())}, "negative_endpoint": negative_text},
        "keywords": {"unique_count": len(keywords), "traffic_count": len(traffic), "competitor_count": len(competitor), "category_count": len(category), "extension_count": len(extensions), "top_traffic": top_traffic[:10], "top_competitor": top_competitor[:10]},
        "trends": {"sales_volume": sales_trend, "price": price_trend, "latest_sales": latest_sales, "recent_avg_sales_excluding_latest": avg_recent_sales},
        "customers_say": customers,
        "data_status": {row.get("tool"): row.get("status") for row in no_data_tasks},
        "limitations": limitations,
    }
    parsed = run_dir / "parsed"
    parsed.mkdir(exist_ok=True)
    (parsed / "optimization_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (parsed / "keywords.csv").write_text("keyword,source,monthly_search_volume,exposure_position,recommended_bid\n" + "\n".join(
        f"{row.get('keyword','').replace(',', ' ')},{source},{row.get('monthly_search_volume','')},{row.get('exposure_position','')},{row.get('recommended_bid',row.get('cpc_exact_bid',''))}"
        for source, rows in (("traffic", traffic), ("competitor", competitor), ("category", category), ("extended", extensions)) for row in rows
    ) + "\n", encoding="utf-8")
    report = render_report(result)
    (run_dir / "optimization_report.md").write_text(report, encoding="utf-8")
    return result


def render_report(data: dict[str, Any]) -> str:
    p = data["product"]
    r = data["reviews"]
    k = data["keywords"]
    t = data["trends"]
    site = data.get("site", "")
    currency = {"US": "USD", "CA": "CAD", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "GB": "GBP"}.get(site, "")
    customer_summary = data.get("customers_say") or {}
    customer_text = customer_summary.get("customer_say", "") if isinstance(customer_summary, dict) else ""
    customer_details = customer_summary.get("details", []) if isinstance(customer_summary, dict) else []
    positive_topics = [str(x.get("keyword")) for x in customer_details if isinstance(x, dict) and float(x.get("positive", 0) or 0) > float(x.get("negative", 0) or 0)]
    negative_topics = [str(x.get("keyword")) for x in customer_details if isinstance(x, dict) and float(x.get("negative", 0) or 0) > float(x.get("positive", 0) or 0)]
    top_keywords = [str(x.get("keyword")) for x in k.get("top_traffic", [])[:5] if x.get("keyword")]
    competitor_status = data.get("data_status", {}).get("competitor_product_keywords")
    competitor_line = (
        "- 竞品自然词接口多次等待约 5 分钟仍无响应，已标记为 `no_data_after_timeout`；当前竞品词数量不代表接口正常返回 0 条。"
        if competitor_status == "no_data_after_timeout" else
        f"- 已获得竞品自然词 {k['competitor_count']} 个。"
    )
    lines = [
        f"# 自有商品优化测试报告：{data.get('asin')}",
        "",
        f"- 站点：{data.get('site')} | 数据来源：Sorftime MCP",
        f"- 标题：{p.get('title')}",
        f"- 品牌：{p.get('brand')} | 价格：{p.get('price')} {currency} | 评分：{p.get('star_rating')} | 评论数：{p.get('review_count')}",
        f"- 月销量估算：{p.get('monthly_sales_volume')} | 月销售额：{p.get('monthly_sales_amount')} {currency} | 类目：{p.get('subcategory') or p.get('category')}",
        "",
        "## 初步结论",
        "",
        f"1. 当前评分 {p.get('star_rating')}、评论数 {p.get('review_count')}、月销量估算 {p.get('monthly_sales_volume')}，应结合类目排名和利润率判断增长空间。",
        f"2. 已采集流量词 {k.get('traffic_count')} 个，当前高流量词包括：{', '.join(top_keywords) or '暂无'}。",
        f"3. Customers Say 摘要：{customer_text or '暂无摘要，不能据此判断用户偏好。'}",
        f"4. 用户正向主题：{', '.join(positive_topics[:6]) or '暂无'}；负向主题：{', '.join(negative_topics[:6]) or '暂无'}。",
        "",
        "## 优化优先级",
        "",
        "### P0：Listing 预期管理",
        "- 根据当前商品属性明确材质、尺寸、承重和适用场景，避免写入详情中不存在的卖点。",
        f"- 当前标题长度约 {len(str(p.get('title') or ''))} 个字符，应围绕真实属性和高相关流量词重排标题与五点。",
        "",
        "### P1：自然流量和关键词",
        f"- 当前合并去重关键词 {k['unique_count']} 个，其中流量反查 {k['traffic_count']} 个、竞品自然词 {k['competitor_count']} 个、类目词 {k['category_count']} 个、扩展词 {k['extension_count']} 个。",
        competitor_line,
        f"- 建议优先验证以下流量词：{', '.join(top_keywords) or '暂无'}，再建立 Exact/Phrase 组并监控自然排名。",
        "- 对明显不相关词建立否定词候选清单，先用广告搜索词报告验证，再正式添加否定。",
        "",
        "### P1：评论和产品体验",
        f"- 本次 Both 评论样本 {r['sample_count']} 条，星级分布：{r['star_counts']}。Negative 专用接口返回：{r['negative_endpoint']}。",
        f"- 用户反馈的正向主题：{', '.join(positive_topics[:8]) or '暂无'}。",
        f"- 主要风险主题：{', '.join(negative_topics[:8]) or '暂无'}；应通过材料说明、承重证据和安装说明降低预期偏差。",
        "",
        "### P2：趋势和经营",
        f"- 最新销量趋势值：{t.get('latest_sales')}；最近可用月份均值（不含最新）：{t.get('recent_avg_sales_excluding_latest')}。",
        f"- 当前配送方式为 {p.get('delivery_type')}；建议结合真实物流成本和配送时效评估配送方案，不应只看页面估算。",
        "",
        "## 数据限制",
        "",
        *[f"- {x}" for x in data["limitations"]],
        "",
        "## 下一步",
        "",
        "1. 用 Seller Central 广告搜索词报告验证低相关词候选。",
        "2. 按产品详情、关键词、评论和趋势原始响应建立月度快照。",
        "3. 修改 Listing 后 2 至 4 周复查自然排名、CTR、CVR、广告花费和退货原因。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = build_report(args.run_dir)
    print(json.dumps({"asin": result.get("asin"), "keywords": result["keywords"]["unique_count"], "reviews": result["reviews"]["sample_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
