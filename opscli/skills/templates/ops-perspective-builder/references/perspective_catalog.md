# 12 个标准透视图清单

## P0 级（优先配置）

### 1. 销售趋势多维透视（Sales Trend Multi-Dim）
- **目的**：按时间、组织、产品、渠道监控销售趋势
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：date_id（周）, dept_name, large_team_name
- **列维度**：平台名称、国家名称、渠道名称
- **下钻**：team_name → asin
- **指标**：原价、订单、订单数量
- **衍生指标**：客单价、环比增长率
- **图表**：透视表 + 折线图
- **复杂度**：P0

### 2. 利润结构成本拆解透视（Profit Structure Breakdown）
- **目的**：拆解成本结构，识别利润压缩点
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：dept_name, team_name, category
- **列维度**：date_id（月）, platform_name
- **下钻**：asin、ed_sku
- **指标**：毛利润、采购成本、广告费、平台手续费、税费、固定成本
- **衍生指标**：各项成本占比、毛利率
- **图表**：透视表 + 堆叠柱状图
- **复杂度**：P0

### 4. 广告效率多维透视（Ad Efficiency Multi-Dim）
- **目的**：评估 ACOS、ROAS、CPC 等核心广告指标
- **数据集**：`advertising_list_set` (`ds_0759e20F0DrG`) + `custom_type_advertising_list`
- **行维度**：date_id, campaign_name, ad_group_name
- **列维度**：ads_type, platform_name, country_name
- **下钻**：asin, sell_sku
- **指标**：ads_acos、ads_sales_cny、ads_clicks、ads_impressions
- **衍生指标**：ROAS、CPC、点击率（CTR）
- **图表**：透视表 + 组合图
- **复杂度**：P0

## P1 级（第二周配置）

### 3. 退款与售后质量透视（Refund & After-Sales）
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) + `custom_refund_place_set` (`ds_y5EoxUyLf6Aq`)
- **行维度**：date_id（周）, dept_name, team_name
- **列维度**：platform_name, refund_reason
- **下钻**：asin、ed_sku
- **指标**：退款百分比、退款数量、原价
- **衍生指标**：退款数量占比
- **图表**：透视表 + 热力图
- **复杂度**：P1

### 6. 流量与转化漏斗透视（Traffic & Conversion Funnel）
- **数据集**：`custom_asin_sales_traffic_set` (`ds_x40rpZlLlo0j`) + `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：date_id（周）, asin, product_name
- **列维度**：platform_name, country_name
- **下钻**：team_name
- **指标**：会话数、浏览量、订单数、原始价格
- **衍生指标**：转化率、人均浏览量
- **图表**：透视表 + 漏斗图
- **复杂度**：P1

### 8. 库存周转健康度透视（Inventory Turnover Health）
- **数据集**：`custom_inventory_turnover_wk_set` (`ds_97zj6R0KDKpB`)
- **行维度**：date_id（周）, dept_name, team_name
- **列维度**：platform_name, warehouse_name
- **下钻**：asin、ed_sku
- **指标**：库存数量、周转天数、销售数量天数
- **衍生指标**：可售天数
- **图表**：透视表 + 预警热力图
- **阈值**：周转天数 > 90 标红，< 14 标黄
- **复杂度**：P1

## P2 级（后续配置）

### 5. 广告类型对比透视（Ad Type Comparison）
- **数据集**：`custom_sp_ads_set`, `custom_sd_ads_set`, `custom_sb_ads_set`
- **行维度**：date_id, campaign_name
- **列维度**：ads_type, platform_name
- **指标**：advertising_fee、ads_sales_cny、ads_clicks
- **图表**：透视表 + 柱状图
- **复杂度**：P2

### 10. 促销效果透视（Promotion Effectiveness）
- **数据集**：`custom_merge_deals` + `order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：date_id, deal_type, team_name
- **列维度**：platform_name
- **指标**：original_price, orders, gross_profit
- **衍生指标**：促销 ROI
- **图表**：透视表 + 时间轴
- **复杂度**：P2

### 11. 组织绩效排名透视（Org Performance Ranking）
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：date_id（月）, dept_name, large_team_name, team_name
- **列维度**：platform_name
- **下钻**：asin
- **指标**：原价、毛利润、订单数、订单数量
- **衍生指标**：毛利率、客单价
- **图表**：透视表 + 柱状图
- **复杂度**：P2

## P3 级（高级配置）

### 7. 设备流量拆分透视（Device Traffic Split）
- **数据集**：`custom_type_asin_sales_traffic`
- **行维度**：date_id, asin, product_name
- **列维度**：device_type, platform_name
- **指标**：sessions, page_views, orders
- **图表**：透视表 + 饼图/环形图
- **复杂度**：P3

### 9. 库存结构分布透视（Inventory Structure Distribution）
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`)
- **行维度**：date_id（月）, category, team_name
- **列维度**：platform_name, warehouse_name
- **指标**：库存数量、原价、订单数量
- **衍生指标**：库存金额占比
- **图表**：透视表 + 堆叠面积图
- **复杂度**：P3

### 12. ASIN 健康度评分透视（ASIN Health Score）
- **数据集**：`order_sale_trend_adv_traffic_inv_set` (`ds_d35ac6f3910c`) + `custom_crawler_listing_snapshot` (`ds_pdTYjvLRCadv`)
- **行维度**：date_id（周）, asin, product_name
- **列维度**：platform_name, country_name
- **下钻**：ed_sku
- **指标**：original_price、gross_profit_percent、refund_percent、star、reviews_qty
- **衍生指标**：健康度评分
- **图表**：透视表 + 雷达图/散点图
- **阈值**：健康度 < 40 标红，> 80 标绿
- **复杂度**：P3
