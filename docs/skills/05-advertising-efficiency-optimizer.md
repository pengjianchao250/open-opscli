# Skill 开发设计文档：advertising-efficiency-optimizer

> **Skill 名称**：`advertising-efficiency-optimizer`
> **复杂度等级**：Level 2 — 中等（需要脚本辅助计算）
> **预计开发时间**：4-5 天
> **业务价值**：高（广告费是最大可变成本之一）

---

## 一、Skill 定位

### 1.1 一句话描述

从广告活动、广告组、广告类型（SP/SD/SB/SBV）多维度分析广告效率，识别高 ACOS 问题点，输出分词/分活动/分时段的优化建议。

### 1.2 解决什么痛点

- 只知道整体 ACOS 高，不知道具体是哪个活动/词在烧钱
- SP/SD/SB 预算分配缺乏数据依据
- 广告优化凭经验，缺少系统性诊断框架

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| ACOS 诊断 | "分析 ASIN B08XXXXXX 的广告效率问题" |
| 类型对比 | "对比 SP 和 SB 广告的表现差异" |
| 活动优化 | "找出 ACOS > 30% 的广告活动并给出优化建议" |
| 预算分配 | "帮我优化下周的广告预算分配" |

---

## 二、文件结构设计

```
opscli/skills/advertising-efficiency-optimizer/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   ├── analyze_ads_efficiency.py         # 广告效率分析主脚本
│   ├── calculate_roas_acos.py            # ROAS/ACOS 计算
│   └── ads_budget_allocator.py           # 广告预算分配优化
└── reference/
    ├── ads_metrics_guide.md              # 广告指标说明与基准
    └── campaign_optimization_playbook.md # 活动优化操作手册
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: advertising-efficiency-optimizer
description: Analyzes advertising efficiency across campaign, ad group, and ad type (SP/SD/SB/SBV) dimensions. Identifies high ACOS problems and generates word-level, campaign-level, and time-segment optimization recommendations. Use when ACOS is above target, reallocating ad budgets, or comparing ad type performance.
---
```

### 3.2 主体内容大纲

```markdown
# Advertising Efficiency Optimizer

Diagnoses advertising performance issues and generates optimization strategies across multiple dimensions.

## Capabilities

- Campaign-level ACOS diagnosis
- Ad type comparison (SP vs SD vs SB vs SBV)
- Keyword performance analysis
- Budget reallocation recommendations
- Time-segment effectiveness analysis
- ROAS and CPC trend tracking

## Core Metrics

| Metric | Formula | Healthy | Warning | Critical |
|--------|---------|---------|---------|----------|
| ACOS | ads_cost / ads_sales | < 20% | 20-30% | > 30% |
| ROAS | ads_sales / ads_cost | > 5.0 | 3.3-5.0 | < 3.3 |
| CPC | ads_cost / clicks | < $1.5 | $1.5-2.5 | > $2.5 |
| CTR | clicks / impressions | > 0.3% | 0.2-0.3% | < 0.2% |
| Conversion Rate | orders / clicks | > 10% | 5-10% | < 5% |

## Ad Type Comparison Framework

### Sponsored Products (SP)
- **Focus**: Keyword targeting, product targeting
- **Key Metrics**: ACOS, CPC, keyword ranking lift
- **Optimization**: Negative keywords, bid adjustment, match type

### Sponsored Brands (SB)
- **Focus**: Brand awareness, store traffic
- **Key Metrics**: Impression share, new-to-brand rate
- **Optimization**: Creative A/B test, headline refinement

### Sponsored Display (SD)
- **Focus**: Retargeting, audience targeting
- **Key Metrics**: Viewable impressions, remarketing CTR
- **Optimization**: Audience segmentation, bid by placement

### SB Video (SBV)
- **Focus**: Video engagement, brand storytelling
- **Key Metrics**: Video view rate, engagement rate
- **Optimization**: Video creative, targeting refinement

## Analysis Dimensions

### 1. Campaign-Level Diagnosis

使用 `advertising_list_set`（`ds_0759e20F0DrG`，子查询类型）：

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
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ds_0759e20F0DrG.ad_group_name", "alias": "f_ad_group" },
      { "expr": "ds_0759e20F0DrG.ads_type", "alias": "f_ad_type" },
      { "expr": "ds_0759e20F0DrG.advertising_fee", "alias": "f_cost", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_sales_cny", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_clicks", "alias": "f_clicks", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_impressions", "alias": "f_impressions", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_conversions", "alias": "f_conversions", "aggregation": "SUM" }
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
    "groupBy": ["f_campaign", "f_ad_group", "f_ad_type"],
    "limit": 1000
  }
}
```

