# Skill 开发设计文档：ops-perspective-builder

> **Skill 名称**：`ops-perspective-builder`
> **复杂度等级**：Level 3 — 复杂（多步骤工作流 + 跨数据集整合）
> **预计开发时间**：7-10 天
> **业务价值**：极高（运营周会核心基础设施）

---

## 一、Skill 定位

### 1.1 一句话描述

根据用户选择的分析主题和数据集，自动构建 BI 透视图的维度、指标、过滤条件配置方案，输出可直接在 Superset/Metabase 中执行的配置清单。

### 1.2 解决什么痛点

- 运营团队不会配置 BI 透视图，每次都需要数据团队支持
- 透视图配置不规范，同一个指标在不同图中计算口径不一致
- 新入职分析师不清楚有哪些数据集和字段可用

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 透视图构建 | "帮我构建一个销售趋势多维透视图" |
| 周会看板 | "生成本周运营周会需要的透视图配置" |
| 新主题分析 | "我想分析广告效率和转化漏斗的关系，怎么配置透视图？" |
| 下钻设计 | "设计一个从集团到 ASIN 的利润结构下钻透视图" |

---

## 二、文件结构设计

```
opscli/skills/ops-perspective-builder/
├── SKILL.md                              # 核心指令文件（工作流模板）
├── scripts/
│   ├── build_perspective_config.py       # 透视图配置生成器
│   ├── validate_config.py                # 配置验证器
│   └── suggest_dimensions.py             # 维度推荐引擎
└── reference/
    ├── perspective_catalog.md            # 12个标准透视图目录
    ├── dataset_fields_index.md           # 数据集字段索引
    ├── dimension_metric_pool.md          # 公共维度池与指标池
    └── chart_type_guide.md               # 图表类型选择指南
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: ops-perspective-builder
description: Builds BI pivot table and chart configurations by automatically selecting dimensions, metrics, and filters from 41 datasets. Outputs executable configuration plans for Superset/Metabase. Use when creating operational dashboards, designing drill-down analysis views, or configuring weekly review reports.
---
```

### 3.2 主体内容大纲

```markdown
# ops Perspective Builder

Automates BI perspective configuration by mapping user requirements to dataset fields and chart types.

## Capabilities

- Standard perspective configuration (12 built-in templates)
- Custom perspective design from scratch
- Dimension and metric recommendation
- Drill-down path design
- Filter and threshold configuration
- Cross-dataset join suggestions

## Workflow

### Phase 1: Requirement Analysis
1. Understand user's analysis goal
2. Identify relevant datasets from 41 available
3. Determine row/column/drill dimensions
4. Select metrics and aggregation methods

### Phase 2: Configuration Design
1. Map dimensions to dataset fields
2. Design metric calculations (SUM/AVG/COUNT/formula)
3. Configure filters and thresholds
4. Select appropriate chart types

### Phase 3: Validation
1. Verify all fields exist in target datasets
2. Check join keys for cross-dataset analysis
3. Validate formula syntax
4. Review output format

### Phase 4: Output Generation
1. Generate JSON/YAML configuration
2. Provide SQL query template
3. Include setup instructions for BI tool

## 12 Standard Perspectives

| # | Perspective Name | Dataset | Chart Type | Complexity |
|---|-----------------|---------|-----------|------------|
| 1 | Sales Trend Multi-Dim | order_sale_trend_adv_traffic_inv_set | Pivot + Line | P0 |
| 2 | Profit Structure Breakdown | order_sale_trend_adv_traffic_inv_set | Pivot + Stacked Bar | P0 |
| 3 | Refund & After-Sales | order_sale_trend_* + custom_refund_place_set | Pivot + Heatmap | P1 |
| 4 | Ad Efficiency Multi-Dim | advertising_list_set + custom_type_* | Pivot + Combo | P0 |
| 5 | Ad Type Comparison | custom_sp/sd/sb_ads_set | Pivot + Bar | P2 |
| 6 | Traffic & Conversion Funnel | custom_asin_sales_traffic_set + order_sale_trend_* | Pivot + Funnel | P1 |
| 7 | Device Traffic Split | custom_type_asin_sales_traffic | Pivot + Pie/Donut | P3 |
| 8 | Inventory Turnover Health | custom_inventory_turnover_wk_* | Pivot + Heatmap | P1 |
| 9 | Inventory Structure Distribution | order_sale_trend_adv_traffic_inv_set | Pivot + Stacked Area | P3 |
| 10 | Promotion Effectiveness | custom_merge_deals + order_sale_trend_* | Pivot + Timeline | P2 |
| 11 | Org Performance Ranking | order_sale_trend_adv_traffic_inv_set | Pivot + Bar | P2 |
| 12 | ASIN Health Score | order_sale_trend_* + custom_crawler_listing_snapshot | Pivot + Radar/Scatter | P3 |

## Decision Tree: Which Perspective?

```
What's your analysis goal?
├── Sales/Profit overview
│   ├── Trend over time → Perspective 1 (Sales Trend)
│   └── Cost breakdown → Perspective 2 (Profit Structure)
├── Advertising
│   ├── Campaign diagnosis → Perspective 4 (Ad Efficiency)
│   └── Type comparison → Perspective 5 (Ad Type)
├── Traffic/Conversion
│   ├── Funnel analysis → Perspective 6 (Traffic Funnel)
│   └── Device split → Perspective 7 (Device Traffic)
├── Inventory
│   ├── Turnover health → Perspective 8 (Inventory Turnover)
│   └── Structure distribution → Perspective 9 (Inventory Structure)
├── Operations
│   ├── Refund quality → Perspective 3 (Refund)
│   ├── Promotion ROI → Perspective 10 (Promotion)
│   └── Team ranking → Perspective 11 (Org Performance)
└── Product
    └── Health diagnosis → Perspective 12 (ASIN Health)
