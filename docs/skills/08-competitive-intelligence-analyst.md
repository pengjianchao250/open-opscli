# Skill 开发设计文档：competitive-intelligence-analyst

> **Skill 名称**：`competitive-intelligence-analyst`
> **复杂度等级**：Level 3 — 复杂（多框架分析 + 外部数据融合）
> **预计开发时间**：7-10 天
> **业务价值**：高（战略级决策支持）

---

## 一、Skill 定位

### 1.1 一句话描述

融合内部品类销售集中度、爬虫竞品数据、品牌搜索分析，应用波特五力 + 定位图 + 四行动框架，输出品类级竞争情报看板与策略建议。

### 1.2 解决什么痛点

- 不知道自己在品类中的真实位置
- 竞争分析靠感觉，缺乏系统性框架
- 内部数据与外部市场数据割裂，无法融合分析

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 品类评估 | "分析 Water Bottle 品类的竞争格局" |
| 进入决策 | "我想进入 Kitchen Gadgets 品类，竞争情况如何？" |
| 定位分析 | "我们品牌在品类中处于什么定位？" |
| 策略制定 | "基于竞争格局，给我们品类制定差异化策略" |

---

## 二、文件结构设计

```
opscli/skills/competitive-intelligence-analyst/
├── SKILL.md                              # 核心指令文件（多框架融合）
├── scripts/
│   ├── porter_five_forces_scorer.py      # 波特五力评分卡
│   ├── positioning_map_generator.py      # 定位图生成器
│   ├── four_actions_analyzer.py          # 四行动框架分析
│   └── competitor_profiler.py            # 竞品画像生成
└── reference/
    ├── porter_template.md                # 波特五力评分模板
    ├── positioning_examples.md           # 定位图示例
    └── category_benchmarks.md            # 品类基准数据
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: competitive-intelligence-analyst
description: Fuses internal sales concentration data with competitor crawling data and brand search analytics. Applies Porter's Five Forces, Positioning Map, and Four Actions Framework to generate category-level competitive intelligence dashboards and strategic recommendations. Use when evaluating market entry, analyzing competitive positioning, or formulating differentiation strategies.
---
```

### 3.2 主体内容大纲

```markdown
# Competitive Intelligence Analyst

Analyzes competitive landscape using multi-framework analysis with internal and external data fusion.

## Capabilities

- Porter's Five Forces scoring
- Positioning map generation
- Four Actions Framework strategy
- Competitor profiling
- Category concentration analysis
- Market entry/exit recommendations

## Analysis Framework Stack

### Layer 1: Porter's Five Forces

| Force | Internal Data | External Data | Score (1-5) |
|-------|--------------|---------------|:-----------:|
| Threat of New Entrants | Category sales growth | New brand count from crawler | 1-5 |
| Bargaining Power of Suppliers | SKU concentration | Supplier diversity | 1-5 |
| Bargaining Power of Buyers | Review sensitivity | Price elasticity | 1-5 |
| Threat of Substitutes | Cross-category sales | Substitute product trends | 1-5 |
| Competitive Rivalry | Sales concentration (HHI) | Competitor count/rating | 1-5 |

**Scoring Logic:**
```python
def calculate_hhi(market_shares):
    """赫芬达尔-赫希曼指数"""
    return sum(share**2 for share in market_shares) * 10000

