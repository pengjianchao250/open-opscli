#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨境选品决策系统 (product_selector.py)

功能：执行完整的 4-Step 选品工作流：
  - Step 1: 品类扫描 (Category Scan)
  - Step 2: BSR 健康度筛选 (BSR Health Filter)
  - Step 3: 四象限分类 (Four-Quadrant Classification)
  - Step 4: 机会评分 (Opportunity Scoring)

输入：JSON（通过 stdin 传入）
输出：JSON（选品机会报告，通过 stdout 输出）
"""

import json
import sys
import math
from typing import Any, Dict, List, Optional

# =============================================================================
# BSR 筛选规则配置
# =============================================================================

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

# =============================================================================
# 数据集字段索引
# =============================================================================

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

# 预估成本率配置（可通过内部能力配置覆盖）
DEFAULT_COST_RATIO = 0.35

# =============================================================================
# Step 1: 品类扫描
# =============================================================================

def scan_category(
    internal_data: List[Dict[str, Any]],
    external_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    品类扫描：分析内部销售和外部竞争数据
    
    参数:
        internal_data: 内部销售数据列表
        external_data: 外部爬虫数据列表
    
    返回:
        品类扫描结果
    """
    # 计算内部指标
    total_sales = sum(item.get("original_price", 0) for item in internal_data)
    asin_count = len(set(item.get("asin", "") for item in internal_data))
    avg_margin = sum(item.get("gross_profit_percent", 0) for item in internal_data) / len(internal_data) if internal_data else 0
    avg_refund = sum(item.get("refund_percent", 0) for item in internal_data) / len(internal_data) if internal_data else 0
    
    # 计算外部指标
    competitor_count = len(set(item.get("asin", "") for item in external_data))
    avg_rating = sum(item.get("star", 0) for item in external_data) / len(external_data) if external_data else 0
    avg_reviews = sum(item.get("reviews_qty", 0) for item in external_data) / len(external_data) if external_data else 0
    
    # 计算 HHI（如果有关键词份额数据）
    market_shares = []
    asin_sales = {}
    for item in internal_data:
        asin = item.get("asin", "")
        if asin:
            asin_sales[asin] = asin_sales.get(asin, 0) + item.get("original_price", 0)
    
    if total_sales > 0:
        shares = [s / total_sales for s in asin_sales.values()]
        hhi = sum(s ** 2 for s in shares) * 10000 if shares else 0
    else:
        hhi = 0
    
    return {
        "total_sales": round(total_sales, 2),
        "asin_count": asin_count,
        "avg_margin_percent": round(avg_margin * 100, 2),
        "avg_refund_percent": round(avg_refund * 100, 2),
        "competitor_count": competitor_count,
        "avg_rating": round(avg_rating, 2),
        "avg_reviews": round(avg_reviews, 2),
        "hhi": round(hhi, 2),
        "concentration_level": "high" if hhi > 2500 else ("medium" if hhi > 1500 else "low")
    }


# =============================================================================
# Step 2: BSR 健康度筛选
# =============================================================================

