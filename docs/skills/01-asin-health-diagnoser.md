# Skill 开发设计文档：asin-health-diagnoser

> **Skill 名称**：`asin-health-diagnoser`
> **复杂度等级**：Level 1 — 简单（纯指令型）
> **预计开发时间**：2-3 天
> **业务价值**：高（运营周会核心需求）

---

## 一、Skill 定位

### 1.1 一句话描述

对单个或多个 ASIN 进行综合健康度评分，基于内部经营数据 + 爬虫快照数据，识别需要运营干预的产品。

### 1.2 解决什么痛点

- 运营团队面对数千个 ASIN，不知道优先关注哪些
- 健康度评估依赖主观经验，缺乏标准化评分体系
- 多维度指标（利润、转化、广告、退款、库存、星级）难以综合判断

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 日常诊断 | "诊断 ASIN B08XXXXXX 的健康状况" |
| 批量筛选 | "找出我部门健康度评分低于 60 的 ASIN" |
| 周会汇报 | "生成本周 Top 10 需要关注的 ASIN 清单" |
| 新品监控 | "监控近 30 天新上架 ASIN 的健康度变化" |

---

## 二、文件结构设计

```
opscli/skills/asin-health-diagnoser/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   └── calculate_health_score.py         # 健康度评分计算脚本
└── reference/
    ├── dataset_fields_mapping.md         # 数据集字段映射
    └── threshold_reference.md            # 预警阈值参考表
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: asin-health-diagnoser
description: Diagnoses ASIN health by calculating composite scores from gross_profit_percent, convert_percent, ads_acos, refund_percent, inventory_turnaround_days, and star rating. Use when evaluating product performance, identifying underperforming ASINs, prioritizing operational interventions, or preparing weekly review reports.
---
```

### 3.2 主体内容大纲

```markdown
# ASIN Health Diagnoser

Calculates a composite health score (0-100) for Amazon ASINs using internal operational data.

## Capabilities

- Single ASIN deep diagnosis
- Batch ASIN health ranking
- Department/team-level health overview
- Trend analysis over time periods
- Prioritized action recommendations

## Health Score Formula

Score = w1 * normalize(gross_profit_percent) +
        w2 * normalize(convert_percent) +
        w3 * normalize(1 - ads_acos) +
        w4 * normalize(1 - refund_percent) +
        w5 * normalize(1 / inventory_days) +
        w6 * normalize(star / 5)

Default weights: [0.30, 0.20, 0.20, 0.15, 0.10, 0.05]

## Threshold Reference

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| gross_profit_percent | > 20% | 10-20% | < 10% |
| convert_percent | > 10% | 5-10% | < 5% |
| ads_acos | < 20% | 20-30% | > 30% |
| refund_percent | < 5% | 5-10% | > 10% |
| inventory_days | < 45 | 45-90 | > 90 |
| star | > 4.3 | 4.0-4.3 | < 4.0 |

## Input Format

- Single ASIN: "B08XXXXXX"
- Multiple ASINs: "B08XXXXXX, B09YYYYYY"
- Team filter: "team_name = 'Kitchen-Team-A'"
- Date range: "last 30 days", "2025-01-01 to 2025-01-31"

## Output Format

For each ASIN:

```
【ASIN】B08XXXXXX（Product Name）
【健康度评分】72/100（良好）
【分项指标】
  ├─ 毛利率：18.5% ⚠️（预警，目标>20%）
  ├─ 转化率：12.3% ✅（健康）
  ├─ ACOS：22.1% ⚠️（预警，目标<20%）
  ├─ 退款率：4.2% ✅（健康）
  ├─ 库存周转：38天 ✅（健康）
  └─ 星级：4.5⭐ ✅（健康）
【主要问题】ACOS 偏高、毛利率低于目标
【建议行动】
  1. [P1] 优化广告投放，将 ACOS 从 22% 降至 18%
  2. [P1] 评估采购成本，谈判降低 2-3%
【数据时间】2025-01-01 ~ 2025-01-31
```

## Scripts

- `calculate_health_score.py`: Calculates composite health score from JSON input

## Best Practices

1. Always compare against team/category averages, not just absolute thresholds
2. When star rating is missing, exclude it from calculation and note the gap
3. For new products (< 30 days), use relaxed thresholds
4. Flag any ASIN with multiple Critical metrics for immediate attention
```

---

## 四、脚本设计：calculate_health_score.py

### 4.1 功能说明

接收 JSON 格式的 ASIN 指标数据，输出健康度评分和分级诊断。

### 4.2 输入格式

