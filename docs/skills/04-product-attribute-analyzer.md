# Skill 开发设计文档：product-attribute-analyzer

> **Skill 名称**：`product-attribute-analyzer`
> **复杂度等级**：Level 2 — 中等（需要脚本辅助计算）
> **预计开发时间**：4-5 天
> **业务价值**：高（指导产品开发方向）

---

## 一、Skill 定位

### 1.1 一句话描述

应用 3-D 产品属性标签体系（Structural/Fit + Material/Process + Design Elements），基于销售加权份额计算各属性组合的市场份额，识别供给不足的高价值属性机会。

### 1.2 解决什么痛点

- 产品开发凭感觉，不知道市场真正偏好什么属性组合
- 按 ASIN 数量算市场份额导致误判（热销款可能被埋没）
- 属性命名不统一，跨团队沟通成本高

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 属性洞察 | "分析 Kitchen 品类中各开发类型的销售加权份额" |
| 机会发现 | "找出销量高但供给少的属性组合" |
| 产品规划 | "我们品类中最受欢迎的 SKU 等级是什么？" |
| 竞争分析 | "对比自主研发和 OEM 产品的单均销量差异" |

---

## 二、文件结构设计

```
opscli/skills/product-attribute-analyzer/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   ├── calculate_weighted_share.py       # 销售加权份额计算
│   ├── analyze_attribute_combo.py        # 属性组合分析
│   └── generate_market_portrait.py       # Market Portrait 生成
└── reference/
    ├── 3d_tag_dictionary.md              # 3-D 标签字典规范
    ├── attribute_mapping_table.md        # 属性→字段映射表
    └── market_portrait_template.md       # Market Portrait 输出模板
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: product-attribute-analyzer
description: Applies 3-Dimensional Product Attribute Tagging (Structural/Fit, Material/Process, Design Elements) to calculate sales-weighted market share for each attribute combination. Identifies under-supplied high-value attribute opportunities. Use when planning product development, analyzing category trends, or optimizing SKU portfolios.
---
```

### 3.2 主体内容大纲

```markdown
# Product Attribute Analyzer

Analyzes product attributes using 3-Dimensional Tagging and sales-weighted market share to guide product development decisions.

## Capabilities

- 3-D attribute tagging and standardization
- Sales-weighted market share calculation
- Attribute combination ranking
- Market Portrait generation
- Under-supplied opportunity identification

## 3-Dimensional Tagging System

### Dimension 1: Development & Structure
Maps to `query_product_set` fields:
- `development_type`: 自主研发 / OEM贴牌 / 外采成品
- `sku_type`: A级 / B级 / C级
- `style_name`: 风格化名称
- `protection_level`: 保护等级

### Dimension 2: Category & Model
- `category`: 一级品类
- `sec_category`: 二级品类
- `model`: 产品型号
- `pmc_type`: 物控编码等级

### Dimension 3: Channel & Level
- `level_name`: 产品等级
- `platform_name`: 平台
- `country_name`: 国家
- `channel_name`: 渠道

## Sales-Weighted Market Share Formula

```
Market Share(Attribute X) = 
    SUM(order_qty) WHERE attribute = X 
    ─────────────────────────────────────
    SUM(order_qty) ALL
```

NOT count(ASIN) — sales volume matters more than SKU count.

## Attribute Combo Analysis

Analyze 2-3 attribute intersections:
```sql
SELECT 
    development_type,
    sku_type,
    SUM(order_qty) as total_sales,
    COUNT(DISTINCT asin) as asin_count,
    SUM(order_qty) * 1.0 / SUM(SUM(order_qty)) OVER() as market_share,
    SUM(order_qty) * 1.0 / COUNT(DISTINCT asin) as sales_per_asin
FROM order_sale_trend_adv_traffic_inv_set
WHERE date_id >= '{start_date}'
GROUP BY development_type, sku_type
ORDER BY market_share DESC;
```

## Opportunity Detection

Flag when:
- `sales_per_asin` > 150% of category average
- `market_share` < 20% but high sales per ASIN
- `asin_count` is low but `total_sales` is high

→ Indicates under-supplied opportunity

## Input Format

- Category level: "category = 'Kitchen Gadgets'"
- Dimension selection: "analyze by development_type + sku_type"
- Date range: "last 90 days"
- Filters: "country_name = 'US'"

## Output Format

```
【品类】Kitchen Gadgets
【分析周期】2024-11-01 ~ 2025-01-31
【样本】156 个 ASIN，总销量 45,200

