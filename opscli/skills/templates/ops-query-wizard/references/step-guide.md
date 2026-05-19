# 十步引导规则

> **AI Agent 必读**：开始引导前必须完整阅读本文档。每步规则包含推荐逻辑、展示格式和防呆规则。

---

## 交互式提问总则（贯穿 Step 1~10）

### 核心原则

> **优先使用 `AskUserQuestion` 工具进行交互式提问，替代纯文本话术。**

`AskUserQuestion` 提供结构化的选项卡片界面，用户可一键选择，每步最后一个选项为"其他（自定义）"支持自由输入。

### 工具能力

| 能力 | 说明 |
|------|------|
| 选项数 | 每个问题 2~4 个选项 |
| 问题数 | 单次调用最多 4 个问题 |
| 多选 | `multiSelect=true` 支持勾选多个选项 |
| 预览 | `preview` 字段可在选项右侧展示预览内容 |
| 自定义输入 | 每步最后一个选项为"其他（自定义）"，用户可在输入框自由输入 |

### 使用策略

| 场景 | 策略 |
|------|------|
| 选项≤4 个 | 直接用 `AskUserQuestion` 展示所有选项 |
| 选项>4 个但推荐项≤4 | 文本展示全量列表 + `AskUserQuestion` 展示推荐项供快速选择 |
| 需要展示大表格/长列表 | 先用文本输出列表，再用 `AskUserQuestion` 做选择交互 |
| 开放性问题 | `AskUserQuestion` 提供模板选项 + "其他（自定义）"选项支持自由输入 |

### 调用格式要求

每步使用 `AskUserQuestion` 时：
1. `question`：用中文清晰描述当前步骤的问题
2. `header`：简短标签（≤12字符），如"数据集"、"维度"、"时间范围"
3. `options`：每项包含 `label`（选项名）和 `description`（说明）
4. `multiSelect`：多选场景设为 `true`
5. `preview`：仅在需要展示代码/参数示例时使用

### 自定义输入铁律（强制）

> **每一步的 `AskUserQuestion` 调用都必须包含一个"其他（自定义）"选项，让用户可以自由输入。**

规则：
1. 每个 AskUserQuestion 的 options 数组中，**必须**包含一个 `"其他（...）"` 选项作为最后一项
2. 该选项的 `description` 须引导用户在输入框中输入自定义内容，并给出输入示例
3. 当选项已达 4 个上限时，合并次要选项腾出一个位置给"其他"选项
4. 这条规则**无例外**（用户的需求不可穷举，必须有自由输入通道）

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
  1. 【强制】必须默认完整输出全量列表，推荐项在列表中用 ✦ 内联标注，禁止单独列一个"推荐"区块而省略其余条目
  2. 字段数 ≤300 一次全部输出；>300 时输出前300并提示"输入'更多'查看剩余"
  3. 每步结尾必须留口让用户增减（"是否需要调整？"）
  4. 推荐置信度低时（关键词模糊）→ 不标注 ✦，仅展示全量列表
  5. 禁止在用户未确认前将推荐直接写入查询参数
  6. 用户说"全选推荐的" → 直接使用 ✦ 标注项，跳过逐一确认
  7. 用户可用序号、中文名、英文字段名任意方式回答，AI 负责解析
```

---

## Step 1 — 需求目标概述

**目标**：理解业务问题，提取需求上下文，建立后续推荐的基础。

**交互方式**：使用 `AskUserQuestion` 提供常见业务场景模板，最后一个选项为"其他（自由描述）"支持自定义输入。

**AskUserQuestion 调用示例**：

```
AskUserQuestion:
  questions:
    - question: "您好！我来一步步帮您完成数据查询。请选择您想分析的业务方向："
      header: "业务方向"
      multiSelect: false
      options:
        - label: "广告效率分析"
          description: "广告花费、ACOS、ROAS、点击转化等广告相关指标"
        - label: "销售订单分析"
          description: "销售额、订单量、销量趋势等销售数据"
        - label: "库存健康分析"
          description: "库存周转、库龄、断货风险等库存指标"
        - label: "其他（自由描述）"
          description: "利润分析、物流、综合或其他业务场景，请在输入框描述"