### 2. Ad Type Portfolio Analysis

使用 `custom_sp_sd_sb_ads_set`（非子查询类型）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "custom_sp_sd_sb_ads_set",
      "alias": "ds_ad_type",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_ad_type.ad_type", "alias": "f_ad_type" },
      { "expr": "ds_ad_type.ads_sp", "alias": "f_sp_spend", "aggregation": "SUM" },
      { "expr": "ds_ad_type.ads_sd", "alias": "f_sd_spend", "aggregation": "SUM" },
      { "expr": "ds_ad_type.ads_sb", "alias": "f_sb_spend", "aggregation": "SUM" },
      { "expr": "ds_ad_type.ads_sbv", "alias": "f_sbv_spend", "aggregation": "SUM" },
      { "expr": "ds_ad_type.ads_sales_cny", "alias": "f_total_sales", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_ad_type.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ad_type"],
    "limit": 1000
  }
}
```

### 3. Budget Reallocation Logic

When ACOS > 30% for a campaign:
1. Reduce bid by 10-20%
2. Add negative keywords for high-spend/low-conversion terms
3. Pause match types with ACOS > 50%
4. Reallocate budget to campaigns with ROAS > 5.0

## Input Format

- ASIN level: "B08XXXXXX"
- Campaign level: "campaign_name = 'Water-Bottle-SP-Exact'"
- Ad type: "analyze SP vs SB"
- Date range: "last 30 days"

## Output Format

```
【分析对象】ASIN B08XXXXXX（Water Bottle）
【分析周期】2025-01-01 ~ 2025-01-31
【总广告费】$8,500 | 【总广告销售额】$35,000 | 【综合 ACOS】24.3%

广告类型对比：
┌──────────┬─────────┬───────────┬───────┬────────┐
│ Ad Type  │ Spend   │ Sales     │ ACOS  │ ROAS   │
├──────────┼─────────┼───────────┼───────┼────────┤
│ SP       │ $5,200  │ $22,000   │ 23.6% │ 4.23   │
│ SB       │ $2,100  │ $10,000   │ 21.0% │ 4.76   │
│ SD       │ $1,000  │ $2,500    │ 40.0% │ 2.50 🔴│
│ SBV      │ $200    │ $500      │ 40.0% │ 2.50 🔴│
└──────────┴─────────┴───────────┴───────┴────────┘

问题诊断：
🔴 SD 广告 ACOS 40%（目标 < 25%）
   └─ 原因：受众定位过宽，展示量高但转化低
   └─ 建议：缩小受众范围，暂停低转化受众组

🔴 SBV 广告 ACOS 40%
   └─ 原因：视频完播率仅 15%（均值 35%）
   └─ 建议：前 3 秒加入产品核心卖点，缩短视频至 15 秒

优化建议（按预期 ROI 排序）：
1. [P0] 暂停 SD 受众组 "Broad-Interest"（月节省 $400）
2. [P0] 将 SBV 视频前 3 秒改为 "Keep Cold 24h"（预计完播率提升至 30%）
3. [P1] SP 大词 "water bottle" 降低竞价 15%（ACOS 从 28% 降至 23%）
4. [P1] 将节省的 $600 预算转移至 SP 长尾词组（预期 ROAS 6.0+）

预期效果：
→ 综合 ACOS 从 24.3% 降至 20.5%
→ 月广告利润增加 $1,200
```

## Scripts

- `analyze_ads_efficiency.py`: Main analysis script for campaign diagnosis
- `calculate_roas_acos.py`: Quick ROAS/ACOS calculator
- `ads_budget_allocator.py`: Budget reallocation optimizer

## Best Practices

1. Always analyze at campaign + ad group level, not just account level
2. Compare ACOS against category benchmarks, not just absolute targets
3. For new campaigns (< 14 days), use relaxed thresholds
4. Consider organic sales lift when evaluating brand campaigns
```

---

## 四、脚本设计

### 4.1 analyze_ads_efficiency.py

**功能**：主分析脚本，接收广告数据，输出诊断报告