# HHI < 1500: 低集中度 (Score: 1-2)
# HHI 1500-2500: 中等集中度 (Score: 3)
# HHI > 2500: 高集中度 (Score: 4-5)
```

### Layer 2: Positioning Map

**Dimensions:**
- X-axis: Average Price (`custom_crawler_listing_snapshot.price`)
- Y-axis: Average Rating (`custom_crawler_listing_snapshot.rating`)
- Bubble Size: Sales Volume (`order_sale_trend_set.order_qty`)
- Bubble Color: Gross Margin (`order_sale_trend_adv_traffic_inv_set.gross_profit_percent`)

**Data Sources:**
- Internal: `order_sale_trend_*`
- External: `custom_crawler_listing_snapshot`

### Layer 3: Four Actions Framework

After positioning analysis, apply:
- **Eliminate**: Remove features that industry takes for granted but customers don't value
- **Reduce**: Reduce factors well below industry standard
- **Raise**: Raise factors well above industry standard
- **Create**: Create factors the industry has never offered

## Data Sources

### Internal
- `custom_brand_search_catalog_set`: Category performance
- `custom_brand_search_query_set`: Search term performance
- `order_sale_trend_adv_traffic_inv_set`: Sales concentration

### External
- `custom_crawler_listing_snapshot`: Competitor price/rating/rank
- `custom_crawler_listing_trend_set`: Competitor trend

## Input Format

- Category: "category = 'Water Bottles'"
- Country: "country_name = 'US'"
- Time: "last 90 days"
- Competitors: "top 10 sellers" or specific ASINs

## Output Format

```
【品类】Water Bottles（US 站）
【分析周期】2024-11-01 ~ 2025-01-31

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 1: Porter's Five Forces
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────┬───────┬─────────────────────────────┐
│ Force                       │ Score │ Evidence                    │
├─────────────────────────────┼───────┼─────────────────────────────┤
│ Threat of New Entrants      │ 3/5   │ 品类年增 25%，但 Top3 占 60% │
│ Bargaining Power (Suppliers)│ 2/5   │ 供应商集中度高，但可替代    │
│ Bargaining Power (Buyers)   │ 4/5   │ 价格敏感，review 影响大     │
│ Threat of Substitutes       │ 2/5   │ 替代品少（保温杯/塑料杯）   │
│ Competitive Rivalry         │ 4/5   │ HHI = 2850，高度集中        │
├─────────────────────────────┼───────┼─────────────────────────────┤
│ 综合吸引力评分              │ 15/25 │ 中等吸引力，竞争激烈        │
└─────────────────────────────┴───────┴─────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 2: Positioning Map
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

High Price
    |
    |     ★ Premium Brand A      ★ Premium Brand B
    |          (4.8★, $89)            (4.7★, $79)
    |
    |                 ● Our Position
    |               (4.5★, $45)
    |
    |    ★ Mid Brand C          ★ Mid Brand D
    |     (4.3★, $39)            (4.2★, $35)
    |
    |  ★ Value Brand E    ★ Value Brand F
    |   (4.0★, $19)        (3.9★, $15)
    |
Low Price |____________________________________________
          Low Rating                          High Rating

气泡大小 = 月销量 | 颜色 = 毛利率（绿=高，红=低）

→ 定位结论：我们处于中段价格带，上方有高端空间，下方有性价比红海。
  建议：通过差异化（智能保温显示）向 $55-65 迁移。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 3: Four Actions Strategy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【Eliminate】
  • 淘汰基础款无特色颜色（占 SKU 30%，贡献仅 8% 销售额）
  • 移除过度包装（降低 3% 成本）

【Reduce】
  • 降低对 "water bottle" 大词的广告依赖（从 60% 降至 40%）
  • 减少 SKU 数量，聚焦核心变体

【Raise】
  • 提升保温时长至 24h（行业均值 12h）
  • 提升品牌搜索占比从 12% 到 25%
  • 提升售价至 $55（当前 $45，有空间）

【Create】
  • 增加温度显示 LED 屏（行业首创）
  • 开发 App 连接功能（饮水提醒）
  • 推出定制化刻字服务

【预期效果】
  → 毛利率从 18% 提升至 28%
  → 品牌搜索占比提升至 25%
  → 避开价格战，建立差异化壁垒