```

> ⚠️ **注意**：用户选择模板选项后，AI 仍需复述理解并总结为 1-2 句需求摘要，请用户确认。用户选择"其他（自由描述）"输入的自定义描述同样需要复述确认。

**执行规则**：
1. 调用 `AskUserQuestion` 展示业务场景模板，或用户已直接描述需求则跳过选择
2. AI 复述理解并总结为 1-2 句需求摘要，请用户确认
3. 若用户否认复述，重新理解后再次复述；**连续 2 次确认失败后**，AI 说"让我们以当前理解先进行，后续可以在 Step 10 随时纠正"，并推进至 Step 2，不再停留
4. 用户确认后，从摘要中提取需求上下文（见推荐机制总则）
5. 若用户直接给出字段名/数据集名，按以下规则跳步：

   | 用户提供的信息 | 跳转目标 |
   |-------------|---------|
   | 仅数据集名 | 跳至 Step 2 展示全量列表并预标注 ✦ 该数据集 |
   | 仅字段名（未知属于哪个数据集） | 先跳 Step 2 选数据集，选定后跳 Step 3 或 4（按字段类型） |
   | 数据集名 + 字段名 | 先 Step 2 确认数据集，再跳 Step 3/4（按字段类型），其余步骤继续引导 |
   | 数据集名 + 字段名 + 时间范围 | Step 2 确认数据集，Step 3/4 确认字段，Step 5 直接展示时间范围确认，其余继续 |

6. 需求摘要作为全程上下文，每步推荐时参考

---

## Step 2 — 选择数据集

**目标**：唯一确定 `table_id` 和 `dataset_alias`。

**交互方式**：文本展示全量数据集列表（规则要求不可省略），然后用 `AskUserQuestion` 展示推荐项供快速选择。

**执行流程**：

```
1. auth_is_authenticated()（自动加载本地凭证）
   → false → 执行登录流程后继续
2. query_catalog() 做意图匹配（远端优先，自动回退本地）
3. 【强制】无论有无推荐，必须完整展示全量数据集列表（query_metadata() 无参调用）
4. 用 AskUserQuestion 展示推荐数据集供快速选择
5. 用户选定后记录 table_id 和 dataset_alias
```

> ⚠️ **展示铁律**：推荐项在列表中用 ✦ 标注，**禁止**仅展示推荐而省略全量列表。全量列表必须默认完整输出，不得折叠或省略。

**文本展示格式**（全量列表，必须完整输出）：

```
"根据您的需求（广告效率分析），全部可用数据集如下（✦ 为推荐，共 N 个）：

 序号 | 数据集别名          | 数据粒度     | 适用场景
  1 ✦ | ads_summary_d      | 按日汇总     | 广告整体效率分析（推荐：含花费/销售/ACOS/点击）
  2 ✦ | ads_detail_d       | campaign明细 | 广告细粒度优化（推荐：可下钻至 campaign 层级）
  3   | sales_order_d      | 按日汇总     | 销售订单分析
  4   | inventory_d        | 快照         | 库存状态查询
  ...（全部 N 个，完整列出）"
```

**AskUserQuestion 调用示例**（在文本列表之后，提供快捷选择）：

```
AskUserQuestion:
  questions:
    - question: "请选择数据集（推荐项如下）："
      header: "数据集"
      multiSelect: false
      options:
        - label: "ads_summary_d（推荐）"
          description: "按日汇总，广告整体效率分析，含花费/销售/ACOS/点击"
        - label: "ads_detail_d（推荐）"
          description: "campaign 明细，广告细粒度优化，可下钻至 campaign 层级"
        - label: "sales_order_d"
          description: "按日汇总，销售订单分析"
        - label: "其他（输入序号或数据集名）"
          description: "在输入框中输入上方列表中的序号或数据集别名"