维度 1: Development Type
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ Attribute Tag   │ ASIN Count│ Total Sales │ Market Share│ Sales/ASIN  │
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ 自主研发        │ 45       │ $890,000    │ 52.3%      │ $19,778 ⭐   │
│ OEM贴牌         │ 78       │ $620,000    │ 36.4%      │ $7,949      │
│ 外采成品        │ 33       │ $192,000    │ 11.3%      │ $5,818      │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘
→ 机会：自主研发产品数量少（29%）但贡献 52% 销售额，单均销量最高。
   建议：增加自主研发 SKU 占比。

维度 2: SKU Type
┌─────────────────┬──────────┬─────────────┬────────────┬──────────────┐
│ Attribute Tag   │ ASIN Count│ Total Sales │ Market Share│ Sales/ASIN  │
├─────────────────┼──────────┼─────────────┼────────────┼──────────────┤
│ A级             │ 23       │ $720,000    │ 42.3%      │ $31,304 ⭐   │
│ B级             │ 56       │ $580,000    │ 34.1%      │ $10,357      │
│ C级             │ 77       │ $402,000    │ 23.6%      │ $5,221      │
└─────────────────┴──────────┴─────────────┴────────────┴──────────────┘
→ 机会：A级 SKU 数量仅占 15%，但贡献 42% 销售额。
   建议：将 B/C 级中表现好的产品（销售额 > $15k）升级为 A 级资源投入。

组合分析: Development Type × SKU Type
┌─────────────────┬──────────┬─────────────┬────────────┐
│ Combo           │ ASIN Count│ Market Share│ Sales/ASIN │
├─────────────────┼──────────┼─────────────┼────────────┤
│ 自主研发 + A级   │ 12       │ 35.2%       │ $42,100 ⭐ │
│ 自主研发 + B级   │ 25       │ 14.8%       │ $15,200   │
│ OEM + A级        │ 8        │ 5.1%        │ $18,900   │
└─────────────────┴──────────┴─────────────┴────────────┘
→ 最高价值组合：自主研发 + A级（Supply/Demand 比最低）

Market Portrait:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 Market Favorite Archetype:
   自主研发 + A级 + US站 + FBA
   → 占品类销售额 32%，仅 8% ASIN 数量
   → 供给严重不足，建议加大开发投入
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Scripts

- `calculate_weighted_share.py`: Calculates sales-weighted market share
- `analyze_attribute_combo.py`: Analyzes attribute combinations for opportunities
- `generate_market_portrait.py`: Generates Market Portrait summary

## Best Practices

1. Always use sales-weighted share, never ASIN-count share
2. Compare sales_per_asin to identify under-supplied opportunities
3. Use 90-day rolling data to smooth seasonality
4. Filter out ASINs with < 10 sales to avoid noise
```

---

## 四、脚本设计

### 4.1 calculate_weighted_share.py

**功能**：计算单个维度的销售加权市场份额

**输入**：
```json
{
  "dimension": "development_type",
  "dataset": "order_sale_trend_adv_traffic_inv_set",
  "filters": {"category": "Kitchen Gadgets", "date_id__gte": "2024-11-01"},
  "weight_field": "order_qty",
  "count_field": "asin",
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["development_type", "sku_type"],
    "metrics": ["order_qty", "original_price"],
    "filters": {
      "category": "Kitchen Gadgets",
      "date_range": ["2024-11-01", "2025-01-31"]
    }
  }
}
```

**输出**：
```json
{
  "dimension": "development_type",
  "total_weight": 45200,
  "total_count": 156,
  "shares": [
    {"value": "自主研发", "weight": 23600, "count": 45, "share": 0.523, "avg_per_unit": 524},
    {"value": "OEM贴牌", "weight": 16400, "count": 78, "share": 0.364, "avg_per_unit": 210},
    {"value": "外采成品", "weight": 5200, "count": 33, "share": 0.113, "avg_per_unit": 158}
  ],
  "query_result": {
    "dataset": "ds_d35ac6f3910c",
    "rows": [...],
    "execution_time_ms": 1200
  }
}
```

### 4.2 analyze_attribute_combo.py

**功能**：分析属性组合，识别供给不足的机会

**核心算法**：
```python
def find_opportunities(combo_data, threshold_ratio=1.5):
    """
    识别机会点：sales_per_asin 显著高于均值但供给少的组合
    """
    avg_sales_per_asin = sum(d['total_sales'] for d in combo_data) / sum(d['asin_count'] for d in combo_data)
    
    opportunities = []
    for combo in combo_data:
        spa = combo['total_sales'] / combo['asin_count']
        if spa > avg_sales_per_asin * threshold_ratio and combo['market_share'] < 0.20:
            opportunities.append({
                'combo': combo['dimensions'],
                'sales_per_asin': spa,
                'market_share': combo['market_share'],
                'opportunity_score': spa / avg_sales_per_asin * (1 - combo['market_share'])
            })
    
    return sorted(opportunities, key=lambda x: x['opportunity_score'], reverse=True)
