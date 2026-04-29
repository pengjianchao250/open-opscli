"""ops-cross-border-product-selector Skill 的核心工具函数。

提供品类扫描、BSR 筛选、四象限分类、机会评分等基础能力，供 CLI 和 MCP 脚本复用。
无任何外部依赖，仅依赖 Python 标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


DATASET_FIELDS: Dict[str, List[str]] = {
    "ds_d35ac6f3910c": [
        "date_id", "dept_name", "team_name", "asin", "ed_sku", "product_name",
        "category", "platform_name", "country_name", "original_price", "order_qty",
        "gross_profit", "gross_profit_percent", "refund_percent", "refund_qty",
        "channel_uuid", "listing_uuid"
    ],
    "ds_pdTYjvLRCadv": [
        "date_id", "asin", "product_name", "price", "star", "reviews_qty",
        "subclass_rank", "category", "asin_ps_uuid"
    ],
    "ds_97zj6R0KDKpB": [
        "date_id", "dept_name", "team_name", "asin", "ed_sku", "platform_name",
        "warehouse_name", "inventory_qty", "turnover_days", "sell_qty_days",
        "channel_uuid", "listing_uuid"
    ]
}

DEFAULT_COST_RATIO = 0.35

BSR_FILTER_RULES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "standard": {
        "subclass_rank": {"min": 100, "max": 5000},
        "reviews_qty": {"min": 300, "max": 1000},
        "rating": {"min": 3.5, "max": 4.3},
        "price": {"min": 15.0, "max": 50.0}
    },
    "loose": {
        "subclass_rank": {"min": 50, "max": 10000},
        "reviews_qty": {"min": 100, "max": 2000},
        "rating": {"min": 3.0, "max": 4.5},
        "price": {"min": 10.0, "max": 80.0}
    },
    "strict": {
        "subclass_rank": {"min": 500, "max": 3000},
        "reviews_qty": {"min": 500, "max": 800},
        "rating": {"min": 3.8, "max": 4.2},
        "price": {"min": 20.0, "max": 40.0}
    }
}


def scan_category(
    internal_data: List[Dict[str, Any]],
    external_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if not internal_data and not external_data:
        return {"total_sales": 0, "asin_count": 0, "avg_margin_percent": 0,
                "avg_refund_percent": 0, "competitor_count": 0, "avg_rating": 0,
                "avg_reviews": 0, "hhi": 0, "concentration_level": "unknown"}
    total_sales = sum(item.get("original_price", 0) for item in internal_data)
    asin_count = len(set(item.get("asin", "") for item in internal_data))
    avg_margin = sum(item.get("gross_profit_percent", 0) for item in internal_data) / len(internal_data) if internal_data else 0
    avg_refund = sum(item.get("refund_percent", 0) for item in internal_data) / len(internal_data) if internal_data else 0
    competitor_count = len(set(item.get("asin", "") for item in external_data))
    avg_rating = sum(item.get("star", 0) for item in external_data) / len(external_data) if external_data else 0
    avg_reviews = sum(item.get("reviews_qty", 0) for item in external_data) / len(external_data) if external_data else 0
    asin_sales: Dict[str, float] = {}
    for item in internal_data:
        asin = item.get("asin", "")
        if asin:
            asin_sales[asin] = asin_sales.get(asin, 0) + item.get("original_price", 0)
    if total_sales > 0 and asin_sales:
        shares = [s / total_sales for s in asin_sales.values()]
        hhi = sum(s ** 2 for s in shares) * 10000
    else:
        hhi = 0
    return {
        "total_sales": round(total_sales, 2), "asin_count": asin_count,
        "avg_margin_percent": round(avg_margin * 100, 2),
        "avg_refund_percent": round(avg_refund * 100, 2),
        "competitor_count": competitor_count,
        "avg_rating": round(avg_rating, 2), "avg_reviews": round(avg_reviews, 2),
        "hhi": round(hhi, 2),
        "concentration_level": "high" if hhi > 2500 else ("medium" if hhi > 1500 else "low")
    }


def apply_bsr_filter(
    listings: List[Dict[str, Any]],
    filter_mode: str = "standard",
    custom_rules: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    rules = custom_rules if custom_rules else BSR_FILTER_RULES.get(filter_mode, BSR_FILTER_RULES["standard"])
    field_mapping = {
        "rating": ["rating", "star"],
        "subclass_rank": ["subclass_rank", "bsr", "rank"],
        "reviews_qty": ["reviews_qty", "reviews", "review_count"],
        "price": ["price"]
    }
    def get_field_value(item: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return None
    filtered = []
    for item in listings:
        valid = True
        for key, rule in rules.items():
            mapped_keys = field_mapping.get(key, [key])
            value = get_field_value(item, mapped_keys)
            if value is None:
                valid = False
                break
            try:
                v = float(value)
                if not (rule["min"] <= v <= rule["max"]):
                    valid = False
                    break
            except (ValueError, TypeError):
                valid = False
                break
        if valid:
            filtered.append(item)
    return filtered


def calculate_review_gap(listing: Dict[str, Any]) -> Dict[str, Any]:
    rating = float(listing.get("star", 0))
    reviews = int(listing.get("reviews_qty", 0))
    rating_gap = max(0, 4.5 - rating)
    review_competitiveness = "high" if reviews > 2000 else ("medium" if reviews > 1000 else "low")
    listing["rating_gap"] = round(rating_gap, 2)
    listing["review_competitiveness"] = review_competitiveness
    listing["is_improvable"] = rating_gap > 0.3 and reviews < 2000
    return listing


def classify_quadrant(sales_volume: str, refund_rate: str, sentiment_score: Optional[float] = None) -> str:
    if sales_volume == "high" and refund_rate == "low":
        return "safe_bet"
    elif sales_volume == "low" and refund_rate == "low":
        return "high_potential"
    elif sales_volume == "high" and refund_rate == "high":
        return "red_ocean"
    else:
        return "false_trend"


def classify_listings(
    listings: List[Dict[str, Any]],
    internal_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    sales_values = [item.get("original_price", 0) for item in internal_data if item.get("original_price", 0) > 0]
    refund_values = [item.get("refund_percent", 0) for item in internal_data if item.get("refund_percent") is not None]
    sales_median = sorted(sales_values)[len(sales_values) // 2] if sales_values else 0
    refund_median = sorted(refund_values)[len(refund_values) // 2] if refund_values else 0
    classified = []
    for item in listings:
        asin = item.get("asin", "")
        internal_items = [d for d in internal_data if d.get("asin") == asin]
        if internal_items:
            avg_sales = sum(d.get("original_price", 0) for d in internal_items) / len(internal_items)
            avg_refund = sum(d.get("refund_percent", 0) for d in internal_items) / len(internal_items)
            sales_volume = "high" if avg_sales > sales_median else "low"
            refund_rate = "high" if avg_refund > refund_median else "low"
        else:
            bsr = int(item.get("subclass_rank", 99999))
            sales_volume = "high" if bsr < 1000 else "low"
            rating = float(item.get("star", 0))
            refund_rate = "high" if rating < 3.8 else "low"
        quadrant = classify_quadrant(sales_volume, refund_rate)
        quadrant_labels = {
            "safe_bet": "🟢 Safe Bet", "high_potential": "🟡 High-Potential",
            "red_ocean": "🔴 Red Ocean", "false_trend": "⚫ False Trend"
        }
        item["quadrant"] = quadrant
        item["quadrant_label"] = quadrant_labels.get(quadrant, "Unknown")
        item["sales_volume"] = sales_volume
        item["refund_rate"] = refund_rate
        classified.append(item)
    return classified


def score_market_size(bsr_rank: int) -> float:
    if bsr_rank <= 100: return 100.0
    elif bsr_rank <= 500: return 90.0
    elif bsr_rank <= 1000: return 80.0
    elif bsr_rank <= 2000: return 70.0
    elif bsr_rank <= 5000: return 60.0
    elif bsr_rank <= 10000: return 45.0
    else: return 30.0


def score_margin_potential(price: float, estimated_cost: float) -> float:
    if price <= 0 or estimated_cost <= 0: return 0.0
    margin = (price - estimated_cost) / price
    if margin >= 0.40: return 100.0
    elif margin >= 0.30: return 85.0
    elif margin >= 0.20: return 70.0
    elif margin >= 0.15: return 55.0
    elif margin >= 0.10: return 40.0
    else: return 20.0


def score_competition_gap(rating: float, reviews: int) -> float:
    rating_score = max(0, (4.5 - rating) * 50)
    review_score = max(0, 50 - reviews / 40)
    return min(100, rating_score + review_score)


def score_internal_capability(category: str, internal_capability: Dict[str, Any]) -> float:
    score = 50.0
    existing_categories = internal_capability.get("existing_categories", [])
    if any(cat.lower() in category.lower() or category.lower() in cat.lower() for cat in existing_categories):
        score += 30.0
    if internal_capability.get("has_motor_supply_chain") and "electric" in category.lower():
        score += 20.0
    return min(100.0, score)


def score_pain_points(negative_reviews: List[str]) -> float:
    if not negative_reviews: return 50.0
    severity_keywords = ["broken", "defective", "poor quality", "waste", "useless", "bad", "terrible", "awful"]
    severity_count = sum(1 for r in negative_reviews if any(kw in r.lower() for kw in severity_keywords))
    base_score = min(len(negative_reviews) * 10, 60)
    severity_bonus = severity_count * 8
    return min(100.0, base_score + severity_bonus)


def calculate_opportunity_score(
    item: Dict[str, Any],
    internal_capability: Dict[str, Any]
) -> Dict[str, Any]:
    bsr = int(item.get("subclass_rank", 99999))
    price = float(item.get("price", 0))
    rating = float(item.get("star", 0))
    reviews = int(item.get("reviews_qty", 0))
    category = item.get("category", "")
    estimated_cost = float(item.get("estimated_cost", 0))
    cost_ratio = internal_capability.get("cost_ratio", DEFAULT_COST_RATIO)
    if estimated_cost <= 0 and price > 0:
        estimated_cost = price * cost_ratio
    market_size_score = score_market_size(bsr)
    margin_score = score_margin_potential(price, estimated_cost)
    competition_gap_score = score_competition_gap(rating, reviews)
    capability_score = score_internal_capability(category, internal_capability)
    pain_score = score_pain_points(item.get("negative_reviews", []))
    weights = {"market_size": 0.25, "margin_potential": 0.30, "competition_gap": 0.20, "capability_match": 0.15, "pain_point_severity": 0.10}
    total_score = (
        market_size_score * weights["market_size"] +
        margin_score * weights["margin_potential"] +
        competition_gap_score * weights["competition_gap"] +
        capability_score * weights["capability_match"] +
        pain_score * weights["pain_point_severity"]
    )
    item["opportunity_score"] = round(total_score, 1)
    item["score_breakdown"] = {
        "market_size": round(market_size_score, 1),
        "margin_potential": round(margin_score, 1),
        "competition_gap": round(competition_gap_score, 1),
        "capability_match": round(capability_score, 1),
        "pain_point_severity": round(pain_score, 1)
    }
    item["estimated_cost"] = round(estimated_cost, 2)
    item["estimated_margin_percent"] = round((price - estimated_cost) / price * 100, 1)
    quadrant = item.get("quadrant", "")
    if quadrant == "safe_bet" and total_score >= 70:
        item["recommendation"] = "GO"
        item["timeline_estimate"] = "2-3个月上市"
    elif quadrant == "high_potential" and total_score >= 75:
        item["recommendation"] = "GO"
        item["timeline_estimate"] = "3-4个月上市"
    elif quadrant == "red_ocean":
        item["recommendation"] = "NO-GO"
        item["timeline_estimate"] = "N/A"
    elif quadrant == "false_trend":
        item["recommendation"] = "NO-GO"
        item["timeline_estimate"] = "N/A"
    elif total_score >= 60:
        item["recommendation"] = "MAYBE"
        item["timeline_estimate"] = "需进一步调研"
    else:
        item["recommendation"] = "NO-GO"
        item["timeline_estimate"] = "N/A"
    return item


def run_selection(params: Dict[str, Any]) -> Dict[str, Any]:
    category = params.get("category", "Unknown")
    country = params.get("country", "US")
    filter_mode = params.get("filter_mode", "standard")
    internal_capability = params.get("internal_capability", {})
    top_n = params.get("top_n", 5)
    internal_data = params.get("internal_data", [])
    external_data = params.get("external_data", [])
    listings = params.get("listings", [])
    custom_rules = params.get("custom_rules")
    result = {"category": category, "country": country, "success": True, "errors": []}
    try:
        result["category_scan"] = scan_category(internal_data, external_data)
    except Exception as e:
        result["errors"].append(f"Step 1 品类扫描失败: {str(e)}")
        result["category_scan"] = {}
    try:
        if not listings and external_data:
            listings = external_data
        filtered_listings = apply_bsr_filter(listings, filter_mode, custom_rules)
        filtered_listings = [calculate_review_gap(item.copy()) for item in filtered_listings]
        result["filter_criteria"] = custom_rules if custom_rules else BSR_FILTER_RULES.get(filter_mode, {})
        result["candidate_count"] = len(filtered_listings)
    except Exception as e:
        result["errors"].append(f"Step 2 BSR 筛选失败: {str(e)}")
        filtered_listings = []
        result["candidate_count"] = 0
    try:
        classified_listings = classify_listings(filtered_listings, internal_data)
    except Exception as e:
        result["errors"].append(f"Step 3 四象限分类失败: {str(e)}")
        classified_listings = filtered_listings
    try:
        scored_listings = []
        for item in classified_listings:
            scored = calculate_opportunity_score(item.copy(), internal_capability)
            scored_listings.append(scored)
        scored_listings.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        top_opportunities = scored_listings[:top_n]
        risk_warnings = [
            {"asin": item.get("asin", ""), "product_name": item.get("product_name", ""),
             "quadrant": item.get("quadrant", ""), "warning": f"分类为 {item.get('quadrant_label', '')}，建议避免",
             "recommendation": "NO-GO"}
            for item in scored_listings if item.get("quadrant") in ("red_ocean", "false_trend")
        ]
        quadrant_dist = {"safe_bet": 0, "high_potential": 0, "red_ocean": 0, "false_trend": 0}
        for item in scored_listings:
            q = item.get("quadrant", "")
            if q in quadrant_dist: quadrant_dist[q] += 1
        result["top_opportunities"] = top_opportunities
        result["risk_warnings"] = risk_warnings[:5]
        result["quadrant_distribution"] = quadrant_dist
        result["all_scored"] = scored_listings
    except Exception as e:
        result["errors"].append(f"Step 4 机会评分失败: {str(e)}")
        result["top_opportunities"] = []
        result["risk_warnings"] = []
        result["quadrant_distribution"] = {}
    if result["errors"]: result["success"] = False
    return result