```

> ⚠️ AskUserQuestion 最多 4 个选项。推荐项≤3 时全部展示 + 1 个"其他"选项；推荐项>3 时展示最相关的 2 个 + 1 个"查看全量列表" + 1 个"其他"选项。用户选"其他"后可输入任意序号或数据集名。

**防呆规则**：
- 用户说出数据集名称 → 先 `query_metadata()` 确认存在，模糊匹配到 ≥2 个仍需列出确认
- 意图匹配到 0 个 → 仍展示全量列表，告知无推荐，让用户自行选择
- 意图匹配到 ≥2 个优先级相近 → 全部在列表中标注 ✦，说明粒度差异

---

## Step 3 — 选择维度字段

**目标**：确定 `dimensions` 列表。

**交互方式**：文本展示全量维度字段列表，然后用 `AskUserQuestion` 展示推荐维度（multiSelect）供快速选择。

**执行流程**：

```
1. query_metadata(dataset=dataset_alias) 获取字段列表
2. 从需求上下文推断推荐维度（见推荐逻辑）
3. 【强制】完整展示该数据集全量维度字段（field_type=dimension），推荐项用 ✦ 标注
4. 用 AskUserQuestion 展示推荐维度供快速选择（multiSelect=true）
5. 用户选定后构造：{"field": "xxx", "alias": "f_xxx"}
6. 日期维度：询问是否需要时间粒度格式化
```

> ⚠️ **展示铁律**：禁止仅展示推荐维度而省略其余字段。全量字段列表必须默认完整输出，推荐项在列表中用 ✦ 内联标注。

**推荐逻辑**：

| 需求关键词 | 推荐维度字段 |
|---------|-----------|
| 时间/趋势/日期 | date_id |
| 部门/小组/组织 | dept_name / team_name |
| 产品/ASIN/SKU | asin / channel_sku |
| 平台/渠道 | platform / marketplace |
| 广告类型 | ad_type（SP/SD/SB） |
| 国家/市场 | country_code |

**文本展示格式**（全量列表，必须完整输出）：

```
"该数据集全部维度字段如下（✦ 为推荐，共 N 个）：

 序号 | 字段名（verbose_name） | 英文名        | 说明
  1 ✦ | 日期                   | date_id       | 数据统计日期（推荐：按时间分析趋势）
  2 ✦ | 部门                   | dept_name     | 业务部门（推荐：按部门对比效率）
  3   | 平台                   | platform      | 销售平台
  4   | 广告类型               | ad_type       | SP/SD/SB/SBV
  5   | 国家                   | country_code  | 投放国家
  ...（全部 N 个，完整列出）"
```

**AskUserQuestion 调用示例**（在文本列表之后，提供快捷多选）：

```
AskUserQuestion:
  questions:
    - question: "请选择维度字段（可多选）：
                 如不需要分组维度，选'不需要维度'即可。"
      header: "维度"
      multiSelect: true
      options:
        - label: "日期（date_id）"
          description: "数据统计日期，按时间分析趋势"
        - label: "部门（dept_name）"
          description: "业务部门，按部门对比效率"
        - label: "不需要维度"
          description: "不分组，返回汇总总计"
        - label: "其他（输入序号或字段名）"
          description: "在输入框中输入上方列表中的序号或字段名，如 '1 3 5'"
```

> ⚠️ 推荐维度≤2 个时全部展示 + "不需要维度" + "其他"选项；推荐维度>2 时展示最相关的 2 个 + "不需要维度" + "其他"。用户选"其他"后可在输入框输入任意序号或字段名实现多选。

**日期维度时间粒度追问**（仅当选了日期维度且未指定粒度时）：

```
AskUserQuestion:
  questions:
    - question: "日期维度需要按什么粒度展示？"
      header: "时间粒度"
      multiSelect: false
      options:
        - label: "按日（默认）"
          description: "每日数据，格式：%Y-%m-%d"
        - label: "按月"
          description: "月度汇总，格式：%Y-%m"
        - label: "按年/按周"
          description: "年度汇总（%Y）或周度汇总"
        - label: "其他（自定义格式）"
          description: "在输入框中输入自定义格式，如 '%Y-%m-%d %H'（按小时）"
```

**防呆规则**：
- 用户不选维度 → `dimensions=[]`（汇总总计），继续
- 选择日期维度 → 判断是否需要追问时间粒度：
  - 需求上下文已含粒度关键词（"按月/按日/按周/按年/月度/日度"）→ 直接使用对应 format，**不再追问**
  - 未提及粒度 → 用 `AskUserQuestion` 追问时间粒度
- 字段歧义（≥2 个匹配）→ 强制列出让用户选，禁止静默选择

---

## Step 4 — 选择指标字段

**目标**：确定 `metrics` 列表，自动识别并标注公式字段。

**交互方式**：文本展示全量指标字段列表，然后用 `AskUserQuestion` 展示推荐指标（multiSelect）供快速选择。

**执行流程**：

```
1. 【强制】完整展示该数据集全量指标字段（field_type=metric），推荐项用 ✦ 标注
2. 用 AskUserQuestion 展示推荐指标供快速选择（multiSelect=true）
3. 对每个选定字段判断类型：
   - summary_expression 非空 → 公式字段：不传 aggregation，传 expr
   - 普通字段 → 询问聚合方式（提供默认推荐）
