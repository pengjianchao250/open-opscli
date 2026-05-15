# ops-query-wizard Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 `ops-query-wizard` Skill，通过十步对话引导业务用户逐步构建合规的 `query_simple` 查询参数，并在取数完成后自动进入数据分析框架，形成完整的引导→取数→分析→反馈闭环。

**Architecture:** 纯文档驱动的 Skill（无 Python 脚本），由 `SKILL.md` 做总控入口，`references/step-guide.md` 承载十步引导规则，`references/analysis-guide.md` 承载分析框架。Skill 作为引导层，查询执行委托给 `ops-dataset-query` 的 `query_simple` 接口，歧义澄清规则复用 `ops-dataset-query/references/rules.md`。

**Tech Stack:** Markdown 文档，opscli CLI / MCP 双模式，query_simple（优先），ops-feedback Skill（闭环）

---

## 文件映射

| 操作 | 路径 | 职责 |
|------|------|------|
| 新建 | `opscli/skills/templates/ops-query-wizard/data/VERSION.json` | SkillDetector 识别标志 |
| 新建 | `opscli/skills/templates/ops-query-wizard/SKILL.md` | 总控：触发条件、铁律、运行模式、文档委托 |
| 新建 | `opscli/skills/templates/ops-query-wizard/references/step-guide.md` | 十步引导规则 + AI 推荐机制 + 字段列举展示 |
| 新建 | `opscli/skills/templates/ops-query-wizard/references/analysis-guide.md` | 五阶段分析框架 |
| 修改 | `opscli/skills/templates/manifest.json` | 注册新 Skill |

---

## Task 1：创建目录结构与 VERSION.json

**Files:**
- 新建目录：`opscli/skills/templates/ops-query-wizard/data/`
- 新建目录：`opscli/skills/templates/ops-query-wizard/references/`
- 创建：`opscli/skills/templates/ops-query-wizard/data/VERSION.json`

- [ ] **Step 1：创建目录结构**

```bash
mkdir -p /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard/data
mkdir -p /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard/references
```

- [ ] **Step 2：写入 VERSION.json**

文件路径：`opscli/skills/templates/ops-query-wizard/data/VERSION.json`

```json
{
  "name": "ops-query-wizard",
  "version": "v0.1.0",
  "data_state": "ready"
}
```

> 注意：`data_state` 设为 `ready`（非 `placeholder`），因为此 Skill 无需远端数据拉取。

- [ ] **Step 3：验证目录结构**

```bash
find /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard -type f
```

预期输出：
```
.../ops-query-wizard/data/VERSION.json
```

- [ ] **Step 4：提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/skills/templates/ops-query-wizard/
git commit -m "feat(skills): 初始化 ops-query-wizard Skill 目录结构"
```

---

## Task 2：编写 SKILL.md 总控文件

**Files:**
- 创建：`opscli/skills/templates/ops-query-wizard/SKILL.md`

- [ ] **Step 1：写入 SKILL.md**

文件路径：`opscli/skills/templates/ops-query-wizard/SKILL.md`

完整内容：

```markdown
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
```

- [ ] **Step 2：验证文件存在**

```bash
wc -l /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard/SKILL.md
```

预期：行数 > 80

- [ ] **Step 3：提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/skills/templates/ops-query-wizard/SKILL.md
git commit -m "feat(skills): 编写 ops-query-wizard SKILL.md 总控文件"
```

---

## Task 3：编写 references/step-guide.md

**Files:**
- 创建：`opscli/skills/templates/ops-query-wizard/references/step-guide.md`

- [ ] **Step 1：写入 step-guide.md**

文件路径：`opscli/skills/templates/ops-query-wizard/references/step-guide.md`

完整内容：