**输入**：
```json
{
  "target": {"type": "asin", "value": "B08XXXXXX"},
  "period": {"start": "2025-01-01", "end": "2025-01-31"},
  "ad_data": {
    "by_campaign": [...],
    "by_ad_type": [...],
    "by_keyword": [...]
  },
  "benchmarks": {
    "acos_target": 0.20,
    "roas_target": 5.0,
    "cpc_target": 1.5
  },
  "query_payload": {
    "dataset": "ds_0759e20F0DrG",
    "dimensions": ["campaign_name", "ad_group_name", "ads_type"],
    "metrics": ["advertising_fee", "ads_sales_cny", "ads_clicks", "ads_impressions", "ads_conversions"],
    "filters": {
      "asin": "B08XXXXXX",
      "date_range": ["2025-01-01", "2025-01-31"]
    }
  }
}
```

**核心逻辑**：
```python
def diagnose_campaign(campaign, benchmarks):
    issues = []
    
    acos = campaign['cost'] / campaign['sales'] if campaign['sales'] > 0 else 1.0
    roas = campaign['sales'] / campaign['cost'] if campaign['cost'] > 0 else 0
    
    if acos > benchmarks['acos_target'] * 1.5:
        issues.append({'severity': 'critical', 'type': 'high_acos', 'value': acos})
    elif acos > benchmarks['acos_target']:
        issues.append({'severity': 'warning', 'type': 'high_acos', 'value': acos})
    
    if roas < benchmarks['roas_target'] * 0.5:
        issues.append({'severity': 'critical', 'type': 'low_roas', 'value': roas})
    
    return issues

def generate_reallocation_plan(campaigns, total_budget):
    """
    基于 ROAS 的预算重新分配
    """
    # 暂停 Critical 活动
    # 增加 High ROAS 活动预算
    # 保持 Healthy 活动预算
    pass
```

### 4.2 calculate_roas_acos.py

**功能**：快速计算器，支持多种输入格式

### 4.3 ads_budget_allocator.py

**功能**：预算分配优化器

**算法**：
```python
def optimize_budget(campaigns, total_budget):
    """
    目标：在总预算约束下最大化总广告销售额
    
    策略：
    1. 按 ROAS 排序活动
    2. 优先满足高 ROAS 活动的预算需求
    3. 削减低 ROAS 活动预算至最低必要水平
    """
    sorted_campaigns = sorted(campaigns, key=lambda x: x['roas'], reverse=True)
    
    allocation = {}
    remaining = total_budget
    
    for camp in sorted_campaigns:
        if camp['roas'] > 4.0:
            # 高 ROAS：给予全额预算
            allocation[camp['name']] = camp['current_spend'] * 1.2
        elif camp['roas'] > 2.5:
            # 中等 ROAS：保持现状
            allocation[camp['name']] = camp['current_spend']
        else:
            # 低 ROAS：削减 50%
            allocation[camp['name']] = camp['current_spend'] * 0.5
    
    return allocation
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

本 Skill 使用两个核心数据集：
- **主数据集**：`advertising_list_set`（`ds_0759e20F0DrG`，**子查询类型**，`inner_where_enabled=true`）
- **辅助数据集**：`custom_sp/sd/sb_ads_set`（非子查询类型）

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_0759e20F0DrG \
  --dimension campaign_name --dimension ad_group_name --dimension ads_type \
  --metric advertising_fee --metric ads_sales_cny --metric ads_clicks --metric ads_impressions \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

广告活动级诊断（`ds_0759e20F0DrG`，子查询类型）：

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
      { "expr": "ds_0759e20F0DrG.campaign_name", "alias": "f_campaign" },
      { "expr": "ds_0759e20F0DrG.ad_group_name", "alias": "f_ad_group" },
      { "expr": "ds_0759e20F0DrG.ads_type", "alias": "f_ad_type" },
      { "expr": "ds_0759e20F0DrG.advertising_fee", "alias": "f_cost", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_sales_cny", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_clicks", "alias": "f_clicks", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_impressions", "alias": "f_impressions", "aggregation": "SUM" },
      { "expr": "ds_0759e20F0DrG.ads_conversions", "alias": "f_conversions", "aggregation": "SUM" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [
        { "field": "ds_0759e20F0DrG.campaign_name", "operator": "eq", "value": "Water-Bottle-SP-Exact" }
      ]}
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_0759e20F0DrG.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_campaign", "f_ad_group", "f_ad_type"],
    "limit": 1000
  }
}
```

#### 数据集类型判断

**关键**：`ds_0759e20F0DrG`（`advertising_list_set`）为**子查询类型**（`inner_where_enabled=true`）：

```python
# 判断方法：检查 from.table 是否包含内层占位符
is_inner_where = '{where_sub_placeholder_' in table_sql or '{and_sub_placeholder_' in table_sql

# 子查询类型（inner_where_enabled=true）
# - 维度过滤条件放 innerWhere[1]
# - 日期条件放 where
```