4. 构造参数
```

> ⚠️ **展示铁律**：禁止仅展示推荐指标而省略其余字段。全量字段列表必须默认完整输出，推荐项在列表中用 ✦ 内联标注。超过 300 个字段时才分批，否则一次全部输出。

**推荐逻辑**：

| 需求关键词 | 推荐指标字段 |
|---------|-----------|
| 广告/推广 | ads_total_spend_cny、ads_sales_cny、ads_acos、ads_clicks、ads_impressions |
| 销售/订单 | sales_amount_cny、order_qty、order_count |
| 物流/运费 | fi_first_leg_fee、shipping_cost |
| 毛利/利润 | gross_profit_cny、gross_profit_rate |
| 库存 | available_qty、inbound_qty、海外仓库存 |
| 对比/环比 | 提示 Step 9 可启用 dataComparison |

**文本展示格式**（全量列表，必须完整输出）：

```
"该数据集全部指标字段如下（✦ 为推荐，共 N 个）：

 序号 | 字段名              | 英文名                  | 类型   | 默认聚合
  1 ✦ | 广告费              | ads_total_spend_cny     | 金额   | SUM（推荐）
  2 ✦ | 广告销售额          | ads_sales_cny           | 金额   | SUM（推荐）
  3 ✦ | ACOS               | ads_acos                | 「公式」 | —（自动，推荐）
  4 ✦ | 广告点击量          | ads_clicks              | 数量   | SUM（推荐）
  5   | ROAS               | ads_roas                | 「公式」 | —（自动）
  6   | 广告展示量          | ads_impressions         | 数量   | SUM
  7   | 广告转化量          | ads_conversions         | 数量   | SUM
  8   | 广告转化率          | ads_conversion_rate     | 「公式」 | —（自动）
  ...（全部 N 个，完整列出）"
```

**AskUserQuestion 调用示例**（在文本列表之后，提供快捷多选）：

```
AskUserQuestion:
  questions:
    - question: "请选择指标字段（可多选）。
                 标注「公式」的字段系统自动处理，无需选择聚合方式。"
      header: "指标"
      multiSelect: true
      options:
        - label: "广告费（SUM）"
          description: "ads_total_spend_cny，广告总花费"
        - label: "广告销售额（SUM）"
          description: "ads_sales_cny，广告带来的销售额"
        - label: "ACOS（公式）"
          description: "ads_acos，广告成本销售比，系统自动计算"
        - label: "其他（输入序号或字段名）"
          description: "在输入框中输入上方列表中的序号或字段名，可多选"
```

> ⚠️ 推荐指标≤3 个时全部展示 + "其他"选项；>3 时展示最相关的 2 个 + "全选推荐的" + "其他"。用户选"其他"后可在输入框输入任意序号或字段名。

**普通字段聚合方式确认（批量优先）**：

判断规则：
- **全部默认 SUM**（所有选定普通字段均为数值型金额/数量）→ 用 `AskUserQuestion` 批量确认一次
- **存在非数值型字段**（如 ID 类、文本类字段被选为指标）→ 用 `AskUserQuestion` 对该字段单独确认
- **用户在选字段时已明确说"求均值/最大值"等** → 直接使用，无需再问

**批量确认 AskUserQuestion 示例**（适用于全部默认 SUM 场景）：

```
AskUserQuestion:
  questions:
    - question: "您选择的指标字段默认均使用 SUM（求和），确认？
                 如需修改某字段的聚合方式，请选择'其他'并在输入框说明。"
      header: "聚合方式"
      multiSelect: false
      options:
        - label: "全部 SUM（确认）"
          description: "广告费 → SUM，广告销售额 → SUM，广告点击量 → SUM"
        - label: "其他（指定调整）"
          description: "在输入框说明哪些字段改为 AVG/MAX/MIN 等，如 '广告费改为 AVG'"