```

## Scripts

- `porter_five_forces_scorer.py`: Calculates Porter's Five Forces scores
- `positioning_map_generator.py`: Generates positioning map data
- `four_actions_analyzer.py`: Analyzes and recommends Four Actions
- `competitor_profiler.py`: Builds competitor profiles

## Best Practices

1. Always use HHI for concentration measurement
2. Positioning map should include at least 5 competitors + self
3. Four Actions must be based on actual cost structure data
4. Consider seasonality when analyzing competitor trends
```

---

## 四、脚本设计

### 4.1 porter_five_forces_scorer.py

**功能**：计算波特五力评分

**输入**：品类销售数据、竞品数据

**输出**：五力评分卡

**核心逻辑**：
```python
def calculate_porter_scores(category_data, competitor_data):
    scores = {}
    
    # 1. Threat of New Entrants
    hhi = calculate_hhi(category_data['market_shares'])
    growth_rate = category_data['growth_rate']
    scores['new_entrants'] = min(5, max(1, int(3 + (hhi/2500) - growth_rate)))
    
    # 2. Supplier Power
    supplier_concentration = category_data['supplier_hhi']
    scores['supplier_power'] = min(5, max(1, int(supplier_concentration / 500)))
    
    # 3. Buyer Power
    price_sensitivity = competitor_data['price_elasticity']
    review_impact = competitor_data['review_impact']
    scores['buyer_power'] = min(5, max(1, int((price_sensitivity + review_impact) / 2)))
    
    # 4. Substitutes
    substitute_availability = category_data['substitute_count']
    scores['substitutes'] = min(5, max(1, int(substitute_availability / 3)))
    
    # 5. Rivalry
    scores['rivalry'] = min(5, max(1, int(hhi / 600)))
    
    return scores
```

### 4.2 positioning_map_generator.py

**功能**：生成定位图数据

**输出**：JSON 格式，可被前端图表库直接使用

### 4.3 four_actions_analyzer.py

**功能**：基于成本结构和定位分析，生成四行动策略

### 4.4 competitor_profiler.py

**功能**：构建竞品画像

**竞品画像模板**：
```json
{
  "competitor": {
    "name": "Brand A",
    "positioning": "Premium",
    "price_range": "$70-90",
    "rating": 4.8,
    "review_count": 15000,
    "top_products": ["ASIN1", "ASIN2"],
    "strengths": ["Brand recognition", "Quality"],
    "weaknesses": ["High price", "Limited colors"],
    "strategy": "Premium differentiation"
  }
}
```

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
- **内部数据集**：`order_sale_trend_adv_traffic_inv_set`（`ds_d35ac6f3910c`，非子查询类型）
- **品牌搜索**：`custom_brand_search_catalog_set`（`ds_I13gHlcdwevS`，非子查询类型）、`custom_brand_search_query_set`（`ds_xsTOkHIpr3ad`，非子查询类型）
- **爬虫数据**：`custom_crawler_listing_snapshot`（`ds_pdTYjvLRCadv`，非子查询类型）

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension category --dimension asin \
  --metric original_price --metric order_qty --metric gross_profit_percent \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

品类销售集中度查询（`ds_d35ac6f3910c`）：

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
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_qty", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_margin", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "Water Bottles" },
        { "field": "ds_d35ac6f3910c.country_name", "operator": "eq", "value": "US" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_category", "f_asin"],
    "limit": 10000
  }
}
```

竞品 Listing 查询（`ds_pdTYjvLRCadv`）：

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
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" },
      { "expr": "ds_pdTYjvLRCadv.category", "alias": "f_category" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.category", "operator": "eq", "value": "Water Bottles" },
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["2024-12-01", "2025-01-31"] }
      ]
    },
    "limit": 10000
  }
}
```

