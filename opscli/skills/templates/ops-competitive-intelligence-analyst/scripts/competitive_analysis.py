#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞争情报综合分析脚本 (competitive_analysis.py)

功能：执行完整的 3-Layer 竞争分析工作流：
  - Layer 1: 波特五力评分 (Porter's Five Forces)
  - Layer 2: 定位图生成 (Positioning Map)
  - Layer 3: 四行动框架策略 (Four Actions Framework)

输入：JSON（通过 stdin 传入）
输出：JSON（综合竞争情报报告，通过 stdout 输出）
"""

import json
import sys
import math
from typing import Any, Dict, List, Optional

# =============================================================================
# 数据集字段索引
# =============================================================================

DATASET_FIELDS: Dict[str, List[str]] = {
    "ds_d35ac6f3910c": [
        "date_id", "dept_name", "team_name", "asin", "ed_sku", "product_name",
        "category", "platform_name", "country_name", "original_price", "order_qty",
        "gross_profit", "gross_profit_percent", "channel_uuid", "listing_uuid"
    ],
    "ds_pdTYjvLRCadv": [
        "date_id", "asin", "product_name", "price", "star", "reviews_qty",
        "subclass_rank", "category", "asin_ps_uuid"
    ],
    "ds_xsTOkHIpr3ad": [
        "date_id", "search_term", "search_volume", "brand_share", "channel_uuid"
    ],
    "ds_I13gHlcdwevS": [
        "date_id", "category", "brand_name", "search_volume", "share_percent", "channel_uuid"
    ]
}

# =============================================================================
# Layer 1: 波特五力评分
# =============================================================================

def calculate_hhi(market_shares: List[float]) -> float:
    """
    计算赫芬达尔-赫希曼指数 (HHI)
    
    参数:
        market_shares: 市场份额列表（小数形式，如 [0.3, 0.2, 0.15]）
    
    返回:
        HHI 值（0-10000）
    """
    return sum(share ** 2 for share in market_shares) * 10000


def score_new_entrants(hhi: float, growth_rate: float) -> int:
    """
    评估新进入者威胁评分
    
    参数:
        hhi: 品类 HHI
        growth_rate: 品类年增长率（小数）
    
    返回:
        1-5 的评分
    """
    base_score = 3
    # HHI 越高，新进入者威胁越低
    hhi_adjustment = -1 if hhi > 2500 else (1 if hhi < 1500 else 0)
    # 增长率越高，新进入者威胁越高
    growth_adjustment = 1 if growth_rate > 0.30 else (-1 if growth_rate < 0.15 else 0)
    return min(5, max(1, base_score + hhi_adjustment + growth_adjustment))


def score_supplier_power(supplier_hhi: float, alternative_count: int) -> int:
    """
    评估供应商议价能力
    
    参数:
        supplier_hhi: 供应商集中度 HHI
        alternative_count: 可替代供应商数量
    
    返回:
        1-5 的评分
    """
    if supplier_hhi > 3000 and alternative_count < 3:
        return 5
    elif supplier_hhi > 2500 or alternative_count < 5:
        return 4
    elif supplier_hhi > 1500 and alternative_count < 10:
        return 3
    elif alternative_count < 20:
        return 2
    else:
        return 1


def score_buyer_power(price_elasticity: float, review_impact: float) -> int:
    """
    评估买方议价能力
    
    参数:
        price_elasticity: 价格弹性系数（绝对值）
        review_impact: Review 影响度评分（1-5）
    
    返回:
        1-5 的评分
    """
    elasticity_score = min(5, max(1, int(price_elasticity * 2)))
    return min(5, max(1, int((elasticity_score + review_impact) / 2)))


def score_substitutes(substitute_count: int, cross_category_sales: float) -> int:
    """
    评估替代品威胁
    
    参数:
        substitute_count: 替代品数量
        cross_category_sales: 跨品类销售额占比
    
    返回:
        1-5 的评分
    """
    if substitute_count > 10 and cross_category_sales > 0.20:
        return 5
    elif substitute_count > 5 or cross_category_sales > 0.15:
        return 4
    elif substitute_count > 3 or cross_category_sales > 0.10:
        return 3
    elif substitute_count > 1:
        return 2
    else:
        return 1


def score_rivalry(hhi: float, competitor_count: int, avg_rating_diff: float) -> int:
    """
    评估现有竞争强度
    
    参数:
        hhi: 品类 HHI
        competitor_count: 活跃竞品数量
        avg_rating_diff: 与竞品平均评分的差距
    
    返回:
        1-5 的评分
    """
    hhi_score = min(5, max(1, int(hhi / 600)))
    count_adjustment = 1 if competitor_count > 50 else (-1 if competitor_count < 10 else 0)
    return min(5, max(1, hhi_score + count_adjustment))


def calculate_porter_scores(category_data: Dict[str, Any], competitor_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    计算完整的波特五力评分卡
    
    参数:
        category_data: 品类内部数据
        competitor_data: 竞品外部数据
    
    返回:
        五力评分结果字典
    """
    market_shares = category_data.get("market_shares", [])
    hhi = calculate_hhi(market_shares) if market_shares else 2000
    
    scores = {
        "new_entrants": {
            "score": score_new_entrants(hhi, category_data.get("growth_rate", 0.20)),
            "evidence": f"品类年增 {category_data.get('growth_rate', 0.20)*100:.0f}%，HHI={hhi:.0f}"
        },
        "supplier_power": {
            "score": score_supplier_power(
                category_data.get("supplier_hhi", 2000),
                category_data.get("alternative_supplier_count", 5)
            ),
            "evidence": f"供应商 HHI={category_data.get('supplier_hhi', 2000):.0f}，替代商 {category_data.get('alternative_supplier_count', 5)} 家"
        },
        "buyer_power": {
            "score": score_buyer_power(
                competitor_data.get("price_elasticity", 1.5),
                competitor_data.get("review_impact", 3.0)
            ),
            "evidence": f"价格弹性 {competitor_data.get('price_elasticity', 1.5):.1f}，Review 影响度 {competitor_data.get('review_impact', 3.0):.1f}"
        },
        "substitutes": {
            "score": score_substitutes(
                category_data.get("substitute_count", 3),
                category_data.get("cross_category_sales", 0.10)
            ),
            "evidence": f"替代品 {category_data.get('substitute_count', 3)} 种，跨品类销售占比 {category_data.get('cross_category_sales', 0.10)*100:.0f}%"
        },
        "rivalry": {
            "score": score_rivalry(
                hhi,
                competitor_data.get("competitor_count", 20),
                competitor_data.get("avg_rating_diff", 0.2)
            ),
            "evidence": f"HHI={hhi:.0f}，活跃竞品 {competitor_data.get('competitor_count', 20)} 家"
        }
    }
    
    total_score = sum(s["score"] for s in scores.values())
    max_score = 25
    
    if total_score <= 10:
        attractiveness = "高吸引力，竞争温和"
    elif total_score <= 17:
        attractiveness = "中等吸引力，竞争激烈"
    else:
        attractiveness = "低吸引力，高度竞争"
    
    scores["total_score"] = total_score
    scores["max_score"] = max_score
    scores["attractiveness"] = attractiveness
    
    return scores


# =============================================================================
# Layer 2: 定位图生成
# =============================================================================

def generate_positioning_map(
    competitor_listings: List[Dict[str, Any]],
    self_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    生成定位图数据
    
    参数:
        competitor_listings: 竞品 Listing 数据列表
        self_data: 自身品牌数据（可选）
    
    返回:
        定位图数据字典
    """
    bubbles = []
    
    for item in competitor_listings:
        bubble = {
            "name": item.get("brand_name", item.get("asin", "Unknown")),
            "x": float(item.get("price", 0)),
            "y": float(item.get("star", 0)),
            "size": float(item.get("reviews_qty", 0)),
            "color": float(item.get("gross_profit_percent", 0)),
            "type": "competitor"
        }
        bubbles.append(bubble)
    
    if self_data:
        self_bubble = {
            "name": self_data.get("brand_name", "Our Brand"),
            "x": float(self_data.get("price", 0)),
            "y": float(self_data.get("star", 0)),
            "size": float(self_data.get("reviews_qty", 0)),
            "color": float(self_data.get("gross_profit_percent", 0)),
            "type": "self"
        }
        bubbles.append(self_bubble)
    
    # 计算定位结论
    avg_price = sum(b["x"] for b in bubbles) / len(bubbles) if bubbles else 0
    avg_rating = sum(b["y"] for b in bubbles) / len(bubbles) if bubbles else 0
    
    self_bubble = next((b for b in bubbles if b["type"] == "self"), None)
    if self_bubble:
        if self_bubble["x"] > avg_price and self_bubble["y"] > avg_rating:
            conclusion = "处于高端高评分区域，品牌溢价能力强"
        elif self_bubble["x"] < avg_price and self_bubble["y"] > avg_rating:
            conclusion = "性价比优势区，可考虑适度提价"
        elif self_bubble["x"] > avg_price and self_bubble["y"] < avg_rating:
            conclusion = "高价低评分风险区，需提升产品质量"
        else:
            conclusion = "处于中段价格带，上方有高端空间，下方有性价比红海"
    else:
        conclusion = "未提供自身数据，无法评估相对位置"
    
    return {
        "x_axis": "price",
        "y_axis": "rating",
        "x_label": "平均售价 ($)",
        "y_label": "平均评分 (★)",
        "size_legend": "评论数 (气泡大小)",
        "color_legend": "毛利率 (颜色深浅)",
        "bubbles": bubbles,
        "statistics": {
            "avg_price": round(avg_price, 2),
            "avg_rating": round(avg_rating, 2),
            "competitor_count": len([b for b in bubbles if b["type"] == "competitor"])
        },
        "positioning_conclusion": conclusion
    }


# =============================================================================
# Layer 3: 四行动框架分析
# =============================================================================

def analyze_four_actions(
    positioning_map: Dict[str, Any],
    category_data: Dict[str, Any],
    cost_structure: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    基于定位分析生成四行动策略
    
    参数:
        positioning_map: 定位图数据
        category_data: 品类数据
        cost_structure: 成本结构数据（可选）
    
    返回:
        四行动策略字典
    """
    bubbles = positioning_map.get("bubbles", [])
    self_bubble = next((b for b in bubbles if b["type"] == "self"), None)
    
    # 分析行业共性与差异点
    avg_price = positioning_map.get("statistics", {}).get("avg_price", 0)
    avg_rating = positioning_map.get("statistics", {}).get("avg_rating", 0)
    
    eliminate = []
    reduce = []
    raise_list = []
    create = []
    
    if self_bubble:
        # Eliminate: 基于定位分析生成消除策略
        if self_bubble["x"] < avg_price * 0.8:
            eliminate.append("淘汰低贡献 SKU，释放资源聚焦高价值产品线")
            eliminate.append("移除过度包装和冗余功能，降低非必要成本")
        
        # Reduce: 基于成本结构数据生成降低策略
        ad_fee_ratio = category_data.get("advertising_fee_ratio", 0.15)
        if ad_fee_ratio > 0.15:
            reduce.append(f"降低广告费占比从 {ad_fee_ratio*100:.0f}% 至行业均值 15%（降低大词依赖，转向长尾词）")
        reduce.append("减少 SKU 数量，聚焦核心变体")
        reduce.append("优化供应链，降低采购和物流成本占比")
        
        # Raise: 基于定位和品牌数据生成提升策略
        if self_bubble["y"] < avg_rating:
            gap = round(avg_rating - self_bubble["y"] + 0.3, 1)
            reduce_rating_note = f"（当前 {self_bubble['y']:.1f}，目标 {avg_rating + 0.3:.1f}）"
            raise_list.append(f"提升产品评分至 {avg_rating + 0.3:.1f}{reduce_rating_note}，重点解决差评痛点")
        brand_share = category_data.get("brand_search_share", 0.12)
        if brand_share < 0.25:
            raise_list.append(f"提升品牌搜索占比从 {brand_share*100:.0f}% 至 25%")
        if self_bubble["x"] < avg_price * 0.85:
            potential_price = round(avg_price * 0.9, 2)
            raise_list.append(f"售价有提升空间（当前 ${self_bubble['x']:.0f}，品类中位 ${avg_price:.0f}，可提至 ${potential_price}）")
        
        # Create: 基于品类趋势生成创新策略
        category_name = category_data.get("category_name", "")
        create.append("基于竞品差评痛点，开发差异化功能（需结合退款和评论数据进一步分析）")
        create.append("开发品牌独有的增值服务或配件生态，提升复购和溢价能力")
        create.append("探索品类交叉创新机会，结合内部供应链优势开发新品")
    else:
        # 无自身数据时的通用建议
        eliminate.append("评估并淘汰低贡献 SKU，释放资源")
        reduce.append("降低对大词广告的依赖，优化广告支出效率")
        raise_list.append("提升品牌搜索占比和产品评分")
        create.append("基于竞品差评痛点开发差异化功能")
    
    # 预期效果估算
    current_margin = category_data.get("gross_profit_percent", 0.18)
    expected_margin = min(0.40, current_margin + 0.10)
    current_brand_search = category_data.get("brand_search_share", 0.12)
    expected_brand_search = min(0.50, current_brand_search + 0.13)
    
    return {
        "eliminate": eliminate,
        "reduce": reduce,
        "raise": raise_list,
        "create": create,
        "expected_impact": {
            "gross_margin_improvement": f"{current_margin*100:.0f}% → {expected_margin*100:.0f}%",
            "brand_search_share": f"{current_brand_search*100:.0f}% → {expected_brand_search*100:.0f}%"
        },
        "strategy_summary": "通过差异化创新避开价格战，建立品牌壁垒"
    }


# =============================================================================
# 竞品画像生成
# =============================================================================

def build_competitor_profiles(competitor_listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    构建竞品画像
    
    参数:
        competitor_listings: 竞品 Listing 数据列表
    
    返回:
        竞品画像列表
    """
    profiles = []
    
    for item in competitor_listings:
        price = float(item.get("price", 0))
        star = float(item.get("star", 0))
        reviews = int(item.get("reviews_qty", 0))
        rank = int(item.get("subclass_rank", 99999))
        
        # 定位判断
        if price > 60 and star > 4.5:
            positioning = "Premium"
        elif price > 40 and star > 4.2:
            positioning = "Mid-High"
        elif price > 25 and star > 4.0:
            positioning = "Mid"
        else:
            positioning = "Value"
        
        # 优劣势分析
        strengths = []
        weaknesses = []
        
        if star > 4.5:
            strengths.append("High rating quality")
        if reviews > 5000:
            strengths.append("Strong social proof")
        if rank < 100:
            strengths.append("Market leader")
        if price > 70:
            weaknesses.append("High price barrier")
        if star < 4.0:
            weaknesses.append("Quality concerns")
        if reviews < 100:
            weaknesses.append("Limited traction")
        
        profile = {
            "name": item.get("brand_name", item.get("asin", "Unknown")),
            "asin": item.get("asin", ""),
            "positioning": positioning,
            "price": price,
            "rating": star,
            "review_count": reviews,
            "bsr_rank": rank,
            "strengths": strengths if strengths else ["Market presence"],
            "weaknesses": weaknesses if weaknesses else ["None obvious"],
            "strategy_guess": f"{positioning} positioning with {'quality' if star > 4.3 else 'volume'} focus"
        }
        profiles.append(profile)
    
    return profiles


# =============================================================================
# 主分析流程
# =============================================================================

def run_analysis(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行完整的 3-Layer 竞争分析
    
    参数:
        params: 分析参数
    
    返回:
        综合竞争情报报告
    """
    category = params.get("category", "Unknown")
    country = params.get("country", "US")
    time_range = params.get("time_range", "last_90_days")
    analysis_layers = params.get("analysis_layers", ["porter", "positioning", "four_actions"])
    
    # 获取输入数据（从 params 中提取）
    category_data = params.get("category_data", {})
    competitor_data = params.get("competitor_data", {})
    competitor_listings = params.get("competitor_listings", [])
    self_data = params.get("self_data")
    cost_structure = params.get("cost_structure")
    
    result = {
        "category": category,
        "country": country,
        "analysis_period": time_range,
        "analysis_layers": analysis_layers,
        "success": True,
        "errors": []
    }
    
    # Layer 1: 波特五力
    if "porter" in analysis_layers:
        try:
            result["layer1_porter_five_forces"] = calculate_porter_scores(category_data, competitor_data)
        except Exception as e:
            result["errors"].append(f"Layer 1 计算失败: {str(e)}")
            result["layer1_porter_five_forces"] = {}
    
    # Layer 2: 定位图
    if "positioning" in analysis_layers:
        try:
            result["layer2_positioning_map"] = generate_positioning_map(competitor_listings, self_data)
        except Exception as e:
            result["errors"].append(f"Layer 2 计算失败: {str(e)}")
            result["layer2_positioning_map"] = {}
    
    # Layer 3: 四行动框架
    if "four_actions" in analysis_layers:
        try:
            positioning_map = result.get("layer2_positioning_map", {})
            result["layer3_four_actions"] = analyze_four_actions(positioning_map, category_data, cost_structure)
        except Exception as e:
            result["errors"].append(f"Layer 3 计算失败: {str(e)}")
            result["layer3_four_actions"] = {}
    
    # 竞品画像
    if competitor_listings:
        try:
            result["competitor_profiles"] = build_competitor_profiles(competitor_listings)
        except Exception as e:
            result["errors"].append(f"竞品画像生成失败: {str(e)}")
            result["competitor_profiles"] = []
    
    # 综合建议
    porter = result.get("layer1_porter_five_forces", {})
    total_score = porter.get("total_score", 15)
    
    if total_score <= 10:
        recommendation = "GO — 市场吸引力高，建议进入"
    elif total_score <= 17:
        recommendation = "GO with differentiation — 市场中等吸引力，需差异化进入"
    else:
        recommendation = "NO-GO or Heavy Differentiation — 市场高度竞争，谨慎进入"
    
    result["recommendation"] = recommendation
    result["confidence_score"] = 0.75 if not result["errors"] else 0.50
    
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
                "error": "输入为空，请通过 stdin 传入 JSON 分析参数",
                "example_input": {
                    "category": "Water Bottles",
                    "country": "US",
                    "time_range": "last_90_days",
                    "competitors": "top_10_sellers",
                    "analysis_layers": ["porter", "positioning", "four_actions"],
                    "category_data": {
                        "market_shares": [0.25, 0.20, 0.15, 0.10, 0.05, 0.05, 0.05, 0.05, 0.03, 0.02],
                        "growth_rate": 0.25,
                        "supplier_hhi": 1800,
                        "alternative_supplier_count": 8,
                        "substitute_count": 2,
                        "cross_category_sales": 0.08,
                        "gross_profit_percent": 0.18,
                        "brand_search_share": 0.12,
                        "advertising_fee_ratio": 0.18
                    },
                    "competitor_data": {
                        "price_elasticity": 2.0,
                        "review_impact": 4.0,
                        "competitor_count": 35,
                        "avg_rating_diff": 0.1
                    },
                    "competitor_listings": [
                        {"brand_name": "Hydro Flask", "price": 89, "star": 4.8, "reviews_qty": 15000, "subclass_rank": 15, "gross_profit_percent": 0.35},
                        {"brand_name": "Yeti", "price": 79, "star": 4.7, "reviews_qty": 12000, "subclass_rank": 25, "gross_profit_percent": 0.32},
                        {"brand_name": "Contigo", "price": 35, "star": 4.3, "reviews_qty": 8000, "subclass_rank": 80, "gross_profit_percent": 0.22}
                    ],
                    "self_data": {"brand_name": "Our Brand", "price": 45, "star": 4.5, "reviews_qty": 5000, "gross_profit_percent": 0.18}
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
        
        result = run_analysis(params)
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
