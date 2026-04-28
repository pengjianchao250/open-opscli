# Skill 开发设计文档：cross-border-product-selector

> **Skill 名称**：`cross-border-product-selector`
> **复杂度等级**：Level 3 — 复杂（多步骤工作流 + 内外数据融合）
> **预计开发时间**：7-10 天
> **业务价值**：高（新品开发决策支持）

---

## 一、Skill 定位

### 1.1 一句话描述

整合内部销售数据、爬虫 Listing 数据、库存周转数据，应用 BSR 健康度筛选 + 四象限分类 + 众筹信号挖掘，构建数据驱动的新品开发决策系统。

### 1.2 解决什么痛点

- 选品靠经验和感觉，缺乏数据支撑
- 内部已有大量数据，但未用于指导新品开发
- 不知道哪些品类已经饱和，哪些还有机会

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 品类探索 | "帮我找找 Kitchen 品类中还有哪些机会" |
| 新品评估 | "评估 ASIN B08XXXXXX 这个竞品，是否值得跟卖/改进？" |
| 选品决策 | "基于我们现有能力，推荐 5 个新品机会" |
| 供应商匹配 | "这个新品方向，找什么供应商合适？" |

---

## 二、文件结构设计

```
opscli/skills/cross-border-product-selector/
├── SKILL.md                              # 核心指令文件（4步工作流）
├── scripts/
│   ├── bsr_filter.py                     # BSR 健康度筛选
│   ├── quadrant_classifier.py            # 四象限分类器
│   ├── opportunity_scorer.py             # 机会评分引擎
│   └── supplier_matcher.py               # 供应商匹配（可选）
└── reference/
    ├── bsr_filtering_rules.md            # BSR 筛选规则
    ├── quadrant_matrix_guide.md          # 四象限分类指南
    └── crowdfunding_signals.md           # 众筹信号参考
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: cross-border-product-selector
description: Integrates internal sales data, crawler listing data, and inventory turnover metrics. Applies BSR health filtering, four-quadrant classification, and crowdfunding signal mining to build a data-driven new product development decision system. Use when exploring new product opportunities, evaluating competitor ASINs for follow-selling, or making go/no-go decisions on new product development.
---
```

### 3.2 主体内容大纲

```markdown
# Cross-Border Product Selector

Data-driven product selection system combining internal and external data sources.

## Capabilities

- BSR health filtering for opportunity identification
- Four-quadrant product classification
- Internal capability gap analysis
- Competitor ASIN evaluation
- Crowdfunding signal monitoring
- Supplier matching (optional)

## 4-Step Selection Workflow

### Step 1: Category Scan（品类扫描）

**Internal Data**（`order_sale_trend_adv_traffic_inv_set` / `ds_d35ac6f3910c`）：

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
      { "expr": "ds_d35ac6f3910c.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_total_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_avg_margin", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_avg_refund", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_category"],
    "orderBy": [{ "field": "f_total_sales", "direction": "DESC" }],
    "limit": 100
  }
}
```

**External Data**（`custom_crawler_listing_snapshot` / `ds_pdTYjvLRCadv`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_crawler.listing_snapshot ...)",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": ["asin_ps_uuid"]
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_pdTYjvLRCadv.asin)", "alias": "f_competitor_count" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_avg_rating", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_avg_reviews", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["2024-12-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_category"],
    "limit": 100
  }
}
```

### Step 2: BSR Health Filter（BSR 健康度筛选）

**Filtering Rules:**

| Criteria | Threshold | Rationale |
|----------|-----------|-----------|
| BSR Rank | 100-5,000 | Proven demand but not monopolized |
| Review Count | 300-1,000 | Validated but improvable |
| Rating | 3.5-4.3 | Room for quality improvement |
| Price | $15-50 | Good margin potential |

使用 `custom_crawler_listing_snapshot`（`ds_pdTYjvLRCadv`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_crawler.listing_snapshot ...)",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": ["asin_ps_uuid"]
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.asin", "alias": "f_asin" },
      { "expr": "ds_pdTYjvLRCadv.product_name", "alias": "f_product_name" },
      { "expr": "ds_pdTYjvLRCadv.price", "alias": "f_price" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.subclass_rank", "operator": "between", "value": [100, 5000] },
        { "field": "ds_pdTYjvLRCadv.reviews_qty", "operator": "between", "value": [300, 1000] },
        { "field": "ds_pdTYjvLRCadv.star", "operator": "between", "value": [3.5, 4.3] },
        { "field": "ds_pdTYjvLRCadv.price", "operator": "between", "value": [15, 50] }
      ]
    },
    "limit": 1000
  }
}
```