```markdown
---
name: ops-query-wizard-step-guide
description: ops-query-wizard 十步引导规则，包含 AI 推荐机制和字段全量列举展示规范
---

# 十步引导规则

> **AI Agent 必读**：开始引导前必须完整阅读本文档。每步规则包含推荐逻辑、展示格式和防呆规则。

---

## 推荐机制总则（贯穿 Step 2~9）

### 需求上下文提取（Step 1 完成后执行）

从 Step 1 的需求摘要中提取以下信息，作为后续各步推荐的依据：

| 信息类型 | 提取关键词示例 | 用途 |
|---------|-------------|------|
| 业务领域 | 广告/销售/库存/物流/财务 | 推荐数据集和指标字段 |
| 时间相关 | 近30天/本月/上月/近一周 | 推荐筛选条件 |
| 人员/组织 | 部门/小组/负责人/团队 | 推荐维度字段 |
| 产品相关 | ASIN/SKU/品类/商品 | 推荐维度字段和过滤条件 |
| 动作意图 | 对比/环比/趋势/排名/占比 | 推荐排序、对比配置、分析方向 |

### 推荐展示规范

```
符号约定：
  ✦ = 强推荐（与需求高度匹配）
  ○ = 备选（可选但非核心需求）

原则：
  1. 推荐项优先展示，不超过 5 个
  2. 推荐后必须展示全量可选列表（字段数 ≤10 全量显示，>10 显示前10并提示"输入'更多'查看全部"）
  3. 每步结尾必须留口让用户增减（"是否需要调整？"）
  4. 推荐置信度低时（关键词模糊）→ 降级为仅展示全量列表，不强推
  5. 禁止在用户未确认前将推荐直接写入查询参数
  6. 用户说"全选推荐的" → 直接使用推荐列表，跳过逐一确认
  7. 用户可用序号、中文名、英文字段名任意方式回答，AI 负责解析
```

---

## Step 1 — 需求目标概述

**目标**：理解业务问题，提取需求上下文，建立后续推荐的基础。

**引导话术**：
> "您好！我来一步步帮您完成数据查询。
> 请先用一两句话描述您想了解的业务问题，例如：
> '我想看上个月各部门的广告花费和 ACOS，找出效率最低的部门'
> 或 '帮我查一下近30天销售额的变化趋势'"

**执行规则**：
1. AI 复述理解并总结为 1-2 句需求摘要，请用户确认
2. 用户确认后，从摘要中提取需求上下文（见推荐机制总则）
3. 若用户直接给出字段名/数据集名 → 记录后跳至对应步骤
4. 需求摘要作为全程上下文，每步推荐时参考

---

## Step 2 — 选择数据集

**目标**：唯一确定 `table_id` 和 `dataset_alias`。

**执行流程**：

```
1. auth_is_authenticated()（自动加载本地凭证）
   → false → 执行登录流程后继续
2. query_catalog() 做意图匹配（远端优先，自动回退本地）
3. 展示推荐数据集 + 全量数据集列表（query_metadata() 无参调用）
4. 用户选定后记录 table_id 和 dataset_alias
```

**展示格式**：

```
"根据您的需求（广告效率分析），可用数据集如下：

 推荐：
 ✦ 1. ads_summary_d — 广告汇总日报，含花费/销售/ACOS/点击，按日聚合
 ✦ 2. ads_detail_d  — 广告明细日报，可下钻至 campaign 层级

 全部可用数据集（共 N 个）：
 序号 | 数据集别名          | 数据粒度     | 适用场景
  1   | ads_summary_d      | 按日汇总     | 广告整体效率分析
  2   | ads_detail_d       | campaign明细 | 广告细粒度优化
  3   | sales_order_d      | 按日汇总     | 销售订单分析
  4   | inventory_d        | 快照         | 库存状态查询
  ...

 请输入序号或数据集名称，也可直接说'用推荐的第1个'。"