```

**单字段确认 AskUserQuestion 示例**（仅在存在歧义字段时使用）：

```
AskUserQuestion:
  questions:
    - question: "'[字段名]' 的聚合方式？"
      header: "聚合方式"
      multiSelect: false
      options:
        - label: "SUM（求和）"
          description: "推荐：适合金额、数量类字段"
        - label: "AVG（平均）"
          description: "适合均值分析"
        - label: "MAX/MIN（极值）"
          description: "适合极值分析"
        - label: "其他（自定义）"
          description: "在输入框输入，如 COUNT_DISTINCT、MEDIAN、PERCENTILE 等"
```

**参数构造规则**：
- 普通字段：`{"field": "xxx", "aggregation": "SUM", "alias": "f_xxx"}`
- 公式字段：`{"field": "xxx", "alias": "f_xxx", "expr": "<summary_expression 的值>"}`
- alias 命名规则：统一使用 `f_` 前缀 + 字段英文名简写

---

## Step 5 — 筛选条件

**目标**：确定 `filters` 列表。

**交互方式**：分两轮，每轮均使用 `AskUserQuestion`。

**执行流程（分两轮，严格串行）**：

```
第一轮（必问）：时间范围 → 用 AskUserQuestion 提供常见选项
  → 用户确认时间范围后，才进入第二轮

第二轮（按需）：其他维度过滤 → 用 AskUserQuestion 提供常见过滤建议
  → 用户确认或选"不需要"后，Step 5 完成
```

> ⚠️ **铁律**：时间范围和其他过滤条件必须分两轮提问，禁止在同一条消息中同时呈现。先等用户确认时间范围，再询问其他过滤条件。

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

**第一轮 AskUserQuestion 示例**（时间范围，必问）：

```
AskUserQuestion:
  questions:
    - question: "请设置时间范围（必填）：
                 根据您说的'近30天'，推荐：2026-04-16 ~ 2026-05-15（共30天，含今天）。"
      header: "时间范围"
      multiSelect: false
      options:
        - label: "近30天（推荐）"
          description: "2026-04-16 ~ 2026-05-15，共30天"
        - label: "本月"
          description: "2026-05-01 ~ 2026-05-19，当月1日至今天"
        - label: "上月"
          description: "2026-04-01 ~ 2026-04-30，上个自然月"
        - label: "其他（自定义日期范围）"
          description: "在输入框中输入日期范围，如 '2026-01-01 ~ 2026-03-31' 或 '近7天'"
```

> ⚠️ 用户选"其他（自定义日期范围）"时可输入任意日期范围（如"2026-01-01 ~ 2026-03-31"）。AI 按时间处理铁律计算起止日期。

**第二轮 AskUserQuestion 示例**（其他过滤条件，时间确认后才展示）：

```
AskUserQuestion:
  questions:
    - question: "是否需要添加其他过滤条件？（可选）"
      header: "过滤条件"
      multiSelect: true
      options:
        - label: "限定特定部门"
          description: "如：只看 XX 部门"
        - label: "限定特定平台"
          description: "如：只看 Amazon"
        - label: "不需要其他过滤"
          description: "时间范围已够，不再添加"
        - label: "其他（自定义过滤条件）"
          description: "在输入框中输入，如 '指定 ASIN B0XXXXX' 或 '只看深圳部门'"
```

> ⚠️ 用户选"其他（自定义过滤条件）"输入具体过滤条件时（如"只看深圳部门的 Amazon 数据"），AI 负责解析为对应的 filter 参数。

**防呆规则**：
- "最近一个月"→ 必须澄清：用 `AskUserQuestion` 让用户选择"近30天"还是"本自然月"
- 跨月对比天数不对等 → 告知差异，用 `AskUserQuestion` 给出两方案让用户选
- 月初（1~5日）用户说"本月" → 提示本月数据很少，用 `AskUserQuestion` 确认是否想查上月

---

## Step 6 — 排序字段

**目标**：确定 `order_by` 配置。

**交互方式**：直接使用 `AskUserQuestion`，排序选项通常≤4 个，天然适合。

> ℹ️ **排序字段范围 = 已选维度 + 已选指标**，不是数据集全量字段。Step 6 无需展示全量字段列表，仅从用户已选的字段中给出选项（这是 Step 6 唯一不遵循"全量列举"原则的步骤）。

**推荐逻辑**：

| 需求动作词 | 推荐排序 |
|---------|--------|
| 排名/Top/最多/最高 | 主要指标 desc（倒序）|
| 趋势/变化 | date_id asc（正序）|
| 最低/最少 | 主要指标 asc（正序）|
| 未提及 | 主要指标 desc（默认推荐）|

**AskUserQuestion 调用示例**：

```
AskUserQuestion:
  questions:
    - question: "请选择排序方式："
      header: "排序"
      multiSelect: false
      options:
        - label: "按广告费从高到低（推荐）"
          description: "方便查看花费最多的部门"
        - label: "按日期正序排列"
          description: "看趋势变化"
        - label: "不排序"
          description: "不指定排序字段"
        - label: "其他（自定义排序）"
          description: "在输入框中输入，如 '按 ACOS 从高到低' 或 '按部门名正序'"