#### 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

#### 公式指标查询规范

公式指标必须使用完整表达式格式：

```json
// 正确
{
  "expr": "ROUND(SUM(ads_sales_cny)/SUM(advertising_fee), 4)",
  "alias": "f_roas"
}

// 错误：额外传 aggregation 会导致二次聚合
{
  "expr": "ads_acos",
  "alias": "f_xxx",
  "aggregation": "AVG"
}
```

---

## 五、Reference 文档设计

### 5.1 ads_metrics_guide.md

```markdown
# 广告指标说明与基准

## 核心指标定义

| 指标 | 英文 | 公式 | 说明 |
|------|------|------|------|
| ACOS | Advertising Cost of Sales | 广告费 / 广告销售额 | 越低越好 |
| ROAS | Return on Ad Spend | 广告销售额 / 广告费 | 越高越好 |
| CPC | Cost Per Click | 广告费 / 点击量 | 越低越好 |
| CTR | Click-Through Rate | 点击量 / 曝光量 | 越高越好 |
| CVR | Conversion Rate | 广告订单 / 点击量 | 越高越好 |
| Impressions | 曝光量 | — | 展示次数 |

## 品类基准值

| 品类 | ACOS 健康线 | ROAS 健康线 | CPC 均值 |
|------|------------|------------|---------|
| Electronics | 25% | 4.0 | $1.8 |
| Home & Kitchen | 18% | 5.5 | $1.2 |
| Clothing | 22% | 4.5 | $1.5 |
| Beauty | 15% | 6.5 | $1.0 |
| Sports | 20% | 5.0 | $1.3 |

## 广告类型基准

| 类型 | ACOS 健康线 | 特点 |
|------|------------|------|
| SP-Exact | 15-20% | 最精准，通常最低 ACOS |
| SP-Phrase | 20-25% | 中等精准 |
| SP-Broad | 25-35% | 用于发现新词 |
| SB | 20-30% | 品牌词通常更低 |
| SD | 25-40% | 再营销通常更低 |
| SBV | 25-35% | 视频完播率影响大 |
```

### 5.2 campaign_optimization_playbook.md

```markdown
# 活动优化操作手册

## ACOS 过高的诊断流程

1. **检查关键词级别**
   - 找出花费 > $100 但 0 订单的词
   - 加入 negative keywords
   
2. **检查匹配类型**
   - Broad 匹配 ACOS 通常比 Exact 高 5-10%
   - 如果 Broad ACOS > 40%，考虑降低 bid 或暂停

3. **检查时段效果**
   - 分析小时级数据
   - 某些时段 CPC 高但转化低
   - 使用 dayparting 调整

4. **检查竞品动态**
   - 竞品是否在大促/降价
   - 是否需要临时调整策略

## 预算分配原则

| 活动状态 | ACOS | 预算操作 |
|---------|------|---------|
| 优秀 | < 15% | 增加 20% |
| 良好 | 15-20% | 增加 10% |
| 一般 | 20-25% | 维持 |
| 预警 | 25-30% | 减少 10% |
| 危险 | > 30% | 减少 30% 或暂停 |
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写广告类型对比框架
- [ ] 编写核心指标和阈值
- [ ] 编写 SQL 查询模板

### Step 2：脚本开发（Day 2-3）

- [ ] 实现 `analyze_ads_efficiency.py`
- [ ] 实现 `calculate_roas_acos.py`
- [ ] 实现 `ads_budget_allocator.py`
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 3）

- [ ] 编写广告指标说明
- [ ] 编写品类基准值表
- [ ] 编写活动优化操作手册

### Step 4：测试验证（Day 4-5）

- [ ] 测试用例 1：高 ACOS 活动诊断
- [ ] 测试用例 2：SP vs SB vs SD 对比
- [ ] 测试用例 3：预算重新分配
- [ ] 测试用例 4：关键词级别分析
- [ ] 测试用例 5：大规模活动批量分析

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 诊断准确性 | 能准确定位高 ACOS 的根因（词/活动/类型） |
| 建议可执行性 | 每条建议包含具体操作和预期效果 |
| 预算分配 | 重新分配后预期总 ROAS 提升 > 10% |
| 多类型支持 | 支持 SP/SD/SB/SBV 四种类型对比 |
| 输出格式 | 表格清晰，分级明确 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 上游触发 | ACOS 预警时触发深度广告分析 |
| `profit-structure-analyzer` | 上游触发 | 广告费占比高时触发优化 |
| `ops-perspective-builder` | 数据供给 | 为广告透视图提供分析能力 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
