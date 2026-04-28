# opscli Skills 开发总览规划

> **文档定位**：基于 Claude Skills 开发规范，结合 opscli 项目现有 41 个数据集与亚马逊运营分析体系，规划 9 个 Skills 的开发路线图与设计方案。
>
> **适用范围**：opscli 开发团队、AI Agent 训练团队、数据产品团队
>
> **版本**：v1.0
> **更新日期**：2026-04-28

---

## 一、Skills 开发规范速查

### 1.1 命名规范

| 项目 | 规范 | 示例 |
|------|------|------|
| Skill 目录名 | 小写字母 + 连字符 + 动名词形式 | `asin-health-diagnoser` |
| 脚本文件名 | 小写字母 + 下划线 | `calculate_health_score.py` |
| 参考文件名 | 小写字母 + 下划线 | `dataset_mapping.md` |
| SKILL.md | 必须大写，置于根目录 | `SKILL.md` |

### 1.2 三层结构

```
{skill-name}/
├── SKILL.md              # 📋 SOP（标准作业程序）- 专家的行动剧本
├── scripts/              # 🔧 工具（Tools）- 确定性的可靠函数
│   ├── __init__.py
│   └── {script_name}.py
└── reference/            # 📚 资源（Resources）- 数据集映射、模板
    ├── dataset_mapping.md
    └── examples.md
```

### 1.3 渐进式披露原则

| 层级 | 内容 | 加载时机 | Token 消耗 |
|------|------|----------|-----------|
| **Level 1** | `name` + `description` | 启动时始终加载 | ~100 tokens/skill |
| **Level 2** | SKILL.md 主体内容 | Skill 被触发时 | ~3-5k tokens |
| **Level 3** | scripts + reference | 按需引用时 | 几乎无限制 |

### 1.4 description 编写规范

- 最大 1024 字符
- 必须包含"做什么"和"何时用"
- 使用第三人称
- 包含触发关键词

**好示例**：
```
description: Diagnoses ASIN health by calculating composite scores from gross_profit_percent, convert_percent, ads_acos, refund_percent, inventory_days, and star rating. Use when evaluating product performance, identifying underperforming ASINs, or prioritizing operational interventions.
```

---

## 二、opscli 项目 Skills 开发路线图

### 2.1 技能分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Level 3 — 复杂工作流                          │
│   多步骤、跨数据集、需要决策树和反馈循环的完整分析流程                 │
│   ├─ ops-perspective-builder（运营透视图构建助手）                  │
│   ├─ competitive-intelligence-analyst（竞争情报分析师）             │
│   └─ cross-border-product-selector（跨境选品决策系统）              │
├─────────────────────────────────────────────────────────────────┤
│                      Level 2 — 中等复杂度                          │
│   需要脚本辅助计算，有明确输入输出和验证逻辑的分析任务                 │
│   ├─ product-attribute-analyzer（产品属性3-D标签分析）              │
│   ├─ advertising-efficiency-optimizer（广告效率优化助手）           │
│   └─ inventory-health-monitor（库存健康度监控）                     │
├─────────────────────────────────────────────────────────────────┤
│                      Level 1 — 简单指令型                          │
│   纯 SKILL.md 指令驱动，无需脚本，基于现有数据集快速诊断               │
│   ├─ asin-health-diagnoser（ASIN健康度诊断助手）                    │
│   ├─ profit-structure-analyzer（利润结构拆解分析）                  │
│   └─ refund-priority-matrix（退款优先级矩阵）                       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 开发时间线与依赖关系