品牌搜索查询（`ds_xsTOkHIpr3ad`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_brand.search_query_set ...)",
      "alias": "ds_xsTOkHIpr3ad",
      "database": "",
      "permission": ["channel_uuid"]
    },
    "select": [
      { "expr": "ds_xsTOkHIpr3ad.search_term", "alias": "f_term" },
      { "expr": "ds_xsTOkHIpr3ad.search_volume", "alias": "f_volume", "aggregation": "SUM" },
      { "expr": "ds_xsTOkHIpr3ad.brand_share", "alias": "f_brand_share", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_xsTOkHIpr3ad.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_term"],
    "limit": 1000
  }
}
```

#### 数据集类型判断

本 Skill 涉及的所有数据集（`ds_d35ac6f3910c`、`ds_pdTYjvLRCadv`、`ds_xsTOkHIpr3ad`、`ds_I13gHlcdwevS`）均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

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

### 5.1 porter_template.md

```markdown
# 波特五力评分模板

## 评分标准（1-5 分）

### 1. Threat of New Entrants

| 条件 | 分数 |
|------|------|
| HHI < 1500，增长 > 30% | 5 |
| HHI 1500-2500，增长 15-30% | 3-4 |
| HHI > 2500，增长 < 15% | 1-2 |

### 2. Bargaining Power of Suppliers

| 条件 | 分数 |
|------|------|
| 供应商集中度高，替代少 | 4-5 |
| 供应商分散，替代多 | 1-2 |

### 3. Bargaining Power of Buyers

| 条件 | 分数 |
|------|------|
| 价格极敏感，review 影响大 | 4-5 |
| 品牌忠诚度高 | 1-2 |

### 4. Threat of Substitutes

| 条件 | 分数 |
|------|------|
| 替代品多且易得 | 4-5 |
| 功能独特，替代少 | 1-2 |

### 5. Competitive Rivalry

| 条件 | 分数 |
|------|------|
| HHI > 3000 | 5 |
| HHI 2000-3000 | 3-4 |
| HHI < 2000 | 1-2 |
```

### 5.2 positioning_examples.md

```markdown
# 定位图示例

## 示例 1：Water Bottle 品类

```
High Price
    |
    |     ★ Hydro Flask ($89, 4.8★)
    |     ★ Yeti ($79, 4.7★)
    |
    |          ● Our Target ($65, 4.6★)
    |
    |     ● Our Current ($45, 4.5★)
    |
    |    ★ Contigo ($35, 4.3★)
    |    ★ Simple Modern ($29, 4.2★)
    |
    |  ★ Amazon Basics ($15, 4.0★)
    |
Low Price +_________________________________________ High Rating
```

## 示例 2：Dog Beds 品类

[略]
```

---

## 六、开发步骤

### Step 1：框架设计（Day 1-2）

- [ ] 设计波特五力评分逻辑
- [ ] 设计定位图数据结构
- [ ] 设计四行动策略生成规则

### Step 2：脚本开发（Day 3-6）

- [ ] 实现 `porter_five_forces_scorer.py`
- [ ] 实现 `positioning_map_generator.py`
- [ ] 实现 `four_actions_analyzer.py`
- [ ] 实现 `competitor_profiler.py`
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 6-7）

- [ ] 编写波特五力评分模板
- [ ] 编写定位图示例
- [ ] 编写品类基准数据

### Step 4：集成测试（Day 8-10）

- [ ] 测试用例 1：完整品类竞争分析
- [ ] 测试用例 2：定位图生成
- [ ] 测试用例 3：四行动策略生成
- [ ] 测试用例 4：竞品画像构建
- [ ] 测试用例 5：多品类对比分析

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 五力评分 | 与人工专家评分偏差 < 1 分 |
| 定位图 | 包含至少 5 个竞品 + 自身，坐标准确 |
| 策略相关性 | 四行动策略与定位分析强相关 |
| 数据融合 | 内部数据与爬虫数据能正确关联 |
| 输出完整性 | 包含五力、定位、策略三层分析 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `product-attribute-analyzer` | 上游调用 | 分析属性格局后再分析竞争格局 |
| `profit-structure-analyzer` | 上游调用 | 成本结构是四行动策略的输入 |
| `cross-border-product-selector` | 下游调用 | 竞争格局是选品决策的输入 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