```

## Configuration Output Format

```json
{
  "perspective_name": "销售趋势多维透视",
  "datasets": ["order_sale_trend_adv_traffic_inv_set"],
  "row_dimensions": [
    {"field": "date_id", "aggregation": "date_trunc('week', date_id)", "alias": "周"},
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
    {"formula": "SUM(price) / SUM(orders)", "alias": "客单价", "format": "$#,##0.00"},
    {"formula": "(SUM(original_price) - LAG(SUM(original_price))) / LAG(SUM(original_price))", "alias": "环比增长率", "format": "0.00%"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": "last_90_days"},
    {"field": "level_name", "operator": "in", "value": ["A", "B"]}
  ],
  "chart_config": {
    "primary_chart": "pivot_table",
    "secondary_chart": "line_chart",
    "x_axis": "date_id",
    "y_axis": "original_price",
    "series": "platform_name"
  },
  "thresholds": [
    {"field": "gross_profit_percent", "condition": "< 0.10", "format": "red_background"}
  ],
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["date_id", "dept_name", "large_team_name", "platform_name", "country_name"],
    "metrics": ["original_price", "orders", "order_qty"],
    "filters": {
      "date_range": ["last_90_days"],
      "level_name": ["A", "B"]
    }
  },
  "query_result": {
    "dataset": "ds_d35ac6f3910c",
    "rows": [...],
    "execution_time_ms": 1200
  }
}
```

## Scripts

- `build_perspective_config.py`: Generates perspective configuration JSON
- `validate_config.py`: Validates field existence and join compatibility
- `suggest_dimensions.py`: Suggests dimensions based on analysis goal

## Best Practices

1. Always prefer `order_sale_trend_adv_traffic_inv_set` for cross-domain analysis
2. Use `date_id` as primary time dimension
3. Include at least one organizational dimension for drill-down
4. Add threshold highlighting for key metrics
5. Validate dataset join keys before cross-dataset analysis
```

---

## 四、脚本设计

### 4.1 build_perspective_config.py

**功能**：根据用户输入生成完整的透视图配置