### Step 3: Four-Quadrant Classification（四象限分类）

**Axes:**
- X-axis: Sales Volume (internal `original_price`)
- Y-axis: Refund/Complaint Rate (internal `refund_percent` + external review sentiment)

**Quadrants:**

```
High Refund
    |
    |  🔴 Red Ocean      │  🟡 High-Potential
    |  (High sales,      │  (High buzz,
    |   high complaints) │   low supply)
    |                    │
    |────────────────────┼────────────────────
    |                    │
    |  ⚫ False Trends   │  🟢 Safe Bets
    |  (Short-term       │  (High sales,
    |   spikes)          │   low complaints)
    |
Low Refund +─────────────────────────────────── High Sales
```

| Quadrant | Internal Signal | External Signal | Strategy |
|----------|----------------|-----------------|----------|
| 🟢 Safe Bets | High sales, low refund | High rating, steady BSR | Follow-sell with minor improvement |
| 🟡 High-Potential | Low sales or no presence | High search trend, few sellers | First-mover opportunity |
| 🔴 Red Ocean | High sales, high refund | Many competitors, price war | Avoid or differentiate heavily |
| ⚫ False Trends | Spike then drop | Short-lived buzz | Ignore |

### Step 4: Opportunity Scoring（机会评分）

**Scoring Formula:**
```python
opportunity_score = (
    w1 * market_size_score +      # 市场规模 (BSR rank inverse)
    w2 * margin_potential_score +  # 毛利潜力 (price - estimated cost)
    w3 * competition_gap_score +   # 竞争缺口 (reviews gap)
    w4 * internal_capability_score # 内部能力匹配度
)
```

## Input Format

- Category: "Kitchen Gadgets"
- BSR range: "100-5000"
- Price range: "$15-50"
- Review range: "300-1000"
- Internal filter: "exclude categories where we have > 50 ASINs"

## Output Format

```
【品类】Kitchen Gadgets
【筛选条件】BSR 100-5000 | Price $15-50 | Reviews 300-1000
【候选 ASIN 数量】23

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Top 5 机会排名
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#1 🥇 ASIN B08XXXXXX（电动蒜泥器）
   ├─ BSR: 1,250 | Price: $29.99 | Rating: 3.9★ (847 reviews)
   ├─ 四象限：🟡 High-Potential
   ├─ 机会评分：87/100
   ├─ 市场规模：$2.3M/月（BSR 推算）
   ├─ 竞争缺口：Top 10 卖家平均 rating 3.8，我们可达 4.5+
   ├─ 内部能力：✅ 已有电机供应链（搅拌机产品线）
   ├─ 预估毛利率：35%（采购 $8，售价 $29.99）
   └─ 建议：【GO】立即开发，预计 3 个月上市

#2 🥈 ASIN B09YYYYYY（折叠沥水架）
   ├─ BSR: 2,800 | Price: $19.99 | Rating: 4.1★ (562 reviews)
   ├─ 四象限：🟢 Safe Bet
   ├─ 机会评分：82/100
   ├─ 市场规模：$1.8M/月
   ├─ 竞争缺口：评论数少，易超越
   ├─ 内部能力：✅ 已有不锈钢供应商
   ├─ 预估毛利率：28%
   └─ 建议：【GO】跟卖+微创新（增加收纳功能）

#3 🥉 ASIN B07ZZZZZZ（硅胶烘焙垫）
   ├─ BSR: 4,200 | Price: $15.99 | Rating: 3.7★ (1,200 reviews)
   ├─ 四象限：🟡 High-Potential
   ├─ 机会评分：78/100
   ├─ 问题：差评集中在 "有异味" 和 "尺寸不准"
   ├─ 我们的优势：可用食品级硅胶+精准尺寸
   └─ 建议：【GO】差异化开发，解决痛点

[... 更多结果 ...]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
风险提醒
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ ASIN B08AAAAAA 被标记为 🔴 Red Ocean：
   ├─ BSR: 850 | Price: $12.99（低价红海）
   ├─ 已有 200+ 卖家，价格战激烈
   ├─ 平均毛利率仅 8%
   └─ 建议：【NO-GO】避免进入
```

