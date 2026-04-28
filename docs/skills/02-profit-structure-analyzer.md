# Skill 开发设计文档：profit-structure-analyzer

> **Skill 名称**：`profit-structure-analyzer`
> **复杂度等级**：Level 1 — 简单（纯指令型）
> **预计开发时间**：2-3 天
> **业务价值**：高（利润优化核心需求）

---

## 一、Skill 定位

### 1.1 一句话描述

拆解 ASIN/品类/团队级别的成本结构，识别利润压缩点，应用 Eliminate/Reduce/Raise/Create 四行动框架输出优化策略。

### 1.2 解决什么痛点

- 知道毛利率低，但不知道具体是哪项成本在"吸血"
- 成本优化缺乏系统性框架，往往是头痛医头
- 不同团队的成本结构差异大，缺乏横向对比基准

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 亏损诊断 | "分析 ASIN B08XXXXXX 的成本结构，为什么毛利率只有 3%？" |
| 横向对比 | "对比 Kitchen 团队和 Home 团队的成本结构差异" |
| 优化建议 | "给我这个品类降本增效的建议" |
| 月度复盘 | "生成 1 月份全公司的成本结构分析报告" |

---

## 二、文件结构设计

```
opscli/skills/profit-structure-analyzer/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   └── analyze_cost_structure.py         # 成本结构拆解与对比脚本
└── reference/
    ├── cost_items_reference.md           # 成本项说明与占比基准
    └── four_actions_template.md          # 四行动框架模板
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: profit-structure-analyzer
description: Analyzes cost structure breakdown for ASINs, categories, or teams using purchase_cost, first_leg, freight, storage, advertising, fee, tax, and fixed_cost data. Applies the Eliminate/Reduce/Raise/Create framework to generate profit optimization strategies. Use when investigating low margins, comparing team profitability, or identifying cost reduction opportunities.
---
```

### 3.2 主体内容大纲

```markdown
# Profit Structure Analyzer

Decomposes sales revenue into 8 cost categories and applies the Four Actions Framework for profit optimization.

## Capabilities

- Single ASIN cost structure breakdown
- Category/team-level cost comparison
- Benchmark deviation analysis
- Four Actions (Eliminate/Reduce/Raise/Create) strategy generation
- Trend analysis over time periods

## Cost Structure Categories

Based on `order_sale_trend_adv_traffic_inv_set` fields:

| Cost Item | Field | Direction |
|-----------|-------|-----------|
| Purchase Cost | `purchase_cost_percent` | Reduce |
| First Leg Freight | `first_leg_percent` | Reduce |
| Shipping/Freight | `freight_percent` | Reduce |
| Storage Charges | `storage_charges_percent` | Reduce/Eliminate |
| Advertising Fee | `advertising_fee_percent` | Reduce |
| Platform Fee | `fee_percent` | — (fixed) |
| Tax | `tax_fee_percent` | — (fixed) |
| Fixed Cost | `fixed_cost_percent` | — (fixed) |
| Refund/Compensation | `refund_percent` + `compensate_percent` | Eliminate |

## Four Actions Framework

### Eliminate
- 清理库龄 > 90 天的滞销库存
- 修复导致高退款率的质量问题
- 淘汰毛利率持续 < 0% 的 SKU

### Reduce
- 谈判降低采购成本
- 优化头程物流方案
- 降低广告 ACOS
- 合并发货降低运费

### Raise
- 提升售价（基于竞品价格带分析）
- 增加品牌溢价
- 提高客单价（配件包/套装）

### Create
- 开发差异化功能避开价格战
- 拓展高毛利变体/颜色/尺寸
- 开发私模产品提升壁垒

## Input Format

- ASIN level: "B08XXXXXX"
- Category level: "category = 'Kitchen Gadgets'"
- Team level: "team_name = 'Kitchen-Team-A'"
- Date range: "last 30 days", "2025-Q1"

## Output Format

```
【分析对象】ASIN B08XXXXXX（蓝牙耳机）
【分析周期】2025-01-01 ~ 2025-01-31
【销售额】$29,990

成本结构拆解：
┌─────────────────────┬──────────┬──────────┬─────────────┐
│ Cost Item           │ Current  │ Benchmark│ Deviation   │
├─────────────────────┼──────────┼──────────┼─────────────┤
│ 采购成本            │ 28.5%    │ 25.0%    │ +3.5% ⚠️   │
│ 头程运费            │ 8.2%     │ 6.5%     │ +1.7% ⚠️   │
│ 平台手续费          │ 15.0%    │ 15.0%    │ —          │
│ 广告费              │ 22.0%    │ 18.0%    │ +4.0% 🔴   │
│ 仓租                │ 5.5%     │ 4.0%     │ +1.5% ⚠️   │
│ 税金                │ 8.0%     │ 8.0%     │ —          │
│ 固定成本            │ 3.0%     │ 3.0%     │ —          │
│ 退款/赔偿           │ 6.8%     │ 3.5%     │ +3.3% 🔴   │
├─────────────────────┼──────────┼──────────┼─────────────┤
│ 毛利率              │ 3.0%     │ 17.0%    │ -14.0% 🔴  │
└─────────────────────┴──────────┴──────────┴─────────────┘

