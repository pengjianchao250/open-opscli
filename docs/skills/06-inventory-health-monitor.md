# Skill 开发设计文档：inventory-health-monitor

> **Skill 名称**：`inventory-health-monitor`
> **复杂度等级**：Level 2 — 中等（需要脚本辅助计算）
> **预计开发时间**：4-5 天
> **业务价值**：高（库存积压和断货都直接影响利润）

---

## 一、Skill 定位

### 1.1 一句话描述

监控库存周转天数、库龄分布、断货风险，识别滞销品和缺货品，输出补货/清仓/调拨建议。

### 1.2 解决什么痛点

- 库存积压占用资金和仓储费，但不知道哪些 SKU 该清
- 热销品断货导致销售损失，但补货时机靠经验判断
- 海外仓、平台仓、在途库存分散，难以统一监控

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 周转诊断 | "分析 ASIN B08XXXXXX 的库存健康状况" |
| 滞销识别 | "找出周转天数 > 90 天的 SKU 并给出处理建议" |
| 断货预警 | "哪些 SKU 有断货风险？" |
| 库存复盘 | "生成本月库存健康度报告" |

---

## 二、文件结构设计

```
opscli/skills/inventory-health-monitor/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   ├── calculate_inventory_health.py     # 库存健康度计算
│   └── generate_replenishment_plan.py    # 补货计划生成
└── reference/
    ├── inventory_thresholds.md           # 库存预警阈值
    └── replenishment_formula.md          # 补货计算公式
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: inventory-health-monitor
description: Monitors inventory turnover days, stock age distribution, and stockout risks. Identifies slow-moving and out-of-stock SKUs, generating replenishment, clearance, and transfer recommendations. Use when managing inventory levels, planning replenishment, or clearing dead stock.
---
```

### 3.2 主体内容大纲

```markdown
# Inventory Health Monitor

Tracks inventory health metrics and generates actionable recommendations for replenishment, clearance, and transfer.

## Capabilities

- Inventory turnover analysis
- Stock age distribution tracking
- Stockout risk prediction
- Slow-moving SKU identification
- Replenishment quantity calculation
- Cross-warehouse transfer suggestions

## Core Metrics

| Metric | Field | Healthy | Warning | Critical |
|--------|-------|---------|---------|----------|
| Turnover Days | `sell_qty_days` | < 45 | 45-90 | > 90 |
| In-transit + Stock Days | `sell_intransit_qty_days` | < 60 | 60-120 | > 120 |
| Platform Stock | `platform_qty` | > 7 days sales | 3-7 days | < 3 days |
| Overseas Warehouse | `transfer_available_qty` | > 14 days sales | 7-14 days | < 7 days |
| Locked Stock Ratio | `transfer_lock_qty / transfer_qty` | < 20% | 20-50% | > 50% |

## Inventory Health Rating

```python
# 库存健康度评级（A/B/C/D/F）
def rate_inventory(sell_qty_days, platform_qty, avg_daily_sales):
    platform_days = platform_qty / avg_daily_sales if avg_daily_sales > 0 else 999
    
    if sell_qty_days < 45 and platform_days > 14:
        return 'A'  # 健康
    elif sell_qty_days < 60 and platform_days > 7:
        return 'B'  # 良好
    elif sell_qty_days < 90 and platform_days > 3:
        return 'C'  # 一般
    elif sell_qty_days < 120:
        return 'D'  # 预警
    else:
        return 'F'  # 滞销
```

## Data Sources

### Primary: custom_inventory_turnover_wk_set
- `ed_sku`: Company SKU
- `sell_qty_days`: Sellable turnover days
- `sell_intransit_qty_days`: Sellable + in-transit days
- `platform_qty`: Platform inventory
- `transfer_qty`: Overseas warehouse inventory
- `transfer_available_qty`: Available overseas stock
- `transfer_lock_qty`: Locked overseas stock
- `intransit_qty`: In-transit inventory
- `average_daily_sales_volume`: Average daily sales

### Secondary: order_sale_trend_adv_traffic_inv_set
- `total_qty`: Total inventory across all locations
- `fba_qty`: FBA inventory

## Analysis Dimensions

### 1. Turnover Health

使用 `custom_inventory_turnover_wk_set`（`ds_97zj6R0KDKpB`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_inventory.turnover_wk_set ...)",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.sell_qty_days", "alias": "f_sell_days" },
      { "expr": "CASE WHEN ds_97zj6R0KDKpB.sell_qty_days < 45 THEN 'Healthy' WHEN ds_97zj6R0KDKpB.sell_qty_days < 90 THEN 'Warning' ELSE 'Critical' END", "alias": "f_health_status" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" }
      ]
    },
    "orderBy": [{ "field": "f_sell_days", "direction": "DESC" }],
    "limit": 1000
  }
}
```