## Scripts

- `bsr_filter.py`: Applies BSR health filtering rules
- `quadrant_classifier.py`: Classifies products into four quadrants
- `opportunity_scorer.py`: Calculates opportunity scores
- `supplier_matcher.py`: Matches products to potential suppliers

## Best Practices

1. Always cross-validate BSR with actual sales data when available
2. Consider seasonality — BSR can be misleading for seasonal products
3. Internal capability match is critical — don't recommend products outside our supply chain capability
4. Flag products with patent/IP risks
```

---

## 四、脚本设计

### 4.1 bsr_filter.py

**功能**：应用 BSR 健康度筛选规则

**输入**：爬虫 Listing 数据

**输出**：符合条件的候选 ASIN 列表

**核心逻辑**：
```python
BSR_RULES = {
    'subclass_rank': {'min': 100, 'max': 5000},
    'reviews_qty': {'min': 300, 'max': 1000},
    'rating': {'min': 3.5, 'max': 4.3},
    'price': {'min': 15, 'max': 50}
}

def apply_bsr_filter(listings, rules=BSR_RULES):
    filtered = []
    for item in listings:
        if all(rules[key]['min'] <= item[key] <= rules[key]['max'] 
               for key in rules):
            filtered.append(item)
    return filtered
```

### 4.2 quadrant_classifier.py

**功能**：四象限分类

**输入**：内部销售数据 + 外部爬虫数据

**输出**：每个 ASIN 的四象限分类

**核心逻辑**：
```python
def classify_quadrant(sales_volume, refund_rate, sentiment_score):
    """
    sales_volume: high/low (vs category median)
    refund_rate: high/low (vs category median)
    """
    if sales_volume == 'high' and refund_rate == 'low':
        return 'safe_bet'
    elif sales_volume == 'low' and refund_rate == 'low':
        return 'high_potential'
    elif sales_volume == 'high' and refund_rate == 'high':
        return 'red_ocean'
    else:
        return 'false_trend'
```

### 4.3 opportunity_scorer.py

**功能**：计算机会评分

**评分维度**：
```python
def calculate_opportunity_score(asin_data, internal_capability):
    scores = {
        'market_size': score_market_size(asin_data['bsr_rank']),
        'margin_potential': score_margin(asin_data['price'], asin_data['estimated_cost']),
        'competition_gap': score_competition_gap(asin_data['reviews_qty'], asin_data['rating']),
        'capability_match': score_capability(internal_capability, asin_data['category']),
        'pain_point_severity': score_pain_points(asin_data['negative_reviews'])
    }
    
    weights = {
        'market_size': 0.25,
        'margin_potential': 0.30,
        'competition_gap': 0.20,
        'capability_match': 0.15,
        'pain_point_severity': 0.10
    }
    
    return sum(scores[k] * weights[k] for k in scores)
