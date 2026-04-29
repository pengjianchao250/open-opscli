#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
透视图配置生成器 (build_perspective_config.py)

功能：根据用户输入的分析目标、维度、指标等，生成完整的 BI 透视图配置 JSON。
支持 12 个标准模板匹配和自定义配置生成。

输入：JSON（通过 stdin 传入）
输出：JSON（完整透视图配置，通过 stdout 输出）
"""

import json
import sys
import re
from typing import Any, Dict, List, Optional

# =============================================================================
# 12 个标准透视图模板
# =============================================================================

PERSPECTIVE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "sales_trend": {
        "perspective_name": "销售趋势多维透视",
        "datasets": ["ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "dept_name", "alias": "部门"},
            {"field": "large_team_name", "alias": "大组"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "team_name", "alias": "销售小组"},
            {"field": "asin", "alias": "ASIN"}
        ],
        "metrics": [
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
            {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
            {"field": "order_qty", "aggregation": "SUM", "alias": "销量"}
        ],
        "derived_metrics": [
            {"formula": "SUM(original_price) / SUM(orders)", "alias": "客单价", "format": "$#,##0.00"},
            {"formula": "(SUM(original_price) - LAG(SUM(original_price))) / LAG(SUM(original_price))", "alias": "环比增长率", "format": "0.00%"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "line_chart", "x_axis": "date_id", "y_axis": "original_price", "series": "platform_name"},
        "thresholds": [{"field": "gross_profit_percent", "condition": "< 0.10", "format": "red_background"}]
    },
    "profit_structure": {
        "perspective_name": "利润结构成本拆解透视",
        "datasets": ["ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "dept_name", "alias": "部门"},
            {"field": "team_name", "alias": "销售小组"},
            {"field": "category", "alias": "品类"}
        ],
        "column_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('month', date_id)", "alias": "月份"},
            {"field": "platform_name", "alias": "平台"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"},
            {"field": "ed_sku", "alias": "公司SKU"}
        ],
        "metrics": [
            {"field": "gross_profit", "aggregation": "SUM", "alias": "毛利", "format": "$#,##0"},
            {"field": "purchase_cost", "aggregation": "SUM", "alias": "采购成本", "format": "$#,##0"},
            {"field": "advertising_fee", "aggregation": "SUM", "alias": "广告费", "format": "$#,##0"},
            {"field": "fee", "aggregation": "SUM", "alias": "平台费用", "format": "$#,##0"},
            {"field": "tax_fee", "aggregation": "SUM", "alias": "税费", "format": "$#,##0"},
            {"field": "fixed_cost", "aggregation": "SUM", "alias": "固定成本", "format": "$#,##0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(gross_profit) / SUM(original_price)", "alias": "毛利率", "format": "0.00%"},
            {"formula": "SUM(purchase_cost) / SUM(original_price)", "alias": "采购成本占比", "format": "0.00%"},
            {"formula": "SUM(advertising_fee) / SUM(original_price)", "alias": "广告费占比", "format": "0.00%"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "stacked_bar", "x_axis": "dept_name", "y_axis": "gross_profit", "series": "platform_name"},
        "thresholds": [{"field": "gross_profit_percent", "condition": "< 0.10", "format": "red_background"}]
    },
    "ad_efficiency": {
        "perspective_name": "广告效率多维透视",
        "datasets": ["ds_0759e20F0DrG"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "campaign_name", "alias": "广告活动"},
            {"field": "ad_group_name", "alias": "广告组"}
        ],
        "column_dimensions": [
            {"field": "ads_type", "alias": "广告类型"},
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"},
            {"field": "sell_sku", "alias": "销售SKU"}
        ],
        "metrics": [
            {"field": "ads_acos", "aggregation": "AVG", "alias": "ACOS", "format": "0.00%"},
            {"field": "ads_sales_cny", "aggregation": "SUM", "alias": "广告销售额", "format": "$#,##0"},
            {"field": "ads_clicks", "aggregation": "SUM", "alias": "点击量"},
            {"field": "ads_impressions", "aggregation": "SUM", "alias": "展示量"}
        ],
        "derived_metrics": [
            {"formula": "SUM(ads_sales_cny) / SUM(advertising_fee)", "alias": "ROAS", "format": "0.00"},
            {"formula": "SUM(advertising_fee) / SUM(ads_clicks)", "alias": "CPC", "format": "$#,##0.00"},
            {"formula": "SUM(ads_clicks) / SUM(ads_impressions)", "alias": "CTR", "format": "0.00%"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "combo", "x_axis": "date_id", "y_axis": "ads_acos", "series": "ads_type"},
        "thresholds": [{"field": "ads_acos", "condition": "> 0.30", "format": "red_background"}]
    },
    "inventory_turnover": {
        "perspective_name": "库存周转健康度透视",
        "datasets": ["ds_97zj6R0KDKpB"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "dept_name", "alias": "部门"},
            {"field": "team_name", "alias": "销售小组"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "warehouse_name", "alias": "仓库"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"},
            {"field": "ed_sku", "alias": "公司SKU"}
        ],
        "metrics": [
            {"field": "inventory_qty", "aggregation": "SUM", "alias": "库存量"},
            {"field": "turnover_days", "aggregation": "AVG", "alias": "周转天数", "format": "0.0"},
            {"field": "sell_qty_days", "aggregation": "AVG", "alias": "日均销量", "format": "0.0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(inventory_qty) / AVG(sell_qty_days)", "alias": "可售天数", "format": "0.0"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "heatmap", "x_axis": "team_name", "y_axis": "turnover_days", "series": "platform_name"},
        "thresholds": [
            {"field": "turnover_days", "condition": "> 90", "format": "red_background"},
            {"field": "turnover_days", "condition": "< 14", "format": "yellow_background"}
        ]
    },
    "refund_aftersales": {
        "perspective_name": "退款与售后质量透视",
        "datasets": ["ds_d35ac6f3910c", "ds_y5EoxUyLf6Aq"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "dept_name", "alias": "部门"},
            {"field": "team_name", "alias": "销售小组"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "refund_reason", "alias": "退款原因"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"},
            {"field": "ed_sku", "alias": "公司SKU"}
        ],
        "metrics": [
            {"field": "refund_percent", "aggregation": "AVG", "alias": "退款率", "format": "0.00%"},
            {"field": "refund_qty", "aggregation": "SUM", "alias": "退款数量"},
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(refund_qty) / SUM(order_qty)", "alias": "退款数量占比", "format": "0.00%"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "heatmap", "x_axis": "refund_reason", "y_axis": "refund_percent", "series": "platform_name"},
        "thresholds": [{"field": "refund_percent", "condition": "> 0.10", "format": "red_background"}]
    },
    "traffic_funnel": {
        "perspective_name": "流量与转化漏斗透视",
        "datasets": ["ds_x40rpZlLlo0j", "ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "asin", "alias": "ASIN"},
            {"field": "product_name", "alias": "产品名称"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "team_name", "alias": "销售小组"}
        ],
        "metrics": [
            {"field": "sessions", "aggregation": "SUM", "alias": "Sessions"},
            {"field": "page_views", "aggregation": "SUM", "alias": "Page Views"},
            {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(orders) / SUM(sessions)", "alias": "转化率", "format": "0.00%"},
            {"formula": "SUM(page_views) / SUM(sessions)", "alias": "人均浏览", "format": "0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "funnel", "x_axis": "date_id", "y_axis": "orders", "series": "platform_name"},
        "thresholds": [{"field": "conversion_rate", "condition": "< 0.05", "format": "red_background"}]
    },
    "org_performance": {
        "perspective_name": "组织绩效排名透视",
        "datasets": ["ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('month', date_id)", "alias": "月份"},
            {"field": "dept_name", "alias": "部门"},
            {"field": "large_team_name", "alias": "大组"},
            {"field": "team_name", "alias": "销售小组"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"}
        ],
        "metrics": [
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
            {"field": "gross_profit", "aggregation": "SUM", "alias": "毛利", "format": "$#,##0"},
            {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
            {"field": "order_qty", "aggregation": "SUM", "alias": "销量"}
        ],
        "derived_metrics": [
            {"formula": "SUM(gross_profit) / SUM(original_price)", "alias": "毛利率", "format": "0.00%"},
            {"formula": "SUM(original_price) / SUM(orders)", "alias": "客单价", "format": "$#,##0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "bar", "x_axis": "team_name", "y_axis": "original_price", "series": "platform_name"},
        "thresholds": [{"field": "gross_profit_percent", "condition": "< 0.10", "format": "red_background"}]
    },
    "ad_type_comparison": {
        "perspective_name": "广告类型对比透视",
        "datasets": ["ds_fE0flP7WonsJ"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "ad_type", "alias": "广告类型"},
            {"field": "platform_name", "alias": "平台"}
        ],
        "column_dimensions": [
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "campaign_name", "alias": "广告活动"},
            {"field": "asin", "alias": "ASIN"}
        ],
        "metrics": [
            {"field": "ads_sp", "aggregation": "SUM", "alias": "SP花费", "format": "$#,##0"},
            {"field": "ads_sd", "aggregation": "SUM", "alias": "SD花费", "format": "$#,##0"},
            {"field": "ads_sb", "aggregation": "SUM", "alias": "SB花费", "format": "$#,##0"},
            {"field": "ads_sbv", "aggregation": "SUM", "alias": "SBV花费", "format": "$#,##0"},
            {"field": "ads_sales_cny", "aggregation": "SUM", "alias": "广告销售额", "format": "$#,##0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(ads_sales_cny) / NULLIF(SUM(ads_sp) + SUM(ads_sd) + SUM(ads_sb) + SUM(ads_sbv), 0)", "alias": "综合ROAS", "format": "0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "bar", "x_axis": "ad_type", "y_axis": "ads_sales_cny", "series": "platform_name"},
        "thresholds": []
    },
    "device_traffic": {
        "perspective_name": "设备流量分布透视",
        "datasets": ["ds_8f24440d149b"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "device_type", "alias": "设备类型"},
            {"field": "platform_name", "alias": "平台"}
        ],
        "column_dimensions": [
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"}
        ],
        "metrics": [
            {"field": "sessions", "aggregation": "SUM", "alias": "Sessions"},
            {"field": "page_views", "aggregation": "SUM", "alias": "Page Views"},
            {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"}
        ],
        "derived_metrics": [
            {"formula": "SUM(orders) / NULLIF(SUM(sessions), 0)", "alias": "转化率", "format": "0.00%"},
            {"formula": "SUM(page_views) / NULLIF(SUM(sessions), 0)", "alias": "人均浏览页数", "format": "0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "pie", "x_axis": "device_type", "y_axis": "sessions", "series": "platform_name"},
        "thresholds": []
    },
    "promotion_effectiveness": {
        "perspective_name": "促销活动效果透视",
        "datasets": ["ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "dept_name", "alias": "部门"},
            {"field": "team_name", "alias": "销售小组"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"}
        ],
        "metrics": [
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
            {"field": "orders", "aggregation": "SUM", "alias": "订单数"},
            {"field": "order_qty", "aggregation": "SUM", "alias": "销量"},
            {"field": "gross_profit_percent", "aggregation": "AVG", "alias": "毛利率", "format": "0.00%"}
        ],
        "derived_metrics": [
            {"formula": "SUM(original_price) / SUM(orders)", "alias": "客单价", "format": "$#,##0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "timeline", "x_axis": "date_id", "y_axis": "original_price", "series": "platform_name"},
        "thresholds": [{"field": "gross_profit_percent", "condition": "< 0.08", "format": "red_background"}]
    },
    "inventory_structure": {
        "perspective_name": "库存结构分布透视",
        "datasets": ["ds_d35ac6f3910c"],
        "row_dimensions": [
            {"field": "dept_name", "alias": "部门"},
            {"field": "category", "alias": "品类"},
            {"field": "level_name", "alias": "产品等级"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "asin", "alias": "ASIN"},
            {"field": "ed_sku", "alias": "公司SKU"}
        ],
        "metrics": [
            {"field": "order_qty", "aggregation": "SUM", "alias": "销量"},
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
            {"field": "sell_qty_days", "aggregation": "AVG", "alias": "周转天数", "format": "0.0"},
            {"field": "refund_percent", "aggregation": "AVG", "alias": "退款率", "format": "0.00%"}
        ],
        "derived_metrics": [
            {"formula": "SUM(original_price) / SUM(order_qty)", "alias": "单品均价", "format": "$#,##0.00"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "stacked_area", "x_axis": "category", "y_axis": "order_qty", "series": "level_name"},
        "thresholds": [
            {"field": "sell_qty_days", "condition": "> 90", "format": "red_background"},
            {"field": "refund_percent", "condition": "> 0.10", "format": "red_background"}
        ]
    },
    "asin_health": {
        "perspective_name": "ASIN 健康度评分透视",
        "datasets": ["ds_d35ac6f3910c", "ds_pdTYjvLRCadv"],
        "row_dimensions": [
            {"field": "date_id", "aggregation": "DATE_TRUNC('week', date_id)", "alias": "周"},
            {"field": "asin", "alias": "ASIN"},
            {"field": "product_name", "alias": "产品名称"}
        ],
        "column_dimensions": [
            {"field": "platform_name", "alias": "平台"},
            {"field": "country_name", "alias": "国家"}
        ],
        "drill_dimensions": [
            {"field": "ed_sku", "alias": "公司SKU"}
        ],
        "metrics": [
            {"field": "original_price", "aggregation": "SUM", "alias": "销售额", "format": "$#,##0"},
            {"field": "gross_profit_percent", "aggregation": "AVG", "alias": "毛利率", "format": "0.00%"},
            {"field": "refund_percent", "aggregation": "AVG", "alias": "退款率", "format": "0.00%"},
            {"field": "star", "aggregation": "AVG", "alias": "评分", "format": "0.0"},
            {"field": "reviews_qty", "aggregation": "SUM", "alias": "评论数"}
        ],
        "derived_metrics": [
            {"formula": "AVG(star) * 20 + (1 - AVG(refund_percent)) * 30 + (1 - AVG(gross_profit_percent) < 0.1 ? 0 : 1) * 20 + LOG(SUM(reviews_qty) + 1) * 10", "alias": "健康度评分", "format": "0.0"}
        ],
        "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "radar", "x_axis": "asin", "y_axis": "health_score", "series": "platform_name"},
        "thresholds": [
            {"field": "health_score", "condition": "< 40", "format": "red_background"},
            {"field": "health_score", "condition": "> 80", "format": "green_background"}
        ]
    }
}

# =============================================================================
# 数据集字段索引（用于验证）
# =============================================================================

DATASET_FIELDS: Dict[str, List[str]] = {
    "ds_d35ac6f3910c": [
        "date_id", "dept_name", "large_team_name", "team_name", "dev_team_name",
        "asin", "parent_asin", "ed_sku", "product_name", "brand_name", "category",
        "platform_name", "country_name", "channel_name", "channel_uuid", "listing_uuid",
        "original_price", "orders", "order_qty", "gross_profit", "gross_profit_percent",
        "purchase_cost", "advertising_fee", "fee", "tax_fee", "fixed_cost",
        "refund_percent", "refund_qty", "level_name"
    ],
    "ds_97zj6R0KDKpB": [
        "date_id", "dept_name", "team_name", "asin", "ed_sku", "platform_name",
        "warehouse_name", "inventory_qty", "turnover_days", "sell_qty_days",
        "channel_uuid", "listing_uuid"
    ],
    "ds_pdTYjvLRCadv": [
        "date_id", "asin", "product_name", "price", "star", "reviews_qty",
        "subclass_rank", "category", "asin_ps_uuid"
    ],
    "ds_0759e20F0DrG": [
        "date_id", "campaign_name", "ad_group_name", "ads_type", "platform_name",
        "country_name", "asin", "sell_sku", "ads_acos", "ads_sales_cny",
        "ads_clicks", "ads_impressions", "advertising_fee", "channel_uuid", "listing_uuid"
    ],
    "ds_x40rpZlLlo0j": [
        "date_id", "asin", "product_name", "platform_name", "country_name",
        "sessions", "page_views", "orders", "channel_uuid", "listing_uuid"
    ],
    "ds_y5EoxUyLf6Aq": [
        "date_id", "refund_reason", "refund_qty", "asin", "ed_sku",
        "platform_name", "channel_uuid", "listing_uuid"
    ]
}

# =============================================================================
# 图表类型映射
# =============================================================================

CHART_TYPE_ALIASES: Dict[str, str] = {
    "line_chart": "折线图",
    "bar": "柱状图",
    "stacked_bar": "堆叠柱状图",
    "pivot_table": "透视表",
    "heatmap": "热力图",
    "combo": "组合图",
    "funnel": "漏斗图",
    "pie": "饼图",
    "donut": "环形图",
    "stacked_area": "堆叠面积图",
    "timeline": "时间轴",
    "radar": "雷达图",
    "scatter": "散点图"
}

# =============================================================================
# 核心函数
# =============================================================================

def match_template(goal: str) -> Optional[str]:
    """
    根据用户目标匹配最佳模板
    
    参数:
        goal: 用户分析目标描述
    
    返回:
        匹配到的模板 key，未匹配到则返回 None
    """
    goal_lower = goal.lower()
    
    # 关键词映射规则
    keyword_map = {
        "sales_trend": ["销售趋势", "销售", "销售额", "营收", "revenue", "sales trend", "sales"],
        "profit_structure": ["利润", "成本", "毛利", "profit", "cost", "breakdown", "结构"],
        "ad_efficiency": ["广告", "ad", "acos", "roas", "cpc", "campaign", "广告效率"],
        "ad_type_comparison": ["广告类型", "广告对比", "sp sd sb", "ad type", "ad comparison", "类型对比"],
        "inventory_turnover": ["库存", "周转", "inventory", "turnover", "库存周转"],
        "inventory_structure": ["库存结构", "库存分布", "inventory structure", "库存品类"],
        "refund_aftersales": ["退款", "售后", "refund", "return", "售后质量"],
        "traffic_funnel": ["流量", "转化", "漏斗", "traffic", "conversion", "funnel", "sessions"],
        "device_traffic": ["设备", "device", "设备流量", "device traffic", "流量分布"],
        "org_performance": ["组织", "绩效", "排名", "团队", "performance", "ranking", "组织绩效"],
        "promotion_effectiveness": ["促销", "活动", "promotion", "deal", "促销效果", "活动效果"],
        "asin_health": ["asin", "健康", "health", "评分", "产品健康"]
    }
    
    scores = {}
    for template_key, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in goal_lower)
        if score > 0:
            scores[template_key] = score
    
    if not scores:
        return None
    
    return max(scores, key=scores.get)


def apply_scope(config: Dict[str, Any], scope: Optional[str]) -> Dict[str, Any]:
    """
    将用户指定的 scope 转换为过滤器配置
    
    参数:
        config: 当前配置字典
        scope: 用户指定的范围条件，如 "team_name = 'Kitchen-Team-A'"
    
    返回:
        更新后的配置字典
    """
    if not scope:
        return config
    
    filters = config.get("filters", [])
    
    # 解析简单的 scope 表达式: "field = 'value'" 或 "field in ['v1', 'v2']"
    # 支持: eq, in, between, gt, lt, gte, lte
    scope = scope.strip()
    
    # 匹配 "field = 'value'"
    eq_match = re.match(r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]", scope)
    if eq_match:
        filters.append({
            "field": eq_match.group(1),
            "operator": "eq",
            "value": eq_match.group(2)
        })
    else:
        # 匹配 "field in ['v1', 'v2']"
        in_match = re.match(r"(\w+)\s+in\s+\[(.*)\]", scope, re.IGNORECASE)
        if in_match:
            values = [v.strip().strip("'\"") for v in in_match.group(2).split(",")]
            filters.append({
                "field": in_match.group(1),
                "operator": "in",
                "value": values
            })
        else:
            # 无法解析时，作为原始条件保留
            filters.append({
                "field": "_raw",
                "operator": "raw",
                "value": scope
            })
    
    config["filters"] = filters
    return config


def apply_time_range(config: Dict[str, Any], time_range: Optional[str]) -> Dict[str, Any]:
    """
    将时间范围转换为过滤器
    
    参数:
        config: 当前配置字典
        time_range: 时间范围描述，如 "last_90_days", "2025-01-01~2025-01-31"
    
    返回:
        更新后的配置字典
    """
    if not time_range:
        return config
    
    filters = config.get("filters", [])
    
    # 检查是否已存在 date_id 过滤器
    has_date_filter = any(f.get("field") == "date_id" for f in filters)
    if has_date_filter:
        return config
    
    if time_range == "last_7_days":
        filters.append({"field": "date_id", "operator": "between", "value": "last_7_days"})
    elif time_range == "last_30_days":
        filters.append({"field": "date_id", "operator": "between", "value": "last_30_days"})
    elif time_range == "last_90_days":
        filters.append({"field": "date_id", "operator": "between", "value": "last_90_days"})
    elif time_range == "last_180_days":
        filters.append({"field": "date_id", "operator": "between", "value": "last_180_days"})
    elif time_range == "last_365_days":
        filters.append({"field": "date_id", "operator": "between", "value": "last_365_days"})
    elif "~" in time_range or " to " in time_range:
        # 解析具体日期范围
        delimiter = "~" if "~" in time_range else " to "
        dates = time_range.split(delimiter)
        if len(dates) == 2:
            filters.append({
                "field": "date_id",
                "operator": "between",
                "value": [dates[0].strip(), dates[1].strip()]
            })
    else:
        filters.append({"field": "date_id", "operator": "between", "value": time_range})
    
    config["filters"] = filters
    return config


def apply_customizations(config: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    应用用户自定义配置
    
    参数:
        config: 当前配置字典
        kwargs: 用户自定义参数
    
    返回:
        更新后的配置字典
    """
    # 覆盖维度
    if "dimensions" in kwargs:
        dims = kwargs["dimensions"]
        # 前三个作为行维度，其余作为列维度
        config["row_dimensions"] = [{"field": d, "alias": d} for d in dims[:3]]
        if len(dims) > 3:
            config["column_dimensions"] = [{"field": d, "alias": d} for d in dims[3:]]
    
    # 覆盖指标
    if "metrics" in kwargs:
        config["metrics"] = [
            {"field": m, "aggregation": "SUM", "alias": m}
            for m in kwargs["metrics"]
        ]
    
    # 覆盖图表类型
    if "chart_type" in kwargs:
        chart_type = kwargs["chart_type"]
        config["chart_config"]["secondary_chart"] = chart_type
    
    # 下钻配置
    if "drill_down" in kwargs:
        if not kwargs["drill_down"]:
            config["drill_dimensions"] = []
    
    return config