def apply_bsr_filter(
    listings: List[Dict[str, Any]],
    filter_mode: str = "standard",
    custom_rules: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    应用 BSR 健康度筛选规则
    
    参数:
        listings: Listing 数据列表
        filter_mode: 筛选模式（standard/loose/strict）
        custom_rules: 自定义规则（可选）
    
    返回:
        筛选后的候选 ASIN 列表
    """
    rules = custom_rules if custom_rules else BSR_FILTER_RULES.get(filter_mode, BSR_FILTER_RULES["standard"])
    
    # 字段映射：爬虫数据中的字段名可能与规则中的字段名不同
    field_mapping = {
        "rating": ["rating", "star"],
        "subclass_rank": ["subclass_rank", "bsr", "rank"],
        "reviews_qty": ["reviews_qty", "reviews", "review_count"],
        "price": ["price"]
    }
    
    def get_field_value(item: Dict[str, Any], keys: List[str]) -> Any:
        """从 item 中获取指定字段的值，支持多个候选字段名"""
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return None
    
    filtered = []
    for item in listings:
        # 检查所有规则条件
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
    """
    计算评分缺口（我们可超越的空间）
    
    参数:
        listing: 单个 Listing 数据
    
    返回:
        包含评分缺口的 Listing 数据
    """
    rating = float(listing.get("star", 0))
    reviews = int(listing.get("reviews_qty", 0))
    
    # 评分缺口：4.5 是我们的目标，计算当前差距
    rating_gap = max(0, 4.5 - rating)
    
    # 评论数缺口：超过 1000 评论较难超越
    review_competitiveness = "high" if reviews > 2000 else ("medium" if reviews > 1000 else "low")
    
    listing["rating_gap"] = round(rating_gap, 2)
    listing["review_competitiveness"] = review_competitiveness
    listing["is_improvable"] = rating_gap > 0.3 and reviews < 2000
    
    return listing


# =============================================================================
# Step 3: 四象限分类
# =============================================================================

def classify_quadrant(
    sales_volume: str,
    refund_rate: str,
    sentiment_score: Optional[float] = None
) -> str:
    """
    将产品分类到四象限
    
    参数:
        sales_volume: 'high' 或 'low'（相对于品类中位数）
        refund_rate: 'high' 或 'low'（相对于品类中位数）
        sentiment_score: 情感评分（可选）
    
    返回:
        象限名称：safe_bet / high_potential / red_ocean / false_trend
    """
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
    """
    对候选 ASIN 进行四象限分类
    
    参数:
        listings: 候选 Listing 列表
        internal_data: 内部销售数据
    
    返回:
        分类后的 Listing 列表
    """
    # 计算品类中位数
    sales_values = [item.get("original_price", 0) for item in internal_data if item.get("original_price", 0) > 0]
    refund_values = [item.get("refund_percent", 0) for item in internal_data if item.get("refund_percent") is not None]
    
    sales_median = sorted(sales_values)[len(sales_values) // 2] if sales_values else 0
    refund_median = sorted(refund_values)[len(refund_values) // 2] if refund_values else 0
    
    classified = []
    for item in listings:
        asin = item.get("asin", "")
        # 查找对应的内部数据
        internal_items = [d for d in internal_data if d.get("asin") == asin]
        
        if internal_items:
            avg_sales = sum(d.get("original_price", 0) for d in internal_items) / len(internal_items)
            avg_refund = sum(d.get("refund_percent", 0) for d in internal_items) / len(internal_items)
            sales_volume = "high" if avg_sales > sales_median else "low"
            refund_rate = "high" if avg_refund > refund_median else "low"
        else:
            # 无内部数据时，基于外部信号推断
            bsr = int(item.get("subclass_rank", 99999))
            sales_volume = "high" if bsr < 1000 else "low"
            rating = float(item.get("star", 0))
            refund_rate = "high" if rating < 3.8 else "low"
        
        quadrant = classify_quadrant(sales_volume, refund_rate)
        quadrant_labels = {
            "safe_bet": "🟢 Safe Bet",
            "high_potential": "🟡 High-Potential",
            "red_ocean": "🔴 Red Ocean",
            "false_trend": "⚫ False Trend"
        }
        
        item["quadrant"] = quadrant
        item["quadrant_label"] = quadrant_labels.get(quadrant, "Unknown")
        item["sales_volume"] = sales_volume
        item["refund_rate"] = refund_rate
        classified.append(item)
    
    return classified


# =============================================================================
# Step 4: 机会评分
# =============================================================================

def score_market_size(bsr_rank: int) -> float:
    """
    市场规模评分（基于 BSR 反推）
    
    参数:
        bsr_rank: BSR 排名
    
    返回:
        0-100 的评分
    """
    # BSR 越小，市场越大（排名越靠前）
    if bsr_rank <= 100:
        return 100.0
    elif bsr_rank <= 500:
        return 90.0
    elif bsr_rank <= 1000:
        return 80.0
    elif bsr_rank <= 2000:
        return 70.0
    elif bsr_rank <= 5000:
        return 60.0
    elif bsr_rank <= 10000:
        return 45.0
    else:
        return 30.0


def score_margin_potential(price: float, estimated_cost: float) -> float:
    """
    毛利潜力评分
    
    参数:
        price: 售价
        estimated_cost: 预估成本
    
    返回:
        0-100 的评分
    """
    if price <= 0 or estimated_cost <= 0:
        return 0.0
    
    margin = (price - estimated_cost) / price
    if margin >= 0.40:
        return 100.0
    elif margin >= 0.30:
        return 85.0
    elif margin >= 0.20:
        return 70.0
    elif margin >= 0.15:
        return 55.0
    elif margin >= 0.10:
        return 40.0
    else:
        return 20.0


def score_competition_gap(rating: float, reviews: int) -> float:
    """
    竞争缺口评分
    
    参数:
        rating: 竞品评分
        reviews: 竞品评论数
    
    返回:
        0-100 的评分
    """
    # 评分越低、评论数越少，竞争缺口越大
    rating_score = max(0, (4.5 - rating) * 50)  # 0-50
    review_score = max(0, 50 - reviews / 40)     # 0-50 (reviews=0 -> 50, reviews=2000 -> 0)
    return min(100, rating_score + review_score)


def score_internal_capability(
    category: str,
    internal_capability: Dict[str, Any]
) -> float:
    """
    内部能力匹配度评分
    
    参数:
        category: 产品品类
        internal_capability: 内部能力配置
    
    返回:
        0-100 的评分
    """
    score = 50.0  # 基础分
    
    existing_categories = internal_capability.get("existing_categories", [])
    if any(cat.lower() in category.lower() or category.lower() in cat.lower() for cat in existing_categories):
        score += 30.0
    
    if internal_capability.get("has_motor_supply_chain") and "electric" in category.lower():
        score += 20.0
    
    return min(100.0, score)


def score_pain_points(negative_reviews: List[str]) -> float:
    """
    痛点严重程度评分
    
    参数:
        negative_reviews: 差评关键词列表
    
    返回:
        0-100 的评分
    """
    if not negative_reviews:
        return 50.0
    
    # 痛点越多且越严重，评分越高（改进空间越大）
    severity_keywords = ["broken", "defective", "poor quality", "waste", "useless", "bad", "terrible", "awful"]
    severity_count = sum(1 for r in negative_reviews if any(kw in r.lower() for kw in severity_keywords))
    
    base_score = min(len(negative_reviews) * 10, 60)
    severity_bonus = severity_count * 8
    return min(100.0, base_score + severity_bonus)


def calculate_opportunity_score(
    item: Dict[str, Any],
    internal_capability: Dict[str, Any]
) -> Dict[str, Any]:
    """
    计算单个 ASIN 的机会评分
    
    参数:
        item: 候选 ASIN 数据
        internal_capability: 内部能力配置
    
    返回:
        包含评分的 ASIN 数据
    """
    bsr = int(item.get("subclass_rank", 99999))
    price = float(item.get("price", 0))
    rating = float(item.get("star", 0))
    reviews = int(item.get("reviews_qty", 0))
    category = item.get("category", "")
    
    # 预估成本：优先使用传入的 estimated_cost，否则用 cost_ratio 估算
    estimated_cost = float(item.get("estimated_cost", 0))
    cost_ratio = internal_capability.get("cost_ratio", DEFAULT_COST_RATIO)
    if estimated_cost <= 0 and price > 0:
        estimated_cost = price * cost_ratio
    
    # 各维度评分
    market_size_score = score_market_size(bsr)
    margin_score = score_margin_potential(price, estimated_cost)
    competition_gap_score = score_competition_gap(rating, reviews)
    capability_score = score_internal_capability(category, internal_capability)
    pain_score = score_pain_points(item.get("negative_reviews", []))
    
    # 权重配置
    weights = {
        "market_size": 0.25,
        "margin_potential": 0.30,
        "competition_gap": 0.20,
        "capability_match": 0.15,
        "pain_point_severity": 0.10
    }
    
    # 综合评分
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
    
    # 推荐决策
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


# =============================================================================
# 主分析流程
# =============================================================================

def run_selection(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行完整的 4-Step 选品工作流
    
    参数:
        params: 选品参数
    
    返回:
        选品机会报告
    """
    category = params.get("category", "Unknown")
    country = params.get("country", "US")
    filter_mode = params.get("filter_mode", "standard")
    internal_capability = params.get("internal_capability", {})
    top_n = params.get("top_n", 5)
    
    # 获取输入数据
    internal_data = params.get("internal_data", [])
    external_data = params.get("external_data", [])
    listings = params.get("listings", [])
    
    # 自定义筛选规则
    custom_rules = params.get("custom_rules")
    
    result = {
        "category": category,
        "country": country,
        "success": True,
        "errors": []
    }
    
    # Step 1: 品类扫描
    try:
        category_scan = scan_category(internal_data, external_data)
        result["category_scan"] = category_scan
    except Exception as e:
        result["errors"].append(f"Step 1 品类扫描失败: {str(e)}")
        result["category_scan"] = {}
    
    # Step 2: BSR 健康度筛选
    try:
        # 如果没有提供 listings，尝试从 external_data 构建
        if not listings and external_data:
            listings = external_data
        
        filtered_listings = apply_bsr_filter(listings, filter_mode, custom_rules)
        
        # 计算评分缺口
        filtered_listings = [calculate_review_gap(item.copy()) for item in filtered_listings]
        
        result["filter_criteria"] = custom_rules if custom_rules else BSR_FILTER_RULES.get(filter_mode, {})
        result["candidate_count"] = len(filtered_listings)
    except Exception as e:
        result["errors"].append(f"Step 2 BSR 筛选失败: {str(e)}")
        filtered_listings = []
        result["candidate_count"] = 0
    
    # Step 3: 四象限分类
    try:
        classified_listings = classify_listings(filtered_listings, internal_data)
    except Exception as e:
        result["errors"].append(f"Step 3 四象限分类失败: {str(e)}")
        classified_listings = filtered_listings
    
    # Step 4: 机会评分
    try:
        scored_listings = []
        for item in classified_listings:
            scored = calculate_opportunity_score(item.copy(), internal_capability)
            scored_listings.append(scored)
        
        # 按评分排序
        scored_listings.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        
        # 取 Top N
        top_opportunities = scored_listings[:top_n]
        
        # 风险提醒（Red Ocean 和 False Trend）
        risk_warnings = [
            {
                "asin": item.get("asin", ""),
                "product_name": item.get("product_name", ""),
                "quadrant": item.get("quadrant", ""),
                "warning": f"分类为 {item.get('quadrant_label', '')}，建议避免",
                "recommendation": "NO-GO"
            }
            for item in scored_listings
            if item.get("quadrant") in ("red_ocean", "false_trend")
        ]
        
        # 象限分布统计
        quadrant_dist = {"safe_bet": 0, "high_potential": 0, "red_ocean": 0, "false_trend": 0}
        for item in scored_listings:
            q = item.get("quadrant", "")
            if q in quadrant_dist:
                quadrant_dist[q] += 1
        
        result["top_opportunities"] = top_opportunities
        result["risk_warnings"] = risk_warnings[:5]  # 最多 5 条风险提醒
        result["quadrant_distribution"] = quadrant_dist
        result["all_scored"] = scored_listings
    except Exception as e:
        result["errors"].append(f"Step 4 机会评分失败: {str(e)}")
        result["top_opportunities"] = []
        result["risk_warnings"] = []
        result["quadrant_distribution"] = {}
    
    if result["errors"]:
        result["success"] = False
    
    return result


def main():
    """
    主入口函数：从 stdin 读取 JSON 输入，输出 JSON 报告
    """
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            result = {
                "success": False,
                "error": "输入为空，请通过 stdin 传入 JSON 选品参数",
                "example_input": {
                    "category": "Kitchen Gadgets",
                    "country": "US",
                    "filter_mode": "standard",
                    "internal_capability": {
                        "has_motor_supply_chain": True,
                        "existing_categories": ["Kitchen", "Home"],
                        "exclude_categories_with_asin_count_gt": 50
                    },
                    "top_n": 5,
                    "listings": [
                        {"asin": "B08XXXXXX", "product_name": "电动蒜泥器", "subclass_rank": 1250, "price": 29.99, "star": 3.9, "reviews_qty": 847, "category": "Kitchen Gadgets"},
                        {"asin": "B09YYYYYY", "product_name": "折叠沥水架", "subclass_rank": 2800, "price": 19.99, "star": 4.1, "reviews_qty": 562, "category": "Kitchen Gadgets"},
                        {"asin": "B07ZZZZZZ", "product_name": "硅胶烘焙垫", "subclass_rank": 4200, "price": 15.99, "star": 3.7, "reviews_qty": 1200, "category": "Kitchen Gadgets"}
                    ],
                    "internal_data": [
                        {"asin": "B08XXXXXX", "original_price": 15000, "gross_profit_percent": 0.35, "refund_percent": 0.05},
                        {"asin": "B09YYYYYY", "original_price": 8000, "gross_profit_percent": 0.28, "refund_percent": 0.03}
                    ]
                }
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError as e:
            result = {
                "success": False,
                "error": f"JSON 解析失败: {str(e)}"
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        
        result = run_selection(params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["success"] else 1)
        
    except Exception as e:
        result = {
            "success": False,
            "error": f"执行异常: {str(e)}"
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