### 2. Stockout Risk

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_inventory.turnover_wk_set ...)",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty", "alias": "f_platform_qty" },
      { "expr": "ds_97zj6R0KDKpB.average_daily_sales_volume", "alias": "f_avg_daily_sales" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "alias": "f_stock_days" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" },
        { "field": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "operator": "lt", "value": 14 }
      ]
    },
    "orderBy": [{ "field": "f_stock_days", "direction": "ASC" }],
    "limit": 1000
  }
}
```

### 3. Replenishment Calculation
```
补货量 = (目标库存天数 × 日均销量) - (平台库存 + 在途库存 + 海外仓可用库存)

目标库存天数：
- 快消品：45-60 天
- 标品：60-90 天
- 季节性：提前 2-3 个月
```

## Input Format

- SKU level: "ed_sku = 'ED-12345'"
- Category level: "category = 'Kitchen'"
- Risk type: "stockout risk" or "slow moving"
- Date: latest available

## Output Format

```
【SKU】ED-12345（Stainless Steel Bottle）
【库存健康评级】D（预警）

库存分布：
┌─────────────────┬──────────┬─────────────┐
│ Location        │ Qty      │ Days Cover  │
├─────────────────┼──────────┼─────────────┤
│ 平台仓 (FBA)    │ 120      │ 8 天 ⚠️    │
│ 海外仓可售      │ 80       │ 5 天 ⚠️    │
│ 海外仓锁定      │ 40       │ —          │
│ 在途            │ 200      │ 13 天      │
├─────────────────┼──────────┼─────────────┤
│ 总计可售        │ 400      │ 26 天      │
│ 总库存          │ 440      │ 29 天      │
└─────────────────┴──────────┴─────────────┘

问题诊断：
⚠️ 平台仓仅剩 8 天库存（健康线 > 14 天）
⚠️ 海外仓锁定比例 33%（健康线 < 20%）

行动建议：
1. [P0] 紧急补货：建议补货 300 件
   → 补货后平台仓覆盖 29 天
   → 预计到货时间：海运 35 天，需在 3 月 15 日前发货

2. [P1] 解锁海外仓库存：调查 40 件锁定原因
   → 预计释放后可售天数 +5 天

3. [P2] 评估在途时效：当前在途 200 件预计 3 月 10 日到港
   → 如时效延迟，考虑空运应急 100 件

【预计销售损失】
如不补货，3 月 20 日后断货，预计损失 $3,500/周
```

## Scripts

- `calculate_inventory_health.py`: Calculates inventory health ratings
- `generate_replenishment_plan.py`: Generates replenishment quantity and timing

## Best Practices

1. Always consider in-transit inventory in replenishment calculations
2. Flag locked stock for investigation
3. Use 30-day rolling average for daily sales to smooth volatility
4. Seasonal products need adjusted target days
```

---

## 四、脚本设计

### 4.1 calculate_inventory_health.py

**功能**：计算库存健康评级和风险识别

**输入**：
```json
{
  "sku": "ED-12345",
  "inventory": {
    "platform_qty": 120,
    "transfer_available_qty": 80,
    "transfer_lock_qty": 40,
    "intransit_qty": 200,
    "total_qty": 440
  },
  "sales": {
    "average_daily_sales_volume": 15,
    "last_7d_avg": 14,
    "last_30d_avg": 15.2
  },
  "thresholds": {
    "healthy_days": 45,
    "warning_days": 90,
    "stockout_risk_days": 14
  },
  "query_payload": {
    "dataset": "ds_97zj6R0KDKpB",
    "dimensions": ["ed_sku", "product_name"],
    "metrics": ["sell_qty_days", "platform_qty", "transfer_available_qty", "transfer_lock_qty", "intransit_qty", "average_daily_sales_volume"],
    "filters": {
      "ed_sku": "ED-12345",
      "date_id": "2025-01-31"
    }
  }
}
```

