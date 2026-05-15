---
name: ops-query-wizard
description: 引导式数据查询向导。当业务用户需要查数据但不知道如何构造查询、想一步一步取数、或说"帮我引导查询/查询向导/引导我取数"时使用本 Skill。通过十步对话逐步构建 query_simple 参数，完成后自动进入数据分析框架，形成取数→分析→反馈完整闭环。
version: v0.1.0
---

# ops-query-wizard — 引导式数据查询向导

帮助业务用户（新手和熟手）通过十步对话逐步构建合规的查询参数，取数完成后进入数据分析框架。

---

## 触发条件

满足以下任一关键词即激活本 Skill：

- 引导查询、查询向导、guided query
- 帮我取数、我要查数据、一步一步查
- 不知道怎么查、教我查、引导我
- 帮我分析数据（需要取数时）

---

## 运行模式判断

> **默认原则：CLI 优先。** CLI 和 MCP 均可用时，使用 CLI。

1. 用户明确指定 → 遵循用户指定
2. CLI 和 MCP 都可用 → **使用 CLI**
3. 仅 MCP 可用 → 使用 MCP
4. CLI 首次调用失败 → 切换到 MCP，本次引导全程保持，不再切换
5. 两者均不可用 → 引导用户安装 `aukeys-opscli`

---

## 十条铁律

| # | 铁律 | 核心约束 |
|---|------|---------|
| 1 | 步骤串行 | 十步必须按顺序进行，禁止跳步或合并步骤 |
| 2 | 每步只问一个问题 | 禁止在同一步骤同时提多个问题 |
| 3 | 歧义必须澄清 | 字段/数据集歧义强制按 `rules.md` 规则处理，禁止猜测 |
| 4 | 简化接口优先 | 所有查询优先使用 `query_simple`，禁止直接手写完整 payload |
| 5 | 公式字段禁止聚合 | 含 `summary_expression` 的字段不传 `aggregation`，传 `expr` |
| 6 | dataComparison 必带主周期 | 对比查询的 `filters` 必须包含当期日期范围 |
| 7 | 字段存在性必须校验 | 构造参数前先通过 `query_metadata` 确认字段真实存在 |
| 8 | 输出列名不可改写 | 必须使用数据集原始 `verbose_name`，禁止意译 |
| 9 | 分析方向由数据驱动 | 分析方向必须基于实际返回数据提出，禁止凭空建议 |
| 10 | 查询闭环强制反馈 | 每次执行查询后必须通过 `ops-feedback` Skill 提交 `query_result` 反馈 |

---

## 文档阅读顺序（强制）

进入本 Skill 后，**必须按以下顺序阅读文档**：

```
1. ops-dataset-query/references/rules.md     ← 歧义澄清规则（Step 1 前必须阅读）
2. references/step-guide.md                  ← 十步引导规则（开始引导前必须阅读）
3. references/analysis-guide.md              ← 查询执行后，进入分析时阅读
```

---

## 标准工作流

```
[Step 1]  需求目标概述          → 提取需求上下文，建立推荐基础
[Step 2]  选择数据集            → catalog 意图匹配 + 全量列举
[Step 3]  选择维度字段          → AI 推荐 + 全量列举维度字段
[Step 4]  选择指标字段          → AI 推荐 + 全量列举指标字段（标注公式字段）
[Step 5]  筛选条件              → 时间范围（必问）+ 其他维度过滤
[Step 6]  排序字段              → AI 推荐 + 用户确认
[Step 7]  获取条数（limit）     → AI 推荐 + 用户确认
[Step 8]  是否分页              → 按需询问，单页满足时跳过
[Step 9]  是否需要对比数据      → dataComparison 配置
[Step 10] 执行查询              → 参数摘要确认 → query_simple → 展示结果
           └── 进入 analysis-guide.md 分析框架
               └── 输出（对话 / Excel / 两者）
               └── ops-feedback 闭环反馈（强制）
```

---

## 查询闭环：调用 ops-feedback

每次 `query_simple` 执行后（无论成功或失败），必须调用 `ops-feedback` Skill 提交反馈：

- `feedback_type`: `query_result`
- `title`: `"引导查询 - [需求摘要]（table_id=N）"`
- `content`: 返回行数、选择的分析方向、一句话结论
- `source`: `cli` 或 `mcp`（与当前运行模式一致）

详细参数规范见 `ops-feedback` Skill。

---

## 与 ops-dataset-query 的关系

本 Skill 是**引导层**，不替代 `ops-dataset-query`：

- 查询执行：委托给 `opscli query simple` / `query_simple` MCP Tool
- 歧义澄清：复用 `ops-dataset-query/references/rules.md`，不重复定义规则
- 字段校验：通过 `opscli query metadata` / `query_metadata` 确认字段存在
- 数据集匹配：通过 `opscli query catalog` / `query_catalog` 做意图匹配
