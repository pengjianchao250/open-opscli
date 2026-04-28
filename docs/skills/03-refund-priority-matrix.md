# Skill 开发设计文档：refund-priority-matrix

> **Skill 名称**：`refund-priority-matrix`
> **复杂度等级**：Level 1 — 简单（纯指令型）
> **预计开发时间**：2-3 天
> **业务价值**：高（直接关联利润优化）

---

## 一、Skill 定位

### 1.1 一句话描述

分析退款数据和运营建议，将问题按 Critical / Important / Nice-to-have 三级分类，输出按 ROI 排序的改进清单。

### 1.2 解决什么痛点

- 退款原因分散，不知道哪些问题最致命
- 运营建议多但缺乏优先级排序
- 无法量化修复某个问题后的预期收益

### 1.3 触发场景

| 场景 | 触发语句示例 |
|------|-------------|
| 退款分析 | "分析 ASIN B08XXXXXX 的退款原因和优先级" |
| 批量诊断 | "找出退款率最高的 10 个 ASIN 并排序问题优先级" |
| 运营建议 | "帮我看看运营建议提醒里哪些问题最紧急" |
| 月度复盘 | "生成本月退款问题优先级矩阵报告" |

---

## 二、文件结构设计

```
opscli/skills/refund-priority-matrix/
├── SKILL.md                              # 核心指令文件
├── scripts/
│   └── calculate_priority_matrix.py      # 优先级矩阵计算脚本
└── reference/
    ├── refund_reasons_catalog.md         # 退款原因分类目录
    └── severity_scoring_guide.md         # 严重程度评分指南
```

---

## 三、SKILL.md 内容设计

### 3.1 YAML Frontmatter

```yaml
---
name: refund-priority-matrix
description: Analyzes refund data and operational suggestions to classify issues into Critical/Important/Nice-to-have priority levels. Quantifies expected impact and ROI for each fix. Use when processing high refund rates, reviewing operational alerts, or prioritizing product improvement tasks.
---
```

### 3.2 主体内容大纲

```markdown
# Refund Priority Matrix

Classifies product issues by severity and frequency, outputting a prioritized action plan with expected ROI.

## Capabilities

- Single ASIN refund issue analysis
- Batch ASIN priority ranking
- Operational suggestion severity mapping
- Expected impact quantification
- Cross-dataset validation (refund + operational suggestions)

## Priority Classification

### 🔴 Critical
- **Criteria**: Severity = High AND (Refund Rate > 10% OR Frequency > 20%)
- **Action**: Fix within 7 days
- **Examples**: Leaking, wrong size, broken on arrival

### 🟡 Important
- **Criteria**: Severity = Medium AND (Refund Rate 5-10% OR Frequency 10-20%)
- **Action**: Fix within 30 days
- **Examples**: Poor insulation, difficult cleaning, color mismatch

### 🟢 Nice-to-have
- **Criteria**: Severity = Low AND (Refund Rate < 5% OR Frequency < 10%)
- **Action**: Fix when resources allow
- **Examples**: Limited colors, simple packaging, minor scratches

## Data Sources

### Primary: custom_refund_place_set
- `refund_reason`: Refund reason text
- `overseas_origin_suffix`: Product origin
- `order_status`: Order status
- `refund_amount`: Refund amount

### Secondary: custom_operation_suggest_suggestions_set
- `issue_type`: Issue category
- `severity`: Severity level
- `operation_stage`: Operation stage
- `suggestion`: Improvement suggestion

### Validation: order_sale_trend_adv_traffic_inv_set
- `refund_percent`: Overall refund rate
- `gross_profit`: Profit impact

## Input Format

- ASIN level: "B08XXXXXX"
- Category level: "category = 'Water Bottles'"
- Date range: "last 30 days"
- Source filter: "from refunds" or "from operational suggestions"

## Output Format

```
【分析对象】ASIN B08XXXXXX（保温杯）
【分析周期】2025-01-01 ~ 2025-01-31
【总退款率】18.5%（🔴 危险，高于品类均值 8.2%）