```

**防呆规则**：
- 用户说出数据集名称 → 先 `query_metadata()` 确认存在，模糊匹配到 ≥2 个仍需列出确认
- 意图匹配到 0 个 → 告知用户，让其描述更具体后重新匹配
- 意图匹配到 ≥2 个优先级相近 → 列出全部候选，说明粒度差异

---

## Step 3 — 选择维度字段

**目标**：确定 `dimensions` 列表。

**执行流程**：

```
1. query_metadata(dataset=dataset_alias) 获取字段列表
2. 从需求上下文推断推荐维度（见推荐逻辑）
3. 展示推荐维度 + 该数据集全量维度字段（field_type=dimension）
4. 用户选定后构造：{"field": "xxx", "alias": "f_xxx"}
5. 日期维度：询问是否需要时间粒度格式化
```

**推荐逻辑**：

| 需求关键词 | 推荐维度字段 |
|---------|-----------|
| 时间/趋势/日期 | date_id |
| 部门/小组/组织 | dept_name / team_name |
| 产品/ASIN/SKU | asin / channel_sku |
| 平台/渠道 | platform / marketplace |
| 广告类型 | ad_type（SP/SD/SB） |
| 国家/市场 | country_code |

**展示格式**：

```
"该数据集支持以下维度字段：

 推荐：
 ✦ 日期（date_id）      — 按时间分析趋势
 ✦ 部门（dept_name）    — 按部门对比效率

 全部维度字段（共 N 个）：
 序号 | 字段名（verbose_name） | 英文名        | 说明
  1   | 日期                   | date_id       | 数据统计日期
  2   | 部门                   | dept_name     | 业务部门
  3   | 平台                   | platform      | 销售平台
  4   | 广告类型               | ad_type       | SP/SD/SB/SBV
  5   | 国家                   | country_code  | 投放国家
  ...

 请输入序号或字段名选择（可多选，如：1 2 或 日期 部门）。
 如不需要分组维度，请说'不需要维度'。"
```

**防呆规则**：
- 用户不选维度 → `dimensions=[]`（汇总总计），继续
- 选择日期维度 → 追问时间粒度：按日（默认）/ 按月（`%Y-%m`）/ 按年（`%Y`）/ 按周
- 字段歧义（≥2 个匹配）→ 强制列出让用户选，禁止静默选择

---

## Step 4 — 选择指标字段

**目标**：确定 `metrics` 列表，自动识别并标注公式字段。

**执行流程**：

```
1. 展示推荐指标 + 全量指标字段（field_type=metric）
2. 对每个选定字段判断类型：
   - summary_expression 非空 → 公式字段：不传 aggregation，传 expr
   - 普通字段 → 询问聚合方式（提供默认推荐）
3. 构造参数
```

**推荐逻辑**：

| 需求关键词 | 推荐指标字段 |
|---------|-----------|
| 广告/推广 | ads_total_spend_cny、ads_sales_cny、ads_acos、ads_clicks、ads_impressions |
| 销售/订单 | sales_amount_cny、order_qty、order_count |
| 物流/运费 | fi_first_leg_fee、shipping_cost |
| 毛利/利润 | gross_profit_cny、gross_profit_rate |
| 库存 | available_qty、inbound_qty、海外仓库存 |
| 对比/环比 | 提示 Step 9 可启用 dataComparison |

**展示格式**：

```
"该数据集支持以下指标字段：

 推荐：
 ✦ 广告费（ads_total_spend_cny）    — SUM 聚合
 ✦ 广告销售额（ads_sales_cny）      — SUM 聚合
 ✦ ACOS（ads_acos）                 — 「公式字段」自动计算，无需选聚合方式
 ✦ 广告点击量（ads_clicks）         — SUM 聚合

 全部指标字段（共 N 个）：
 序号 | 字段名              | 英文名                  | 类型   | 默认聚合
  1   | 广告费              | ads_total_spend_cny     | 金额   | SUM
  2   | 广告销售额          | ads_sales_cny           | 金额   | SUM
  3   | ACOS               | ads_acos                | 「公式」 | —（自动）
  4   | ROAS               | ads_roas                | 「公式」 | —（自动）
  5   | 广告点击量          | ads_clicks              | 数量   | SUM
  6   | 广告展示量          | ads_impressions         | 数量   | SUM
  7   | 广告转化量          | ads_conversions         | 数量   | SUM
  8   | 广告转化率          | ads_conversion_rate     | 「公式」 | —（自动）
  ...（还有 N 个字段，输入'更多'查看全部）

 请输入序号或字段名选择（可多选）。
 标注「公式」的字段系统自动处理，您无需选择聚合方式。"
```

**普通字段聚合方式确认**（逐一或批量）：

```
"您选择了'广告费'，默认使用 SUM（求和）。
 可选聚合方式：SUM（求和）/ AVG（平均）/ MAX（最大）/ MIN（最小）/ COUNT_DISTINCT（去重计数）
 直接回车使用默认 SUM，或输入其他方式。"