**输入**：
```json
{
  "goal": "分析销售趋势",
  "scope": "team_name = 'Kitchen-Team-A'",
  "time_range": "last_90_days",
  "dimensions": ["date_id", "dept_name", "platform_name", "country_name"],
  "metrics": ["original_price", "orders", "gross_profit"],
  "chart_type": "line_chart",
  "drill_down": true,
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["date_id", "dept_name", "platform_name", "country_name"],
    "metrics": ["original_price", "orders", "gross_profit"],
    "filters": {
      "team_name": "Kitchen-Team-A",
      "date_range": ["last_90_days"]
    }
  }
}
```

**输出**：完整的 JSON 配置（见上文）

**核心逻辑**：
```python
PERSPECTIVE_TEMPLATES = {
    'sales_trend': {
        'dataset': 'order_sale_trend_adv_traffic_inv_set',
        'row_dims': ['date_id', 'dept_name', 'large_team_name'],
        'col_dims': ['platform_name', 'country_name'],
        'metrics': ['original_price', 'orders', 'order_qty'],
        'chart': 'pivot_table + line_chart'
    },
    'profit_structure': {
        'dataset': 'order_sale_trend_adv_traffic_inv_set',
        'row_dims': ['dept_name', 'team_name'],
        'col_dims': ['date_id'],
        'metrics': ['gross_profit', 'purchase_cost', 'advertising_fee', 'fee'],
        'chart': 'pivot_table + stacked_bar'
    },
    # ... 其他模板
}

def build_config(goal, scope, time_range, **kwargs):
    """
    根据目标匹配模板，然后定制化
    """
    template = match_template(goal)
    config = apply_scope(template, scope)
    config = apply_time_range(config, time_range)
    config = apply_customizations(config, kwargs)
    return config
```

### 4.2 validate_config.py

**功能**：验证配置的有效性

**检查项**：
1. 所有字段是否存在于目标数据集
2. 跨数据集分析时，join keys 是否兼容
3. 公式语法是否正确
4. 聚合方式是否与字段类型匹配

### 4.3 suggest_dimensions.py

**功能**：基于分析目标推荐维度

**算法**：
```python
def suggest_dimensions(goal, dataset):
    """
    基于关键词匹配推荐维度
    """
    goal_keywords = extract_keywords(goal)
    
    dimension_scores = {}
    for dim in DATASET_FIELDS[dataset]:
        score = keyword_match_score(goal_keywords, dim['description'])
        if dim['field_type'] == 'dimension':
            dimension_scores[dim['field_name']] = score
    
    return sorted(dimension_scores.items(), key=lambda x: x[1], reverse=True)[:10]
```

### 4.4 数据查询接口规范

#### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

#### 查询构造方式

本 Skill 是透视图构建助手，需要支持多种数据集的查询配置。核心数据集包括：

| 数据集 | dataset_alias | inner_where_enabled | 权限字段 |
|--------|--------------|-------------------|---------|
| order_sale_trend_adv_traffic_inv_set | ds_d35ac6f3910c | false | channel_uuid, listing_uuid |
| advertising_list_set | ds_0759e20F0DrG | true | channel_uuid, listing_uuid |
| custom_asin_sales_traffic_set | ds_x40rpZlLlo0j | true | channel_uuid, listing_uuid |
| custom_inventory_turnover_wk_set | ds_97zj6R0KDKpB | false | channel_uuid, listing_uuid |
| custom_refund_place_set | ds_y5EoxUyLf6Aq | false | channel_uuid, listing_uuid |
| custom_crawler_listing_snapshot | ds_pdTYjvLRCadv | false | asin_ps_uuid |
| custom_brand_search_query_set | ds_xsTOkHIpr3ad | false | channel_uuid |
| custom_brand_search_catalog_set | ds_I13gHlcdwevS | false | channel_uuid |
| custom_operation_suggest_suggestions_set | ds_zY0BAi0Txsga | false | channel_uuid, listing_uuid |
| custom_merge_deals | ds_q0sbhk0fqwFh | false | channel_uuid, listing_uuid |

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension date_id --dimension dept_name --dimension large_team_name \
  --metric original_price --metric orders --metric order_qty \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