```json
{
  "asin": "B08XXXXXX",
  "product_name": "Stainless Steel Water Bottle",
  "metrics": {
    "gross_profit_percent": 0.185,
    "convert_percent": 0.123,
    "ads_acos": 0.221,
    "refund_percent": 0.042,
    "inventory_days": 38,
    "star": 4.5
  },
  "weights": {
    "gross_profit_percent": 0.30,
    "convert_percent": 0.20,
    "ads_acos": 0.20,
    "refund_percent": 0.15,
    "inventory_days": 0.10,
    "star": 0.05
  },
  "benchmarks": {
    "gross_profit_percent": {"healthy": 0.20, "warning": 0.10},
    "convert_percent": {"healthy": 0.10, "warning": 0.05},
    "ads_acos": {"healthy": 0.20, "warning": 0.30},
    "refund_percent": {"healthy": 0.05, "warning": 0.10},
    "inventory_days": {"healthy": 45, "warning": 90},
    "star": {"healthy": 4.3, "warning": 4.0}
  },
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["asin", "product_name"],
    "metrics": ["gross_profit_percent", "convert_percent", "ads_acos", "refund_percent", "sell_qty_days"],
    "filters": {
      "asin": "B08XXXXXX",
      "date_range": ["2025-01-01", "2025-01-31"]
    }
  }
}
```

### 4.3 输出格式

```json
{
  "asin": "B08XXXXXX",
  "product_name": "Stainless Steel Water Bottle",
  "health_score": 72,
  "health_level": "Good",
  "metrics_detail": [
    {
      "metric": "gross_profit_percent",
      "value": 0.185,
      "normalized_score": 75,
      "status": "warning",
      "benchmark": {"healthy": 0.20, "warning": 0.10}
    }
  ],
  "issues": [
    {
      "metric": "ads_acos",
      "severity": "warning",
      "description": "ACOS 22.1% exceeds healthy threshold 20%",
      "recommendation": "Optimize ad campaigns to reduce ACOS"
    }
  ],
  "prioritized_actions": [
    {"priority": "P1", "action": "Optimize ads to reduce ACOS from 22% to 18%"}
  ],
  "query_result": {
    "dataset": "ds_d35ac6f3910c",
    "rows": [...],
    "execution_time_ms": 1200
  }
}
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

**推荐方式**：使用 `opscli query build` 构造 payload，然后 `opscli query run` 执行：

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

本 Skill 使用 `order_sale_trend_adv_traffic_inv_set` 数据集（`ds_d35ac6f3910c`，非子查询类型），配合 `custom_crawler_listing_snapshot`（`ds_pdTYjvLRCadv`）辅助查询。

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
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "ds_d35ac6f3910c.product_name", "alias": "f_product_name" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_gross_profit", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.convert_percent", "alias": "f_convert", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.ads_acos", "alias": "f_acos", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.sell_qty_days", "alias": "f_inventory_days", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_product_name"],
    "limit": 1000
  }
}
```

星级数据通过 `ds_pdTYjvLRCadv` 关联查询：

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
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.asin", "operator": "eq", "value": "B08XXXXXX" }
      ]
    },
    "groupBy": ["f_asin"],
    "limit": 1000
  }
}
```

#### 数据集类型判断

`ds_d35ac6f3910c`（`order_sale_trend_adv_traffic_inv_set`）为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

#### 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`，如 `f_754ed2fb474f09f9`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

#### 公式指标查询规范

公式指标（如 `sell_qty_days`, `gross_profit_percent`）必须使用完整表达式格式：

```json
// 正确：使用 summary_expression
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

### 4.5 核心算法逻辑

```python
def normalize(value, metric_type, benchmark):
    """
    将原始指标值归一化为 0-100 分
    
    规则：
    - 对于"越高越好"指标（利润、转化、星级）：
      100分 = healthy阈值，0分 = warning阈值，线性插值
    - 对于"越低越好"指标（ACOS、退款率、库存天数）：
      100分 = healthy阈值，0分 = warning阈值，线性插值
    """
    pass

def calculate_composite_score(metrics, weights, benchmarks):
    """
    计算加权综合评分
    """
    total_score = 0
    for metric, weight in weights.items():
        normalized = normalize(metrics[metric], metric, benchmarks[metric])
        total_score += normalized * weight
    return round(total_score)
```

---

## 五、Reference 文档设计

### 5.1 dataset_fields_mapping.md

```markdown
# ASIN Health Diagnoser — 数据集字段映射

## 主数据集：order_sale_trend_adv_traffic_inv_set