```

**参数构造规则**：
- 普通字段：`{"field": "xxx", "aggregation": "SUM", "alias": "f_xxx"}`
- 公式字段：`{"field": "xxx", "alias": "f_xxx", "expr": "<summary_expression 的值>"}`
- alias 命名规则：统一使用 `f_` 前缀 + 字段英文名简写

---

## Step 5 — 筛选条件

**目标**：确定 `filters` 列表。

**执行流程**：

```
1. 必问：时间范围（date_id 是核心过滤条件，不可跳过）
2. 按需：其他维度过滤（平台、部门、ASIN 等）
```

**时间处理铁律**（来自 ops-dataset-query/references/rules.md 第一章）：

```
"近N天"推算公式：
  结束日期 = 今天
  起始日期 = 今天 - (N-1) 天   ← 注意是 N-1，不是 N

常见表述处理：
  近30天 → 精确计算起止日期，在回复中列出
  本月   → 当月1日~今天
  上月   → 上月1日~上月最后一天
  最近一个月 → 歧义！必须确认：近30天 还是 本自然月？
  本周   → 本周一~今天
  最近一周 → 近7天（≠上周）
```

**展示格式**：

```
"请设置筛选条件：

 时间范围（必填）：
 根据您说的'近30天'，推荐：
 ✦ 日期范围：2026-04-16 ~ 2026-05-15（共30天，含今天）
 如需调整请告知，或直接说'确认'。

 其他过滤条件（可选）：
 - 是否限定特定部门？（如：只看 XX 部门）
 - 是否限定特定平台？（如：只看 Amazon）
 - 是否限定特定产品？（如：指定 ASIN）
 如不需要其他过滤，说'不需要'即可。"
```

**防呆规则**：
- "最近一个月"→ 必须澄清：近30天 vs 自然月
- 跨月对比天数不对等 → 告知差异，给出两方案让用户选
- 月初（1~5日）用户说"本月" → 提示本月数据很少，确认是否想查上月

---

## Step 6 — 排序字段

**目标**：确定 `order_by` 配置。

**推荐逻辑**：

| 需求动作词 | 推荐排序 |
|---------|--------|
| 排名/Top/最多/最高 | 主要指标 desc（倒序）|
| 趋势/变化 | date_id asc（正序）|
| 最低/最少 | 主要指标 asc（正序）|
| 未提及 | 主要指标 desc（默认推荐）|

**展示格式**：

```
"推荐排序方式：
 ✦ 按广告费从高到低排序（方便查看花费最多的部门）

 也可选择：
 ○ 按 ACOS 从高到低排序（找效率最低的）
 ○ 按日期正序排列（看趋势变化）
 ○ 不排序

 是否采用推荐排序，或选择其他？"
```

**参数构造**：`[{"field": "f_xxx", "desc": true}]`

---

## Step 7 — 获取条数

**目标**：确定 `limit`。

**推荐逻辑**：
- 需求含"Top N" → 直接使用 N
- 需求含"全部" → 推荐先用 50 条预览，提示全量可能较慢
- 未提及 → 推荐 20 条

**展示格式**：

```
"需要获取多少条数据？

 推荐：✦ 20 条（快速预览）

 常用选项：
 ○ 10 条（Top 10）
 ○ 50 条（较完整）
 ○ 100 条（全面分析）
 ○ 自定义（请输入数字）

 如需全量数据，建议先用 50 条预览，确认结果正确后再获取全量。"
```

---

## Step 8 — 是否分页

**目标**：确定是否需要多页查询（offset）。

**触发规则**：用户明确需要"全部数据"或数据量较大时才询问，否则跳过此步。

**展示格式（仅在触发时显示）**：

```
"需要获取多页数据吗？

 当前每页获取：N 条
 请问共需要几页？（输入页数，或说'只要第1页'）

 第 1 页：offset=0
 第 2 页：offset=N
 第 k 页：offset=(k-1)*N"