优先级矩阵：
┌─────────────────────┬──────────┬──────────┬──────────────────────────────┐
│ Issue               │ Severity │ Frequency│ 内部数据验证                  │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🔴 Critical         │          │          │                              │
│ 漏水（leaking）     │ 高       │ 23%      │ refund_reason 中占比 23%     │
│                     │          │          │ 预估损失：$1,200/月           │
│ 容量虚标            │ 高       │ 15%      │ "尺寸不符" 占退款 31%         │
│                     │          │          │ 预估损失：$800/月             │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🟡 Important        │          │          │                              │
│ 保温时间短          │ 中       │ 19%      │ 星级 3.8（品类均值 4.3）      │
│                     │          │          │ 预估提升：rating +0.3         │
│ 杯盖难清洗          │ 中       │ 12%      │ 无直接退款关联                │
│                     │          │          │ 预估提升：reviews  sentiment  │
├─────────────────────┼──────────┼──────────┼──────────────────────────────┤
│ 🟢 Nice-to-have     │          │          │                              │
│ 颜色选择少          │ 低       │ 8%       │ 无显著销售影响                │
│ 包装简陋            │ 低       │ 5%       │ 无退款关联                    │
└─────────────────────┴──────────┴──────────┴──────────────────────────────┘

行动建议（按 ROI 排序）：
1. 【Critical|P0】排查漏水原因（密封圈/焊接工艺）
   → 预计修复后退款率从 18.5% 降至 10%
   → 预计月节省损失 $1,200
   → 投入：工程师 3 天 | 产出：$1,200/月

2. 【Critical|P0】修正容量标注，增加实物对比图
   → 预计降低 "尺寸不符" 退款 50%
   → 预计月节省损失 $400
   → 投入：设计 1 天 | 产出：$400/月

3. 【Important|P1】升级保温材料或调整用户预期
   → 预计提升 rating 0.3-0.5 星
   → 预计转化率提升 1-2%
   → 投入：采购谈判 1 周 | 产出：长期收益
```

## Scripts

- `calculate_priority_matrix.py`: Classifies issues and calculates priority scores

## Best Practices

1. Always cross-validate refund reasons with operational suggestions
2. Quantify expected impact in dollar terms when gross_profit data is available
3. Consider fix cost vs. expected savings for ROI ranking
4. For "origin" related issues, flag to dev_team_name for supplier discussion
```

---

## 四、脚本设计：calculate_priority_matrix.py

### 4.1 功能说明

接收退款原因数据和运营建议数据，计算问题频率、严重程度，生成分级矩阵和排序建议。

### 4.2 输入格式

```json
{
  "target": {
    "type": "asin",
    "value": "B08XXXXXX"
  },
  "period": {
    "start": "2025-01-01",
    "end": "2025-01-31"
  },
  "refund_data": [
    {"reason": "leaking", "count": 23, "amount": 1200},
    {"reason": "size_mismatch", "count": 15, "amount": 800},
    {"reason": "poor_insulation", "count": 19, "amount": 600}
  ],
  "operation_suggestions": [
    {"issue_type": "quality", "severity": "high", "suggestion": "Fix seal"},
    {"issue_type": "design", "severity": "medium", "suggestion": "Add size chart"}
  ],
  "financial_context": {
    "refund_percent": 0.185,
    "category_avg_refund": 0.082,
    "monthly_sales": 15000,
    "gross_profit_percent": 0.15
  },
  "query_payload": {
    "dataset": "ds_y5EoxUyLf6Aq",
    "dimensions": ["asin", "refund_reason", "overseas_origin_suffix"],
    "metrics": ["refund_amount"],
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
  "overall_refund_percent": 0.185,
  "category_benchmark": 0.082,
  "priority_matrix": {
    "critical": [
      {
        "issue": "leaking",
        "frequency": 0.23,
        "severity": "high",
        "monthly_loss": 1200,
        "recommended_action": "Fix seal design",
        "expected_saving": 800,
        "roi_score": 95
      }
    ],
    "important": [...],
    "nice_to_have": [...]
  },
  "sorted_actions": [
    {"rank": 1, "action": "Fix seal", "roi_score": 95, "priority": "P0"}
  ],
  "query_result": {
    "dataset": "ds_y5EoxUyLf6Aq",
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

本 Skill 使用两个核心数据集：
- **主数据集**：`custom_refund_place_set`（`ds_y5EoxUyLf6Aq`，非子查询类型）
- **辅助数据集**：`order_sale_trend_adv_traffic_inv_set`（`ds_d35ac6f3910c`，非子查询类型）
- **运营建议数据集**：`custom_operation_suggest_suggestions_set`（`ds_zY0BAi0Txsga`，非子查询类型）

```bash
# 构造查询 payload
opscli query build \
  --dataset ds_y5EoxUyLf6Aq \
  --dimension asin --dimension refund_reason \
  --metric refund_amount --metric order_status \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**：