```
Week 1-2: Level 1（简单Skills）
    ├─ asin-health-diagnoser ──┐
    ├─ profit-structure-analyzer ──┼──→ 可独立并行开发
    └─ refund-priority-matrix ────┘

Week 3-4: Level 2（中等Skills）
    ├─ product-attribute-analyzer ───┐
    ├─ advertising-efficiency-optimizer ──┼──→ 依赖 Level 1 的验证逻辑
    └─ inventory-health-monitor ─────┘

Week 5-8: Level 3（复杂Skills）
    ├─ ops-perspective-builder ────┐
    ├─ competitive-intelligence-analyst ──┼──→ 依赖 Level 1+2 的组件
    └─ cross-border-product-selector ────┘
```

### 2.3 技能与数据集映射总表

| Skill | 核心数据集 | 辅助数据集 | 依赖外部数据 |
|-------|-----------|-----------|-------------|
| `asin-health-diagnoser` | `order_sale_trend_adv_traffic_inv_set` | `custom_crawler_listing_snapshot` | 无 |
| `profit-structure-analyzer` | `order_sale_trend_adv_traffic_inv_set` | — | 无 |
| `refund-priority-matrix` | `custom_refund_place_set` | `order_sale_trend_adv_traffic_inv_set` | 无 |
| `product-attribute-analyzer` | `query_product_set` + `order_sale_trend_*` | `query_listing_set` | 无 |
| `advertising-efficiency-optimizer` | `advertising_list_set` + `custom_type_advertising_list` | `custom_sp/sd/sb_ads_set` | 无 |
| `inventory-health-monitor` | `custom_inventory_turnover_wk_set` | `order_sale_trend_adv_traffic_inv_set` | 无 |
| `ops-perspective-builder` | 全部核心数据集 | `custom_merge_deals` | 无 |
| `competitive-intelligence-analyst` | `custom_crawler_listing_snapshot` + `custom_brand_search_*` | `order_sale_trend_*` | 爬虫扩展 |
| `cross-border-product-selector` | `custom_crawler_listing_snapshot` + `order_sale_trend_*` | `custom_inventory_turnover_*` | 众筹数据 |

---

## 三、统一设计原则

### 3.1 数据驱动原则

所有 Skills 必须以 opscli 现有 41 个数据集为基础，**不做无数据支撑的建议**。每个诊断结论必须标注数据来源（dataset_name.field_name）。

### 3.2 分层下钻原则

所有分析结果必须支持从 **集团 → 部门 → 大组 → 小组 → ASIN** 的逐层下钻，维度包括：
- `dept_name`（部门）
- `large_team_name`（大组）
- `team_name`（销售小组）
- `dev_team_name`（开发小组）
- `asin` / `parent_asin` / `ed_sku`

### 3.3 预警阈值原则

所有诊断类 Skill 必须内置行业/内部预警阈值：

| 指标 | 健康 | 预警 | 危险 |
|------|------|------|------|
| 毛利率 | > 20% | 10%-20% | < 10% |
| ACOS | < 20% | 20%-30% | > 30% |
| 转化率 | > 10% | 5%-10% | < 5% |
| 退款率 | < 5% | 5%-10% | > 10% |
| 库存周转天数 | < 45 | 45-90 | > 90 |
| 星级 | > 4.3 | 4.0-4.3 | < 4.0 |

### 3.4 行动导向原则

所有分析必须输出 **可执行的运营建议**，而非仅展示数据。建议格式：

```
【问题】{问题描述}
【数据依据】{dataset.field = value}（vs 基准值 = X）
【影响】{对销售额/利润/库存的具体影响量化}
【建议】{具体行动 + 预期效果}
【优先级】P0/P1/P2
```

### 3.5 渐进式复杂度原则

- **Level 1**：纯文本指令，Claude 直接根据 SKILL.md 生成 SQL/分析逻辑
- **Level 2**：确定性计算脚本，避免 Claude 重复生成相同代码
- **Level 3**：工作流模板 + 决策树 + 反馈循环，处理复杂多步骤任务

---

## 五、数据查询接口规范

### 5.1 认证流程

所有数据查询必须通过 opscli 认证体系：