```

---

## Step 9 — 是否需要对比数据

**目标**：确定是否启用 `data_comparison`，配置对比周期。

**触发逻辑**：
- 需求含"环比/同比/对比/上期/上月/变化" → 主动推荐开启
- 未提及 → 询问是否需要对比

**展示格式（主动推荐场景）**：

```
"您的需求中提到对比，是否开启数据对比？

 推荐对比方案：
 ✦ 当期：2026-04-16 ~ 2026-05-15
   对比期（上月同期）：2026-03-16 ~ 2026-04-15

 开启后，查询结果将额外返回：
 - last_f_xxx（对比期数值）
 - diff_f_xxx（差值）
 - pct_f_xxx（变化率，如 +12.5%）

 是否采用此对比方案？或指定其他对比时间范围？"
```

**铁律**：`data_comparison` 必须同时传主周期 `filters`，缺一不可（否则报 QS-EXE-005）。

---

## Step 10 — 执行查询

**目标**：参数确认 → 执行 `query_simple` → 展示结果 → 进入分析框架。

**执行流程**：

```
1. 展示完整参数摘要（以下格式），让用户确认
2. 用户确认后执行 query_simple
3. 成功 → 以表格展示数据（列名使用 verbose_name）→ 进入 analysis-guide.md
4. 失败 → 按错误码处理：
     QS-EXE-005 → 补充主周期 filters
     无字段错误 → 检查字段名拼写，重新 query_metadata 确认
     0行返回   → 提示检查过滤条件，询问是否去掉部分条件重试
5. 无论成功失败 → 调用 ops-feedback 提交反馈
```

**参数摘要展示格式**：

```
"查询参数已配置完成，请确认：

 数据集：ads_summary_d（table_id=15）
 维度：日期（按月）、部门
 指标：广告费（SUM）、广告销售额（SUM）、ACOS（公式）
 筛选：日期 2026-04-16 ~ 2026-05-15
 排序：广告费 倒序
 获取条数：20 条
 数据对比：开启（对比期 2026-03-16 ~ 2026-04-15）

 确认无误后输入'执行'，或指出需要调整的步骤编号。"
```

**query_simple 参数构造示例**：

```python
query_simple(
    table_id=15,
    dimensions=[
        {"field": "date_id", "alias": "f_date", "format": "%Y-%m"},
        {"field": "dept_name", "alias": "f_dept"}
    ],
    metrics=[
        {"field": "ads_total_spend_cny", "aggregation": "SUM", "alias": "f_spend"},
        {"field": "ads_sales_cny", "aggregation": "SUM", "alias": "f_sales"},
        {"field": "ads_acos", "alias": "f_acos", "expr": "<summary_expression>"}
    ],
    filters=[
        {"field": "date_id", "operator": "between", "value": ["2026-04-16", "2026-05-15"]}
    ],
    data_comparison={"field": "date_id", "startDate": "2026-03-16", "endDate": "2026-04-15"},
    order_by=[{"field": "f_spend", "desc": True}],
    limit=20
)
```
```

- [ ] **Step 2：验证关键章节存在**

```bash
grep -c "## Step" /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard/references/step-guide.md
```

预期输出：`10`（共10个步骤标题）

- [ ] **Step 3：提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/skills/templates/ops-query-wizard/references/step-guide.md
git commit -m "feat(skills): 编写 ops-query-wizard step-guide.md 十步引导规则"
```

---

## Task 4：编写 references/analysis-guide.md

**Files:**
- 创建：`opscli/skills/templates/ops-query-wizard/references/analysis-guide.md`

- [ ] **Step 1：写入 analysis-guide.md**

文件路径：`opscli/skills/templates/ops-query-wizard/references/analysis-guide.md`

完整内容：

```markdown
---
name: ops-query-wizard-analysis-guide
description: ops-query-wizard 数据分析框架，在 query_simple 执行成功后触发，包含五阶段分析流程和五种分析方向模板
---

# 数据分析框架

> **触发时机**：`query_simple` 执行成功、数据返回后，AI 自动进入本框架。
> 0 行返回时也需执行阶段一（说明无数据原因）。

---

## 阶段一：数据概览（自动执行，无需用户交互）