| 指标 | 字段名 | 数据类型 | 说明 |
|------|--------|---------|------|
| 销售额 | `original_price` | DECIMAL | SUM 聚合 |
| 毛利率 | `gross_profit_percent` | DECIMAL | 公式计算 |
| 转化率 | `convert_percent` | DECIMAL | 来自关联流量表 |
| ACOS | `ads_acos` | DECIMAL | 公式计算 |
| 退款率 | `refund_percent` | DECIMAL | 公式计算 |
| 周转天数 | `sell_qty_days` | DECIMAL | 来自关联库存表 |

## 辅助数据集：custom_crawler_listing_snapshot

| 指标 | 字段名 | 数据类型 | 说明 |
|------|--------|---------|------|
| 星级 | `star` / `rating` | DECIMAL | AVG 聚合 |
| 评论数 | `reviews_qty` | INT | SUM 聚合 |
| 排名 | `subclass_rank` | INT | MIN 聚合 |

## 数据查询 Payload 模板

### 主数据集查询（order_sale_trend_adv_traffic_inv_set / ds_d35ac6f3910c）

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
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "ds_d35ac6f3910c.product_name", "alias": "f_product_name" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_gross_profit", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.convert_percent", "alias": "f_convert", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.ads_acos", "alias": "f_acos", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.sell_qty_days", "alias": "f_inventory_days", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_product_name"],
    "limit": 1000
  }
}
```

### 辅助数据集查询（custom_crawler_listing_snapshot / ds_pdTYjvLRCadv）

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
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews", "aggregation": "SUM" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank", "aggregation": "MIN" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.asin", "operator": "eq", "value": "B08XXXXXX" }
      ]
    },
    "groupBy": ["f_asin"],
    "limit": 1000
  }
}
```
```

### 5.2 threshold_reference.md

```markdown
# 预警阈值参考表

## 默认阈值（全品类）

| 指标 | 健康 | 预警 | 危险 | 说明 |
|------|------|------|------|------|
| gross_profit_percent | ≥20% | 10%-20% | <10% | 低于 0% 标红 |
| convert_percent | ≥10% | 5%-10% | <5% | 需对比品类均值 |
| ads_acos | ≤20% | 20%-30% | >30% | 新品可放宽至 35% |
| refund_percent | ≤5% | 5%-10% | >10% | 季节性产品需调整 |
| inventory_days | ≤45 | 45-90 | >90 | 快销品应 <30 |
| star | ≥4.3 | 4.0-4.3 | <4.0 | 低于 3.5 需立即下架 |

## 品类差异化阈值（未来扩展）

| 品类 | convert_percent 健康线 | ads_acos 健康线 |
|------|----------------------|----------------|
| Electronics | 8% | 25% |
| Home & Kitchen | 12% | 20% |
| Clothing | 10% | 22% |
| Beauty | 11% | 18% |
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写 Capabilities、Formula、Threshold、Input/Output 章节
- [ ] 编写 3 个以上 Example Usage
- [ ] 检查 description 触发关键词覆盖度

### Step 2：脚本开发（Day 2）

- [ ] 实现 `calculate_health_score.py`
- [ ] 实现 normalize 函数（支持越高越好/越低越好两种模式）
- [ ] 实现缺失值处理逻辑
- [ ] 添加 JSON 输入输出接口
- [ ] 编写单元测试（覆盖正常/异常/缺失值场景）

### Step 3：Reference 文档（Day 2）

- [ ] 整理数据集字段映射表
- [ ] 编写 SQL 查询模板
- [ ] 整理品类差异化阈值（如有）

### Step 4：测试验证（Day 3）

- [ ] 测试用例 1：单个 ASIN 完整指标诊断
- [ ] 测试用例 2：批量 ASIN 排序输出
- [ ] 测试用例 3：缺失星级数据时的降级处理
- [ ] 测试用例 4：所有指标 Critical 的极端情况
- [ ] 测试用例 5：权重自定义场景

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 评分准确性 | 与手动计算对比，误差 < 1 分 |
| 响应时间 | 单 ASIN < 3 秒，批量 50 个 ASIN < 10 秒 |
| 覆盖率 | 支持 6 个核心指标，缺失值自动降级 |
| 可用性 | 输出包含明确的问题描述和行动建议 |
| 扩展性 | 支持权重自定义、阈值自定义 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `profit-structure-analyzer` | 下游调用 | 健康度低时，进一步分析利润结构 |
| `advertising-efficiency-optimizer` | 下游调用 | ACOS 预警时，调用广告优化 |
| `inventory-health-monitor` | 下游调用 | 库存天数异常时，调用库存分析 |
| `ops-perspective-builder` | 上游调用 | 透视图构建时批量调用健康度评分 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