```

> ⚠️ 排序选项基于已选字段动态生成，保留推荐项 + "不排序" + "其他（自定义排序）"三个固定槽位，剩余 1 个槽位放次推荐项。

**参数构造**：`[{"field": "f_xxx", "desc": true}]`

---

## Step 7 — 获取条数

**目标**：确定 `limit`。

**交互方式**：直接使用 `AskUserQuestion`，选项天然≤4 个，完美匹配。

**推荐逻辑**：
- 需求含"Top N" → 直接使用 N
- 需求含"全部" → 推荐先用 50 条预览，提示全量可能较慢
- 未提及 → 推荐 20 条

**AskUserQuestion 调用示例**：

```
AskUserQuestion:
  questions:
    - question: "需要获取多少条数据？"
      header: "条数"
      multiSelect: false
      options:
        - label: "20 条（推荐）"
          description: "快速预览，适合初步查看数据分布"
        - label: "50 条"
          description: "较完整，适合确认结果正确性"
        - label: "100 条"
          description: "全面分析，数据量较大时响应稍慢"
        - label: "其他（自定义条数）"
          description: "在输入框中输入数字，如 '10'、'200' 或 '全部'"
```

> ⚠️ 用户选"其他（自定义条数）"后可输入自定义数字。如用户之前说"全部数据"，AI 应提示"建议先用 50 条预览，确认结果正确后再获取全量"。

---

## Step 8 — 是否分页

**目标**：确定是否需要多页查询（offset）。

**交互方式**：直接使用 `AskUserQuestion`，仅在触发条件下展示。

**触发规则**：

| 条件 | 处理方式 |
|------|---------|
| 用户明确说"全部数据/所有数据/不限条数" | 触发 Step 8，询问分页方案 |
| Step 7 设定的 limit > 100 | 触发 Step 8，提示数据量较多，建议分页获取 |
| limit ≤ 100 且未提及全量 | **直接跳过 Step 8**，进入 Step 9 |

**AskUserQuestion 调用示例**（仅在触发时展示）：

```
AskUserQuestion:
  questions:
    - question: "需要获取多页数据吗？当前每页 N 条。"
      header: "分页"
      multiSelect: false
      options:
        - label: "只要第 1 页"
          description: "offset=0，获取前 N 条"
        - label: "获取前 2 页"
          description: "offset=0 + offset=N，共 2N 条"
        - label: "获取前 5 页"
          description: "offset=0~4N，共 5N 条"
        - label: "其他（自定义页数）"
          description: "在输入框中输入页数，如 '3 页' 或 '全部页'"
```

---

## Step 9 — 是否需要对比数据

**目标**：确定是否启用 `data_comparison`，配置对比周期。

**交互方式**：直接使用 `AskUserQuestion` 展示对比方案选项。

**触发逻辑（默认跳过）**：

| 情况 | 处理方式 |
|------|---------|
| 需求含"环比/同比/对比/上期/上月/变化/趋势对比" | 主动推荐开启，用 `AskUserQuestion` 展示推荐方案 |
| 未提及任何对比关键词 | **直接跳过 Step 9**，进入 Step 10，参数摘要中标注"数据对比：未启用（如需对比可在此修改）" |

> ⚠️ **默认行为**：大多数查询不需要对比，跳过 Step 9 可减少不必要的提问。只有需求上下文中有明确对比意图时才触发本步骤。

**AskUserQuestion 调用示例**（主动推荐场景）：

```
AskUserQuestion:
  questions:
    - question: "您的需求中提到对比，是否开启数据对比？
                 开启后查询结果将额外返回：last_xxx（对比期）、diff_xxx（差值）、pct_xxx（变化率）。"
      header: "数据对比"
      multiSelect: false
      options:
        - label: "开启环比对比（推荐）"
          description: "当期：2026-04-16~05-15，对比期：2026-03-16~04-15"
          preview: "当期：2026-04-16 ~ 2026-05-15\n对比期（上月同期）：2026-03-16 ~ 2026-04-15"
        - label: "不开启对比"
          description: "仅查看当期数据"
        - label: "其他（自定义对比方案）"
          description: "在输入框中输入，如 '同比对比' 或 '2026-01-01 ~ 2026-03-31'"