查询结果展示后，立即输出以下概览，无需等待用户提问：

**输出内容**：

```
1. 数据摘要
   - 返回行数、时间范围、维度组合
   - 主要指标的：总计 / 均值 / 最大值 / 最小值

2. 数据质量标注
   - 是否有空值字段（标注哪列）
   - 是否有异常值（ACOS > 100%、负毛利、订单量归零等）

3. 对比数据摘要（如有 dataComparison）
   - 整体环比趋势（主要指标：↑+X% 或 ↓-X%）
```

**示例输出**：

```
"查询返回 18 行数据（2026-04-16 ~ 2026-05-15，按部门统计）

 数据摘要：
 广告费合计：¥128,450   均值：¥7,136/部门   最高：¥24,800（XX部门）
 广告销售额合计：¥389,200
 整体 ACOS：33.0%   范围：12.3% ~ 61.4%

 数据质量：
 ⚠ 发现 3 个部门 ACOS > 40%（超出健康阈值）
 ⚠ 1 个部门广告费环比上升 38%，但销售额下降 12%

 环比趋势（对比上月同期）：
 广告费 ↑ +15.2%    广告销售额 ↑ +3.1%    ACOS ↑ +7.8%（恶化）"
```

---

## 阶段二：分析方向识别

基于实际返回数据和需求上下文，AI 自动识别可分析方向，最多推荐 4 个，按优先级排序。

### 方向识别规则

| 触发条件 | 推荐方向 | 优先级 |
|---------|---------|--------|
| 数据中存在异常值（ACOS > 阈值、负毛利等） | 异常归因分析 | 最高 |
| 有对比数据（dataComparison）且整体趋势明显 | 环比变化分析 | 高 |
| 指标含 ACOS / ROAS / 广告效率字段 | 广告效率分析 | 高 |
| 有维度分组（部门/平台/品类）且分布不均 | 维度结构分析 | 中 |
| 有日期维度 + 多行数据 | 趋势分析 | 中 |
| 指标含毛利/利润字段 | 盈利能力分析 | 中 |
| 指标含库存字段 | 库存健康分析 | 低 |

### 展示格式

```
"基于您的数据，以下分析方向值得深入：

 ✦ 1. 异常归因分析 — 3个部门 ACOS 严重偏高，需定位原因
 ✦ 2. 广告效率分析 — 整体 ACOS 33%，部门间差异达49个百分点
 ○ 3. 环比变化分析 — 广告费增15%但销售额仅增3%，ROI 明显恶化
 ○ 4. 维度结构分析 — 各部门广告费占比差异较大

 请选择一个方向进行深度分析（输入序号即可）。"
```

---

## 阶段三：深度分析（按选定方向执行）

### 方向模板 A — 广告效率分析

```
分析步骤：
1. 按 ACOS 从高到低排序，列出超出阈值（>30%）的维度
2. 计算各维度的 ROI = 广告销售额 / 广告费
3. 识别"高花费 + 高 ACOS"危险组合（花费 Top50% + ACOS > 阈值）
4. 识别"低花费 + 低 ACOS"潜力组合（可加大投入）

输出结论格式：
  "广告效率分析结论：
   危险组合（建议降低预算）：XX部门（ACOS 61.4%，花费¥18,200）
   潜力组合（建议加大投入）：YY部门（ACOS 12.3%，花费¥2,800）
   整体建议：将高ACOS部门预算的20%转移至低ACOS部门"
```

### 方向模板 B — 环比变化分析

```
分析步骤：
1. 展示各维度当期 vs 对比期对比表（含涨跌幅 ↑↓ 和绝对差值）
2. 识别异常变动：涨幅 > 30% 或降幅 > 20%
3. 识别"费用涨 + 销售跌"的 ROI 恶化维度（重点关注）
4. 找出整体变化的主要驱动维度（贡献最大的涨/跌）

输出结论格式：
  "环比变化分析结论：
   ROI 恶化最严重：XX部门（广告费 ↑38%，销售额 ↓12%）
   增长最健康：YY部门（广告费 ↑5%，销售额 ↑28%）
   整体判断：本期广告投入效率下降，建议审查 XX 部门投放策略"
```