四行动策略：
【Eliminate】
  1. 清理库龄 > 90 天滞销库存（预计减少仓租 1.5%）
  2. 修复充电口松动导致的 6.8% 退款率（预计降至 3.5%）

【Reduce】
  1. 将广告 ACOS 从 22% 优化至 18%（预计节省 $1,200/月）
  2. 头程运费占比从 8.2% 降至 7%（货量整合谈判）

【Raise】
  1. 提升售价 10%（当前 $29.99，竞品区间 $35-45）

【Create】
  1. 增加主动降噪功能，避开价格战

【预期效果】
  执行后毛利率可从 3% 提升至 15-18%
```

## Scripts

- `analyze_cost_structure.py`: Breaks down cost structure and generates Four Actions recommendations

## Best Practices

1. Always compare against internal benchmark (team/category average), not external guess
2. Flag fixed costs (`fee_percent`, `tax_fee_percent`, `fixed_cost_percent`) as non-actionable
3. Focus on top 3 cost deviations, don't overwhelm with too many actions
4. Quantify expected impact in dollar terms when possible
```

---

## 四、脚本设计：analyze_cost_structure.py

### 4.1 功能说明

接收成本结构数据，计算各项偏离度，应用四行动框架生成策略。

### 4.2 输入格式

```json
{
  "target": {
    "type": "asin",
    "value": "B08XXXXXX",
    "name": "Bluetooth Earbuds"
  },
  "period": {
    "start": "2025-01-01",
    "end": "2025-01-31"
  },
  "cost_structure": {
    "purchase_cost_percent": 0.285,
    "first_leg_percent": 0.082,
    "freight_percent": 0.0,
    "storage_charges_percent": 0.055,
    "advertising_fee_percent": 0.22,
    "fee_percent": 0.15,
    "tax_fee_percent": 0.08,
    "fixed_cost_percent": 0.03,
    "refund_percent": 0.068,
    "compensate_percent": 0.0
  },
  "benchmark": {
    "purchase_cost_percent": 0.25,
    "first_leg_percent": 0.065,
    "advertising_fee_percent": 0.18,
    "storage_charges_percent": 0.04,
    "refund_percent": 0.035
  },
  "sales_amount": 29990,
  "query_payload": {
    "dataset": "ds_d35ac6f3910c",
    "dimensions": ["asin", "product_name"],
    "metrics": ["original_price", "purchase_cost_percent", "first_leg_percent", "advertising_fee_percent", "fee_percent", "tax_fee_percent", "fixed_cost_percent", "refund_percent", "gross_profit_percent"],
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
  "target": "B08XXXXXX",
  "gross_profit_percent": 0.03,
  "deviations": [
    {
      "item": "advertising_fee_percent",
      "current": 0.22,
      "benchmark": 0.18,
      "deviation": 0.04,
      "severity": "critical",
      "action_category": "Reduce"
    }
  ],
  "four_actions": {
    "eliminate": [...],
    "reduce": [...],
    "raise": [...],
    "create": [...]
  },
  "expected_impact": {
    "current_margin": 0.03,
    "target_margin": 0.15,
    "monthly_value": 3600
  },
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

本 Skill 使用 `order_sale_trend_adv_traffic_inv_set` 数据集（`ds_d35ac6f3910c`，非子查询类型）。

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension team_name \
  --metric original_price --metric purchase_cost --metric advertising_fee \
  --metric fee --metric tax_fee --metric fixed_cost --metric refund_percent \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

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
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.purchase_cost_percent", "alias": "f_purchase_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.first_leg_percent", "alias": "f_first_leg_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.freight_percent", "alias": "f_freight_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.storage_charges_percent", "alias": "f_storage_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.advertising_fee_percent", "alias": "f_ad_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.fee_percent", "alias": "f_fee_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.tax_fee_percent", "alias": "f_tax_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.fixed_cost_percent", "alias": "f_fixed_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.compensate_percent", "alias": "f_compensate_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_gross_profit", "aggregation": "AVG" }
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
  "expr": "gross_profit_percent",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

### 4.5 核心逻辑

```python
def calculate_deviation(current, benchmark, direction='lower_is_better'):
    """
    计算偏离度并分级
    """
    deviation = current - benchmark
    
    if direction == 'lower_is_better':
        if deviation > 0.05: return 'critical'
        elif deviation > 0.02: return 'warning'
        else: return 'normal'
    else:
        if deviation < -0.05: return 'critical'
        elif deviation < -0.02: return 'warning'
        else: return 'normal'