def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    验证配置的有效性
    
    参数:
        config: 配置字典
    
    返回:
        错误信息列表，空列表表示验证通过
    """
    errors = []
    
    datasets = config.get("datasets", [])
    if not datasets:
        errors.append("未指定数据集")
        return errors
    
    # 验证字段存在性
    all_dims = (
        config.get("row_dimensions", []) +
        config.get("column_dimensions", []) +
        config.get("drill_dimensions", [])
    )
    all_metrics = config.get("metrics", []) + config.get("derived_metrics", [])
    
    for dataset in datasets:
        available_fields = DATASET_FIELDS.get(dataset, [])
        if not available_fields:
            errors.append(f"未知数据集: {dataset}")
            continue
        
        for dim in all_dims:
            field = dim.get("field", "")
            if field and field not in available_fields:
                errors.append(f"字段 '{field}' 不存在于数据集 '{dataset}' 中")
        
        for metric in all_metrics:
            field = metric.get("field", "")
            if field and field not in available_fields:
                errors.append(f"指标字段 '{field}' 不存在于数据集 '{dataset}' 中")
    
    # 验证跨数据集 Join Key
    if len(datasets) > 1:
        join_candidates = ["asin", "ed_sku", "channel_uuid", "listing_uuid"]
        all_fields = set()
        for dataset in datasets:
            all_fields.update(DATASET_FIELDS.get(dataset, []))
        
        available_joins = [j for j in join_candidates if j in all_fields]
        if not available_joins:
            errors.append(f"数据集 {datasets} 之间没有可用的 Join Key")
        else:
            config["join_keys"] = available_joins
    
    return errors


def generate_sql_template(config: Dict[str, Any]) -> str:
    """
    生成 SQL 查询模板
    
    参数:
        config: 配置字典
    
    返回:
        SQL 模板字符串
    """
    datasets = config.get("datasets", [])
    row_dims = config.get("row_dimensions", [])
    col_dims = config.get("column_dimensions", [])
    metrics = config.get("metrics", [])
    filters = config.get("filters", [])
    
    all_dims = row_dims + col_dims
    
    # SELECT 子句
    select_parts = []
    for dim in all_dims:
        field = dim["field"]
        agg = dim.get("aggregation", "")
        alias = dim.get("alias", field)
        if agg:
            select_parts.append(f"  {agg} AS {alias}")
        else:
            select_parts.append(f"  {field} AS {alias}")
    
    for metric in metrics:
        field = metric["field"]
        agg = metric.get("aggregation", "SUM")
        alias = metric.get("alias", field)
        select_parts.append(f"  {agg}({field}) AS {alias}")
    
    select_clause = ",\n".join(select_parts)
    
    # FROM 子句
    from_clause = f"FROM {datasets[0]}" if datasets else "FROM table"
    
    # WHERE 子句
    where_parts = []
    for f in filters:
        field = f["field"]
        op = f["operator"]
        value = f["value"]
        if field == "_raw":
            where_parts.append(f"  ({value})")
        elif op == "between":
            if isinstance(value, list):
                where_parts.append(f"  {field} BETWEEN '{value[0]}' AND '{value[1]}'")
            else:
                where_parts.append(f"  {field} BETWEEN 'start' AND 'end'  /* {value} */")
        elif op == "in":
            vals = ", ".join(f"'{v}'" for v in value)
            where_parts.append(f"  {field} IN ({vals})")
        elif op == "eq":
            where_parts.append(f"  {field} = '{value}'")
        else:
            where_parts.append(f"  {field} {op} '{value}'")
    
    where_clause = "\nAND".join(where_parts) if where_parts else "1=1"
    
    # GROUP BY 子句
    group_parts = [d.get("alias", d["field"]) for d in all_dims]
    group_clause = ", ".join(group_parts) if group_parts else ""
    
    sql = f"""SELECT
{select_clause}
{from_clause}
WHERE
{where_clause}
{"GROUP BY " + group_clause if group_clause else ""}
LIMIT 10000"""
    
    return sql


def build_config(goal: str, scope: Optional[str], time_range: Optional[str], **kwargs) -> Dict[str, Any]:
    """
    主函数：根据用户输入构建完整透视图配置
    
    参数:
        goal: 分析目标
        scope: 数据范围
        time_range: 时间范围
        **kwargs: 其他自定义参数
    
    返回:
        完整配置字典
    """
    # Step 1: 匹配模板
    template_key = match_template(goal)
    
    if template_key and template_key in PERSPECTIVE_TEMPLATES:
        config = PERSPECTIVE_TEMPLATES[template_key].copy()
    else:
        # 未匹配到模板，使用通用配置
        config = {
            "perspective_name": f"自定义透视 - {goal}",
            "datasets": ["ds_d35ac6f3910c"],
            "row_dimensions": [],
            "column_dimensions": [],
            "drill_dimensions": [],
            "metrics": [],
            "derived_metrics": [],
            "filters": [],
            "chart_config": {"primary_chart": "pivot_table", "secondary_chart": "line_chart"},
            "thresholds": []
        }
    
    # Step 2: 应用 scope
    config = apply_scope(config, scope)
    
    # Step 3: 应用时间范围
    config = apply_time_range(config, time_range)
    
    # Step 4: 应用自定义配置
    config = apply_customizations(config, kwargs)
    
    # Step 5: 验证
    errors = validate_config(config)
    config["validation"] = {
        "passed": len(errors) == 0,
        "errors": errors
    }
    
    # Step 6: 生成 SQL 模板
    config["sql_template"] = generate_sql_template(config)
    
    # Step 7: 生成 setup 说明
    config["setup_instructions"] = (
        "1. 在 Superset/Metabase 中创建新图表\n"
        "2. 选择数据集: " + ", ".join(config.get("datasets", [])) + "\n"
        "3. 配置行维度: " + ", ".join(d.get("alias", d["field"]) for d in config.get("row_dimensions", [])) + "\n"
        "4. 配置列维度: " + ", ".join(d.get("alias", d["field"]) for d in config.get("column_dimensions", [])) + "\n"
        "5. 配置指标: " + ", ".join(m.get("alias", m["field"]) for m in config.get("metrics", [])) + "\n"
        "6. 应用过滤条件并保存"
    )
    
    return config


def main():
    """
    主入口函数：从 stdin 读取 JSON 输入，输出 JSON 配置
    """
    try:
        # 读取 stdin 输入
        input_data = sys.stdin.read().strip()
        if not input_data:
            result = {
                "success": False,
                "error": "输入为空，请通过 stdin 传入 JSON 配置参数",
                "example_input": {
                    "goal": "分析销售趋势",
                    "scope": "team_name = 'Kitchen-Team-A'",
                    "time_range": "last_90_days",
                    "dimensions": ["date_id", "dept_name", "platform_name"],
                    "metrics": ["original_price", "orders"],
                    "chart_type": "line_chart"
                }
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        
        # 解析 JSON
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError as e:
            result = {
                "success": False,
                "error": f"JSON 解析失败: {str(e)}"
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        
        # 提取参数
        goal = params.get("goal", "")
        scope = params.get("scope")
        time_range = params.get("time_range")
        
        # 移除已提取的参数，剩余作为 kwargs
        kwargs = {k: v for k, v in params.items() if k not in ("goal", "scope", "time_range")}
        
        # 构建配置
        config = build_config(goal, scope, time_range, **kwargs)
        
        # 输出结果
        result = {
            "success": config["validation"]["passed"],
            "config": config,
            "matched_template": match_template(goal),
            "warnings": config["validation"]["errors"] if not config["validation"]["passed"] else []
        }
        
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if config["validation"]["passed"] else 1)
        
    except Exception as e:
        result = {
            "success": False,
            "error": f"执行异常: {str(e)}"
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