### 方向模板 C — 维度结构分析

```
分析步骤：
1. 计算各维度占总量的百分比（主要指标）
2. 计算头部集中度：Top3 维度占比之和
3. 识别异常：单一维度占比 > 50%（过度集中）或 < 1%（边缘维度）
4. 对比各维度的效率指标（ACOS / 毛利率）

输出结论格式：
  "维度结构分析结论：
   广告费集中度：Top3部门占总量的 72%（集中度较高）
   效率最优：YY部门（占比8%，ACOS 12.3%）
   资源错配风险：ZZ部门占广告费 35% 但销售额仅占 15%"
```

### 方向模板 D — 趋势分析

```
分析步骤：
1. 按日期维度展示主要指标走势（需要数据中有日期维度）
2. 识别拐点：连续上升或下降超过 3 天/周
3. 标注异常波动点（与均值偏差 > 2倍标准差）
4. 判断整体趋势方向（上升/下降/平稳/波动）

输出结论格式：
  "趋势分析结论：
   整体趋势：广告费呈上升趋势，近7天加速（日均+5.2%）
   关键拐点：4月22日起 ACOS 开始持续上升，与节日促销节点吻合
   预警：如不干预，本月 ACOS 可能突破 40%"
```

### 方向模板 E — 异常归因分析

```
分析步骤：
1. 列出所有检测到的异常（按严重度排序：critical > warning > info）
2. 对每个异常推断可能原因（基于同期其他指标的关联关系）
3. 评估影响范围（异常维度的业务占比）
4. 给出优先处理建议

异常类型识别规则：
  negative_margin : 毛利率 < 0                → 严重（critical）
  high_acos       : ACOS > 40%               → 警告（warning）
  revenue_cliff   : 销售额环比下降 > 20%      → 警告（warning）
  profit_drop     : 毛利环比下降 > 30%        → 警告（warning）
  ad_roi_decline  : 广告费涨 + 毛利跌         → 警告（warning）
  zero_orders     : 当期订单归零（对比期>0）   → 提示（info）

输出结论格式：
  "异常归因分析：
   发现 3 个异常（1严重 / 2警告）

   [严重] XX部门 毛利率 -8.4%（亏损运营）
     可能原因：广告费占收入比过高（广告费/销售额 = 45%）
     建议：立即暂停该部门非必要广告投放

   [警告] YY部门 ACOS 61.4%（超健康阈值2倍）
     可能原因：点击量高但转化率极低（0.3%），关键词匹配度差
     建议：审查关键词相关性，收紧匹配方式"
```

---

## 阶段四：输出规范

### 输出方式选择

深度分析完成后，询问输出方式：

```
"分析完成。请选择输出方式：
 1. 仅保留对话结论（当前已完成）
 2. 导出 Excel 数据透视表到本地
 3. 两者都要"
```

### 对话输出规范

- 列名必须使用数据集 `verbose_name`，禁止意译
- 引用数据时必须注明维度和时间范围
- 分析结论分为：现状描述 + 问题定位 + 行动建议 三部分

### Excel 导出规范

```
调用：ops-dataset-query/scripts/excel_export_core.py 中的 export_to_excel()

参数：
  queries        ← query_simple 返回的查询结果
  mapped_queries ← 经过 map_chart_queries 处理的字段映射结果
  output_path    ← "/tmp/ops-query-wizard-<timestamp>.xlsx"
  sheet_name     ← "数据透视表"

导出后告知用户文件路径：
  "Excel 文件已导出至：/tmp/ops-query-wizard-20260515-143022.xlsx"
```

---

## 阶段五：闭环反馈（强制）

**无论分析是否完成，最后一步必须调用 ops-feedback。**

### 调用规范

**CLI 模式**：

```bash
opscli feedback submit \
  --feedback-type query_result \
  --title "引导查询 - [需求摘要]（table_id=N）" \
  --content "返回 N 行，选择[分析方向]进行深度分析，结论：[一句话摘要]" \
  --source cli \
  --execution-summary '{"summary":"通过引导查询执行 query_simple","successful_calls":[{"tool":"query_simple","result":"success, N rows"}],"failed_calls":[],"final_resolution":"分析完成"}'
```