```bash
# 1. 登录授权（一次性）
opscli auth login

# 2. 获取 ops 系统 JWT（脚本中调用）
opscli auth token get -s ops
```

### 5.2 查询构造方式

**推荐方式**：使用 `opscli query build` 构造 payload，然后 `opscli query run` 执行：

```bash
# 构造查询 payload
opscli query build \
  --dataset {dataset_alias} \
  --dimension {dim1} --dimension {dim2} \
  --metric {metric1} --metric {metric2} \
  --output payload.json

# 执行查询
opscli query run --payload payload.json
```

**直接构造 payload 方式**（用于复杂场景）：

```json
{
  "userEmail": "user@example.com",
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "...",
      "alias": "ds_xxx",
      "database": "",
      "permission": ["channel_uuid", "listing_uuid"]
    },
    "select": [...],
    "where": {...},
    "groupBy": [...],
    "limit": 1000,
    "offset": 0
  }
}
```

### 5.3 数据集类型判断

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

### 5.4 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`，如 `f_754ed2fb474f09f9`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

### 5.5 translate 字段映射

跨表关联查询时，可能需要使用 translate 翻译枚举：

| 过滤字段 | translate 枚举值 | 含义 |
|---------|-----------------|------|
| `platform_name` | `PLATFORM_TO_SKU` | 平台 → 公司 SKU |
| `country_name` | `COUNTRY_TO_SKU` | 国家 → 公司 SKU |
| `channel_name` | `CHANNEL_TO_SKU` | 渠道 → 公司 SKU |
| `team_name` | `TEAM_TO_SKU` | 销售小组 → 公司 SKU |
| `ed_sku` | `SKU_TO_ASIN` | 公司 SKU → ASIN |
| `asin` | `ASIN_TO_SKU` | ASIN → 公司 SKU |

### 5.6 公式指标查询规范

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

---

## 六、开发环境建议

### 4.1 目录结构（项目内）

```
/Users/mask/python3/opscli/
├── docs/
│   └── skills/                    # 本规划文档目录
│       ├── README.md              # 本总览文档
│       ├── 01-asin-health-diagnoser.md
│       ├── 02-profit-structure-analyzer.md
│       ├── 03-refund-priority-matrix.md
│       ├── 04-product-attribute-analyzer.md
│       ├── 05-advertising-efficiency-optimizer.md
│       ├── 06-inventory-health-monitor.md
│       ├── 07-ops-perspective-builder.md
│       ├── 08-competitive-intelligence-analyst.md
│       └── 09-cross-border-product-selector.md
├── skills/                        # 实际 Skill 代码目录（待创建）
│   ├── asin-health-diagnoser/
│   ├── profit-structure-analyzer/
│   └── ...
└── ...
```

### 4.2 开发检查清单

每个 Skill 开发完成后，必须通过以下检查：

- [ ] SKILL.md 包含 YAML frontmatter（name + description）
- [ ] description 包含触发关键词（"Use when..."）
- [ ] 所有 SQL/分析逻辑基于现有数据集字段
- [ ] 输出格式包含【问题】【数据依据】【影响】【建议】【优先级】
- [ ] scripts/ 脚本有完善的错误处理和输入验证
- [ ] reference/ 包含数据集字段映射表
- [ ] 已在至少 3 个测试用例上验证

---

## 六、下一步行动

1. **Week 1**：完成 Level 1 三个 Skills 的 SKILL.md 开发与测试
2. **Week 2**：完成 Level 1 脚本优化与 reference 文档补充
3. **Week 3**：启动 Level 2 开发，同时收集 Level 1 的业务反馈
4. **Week 4**：完成 Level 2 开发与测试
5. **Week 5-6**：启动 Level 3 设计，完成 `ops-perspective-builder`
6. **Week 7-8**：完成剩余两个 Level 3 Skills

---

*本文档为 opscli Skills 开发的总览规划，各 Skill 的详细设计请查看同目录下的独立设计文档。*