退款数据查询（`ds_y5EoxUyLf6Aq`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_refund.place_set ...)",
      "alias": "ds_y5EoxUyLf6Aq",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_y5EoxUyLf6Aq.asin", "alias": "f_asin" },
      { "expr": "ds_y5EoxUyLf6Aq.refund_reason", "alias": "f_reason" },
      { "expr": "ds_y5EoxUyLf6Aq.refund_amount", "alias": "f_amount", "aggregation": "SUM" },
      { "expr": "COUNT(*)", "alias": "f_count" },
      { "expr": "ds_y5EoxUyLf6Aq.overseas_origin_suffix", "alias": "f_origin" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_y5EoxUyLf6Aq.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_y5EoxUyLf6Aq.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_reason", "f_origin"],
    "limit": 1000
  }
}
```

整体退款率验证（`ds_d35ac6f3910c`）：

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
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.gross_profit", "alias": "f_profit", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin"],
    "limit": 1000
  }
}
```

运营建议查询（`ds_zY0BAi0Txsga`）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "(SELECT ... FROM custom_operation.suggest_suggestions_set ...)",
      "alias": "ds_zY0BAi0Txsga",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [
      { "expr": "ds_zY0BAi0Txsga.asin", "alias": "f_asin" },
      { "expr": "ds_zY0BAi0Txsga.issue_type", "alias": "f_issue_type" },
      { "expr": "ds_zY0BAi0Txsga.severity", "alias": "f_severity" },
      { "expr": "ds_zY0BAi0Txsga.suggestion", "alias": "f_suggestion" },
      { "expr": "ds_zY0BAi0Txsga.operation_stage", "alias": "f_stage" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_zY0BAi0Txsga.asin", "operator": "eq", "value": "B08XXXXXX" }
      ]
    },
    "limit": 1000
  }
}
```

#### 数据集类型判断

`ds_y5EoxUyLf6Aq`、`ds_d35ac6f3910c`、`ds_zY0BAi0Txsga` 均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

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
  "expr": "refund_percent",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

### 4.5 核心逻辑

```python
def classify_priority(severity, frequency, refund_rate):
    """
    三级分类逻辑
    """
    if severity == 'high' and (frequency > 0.20 or refund_rate > 0.10):
        return 'critical'
    elif severity == 'medium' and (frequency > 0.10 or refund_rate > 0.05):
        return 'important'
    else:
        return 'nice_to_have'

def calculate_roi(expected_saving, fix_cost_estimate):
    """
    简单 ROI 评分（0-100）
    """
    if fix_cost_estimate == 0:
        return 100
    monthly_roi = (expected_saving * 12) / fix_cost_estimate
    return min(100, monthly_roi * 10)
```

---

## 五、Reference 文档设计

### 5.1 refund_reasons_catalog.md

```markdown
# 退款原因分类目录

## 质量问题（Quality）