```

### 4.3 generate_market_portrait.py

**功能**：生成 Market Portrait 摘要报告

**输出格式**：Markdown 结构化报告，包含：
- Market Favorite Archetype（市场最受欢迎原型）
- Top 3 机会组合
- Bottom 3 过度供给组合
- 行动建议

### 4.4 数据查询接口规范

#### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

#### 查询构造方式

本 Skill 使用 `order_sale_trend_adv_traffic_inv_set` 数据集（`ds_d35ac6f3910c`，非子查询类型）作为销量数据源。

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension development_type --dimension sku_type \
  --metric order_qty --metric original_price \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

属性组合销量分析：

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
      { "expr": "ds_d35ac6f3910c.development_type", "alias": "f_dev_type" },
      { "expr": "ds_d35ac6f3910c.sku_type", "alias": "f_sku_type" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_total_sales", "aggregation": "SUM" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_revenue", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "Kitchen Gadgets" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_dev_type", "f_sku_type"],
    "limit": 1000
  }
}
```

#### 数据集类型判断

`ds_d35ac6f3910c` 为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

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
  "expr": "order_qty",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

---

## 五、Reference 文档设计

### 5.1 3d_tag_dictionary.md

```markdown
# 3-D 标签字典规范

## Dimension 1: Structural/Fit（结构/版型）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| development_type | 自主研发 / OEM贴牌 / 外采成品 | 直接使用，去空格 |
| sku_type | A级 / B级 / C级 | 统一为大写字母+级 |
| style_name | 简约 / 复古 / 工业 | 建立同义词映射表 |
| protection_level | 高 / 中 / 低 | 统一为中文 |

## Dimension 2: Material/Process（材料/工艺）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| category | Kitchen / Home / Electronics | 直接使用 |
| sec_category | Gadgets / Decor / Tools | 直接使用 |
| model | 型号编码 | 按前缀聚类 |
| pmc_type | PMC等级 | 映射为高/中/低 |

## Dimension 3: Design Elements（设计元素）

| 内部字段 | 取值示例 | 标签标准化规则 |
|---------|---------|--------------|
| level_name | 普通 / 精品 / 旗舰 | 直接使用 |
| platform_name | Amazon / Walmart | 直接使用 |
| country_name | US / UK / DE | 大写标准化 |
| channel_name | FBA / FBM | 直接使用 |

## 标签优先级规则

当多个标签描述同一属性时，优先级：
1. `query_product_set` 字段优先于 `order_sale_trend_*` 字段
2. 枚举值优先于自由文本
3. 中文标签优先于英文标签
```

### 5.2 attribute_mapping_table.md