**输出**：
```json
{
  "sku": "ED-12345",
  "health_rating": "D",
  "total_days_cover": 26,
  "platform_days_cover": 8,
  "risks": [
    {"type": "stockout", "severity": "high", "days_until_stockout": 8},
    {"type": "high_lock_ratio", "severity": "medium", "lock_ratio": 0.33}
  ],
  "recommendations": [
    {"action": "replenish", "quantity": 300, "urgency": "high"},
    {"action": "unlock_investigate", "quantity": 40, "urgency": "medium"}
  ],
  "query_result": {
    "dataset": "ds_97zj6R0KDKpB",
    "rows": [...],
    "execution_time_ms": 1200
  }
}
```

### 4.2 generate_replenishment_plan.py

**功能**：生成补货计划

**核心算法**：
```python
def calculate_replenishment(sku_data, target_days, lead_time_days):
    """
    计算补货量和建议发货时间
    """
    daily_sales = sku_data['average_daily_sales_volume']
    current_available = (
        sku_data['platform_qty'] + 
        sku_data['transfer_available_qty'] + 
        sku_data['intransit_qty']
    )
    
    # 目标库存量 = 目标天数 × 日均销量
    target_inventory = target_days * daily_sales
    
    # 补货量 = 目标库存 - 当前可用
    replenishment_qty = max(0, target_inventory - current_available)
    
    # 安全库存 =  lead_time × 日均销量 × 1.5（安全系数）
    safety_stock = lead_time_days * daily_sales * 1.5
    
    # 最终建议 = 补货量 + 安全库存
    recommended_qty = replenishment_qty + safety_stock
    
    # 建议发货日期 = 当前日期 + (平台库存天数 - lead_time - 缓冲)
    platform_days = sku_data['platform_qty'] / daily_sales
    buffer_days = 7
    ship_by_date = datetime.now() + timedelta(
        days=max(0, platform_days - lead_time_days - buffer_days)
    )
    
    return {
        'replenishment_qty': round(replenishment_qty),
        'recommended_qty': round(recommended_qty),
        'ship_by_date': ship_by_date.strftime('%Y-%m-%d'),
        'urgency': 'high' if platform_days < 14 else 'medium'
    }
```

### 4.3 数据查询接口规范

#### 认证流程

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

#### 查询构造方式

本 Skill 使用两个核心数据集：
- **主数据集**：`custom_inventory_turnover_wk_set`（`ds_97zj6R0KDKpB`，非子查询类型）
- **辅助数据集**：`order_sale_trend_adv_traffic_inv_set`（`ds_d35ac6f3910c`，非子查询类型）

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_97zj6R0KDKpB \
  --dimension ed_sku --dimension product_name \
  --metric sell_qty_days --metric platform_qty --metric transfer_available_qty \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

库存周转数据查询（`ds_97zj6R0KDKpB`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_inventory.turnover_wk_set ...)",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.sell_qty_days", "alias": "f_sell_days" },
      { "expr": "ds_97zj6R0KDKpB.sell_intransit_qty_days", "alias": "f_intransit_days" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty", "alias": "f_platform_qty" },
      { "expr": "ds_97zj6R0KDKpB.transfer_qty", "alias": "f_transfer_qty" },
      { "expr": "ds_97zj6R0KDKpB.transfer_available_qty", "alias": "f_transfer_avail" },
      { "expr": "ds_97zj6R0KDKpB.transfer_lock_qty", "alias": "f_transfer_lock" },
      { "expr": "ds_97zj6R0KDKpB.intransit_qty", "alias": "f_intransit" },
      { "expr": "ds_97zj6R0KDKpB.average_daily_sales_volume", "alias": "f_avg_daily_sales" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.ed_sku", "operator": "eq", "value": "ED-12345" },
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" }
      ]
    },
    "limit": 1000
  }
}
```

辅助库存数据查询（`ds_d35ac6f3910c`）：

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
      { "expr": "ds_d35ac6f3910c.total_qty", "alias": "f_total_qty", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.fba_qty", "alias": "f_fba_qty", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.ed_sku", "operator": "eq", "value": "ED-12345" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ed_sku"],
    "limit": 1000
  }
}
```