| 关键词 | 严重程度 | 常见根因 | 修复方向 |
|--------|---------|---------|---------|
| leaking | Critical | 密封圈、焊接 |  redesign seal |
| broken | Critical | 运输/材质 | 加固包装/换材料 |
| not working | Critical | 电路/组装 | 质检流程 |
| poor quality | Important | 材料/工艺 | 供应商谈判 |
| scratch | Nice-to-have | 运输/质检 | 包装改进 |

## 尺寸问题（Size）

| 关键词 | 严重程度 | 常见根因 | 修复方向 |
|--------|---------|---------|---------|
| too small | Critical | 标注不清 | 加对比图/改标注 |
| too big | Important | 标注不清 | 加对比图/改标注 |
| size mismatch | Critical | 尺码表错误 | 修正尺码表 |

## 描述不符（Description）

| 关键词 | 严重程度 | 常见根因 | 修复方向 |
|--------|---------|---------|---------|
| not as described | Important | 图片/文案过度美化 | 实拍图/保守文案 |
| color mismatch | Important | 屏幕色差 | 色卡标注 |
| missing parts | Critical | 质检/包装 | 包装清单核对 |

## 物流问题（Delivery）

| 关键词 | 严重程度 | 常见根因 | 修复方向 |
|--------|---------|---------|---------|
| late delivery | Important | 物流时效 | 换物流商 |
| damaged box | Nice-to-have | 物流暴力 | 加固包装 |
```

### 5.2 severity_scoring_guide.md

```markdown
# 严重程度评分指南

## 自动评分规则

| 条件 | 基础分 | 加分项 |
|------|--------|--------|
| 退款率 > 品类均值 2 倍 | +30 | 每多 1 倍 +10 |
| 频率 > 20% | +25 | 每多 5% +5 |
| 涉及安全问题 | +50 | — |
| 影响星级 > 0.3 | +20 | — |

## 总分映射

| 总分 | 等级 | 处理时限 |
|------|------|---------|
| 80-100 | Critical | 7 天 |
| 50-79 | Important | 30 天 |
| 0-49 | Nice-to-have | 按需 |
```

---

## 六、开发步骤

### Step 1：SKILL.md 编写（Day 1）

- [ ] 编写 YAML frontmatter
- [ ] 编写三级分类标准
- [ ] 编写 Input/Output 格式
- [ ] 编写与运营建议的关联逻辑

### Step 2：脚本开发（Day 2）

- [ ] 实现退款原因频率统计
- [ ] 实现与运营建议的交叉验证
- [ ] 实现三级优先级分类
- [ ] 实现 ROI 排序逻辑
- [ ] 编写单元测试

### Step 3：Reference 文档（Day 2）

- [ ] 整理退款原因分类目录
- [ ] 编写严重程度评分规则
- [ ] 编写修复方向参考表

### Step 4：测试验证（Day 3）

- [ ] 测试用例 1：高退款率 + 多原因混合
- [ ] 测试用例 2：单一 Critical 原因
- [ ] 测试用例 3：所有问题均为 Nice-to-have
- [ ] 测试用例 4：运营建议与退款数据不一致时的处理
- [ ] 测试用例 5：大规模批量分析（50+ ASIN）

---

## 七、验收标准

| 检查项 | 标准 |
|--------|------|
| 分类准确性 | Critical 问题不漏报，Nice-to-have 不误报 |
| ROI 排序 | 高 ROI 建议排在前列 |
| 数据交叉 | 退款数据与运营建议能相互验证 |
| 输出格式 | 矩阵清晰，行动建议具体可执行 |
| 扩展性 | 支持新增退款原因和分类规则 |

---

## 八、与其他 Skill 的关系

| 关联 Skill | 关系类型 | 说明 |
|-----------|---------|------|
| `asin-health-diagnoser` | 上游触发 | 退款率高时触发优先级分析 |
| `profit-structure-analyzer` | 下游调用 | Critical 问题定位到成本结构 |
| `product-attribute-analyzer` | 平行协作 | 尺寸/颜色问题关联属性分析 |

---

*文档版本：v1.0 | 设计阶段 | 待开发*