**MCP 模式**：

```python
feedback_submit(
    feedback_type="query_result",
    title="引导查询 - [需求摘要]（table_id=N）",
    content="返回 N 行，选择[分析方向]进行深度分析，结论：[一句话摘要]",
    source="mcp",
    execution_summary={
        "summary": "通过 ops-query-wizard 引导，执行 query_simple 取数并完成[分析方向]",
        "successful_calls": [{"tool": "query_simple", "result": f"success, N rows"}],
        "failed_calls": [],
        "final_resolution": "分析完成，已输出结论给用户"
    }
)
```

### 反馈必须包含的信息

| 字段 | 内容 |
|------|------|
| 引导步骤耗时 | 共经历几轮对话完成引导 |
| 查询结果 | 成功/失败、返回行数 |
| 选择的分析方向 | 广告效率/环比变化/维度结构/趋势/异常归因 |
| 是否有降级操作 | 如去掉 default_filters 重试、切换 MCP 模式等 |
```

- [ ] **Step 2：验证关键章节存在**

```bash
grep -c "^## 阶段" /Users/mask/python3/opscli/opscli/skills/templates/ops-query-wizard/references/analysis-guide.md
```

预期输出：`5`

- [ ] **Step 3：提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/skills/templates/ops-query-wizard/references/analysis-guide.md
git commit -m "feat(skills): 编写 ops-query-wizard analysis-guide.md 分析框架"
```

---

## Task 5：更新 manifest.json 注册新 Skill

**Files:**
- 修改：`opscli/skills/templates/manifest.json`（在 `skills` 对象末尾追加条目）

- [ ] **Step 1：确认当前 manifest.json 内容**

```bash
cat /Users/mask/python3/opscli/opscli/skills/templates/manifest.json
```

- [ ] **Step 2：在 manifest.json 的 skills 对象中追加条目**

在 `"ops-cli-view-runner"` 条目后追加：

```json
"ops-query-wizard": {
  "source": false,
  "wheel": false,
  "binary": false,
  "binary_full": false,
  "tier": "internal",
  "reason": "引导式查询向导，面向业务用户，依赖 ops-dataset-query，现阶段内部使用"
}
```

- [ ] **Step 3：验证 JSON 合法性**

```bash
python3 -c "import json; json.load(open('/Users/mask/python3/opscli/opscli/skills/templates/manifest.json')); print('JSON 合法')"
```

预期输出：`JSON 合法`

- [ ] **Step 4：验证新条目存在**

```bash
grep "ops-query-wizard" /Users/mask/python3/opscli/opscli/skills/templates/manifest.json
```

预期输出：包含 `ops-query-wizard` 的行

- [ ] **Step 5：提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/skills/templates/manifest.json
git commit -m "feat(skills): 在 manifest.json 注册 ops-query-wizard Skill"
```

---

## 自检清单（实施前核查）

- [ ] Spec 覆盖：SKILL.md 包含触发条件 ✓ / 铁律10条 ✓ / 文档阅读顺序 ✓ / 工作流概览 ✓ / ops-feedback 闭环 ✓
- [ ] Spec 覆盖：step-guide.md 包含 Step 1~10 ✓ / 推荐机制总则 ✓ / 字段全量列举展示规范 ✓ / query_simple 参数构造示例 ✓
- [ ] Spec 覆盖：analysis-guide.md 包含五阶段 ✓ / 五种分析方向模板 ✓ / 输出规范 ✓ / 闭环反馈 ✓
- [ ] 路径一致性：SKILL.md 引用 `references/step-guide.md` 和 `references/analysis-guide.md` 路径与实际文件一致
- [ ] 路径一致性：SKILL.md 引用 `ops-dataset-query/references/rules.md` 为相对路径，实际使用时需确认宿主 AI 能找到
- [ ] 铁律13：Skill 名称以 `ops-` 开头 ✓
- [ ] 铁律14：包含 `data/VERSION.json` ✓ / 包含 `SKILL.md` ✓
- [ ] 铁律16：plan 文件名使用英文（superpowers 约定），Skill 内容文件使用中文注释 ✓