销售趋势透视图查询（`ds_d35ac6f3910c`，非子查询类型）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM core_data.smarty_sale_stat ...)",
      "alias": "ds_d35ac6f3910c",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "DATE_TRUNC('week', ds_d35ac6f3910c.date_id)", "alias": "f_week" },
      { "expr": "ds_d35ac6f3910c.dept_name", "alias": "f_dept" },
      { "expr": "ds_d35ac6f3910c.large_team_name", "alias": "f_large_team" },
      { "expr": "ds_d35ac6f3910c.platform_name", "alias": "f_platform" },
      { "expr": "ds_d35ac6f3910c.country_name", "alias": "f_country" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.orders", "alias": "f_orders", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_qty", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] },
        { "field": "ds_d35ac6f3910c.level_name", "operator": "in", "value": ["A", "B"] }
      ]
    },
    "groupBy": ["f_week", "f_dept", "f_large_team", "f_platform", "f_country"],
    "limit": 10000
  }
}
```

广告效率透视图查询（`ds_0759e20F0DrG`，**子查询类型**）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_advertising.list_set ... WHERE ... {and_sub_placeholder_1} ...)",
      "alias": "ds_0759e20F0DrG",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_0759e20F0DrG.date_id", "alias": "f_date" },
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ds_0759e20F0DrG.ad_group_name", "alias": "f_ad_group" },
      { "expr": "ds_0759e20F0DrG.ads_type", "alias": "f_ad_type" },
      { "expr": "ds_0759e20F0DrG.advertising_fee", "alias": "f_cost", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_sales_cny", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_clicks", "alias": "f_clicks", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_impressions", "alias": "f_impressions", "aggregation": "SUM" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [] }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_0759e20F0DrG.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_date", "f_campaign", "f_ad_group", "f_ad_type"],
    "limit": 10000
  }
}
```

#### 数据集类型判断

**关键**：必须先判断数据集是"子查询类型"还是"非子查询类型"：

```python
# 判断方法：检查 from.table 是否包含内层占位符
is_inner_where = '{where_sub_placeholder_' in table_sql or '{and_sub_placeholder_' in table_sql

# 子查询类型（inner_where_enabled=true）
# - 维度过滤条件放 innerWhere[1]
# - 日期条件放 where

# 非子查询类型（标准模式）
# - 所有条件放 where
```

#### 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`，如 `f_754ed2fb474f09f9`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

#### translate 字段映射

跨表关联查询时，可能需要使用 translate 翻译枚举：

| 过滤字段 | translate 枚举值 | 含义 |
|---------|-----------------|------|
| `platform_name` | `PLATFORM_TO_SKU` | 平台 → 公司 SKU |
| `country_name` | `COUNTRY_TO_SKU` | 国家 → 公司 SKU |
| `channel_name` | `CHANNEL_TO_SKU` | 渠道 → 公司 SKU |
| `team_name` | `TEAM_TO_SKU` | 销售小组 → 公司 SKU |
| `ed_sku` | `SKU_TO_ASIN` | 公司 SKU → ASIN |
| `asin` | `ASIN_TO_SKU` | ASIN → 公司 SKU |

#### 公式指标查询规范

公式指标必须使用完整表达式格式：

```json
// 正确
{
  "expr": "ROUND(SUM(dsp)/SUM(price), 4)",
  "alias": "f_yZZfW7cNu8nYMGCS"
}

// 错误：额外传 aggregation 会导致二次聚合
{
  "expr": "sell_qty_days",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

---

## 五、Reference 文档设计

### 5.1 perspective_catalog.md

```markdown
# 12个标准透视图目录

## P0 级（优先配置）

### 1. 销售趋势多维透视
- **目的**：按时间、组织、产品、渠道监控销售趋势
- **数据集**：order_sale_trend_adv_traffic_inv_set
- **行维度**：date_id（周）, dept_name, large_team_name
- **列维度**：platform_name, country_name, channel_name
- **下钻**：team_name → asin
- **指标**：original_price, orders, order_qty
- **衍生指标**：客单价, 环比增长率
- **图表**：透视表 + 折线图