#### 数据集类型判断

`ds_97zj6R0KDKpB` 和 `ds_d35ac6f3910c` 均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

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
  "expr": "sell_qty_days",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

---

## 五、Reference 文档设计

### 5.1 inventory_thresholds.md

```markdown
# 库存预警阈值

## 通用阈值

| 指标 | A级（健康） | B级（良好） | C级（一般） | D级（预警） | F级（滞销） |
|------|-----------|-----------|-----------|-----------|-----------|
| 可售周转天数 | < 45 | 45-60 | 60-90 | 90-120 | > 120 |
| 平台仓覆盖 | > 21 天 | 14-21 天 | 7-14 天 | 3-7 天 | < 3 天 |
| 海外仓覆盖 | > 30 天 | 21-30 天 | 14-21 天 | 7-14 天 | < 7 天 |
| 锁定比例 | < 10% | 10-20% | 20-30% | 30-50% | > 50% |

## 品类差异化阈值

| 品类 | 目标周转天数 | 安全库存天数 |
|------|------------|------------|
| 快消品 | 30-45 | 14 |
| 标品 | 60-90 | 21 |
| 季节性 | 提前 2-3 月 | 30 |
| 大件 | 45-60 | 21 |
```

### 5.2 replenishment_formula.md

```markdown
# 补货计算公式

## 基础公式

```
补货量 = (目标库存天数 × 日均销量) - (平台库存 + 海外仓可售 + 在途)
```

## 考虑因素

1. **Lead Time（交期）**
   - 海运：30-45 天
   - 空运：7-14 天
   - 生产：14-30 天

2. **Safety Stock（安全库存）**
   - 公式：Lead Time × 日均销量 × 安全系数
   - 安全系数：稳定产品 1.2，波动大产品 1.5，新品 2.0

3. **季节性调整**
   - 旺季前 2-3 个月增加目标库存天数
   - 旺季倍数：参考历史同期销售倍数

4. **促销调整**
   - 大促前提前备货
   - 促销期间日均销量 = 正常日均 × 促销倍数

## 完整计算示例

```python
# SKU: ED-12345, Water Bottle
normal_daily_sales = 15
seasonal_factor = 1.8  # 夏季旺季
lead_time = 35  # 海运
target_days = 60

adjusted_daily = normal_daily_sales * seasonal_factor  # 27
target_inventory = target_days * adjusted_daily  # 1,620
current_available = 400  # 平台 + 海外仓 + 在途
safety_stock = lead_time * adjusted_daily * 1.2  # 1,134

replenishment = target_inventory - current_available + safety_stock
# = 1,620 - 400 + 1,134 = 2,354

# 建议：分两批发货
# 第一批：1,200（空运应急，10 天后到）
# 第二批：1,200（海运，45 天后到）
```
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写核心指标和健康评级
- [ ] 编写补货计算公式
- [ ] 编写 SQL 查询模板

### Step 2：脚本开发（Day 2-3）

- [ ] 实现 `calculate_inventory_health.py`
- [ ] 实现 `generate_replenishment_plan.py`
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 3）

- [ ] 编写库存预警阈值表
- [ ] 编写补货计算公式详解

### Step 4：测试验证（Day 4-5）

- [ ] 测试用例 1：健康库存 SKU
- [ ] 测试用例 2：滞销 SKU（> 90 天）
- [ ] 测试用例 3：断货风险 SKU（< 14 天）
- [ ] 测试用例 4：高锁定比例 SKU
- [ ] 测试用例 5：季节性补货计算

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 健康评级准确性 | 与人工判断一致率 > 90% |
| 断货预警 | 提前 14 天预警，误报率 < 10% |
| 补货建议 | 补货量计算误差 < 15% |
| 多仓支持 | 支持平台仓/海外仓/在途分别监控 |
| 输出格式 | 包含天数覆盖、风险识别、行动建议 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 上游触发 | 库存天数预警时触发深度分析 |
| `profit-structure-analyzer` | 上游触发 | 仓租占比高时分析库存结构 |
| `ops-perspective-builder` | 数据供给 | 为库存透视图提供分析能力 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