```

**输入格式**：
```json
{
  "asin_data": {
    "asin": "B08XXXXXX",
    "product_name": "Electric Garlic Press",
    "bsr_rank": 1250,
    "price": 29.99,
    "rating": 3.9,
    "reviews_qty": 847,
    "category": "Kitchen Gadgets"
  },
  "internal_capability": {
    "has_motor_supply_chain": true,
    "existing_categories": ["Kitchen", "Home"]
  },
  "query_payload": {
    "dataset": "ds_pdTYjvLRCadv",
    "dimensions": ["asin", "product_name", "category"],
    "metrics": ["price", "star", "reviews_qty", "subclass_rank"],
    "filters": {
      "subclass_rank": [100, 5000],
      "reviews_qty": [300, 1000],
      "star": [3.5, 4.3],
      "price": [15, 50]
    }
  },
  "query_result": {
    "dataset": "ds_pdTYjvLRCadv",
    "rows": [...],
    "execution_time_ms": 1200
  }
}
```

### 4.4 supplier_matcher.py（可选）

**功能**：匹配潜在供应商

**输入**：产品属性 + 供应商数据库

**输出**：推荐供应商列表

### 4.5 数据查询接口规范

#### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

#### 查询构造方式

本 Skill 使用多个数据集：
- **内部销售**：`order_sale_trend_adv_traffic_inv_set`（`ds_d35ac6f3910c`，非子查询类型）
- **爬虫 Listing**：`custom_crawler_listing_snapshot`（`ds_pdTYjvLRCadv`，非子查询类型）
- **库存周转**：`custom_inventory_turnover_wk_set`（`ds_97zj6R0KDKpB`，非子查询类型）

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_pdTYjvLRCadv \
  --dimension asin --dimension product_name \
  --metric price --metric star --metric reviews_qty --metric subclass_rank \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

品类扫描 - 内部数据（`ds_d35ac6f3910c`）：

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
      { "expr": "ds_d35ac6f3910c.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_total_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_avg_margin", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_avg_refund", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_category"],
    "orderBy": [{ "field": "f_total_sales", "direction": "DESC" }],
    "limit": 100
  }
}
```

品类扫描 - 爬虫数据（`ds_pdTYjvLRCadv`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_crawler.listing_snapshot ...)",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": ["asin_ps_uuid"]
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_pdTYjvLRCadv.asin)", "alias": "f_competitor_count" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_avg_rating", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_avg_reviews", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["2024-12-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_category"],
    "limit": 100
  }
}
```

BSR 健康度筛选（`ds_pdTYjvLRCadv`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_crawler.listing_snapshot ...)",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": ["asin_ps_uuid"]
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.asin", "alias": "f_asin" },
      { "expr": "ds_pdTYjvLRCadv.product_name", "alias": "f_product_name" },
      { "expr": "ds_pdTYjvLRCadv.price", "alias": "f_price" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.subclass_rank", "operator": "between", "value": [100, 5000] },
        { "field": "ds_pdTYjvLRCadv.reviews_qty", "operator": "between", "value": [300, 1000] },
        { "field": "ds_pdTYjvLRCadv.star", "operator": "between", "value": [3.5, 4.3] },
        { "field": "ds_pdTYjvLRCadv.price", "operator": "between", "value": [15, 50] }
      ]
    },
    "limit": 1000
  }
}
```

#### 数据集类型判断

本 Skill 涉及的所有数据集（`ds_d35ac6f3910c`、`ds_pdTYjvLRCadv`、`ds_97zj6R0KDKpB`）均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

#### 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

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
  "expr": "gross_profit_percent",
  "alias": "f_xxx",
  "aggregation": "AVG"
}
```

---

## 五、Reference 文档设计

### 5.1 bsr_filtering_rules.md

```markdown
# BSR 健康度筛选规则

## 标准筛选（通用）