def classify_action(cost_item, deviation):
    """
    将成本项映射到四行动框架
    """
    action_map = {
        'refund_percent': 'Eliminate',
        'storage_charges_percent': 'Eliminate',
        'advertising_fee_percent': 'Reduce',
        'purchase_cost_percent': 'Reduce',
        'first_leg_percent': 'Reduce',
    }
    return action_map.get(cost_item, 'Review')
```

---

## 五、Reference 文档设计

### 5.1 cost_items_reference.md

```markdown
# 成本项说明与占比基准

## 成本项明细

| 字段名 | 中文名 | 计算方式 | 可优化性 | 优化难度 |
|--------|--------|---------|---------|---------|
| purchase_cost_percent | 采购成本占比 | purchase_cost / original_price | 高 | 中 |
| first_leg_percent | 头程运费占比 | first_leg / original_price | 高 | 低 |
| freight_percent | 运费占比 | freight / original_price | 中 | 低 |
| storage_charges_percent | 仓租占比 | storage_charges / original_price | 高 | 低 |
| advertising_fee_percent | 广告费占比 | advertising_fee / original_price | 高 | 中 |
| fee_percent | 平台手续费占比 | fee / original_price | 无 | — |
| tax_fee_percent | 税金占比 | tax_fee / original_price | 无 | — |
| fixed_cost_percent | 固定成本占比 | fixed_cost / original_price | 无 | — |
| refund_percent | 退款占比 | refund / original_price | 高 | 高 |
| compensate_percent | 物料赔偿占比 | compensate / original_price | 高 | 高 |

## 内部基准值（全公司均值，需定期更新）

| 成本项 | 健康线 | 团队均值 | Top 10% 最优 |
|--------|--------|---------|-------------|
| purchase_cost_percent | 25% | 27% | 22% |
| first_leg_percent | 6.5% | 7.5% | 5.0% |
| advertising_fee_percent | 18% | 22% | 15% |
| storage_charges_percent | 4% | 6% | 2% |
| refund_percent | 3.5% | 6% | 2% |
```

### 5.2 four_actions_template.md

```markdown
# 四行动框架模板

## Eliminate（消除）

适用场景：
- 库龄 > 90 天的滞销 SKU
- 退款率 > 10% 的质量问题 SKU
- 毛利率连续 3 月 < 0% 的亏损 SKU

行动清单：
1. 滞销库存清仓或移除
2. 质量问题根因分析与修复
3. 亏损 SKU 下架评估

## Reduce（降低）

适用场景：
- 采购成本高于品类均值
- 广告 ACOS 高于目标
- 头程运费占比异常

行动清单：
1. 供应商谈判或替换
2. 广告关键词优化
3. 货代整合与招标

## Raise（提升）

适用场景：
- 定价低于竞品价格带中位数
- 品牌搜索占比低
- 客单价有提升空间

行动清单：
1. 渐进式提价测试
2. 配件包/套装组合
3. 品牌广告投放

## Create（创造）

适用场景：
- 同质化严重、价格战激烈
- 功能迭代空间大的品类
- 供应链有能力支持新品

行动清单：
1. 微创新功能开发
2. 差异化包装设计
3. 私模产品开发
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写成本结构分类表
- [ ] 编写四行动框架详细说明
- [ ] 编写 Input/Output 格式规范

### Step 2：脚本开发（Day 2）

- [ ] 实现成本结构拆解函数
- [ ] 实现偏离度计算与分级
- [ ] 实现四行动策略自动分类
- [ ] 实现预期效果量化计算
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 2）

- [ ] 整理成本项说明与可优化性评估
- [ ] 编写四行动框架标准模板
- [ ] 整理内部基准值（占位，后续填充真实数据）

### Step 4：测试验证（Day 3）

- [ ] 测试用例 1：高广告费 + 高退款的亏损 ASIN
- [ ] 测试用例 2：低采购成本但高仓租的 ASIN
- [ ] 测试用例 3：团队级成本结构横向对比
- [ ] 测试用例 4：品类级成本结构对比
- [ ] 测试用例 5：所有成本均健康的 ASIN（无建议场景）

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 成本拆解完整性 | 覆盖 8+ 个成本项，无遗漏 |
| 偏离度准确性 | 与手动计算误差 < 0.1% |
| 策略相关性 | 生成的建议与偏离项强相关 |
| 可执行性 | 每条建议包含具体数字和预期效果 |
| 输出格式 | 表格清晰，分级明确（✅/⚠️/🔴） |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 上游触发 | 毛利率低时触发成本结构分析 |
| `advertising-efficiency-optimizer` | 下游调用 | 广告费偏离时深入分析广告 |
| `inventory-health-monitor` | 下游调用 | 仓租高时分析库存结构 |
| `refund-priority-matrix` | 下游调用 | 退款率高时分析退款根因 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