```markdown
# 属性→数据集字段映射表

## 主数据源：query_product_set

| 分析维度 | 字段名 | 数据类型 | 备注 |
|---------|--------|---------|------|
| 开发类型 | development_type | CHAR | 自主研发/OEM贴牌/外采成品 |
| SKU等级 | sku_type | CHAR | A级/B级/C级 |
| 风格 | style_name | CHAR | 风格化名称 |
| 保护等级 | protection_level | CHAR | 高/中/低 |
| 品类 | category | STRING | 一级品类 |
| 二级品类 | sec_category | STRING | 二级品类 |
| 型号 | model | STRING | 产品型号 |
| 产品等级 | level_name | STRING | 普通/精品/旗舰 |

## 销量数据源：order_sale_trend_adv_traffic_inv_set

| 指标 | 字段名 | 聚合方式 |
|------|--------|---------|
| 销量 | order_qty | SUM |
| 销售额 | original_price | SUM |
| ASIN数量 | asin | COUNT DISTINCT |

## 关联方式

通过 `ed_sku` 字段跨数据集关联查询。先分别查询两个数据集，再在脚本中关联：

### 产品属性查询（query_product_set）

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "query_product_set",
      "alias": "ds_product",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_product.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_product.development_type", "alias": "f_dev_type" },
      { "expr": "ds_product.sku_type", "alias": "f_sku_type" },
      { "expr": "ds_product.style_name", "alias": "f_style" },
      { "expr": "ds_product.category", "alias": "f_category" },
      { "expr": "ds_product.sec_category", "alias": "f_sec_category" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_product.category", "operator": "eq", "value": "Kitchen Gadgets" }
      ]
    },
    "limit": 10000
  }
}
```

### 销量数据查询（order_sale_trend_adv_traffic_inv_set / ds_d35ac6f3910c）

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
      { "expr": "ds_d35ac6f3910c.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_order_qty", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_revenue", "aggregation": "SUM" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "Kitchen Gadgets" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ed_sku"],
    "limit": 10000
  }
}
```
```

### 5.3 market_portrait_template.md

```markdown
# Market Portrait 输出模板

## 模板结构

```markdown
# Market Portrait: {Category}

## Executive Summary
- Total ASINs: {count}
- Total Sales: {amount}
- Analysis Period: {period}

## Market Favorite Archetype
🏆 {top_combo}
- Market Share: {share}%
- ASIN Count: {count} ({count_pct}% of total)
- Sales per ASIN: ${spa}
- Status: {over/under}-supplied

## Top 3 Opportunities
1. {combo_1} — Opportunity Score: {score}
2. {combo_2} — Opportunity Score: {score}
3. {combo_3} — Opportunity Score: {score}

## Over-Supplied Segments
1. {combo_1} — Low efficiency, consider reduction

## Recommendations
- {recommendation_1}
- {recommendation_2}
```

## 判定规则

- **Under-supplied**: sales_per_asin > 1.5x average AND market_share < 20%
- **Over-supplied**: sales_per_asin < 0.5x average AND market_share > 30%
- **Balanced**: sales_per_asin within 0.8-1.2x average
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写 3-D 标签体系定义
- [ ] 编写销售加权份额公式
- [ ] 编写组合分析和机会识别逻辑

### Step 2：脚本开发（Day 2-3）

- [ ] 实现 `calculate_weighted_share.py`
- [ ] 实现 `analyze_attribute_combo.py`
- [ ] 实现 `generate_market_portrait.py`
- [ ] 编写单元测试（覆盖单维度/组合维度/机会识别）

### Step 3：Reference 文档（Day 3）

- [ ] 编写 3-D 标签字典规范
- [ ] 编写属性→字段映射表
- [ ] 编写 Market Portrait 输出模板

### Step 4：集成测试（Day 4-5）

- [ ] 测试用例 1：单维度分析（development_type）
- [ ] 测试用例 2：双维度组合分析（development_type × sku_type）
- [ ] 测试用例 3：Market Portrait 生成
- [ ] 测试用例 4：机会识别（高 sales_per_asin + 低 market_share）
- [ ] 测试用例 5：大数据量测试（1000+ ASIN）

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 份额计算准确性 | 与手动 SQL 计算误差 < 0.1% |
| 机会识别准确率 | 识别的机会组合 sales_per_asin 确实高于均值 1.5x |
| 输出格式 | Market Portrait 包含所有必填字段 |
| 性能 | 1000 ASIN 分析 < 5 秒 |
| 扩展性 | 支持新增维度字段和组合规则 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 下游调用 | 识别机会后，评估目标 ASIN 健康度 |
| `cross-border-product-selector` | 上游调用 | 选品时分析属性市场格局 |
| `ops-perspective-builder` | 数据供给 | 为透视图提供属性维度分析能力 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