| 指标 | 最小值 | 最大值 | 说明 |
|------|--------|--------|------|
| subclass_rank | 100 | 5,000 | 已验证需求但非垄断 |
| reviews_qty | 300 | 1,000 | 已验证但有改进空间 |
| rating | 3.5 | 4.3 | 有质量提升空间 |
| price | $15 | $50 | 毛利空间充足 |

## 宽松筛选（新品探索）

| 指标 | 最小值 | 最大值 | 说明 |
|------|--------|--------|------|
| subclass_rank | 50 | 10,000 | 更广范围 |
| reviews_qty | 100 | 2,000 | 包含较新品 |
| rating | 3.0 | 4.5 | 包含改进空间大 |
| price | $10 | $80 | 更广价格带 |

## 严格筛选（保守跟卖）

| 指标 | 最小值 | 最大值 | 说明 |
|------|--------|--------|------|
| subclass_rank | 500 | 3,000 | 低风险区间 |
| reviews_qty | 500 | 800 | 已充分验证 |
| rating | 3.8 | 4.2 | 明确改进点 |
| price | $20 | $40 | 稳定价格带 |
```

### 5.2 quadrant_matrix_guide.md

```markdown
# 四象限分类指南

## 分类标准

### X-axis: 销售额（内部数据）

以品类中位数为界：
- High: > 品类销售额中位数
- Low: ≤ 品类销售额中位数

### Y-axis: 问题率（综合指标）

问题率 = (退款率 × 0.6) + (差评占比 × 0.4)

以品类中位数为界：
- High: > 品类问题率中位数
- Low: ≤ 品类问题率中位数

## 各象限策略

### 🟢 Safe Bets（高销售，低问题）
- **特征**：市场已验证，产品成熟
- **策略**：跟卖+微创新，优化成本
- **风险**：低

### 🟡 High-Potential（低销售，低问题）
- **特征**：新兴需求，供给不足
- **策略**：快速进入，抢占先机
- **风险**：中

### 🔴 Red Ocean（高销售，高问题）
- **特征**：市场大但竞争激烈/问题多
- **策略**：避免或大幅差异化
- **风险**：高

### ⚫ False Trends（低销售，高问题）
- **特征**：短期热点，不可持续
- **策略**：忽略
- **风险**：极高
```

---

## 六、开发步骤

### Step 1：工作流设计（Day 1-2）

- [ ] 设计 4 步选品工作流
- [ ] 设计 BSR 筛选规则
- [ ] 设计四象限分类逻辑
- [ ] 设计机会评分公式

### Step 2：脚本开发（Day 3-6）

- [ ] 实现 `bsr_filter.py`
- [ ] 实现 `quadrant_classifier.py`
- [ ] 实现 `opportunity_scorer.py`
- [ ] 实现 `supplier_matcher.py`（可选）
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 6-7）

- [ ] 编写 BSR 筛选规则详解
- [ ] 编写四象限分类指南
- [ ] 编写众筹信号参考

### Step 4：集成测试（Day 8-10）

- [ ] 测试用例 1：完整选品流程
- [ ] 测试用例 2：BSR 筛选准确性
- [ ] 测试用例 3：四象限分类验证
- [ ] 测试用例 4：机会评分排序
- [ ] 测试用例 5：多品类对比分析

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 筛选准确性 | BSR 100-5000 区间命中率 > 80% |
| 分类准确性 | 四象限分类与人工判断一致率 > 85% |
| 评分排序 | Top 5 机会中至少 3 个被业务认可 |
| 数据融合 | 内部数据与爬虫数据正确关联 |
| 输出完整性 | 包含评分、象限、建议、风险提醒 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `product-attribute-analyzer` | 上游调用 | 分析属性市场格局 |
| `competitive-intelligence-analyst` | 上游调用 | 分析竞争格局 |
| `asin-health-diagnoser` | 下游调用 | 评估选定 ASIN 的健康度 |
| `inventory-health-monitor` | 下游调用 | 评估供应链能力匹配 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