```

> ⚠️ 用户选"其他（自定义对比方案）"后可输入自定义对比时间范围（如"同比对比"或"和上个季度对比"）。

**铁律**：`data_comparison` 必须同时传主周期 `filters`，缺一不可（否则报 QS-EXE-005）。

---

## Step 10 — 执行查询

**目标**：参数确认 → 执行 `query_simple` → 展示结果 → 进入分析框架。

**交互方式**：文本展示参数摘要 + `AskUserQuestion` 提供确认/修改选项。

**执行流程**：

```
1. 文本展示完整参数摘要（以下格式）
2. 用 AskUserQuestion 提供确认/修改选项
3. 用户确认后执行 query_simple
4. 成功 → 以表格展示数据（列名使用 verbose_name）→ 进入 analysis-guide.md
5. 失败 → 按错误码处理：
     QS-EXE-005 → 补充主周期 filters
     无字段错误 → 检查字段名拼写，重新 query_metadata 确认
     0行返回   → 提示检查过滤条件，用 AskUserQuestion 询问是否去掉部分条件重试
6. 无论成功失败 → 调用 ops-feedback 提交反馈
```

**参数摘要文本展示格式**：

```
"查询参数已配置完成，请确认：

 数据集：ads_summary_d（table_id=15）
 维度：日期（按月）、部门
 指标：广告费（SUM）、广告销售额（SUM）、ACOS（公式）
 筛选：日期 2026-04-16 ~ 2026-05-15
 排序：广告费 倒序
 获取条数：20 条
 数据对比：未启用（如需对比可返回修改 Step 9）"
```

**AskUserQuestion 调用示例**（确认/修改选项）：

```
AskUserQuestion:
  questions:
    - question: "以上参数是否正确？"
      header: "确认执行"
      multiSelect: false
      options:
        - label: "确认执行"
          description: "参数无误，立即执行查询"
        - label: "修改数据集（Step 2）"
          description: "重新选择数据集，Step 3~9 全部重置"
        - label: "修改维度/指标/筛选（Step 3~5）"
          description: "调整维度、指标或过滤条件"
        - label: "其他（自定义调整指令）"
          description: "在输入框中输入，如 'Step 7 改成 50 条' 或 '加一个维度' 或 '修改排序'"
```

> ⚠️ 用户选"其他（自定义调整指令）"后可输入任意调整指令（如"Step 7 改成 50 条"）。AI 根据回跳规则定位到对应步骤。修改完成后立即重新展示完整参数摘要。

**Step 10 参数摘要回跳规则**：

用户在参数摘要确认阶段说"要改 Step N"时，直接跳回对应步骤修改，无需重走前面所有步骤：

| 用户说 | 跳转到 | 其他步骤参数 |
|--------|--------|------------|
| 数据集不对 / Step 2 | Step 2 重新选数据集 | Step 3~9 全部重置 |
| 维度不对 / Step 3 | Step 3 重新选维度 | 原维度在列表中高亮 → 标注，Step 4~9 保留可复用 |
| 指标不对 / Step 4 | Step 4 重新选指标 | 原指标高亮 → 标注，Step 5~9 保留可复用 |
| 条件不对 / Step 5 | Step 5 重新设筛选 | Step 6~9 保留可复用 |
| 排序不对 / Step 6 | Step 6 仅修改排序 | 其他不变 |
| 条数不对 / Step 7 | Step 7 仅修改 limit | 其他不变 |
| 对比不对 / Step 9 | Step 9 仅修改 dataComparison | 其他不变 |

修改完成后立即重新展示完整参数摘要，等待用户再次确认执行。支持连续多步修改：用户在新摘要中仍可继续说"还要改 Step N"。

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
