"""Generate a readable detail report for each stored Sorftime product."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:80] or "unknown"


def parse_attributes(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def clean_description(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def render_report(row: dict[str, Any]) -> str:
    asin = row.get("asin", "")
    site = row.get("site", "")
    currency = {"US": "USD", "CA": "CAD", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "GB": "GBP"}.get(site, "")
    attributes = parse_attributes(row.get("attributes"))
    lines = [
        f"# 商品详情：{asin}",
        "",
        f"> 站点：{site} | 数据来源：Sorftime MCP | 采集时间：{row.get('requested_at', '')}",
        "",
        "## 核心信息",
        "",
        f"- 标题：{row.get('title', '')}",
        f"- 品牌：{row.get('brand', '')}",
        f"- 父 ASIN：{row.get('parent_asin', '')}",
        f"- 卖家：{row.get('seller_name', '')}",
        f"- 类目：{row.get('category', '')}",
        f"- 节点：{row.get('node_id', '')}",
        "",
        "## 经营指标",
        "",
        f"- 价格：{row.get('price', '')} {currency}".rstrip(),
        f"- 优惠券：{row.get('coupon', '')} {currency}".rstrip(),
        f"- 评分：{row.get('star_rating', '')} / 5",
        f"- 评论数：{row.get('review_count', '')}",
        f"- 月销量估算：{row.get('monthly_sales_volume', '')}",
        f"- 月销售额估算：{row.get('monthly_sales_amount', '')} {currency}".rstrip(),
        f"- 顶级类目排名：{row.get('top_category', '')}",
        f"- 子类目排名：{row.get('subcategory', '')}",
        f"- 配送方式：{row.get('delivery_type', '')}",
        f"- FBA 费用：{row.get('fba_fee', '')} {currency}".rstrip(),
        f"- 毛利：{row.get('gross_profit', '')} {currency}".rstrip(),
        f"- 毛利率：{row.get('gross_profit_rate', '')}%",
        "",
        "## 上架与规格",
        "",
        f"- 上架日期：{row.get('online_date', '')}",
        f"- 在架天数：{row.get('days_on_shelf', '')}",
        f"- 变体数量：{row.get('variation_count', '')}",
        f"- A+：{row.get('a_plus', '')}",
        f"- 包装尺寸（cm）：{row.get('package_size_cm', '')}",
        f"- 重量（g）：{row.get('weight_g', '')}",
    ]
    if attributes:
        lines.extend(["", "### 属性", ""])
        lines.extend(f"- {key}：{value}" for key, value in attributes.items())
    description = clean_description(row.get("description"))
    if description:
        lines.extend(["", "## 商品描述", "", description])
    lines.extend([
        "",
        "## 后续分析",
        "",
        "本文件为 product_detail 基础详情。评论、流量词、竞品词和趋势等 MCP 返回会继续保存到同一 ASIN/站点运行目录，并由分析脚本合并生成优化报告。",
        "",
        f"原始返回：`{row.get('raw_path', '')}`",
    ])
    return "\n".join(lines) + "\n"


def generate(input_path: Path, output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for raw_line in input_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        asin = safe(str(row.get("asin", "unknown")))
        site = safe(str(row.get("site", "unknown")))
        run_dir = output_dir / f"detail_{asin}_{site}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "detail.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "detail_report.md").write_text(render_report(row), encoding="utf-8")
        (run_dir / "run.json").write_text(json.dumps({
            "asin": row.get("asin"), "site": row.get("site"), "tool": "product_detail",
            "status": "success", "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": row.get("raw_path"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        count += 1
    summary = {"generated": count, "output_dir": str(output_dir)}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Sorftime detail reports")
    parser.add_argument("--input", type=Path, default=Path("test-data/sorftime/product-details/product_details.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/runs/details"))
    args = parser.parse_args()
    print(json.dumps(generate(args.input, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