### 2. 利润结构成本拆解透视
- **目的**：拆解成本结构，识别利润压缩点
- **数据集**：order_sale_trend_adv_traffic_inv_set
- **行维度**：dept_name, team_name, category
- **列维度**：date_id（月）, platform_name
- **下钻**：asin, ed_sku
- **指标**：gross_profit, purchase_cost, advertising_fee, fee, tax_fee, fixed_cost
- **衍生指标**：各项成本占比
- **图表**：透视表 + 堆叠柱状图

### 4. 广告效率多维透视
- **目的**：评估 ACOS、ROAS、CPC 等核心广告指标
- **数据集**：advertising_list_set + custom_type_advertising_list
- **行维度**：date_id, campaign_name, ad_group_name
- **列维度**：ads_type, platform_name, country_name
- **下钻**：asin, sell_sku
- **指标**：ads_acos, ads_sales_cny, ads_clicks, ads_impressions
- **衍生指标**：ROAS, CPC, 点击率
- **图表**：透视表 + 组合图

## P1 级（第二周配置）

### 3. 退款与售后质量透视
- **数据集**：order_sale_trend_* + custom_refund_place_set
- **图表**：透视表 + 热力图

### 6. 流量与转化漏斗透视
- **数据集**：custom_asin_sales_traffic_set + order_sale_trend_*
- **图表**：透视表 + 漏斗图

### 8. 库存周转健康度透视
- **数据集**：custom_inventory_turnover_wk_set
- **图表**：透视表 + 预警热力图

## P2/P3 级（后续配置）

[略，详见原文档]
```

### 5.2 dataset_fields_index.md

```markdown
# 数据集字段索引

## 公共维度池

| 维度 | 字段名 | 适用数据集 | 数据类型 |
|------|--------|-----------|---------|
| 时间 | date_id | 全部 | DATETIME |
| 部门 | dept_name | 全部 | STRING |
| 大组 | large_team_name | 全部 | STRING |
| 销售小组 | team_name | 全部 | STRING |
| 开发小组 | dev_team_name | 全部 | STRING |
| ASIN | asin | 全部 | STRING |
| 父ASIN | parent_asin | 全部 | STRING |
| 公司SKU | ed_sku | 全部 | STRING |
| 产品名称 | product_name | 全部 | STRING |
| 品牌 | brand_name | 全部 | STRING |
| 品类 | category | 全部 | STRING |
| 平台 | platform_name | 全部 | STRING |
| 国家 | country_name | 全部 | STRING |

## 核心指标池

[详见原文档指标速查表]
```

---

## 六、开发步骤

### Step 1：需求分析与模板设计（Day 1-2）

- [ ] 整理 12 个标准透视图的完整配置
- [ ] 设计配置 JSON Schema
- [ ] 编写决策树逻辑

### Step 2：核心脚本开发（Day 3-5）

- [ ] 实现 `build_perspective_config.py`
- [ ] 实现 `validate_config.py`
- [ ] 实现 `suggest_dimensions.py`
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 5-6）

- [ ] 编写 12 个透视图详细目录
- [ ] 编写数据集字段索引
- [ ] 编写图表类型选择指南

### Step 4：集成测试（Day 7-10）

- [ ] 测试用例 1：标准透视图配置生成
- [ ] 测试用例 2：自定义透视图设计
- [ ] 测试用例 3：跨数据集配置验证
- [ ] 测试用例 4：错误输入处理
- [ ] 测试用例 5：12 个标准模板全部验证

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 配置完整性 | 输出包含维度、指标、图表、过滤全部要素 |
| 字段准确性 | 推荐的字段存在于目标数据集 |
| 跨集验证 | 跨数据集分析时 join key 正确 |
| 可用性 | 配置可直接用于 BI 工具导入 |
| 覆盖度 | 支持 12 个标准透视图 + 自定义设计 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 组件调用 | 透视图 12 调用健康度评分 |
| `profit-structure-analyzer` | 组件调用 | 透视图 2 调用成本分析 |
| `advertising-efficiency-optimizer` | 组件调用 | 透视图 4/5 调用广告分析 |
| `inventory-health-monitor` | 组件调用 | 透视图 8/9 调用库存分析 |
| `product-attribute-analyzer` | 组件调用 | 透视图增加属性维度分析 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
