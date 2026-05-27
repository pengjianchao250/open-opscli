---
name: ops-dataset-query
description: 简化查询接口指南 — 7 个纯业务概念完成数据查询
---

# 简化查询接口指南

本指南面向 AI Agent / Skill 开发者，介绍如何通过**极简业务语义参数**完成数据查询，无需理解 `translate`、`cacl_type` 等技术实现细节。

服务端 `SimpleQueryBuilder` 会自动将这些简化参数转换为完整 Query Payload 并执行。

---

## 字段选择优先级（必读）

执行查询前，选取维度/指标字段时，**必须按以下优先级顺序**判断：

| 优先级 | 来源 | CLI | MCP |
|--------|------|-----|-----|
| **1（最高）** | 用户偏好设置 | `opscli query preferences` | `query_preferences()` |
| **2** | 远端 metadata | `opscli query metadata --dataset xxx` | `query_metadata(dataset=xxx)` |
| **3（最低）** | 本地缓存 | `opscli query metadata`（无参） | `query_metadata()`（无参） |

**规则**：
- 偏好数据存在且包含目标数据集 → **直接使用偏好中的 `dimensions`/`metrics` 字段，禁止跳过**
- 偏好数据为空或不含目标数据集 → 再走远端 metadata
- 远端失败 → 回退本地缓存

---

## 何时使用简化接口

- ✅ 普通聚合查询（按维度分组 + 指标聚合）
- ✅ 数据对比（环比/同比，dataComparison）
- ✅ 趋势分析（MOY 月环比/年同比）
- ✅ 需要 translate 自动转换的维度过滤

**扩展能力**：图表查询（`query_chart`）支持多 query 自动合并、小计/总计等复杂场景。

---

## 7 个核心概念

> **⚠️ 参数命名约定（重要）**
>
> 本文档中的示例涉及两种不同的参数命名风格，**务必严格区分**：
>
> | 场景 | 命名风格 | 示例 |
> |------|---------|------|
> | JSON payload（发给后端 API 的数据） | **camelCase** | `tableId`、`dataComparison`、`orderBy` |
> | MCP Tool 函数调用参数 | **snake_case** | `table_id`、`data_comparison`、`order_by` |
> | CLI 命令行参数 | **kebab-case** | `--table-id`、`--data-comparison`、`--order-by` |
>
> **常见错误**：在 MCP 调用 `query_simple(tableId=15, ...)` → 报错 `Unexpected keyword argument`。**正确写法**：`query_simple(table_id=15, ...)`。

| 概念 | JSON payload 字段名 | MCP 参数名 | 说明 | 必填 |
|------|---------------------|-----------|------|------|
| 数据集 ID | `tableId` | `table_id` | 数据集 ID | 是 |
| 维度字段列表 | `dimensions` | `dimensions` | 分组依据 | 否 |
| 指标字段列表 | `metrics` | `metrics` | 聚合计算 | 否 |
| 过滤条件 | `filters` | `filters` | 统一列表 | 否 |
| 数据对比 | `dataComparison` | `data_comparison` | 环比/同比 | 否 |
| 排序规则 | `orderBy` | `order_by` | 排序 | 否 |
| 分页 | `limit` / `offset` | `limit` / `offset` | 分页 | 否（默认 limit=20） |

> 不需要理解的概念（服务端自动处理）：`translate`、`from`、`field_name` vs `bc.` 前缀、`cacl_type`、`params.dim/date`

### 时间范围与 dataComparison 规则

- 普通时间范围查询：只传 `filters`，用日期字段限定主查询周期。
- 环比、同比、上期对比等汇总对比：必须同时传 `filters` 与 `dataComparison`。
- `filters` 表示当前主查询周期；`dataComparison` 只表示对比周期。
- 不要只传 `dataComparison`。缺少主周期日期 `filters` 时，服务端可能生成非法 SQL，并返回类似 `QS-EXE-005 missing ')' at '{'` 的解析错误。

推荐模板：

```json
{
  "filters": [
    {"field": "ds_xxx.date_id", "operator": ">=", "value": "主周期开始日期"},
    {"field": "ds_xxx.date_id", "operator": "<=", "value": "主周期结束日期"}
  ],
  "dataComparison": {
    "field": "ds_xxx.date_id",
    "startDate": "对比周期开始日期",
    "endDate": "对比周期结束日期"
  }
}
```

---

## 参数详解

### dimensions — 维度

```json
[
  {"field": "dept_name", "alias": "f_dept"},
  {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}
]
```

- `field`：字段的 origin_name（不含数据集前缀，服务端自动拼接）
- `alias`：返回结果中的列名（建议使用 global_alias）
- `format`（可选）：日期格式化，如 `%Y-%m` 按月分组

### metrics — 指标

```json
[
  {"field": "price", "aggregation": "SUM", "alias": "f_price_sum"},
  {"field": "price", "aggregation": "SUM", "alias": "f_price_moy", "comparison": "MOY", "moyType": "MOM_MONTH"}
]
```

- `aggregation`：聚合方式（`SUM`、`COUNT`、`AVG`、`MAX`、`MIN`）。**注意：公式字段不要传此参数，见下方警告**
- `comparison`（可选）：`MOY`（月环比/年同比趋势）、`ACC`（累计）、`PPT`（百分点）
- `moyType`（可选）：`MOM_MONTH`（月环比）、`YOY_YEAR`（年同比）

> ⚠️ **公式字段警告**：如果字段的 metadata 中包含 `formula_config` 或 `summary_expression`（如 ACOS、ROAS、平均单价等比率/占比指标），**不要传 `aggregation`**。公式字段的聚合逻辑已内置在表达式中，再传 `aggregation`（如 SUM）会导致二次聚合，产生错误的语义结果（例如把每行的 ACOS 百分比加在一起，而非计算整体 ACOS）。
>
> **公式字段的正确处理方式**：
> - 聚合/分组查询：使用 `summary_expression` 作为 `field`，不传 `aggregation`
> - 明细查询：使用 `detail_expression` 作为 `field`，不传 `aggregation`
> - 简化接口中：直接用字段名传 `field`，不传 `aggregation`，服务端会自动识别公式字段并使用正确的表达式

### filters — 过滤条件

```json
[
  {"field": "platform_name", "operator": "in", "value": ["Amazon"]},
  {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
]
```

- `operator`：`=`、`!=`、`>`、`>=`、`<`、`<=`、`in`、`not in`、`between`

### dataComparison — 数据对比

```json
{
  "field": "date_id",
  "startDate": "2026-03-01",
  "endDate": "2026-03-22"
}
```

- 必须同时传 `filters` 中的主周期日期，否则报 `QS-EXE-005`
- 返回字段：`last_{alias}`（上期值）、`diff_{alias}`（差值）、`pct_{alias}`（环比百分比）

### orderBy — 排序

```json
[
  {"field": "f_price_sum", "desc": true}
]
```

- `field`：使用 metric/dimension 的 `alias`
- `desc`：`true` 降序，`false` 升序

---

## 完整示例

### 示例 1：普通聚合查询

```json
{
  "tableId": 1,
  "dimensions": [
    {"field": "dept_name", "alias": "f_dept"}
  ],
  "metrics": [
    {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
  ],
  "orderBy": [
    {"field": "f_fee_sum", "desc": true}
  ],
  "limit": 10
}
```

### 示例 2：数据对比（环比）

```json
{
  "tableId": 1,
  "dimensions": [
    {"field": "dept_name", "alias": "f_dept"}
  ],
  "metrics": [
    {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
  ],
  "dataComparison": {
    "field": "date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  },
  "limit": 10
}
```

**返回**：
```json
{
  "f_dept": "项目二部",
  "f_fee_sum": "68247.1073",
  "last_f_fee_sum": "73316.2101",
  "diff_f_fee_sum": "-5069.1028",
  "pct_f_fee_sum": "-0.0691"
}
```

### 示例 3：MOY 月环比趋势

```json
{
  "tableId": 1,
  "dimensions": [
    {"field": "dept_name", "alias": "f_dept"},
    {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}
  ],
  "metrics": [
    {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"},
    {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_moy", "comparison": "MOY", "moyType": "MOM_MONTH"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-04-22"]}
  ],
  "orderBy": [
    {"field": "f_month", "desc": true}
  ],
  "limit": 20
}
```

**返回**：`f_fee_moy_prev`、`f_fee_moy_diff`、`f_fee_moy_pct`

### 示例 4：子查询类型数据集

```json
{
  "tableId": 15,
  "dimensions": [
    {"field": "platform_name", "alias": "f_plat"}
  ],
  "metrics": [
    {"field": "ads_sales", "aggregation": "SUM", "alias": "f_sales_sum"}
  ],
  "filters": [
    {"field": "platform_name", "operator": "in", "value": ["Amazon"]},
    {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
  ],
  "limit": 5
}
```

---

## 注意事项

### catalog default_filters 需验证

catalog 中 `default_filters`（如 `amazon_cat=Amazon`）可能与实际数据不匹配。首次使用时应先不带 `default_filters` 探查数据是否存在，确认后再决定是否加上。若加上后返回 0 行，则去掉继续查询。

---

## CLI 调用方式

```bash
# 构造简化 payload（不执行）
opscli query simple --table-id 1 \
  --payload /tmp/simple.json \
  --output /tmp/payload.json

# 构造并立即执行
opscli query simple --table-id 1 \
  --payload /tmp/simple.json \
  --run --pretty

# 使用内联 JSON
opscli query simple --table-id 1 \
  --json '{"dimensions":[...],"metrics":[...]}' \
  --run --pretty
```

## MCP 调用方式

> **注意**：MCP Tool 参数使用 **snake_case** 命名（如 `table_id`、`data_comparison`、`order_by`），不是 JSON payload 的 camelCase（如 `tableId`、`dataComparison`、`orderBy`）。

```python
# 注意：MCP 参数用 snake_case，不是 camelCase！
# table_id（不是 tableId），data_comparison（不是 dataComparison）
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "price", "aggregation": "SUM", "alias": "f_price"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="xxx"
)
```

---

## 服务端内部参数映射

| 简化参数 | 完整 Query 对应 |
|----------|----------------|
| `dimensions` | `query.select`（无 aggregation 的字段）+ `query.groupBy` |
| `metrics` | `query.select`（带 aggregation 的字段） |
| `metrics.comparison=MOY` | 展开为 3 个 `select` 项（`cacl_type`: ORIGINAL/COMPARE/PERCENT） |
| `filters` | `query.where` |
| `filters`（含 translate 字段） | 自动添加 `translate` 字段 |
| `dataComparison` | 顶层 `dataComparison`（`switch: true`） |
| `orderBy` | `query.orderBy` |
| `limit` / `offset` | `query.limit` / `query.offset` |

---

## 扩展能力

- 图表查询（`opscli query chart`、`query_chart`）支持通过图表 UUID 获取查询结构并执行，适用于多 query、小计/总计等复杂场景
- 简化接口不满足需求时，可使用 `query_build_and_run`（MCP）或 `opscli query chart`（CLI）

---

## 错误处理

| 场景 | 错误码 | 解决方式 |
|------|--------|----------|
| 字段不存在 | 400 | 检查 `field` 是否为正确的 origin_name |
| 无数据集权限 | 403 | 确认用户有该数据集访问权限 |
| 缺少必填 alias | 400 | dimension / metric 必须提供 `alias` |
| 不支持 comparison 类型 | 400 | 仅支持 `MOY`、`ACC`、`PPT` |
| `dataComparison` SQL 解析错误 | `QS-EXE-005` 等 | 先检查是否缺少主周期日期 `filters`；缺少时补上当前周期日期过滤后重试，仍失败再降级为纯 `filters` 查询 |
| `dataComparison` 未返回对比字段 | 无错误码 | 若未返回对比字段，降级为分别查询两个周期后本地合并计算 |
| catalog `default_filters` 返回 0 行 | 无错误码 | `default_filters` 可能与实际数据不匹配，去掉后重试 |

---

## 字段命名约定速查

| 类型 | 格式 | 示例 |
|------|------|------|
| origin_name | `数据集别名.field_name`（服务端自动拼接） | `ds_d35ac6f3910c.dept_name` |
| global_alias | `f_` 前缀随机字符串 | `f_520fb9a831ccd52a` |
| verbose_name | 中文业务名 | `部门名称` |

> 构造简化参数时，`field` 使用 **origin_name**，`alias` 使用 **global_alias**。

## 字段歧义硬门禁

`opscli query simple` / `query_simple` 在执行前会对以下字段引用做 metadata 校验：

- `dimensions[].field`
- `metrics[].field`
- `filters[].field`，包括嵌套 `conditions`
- `dataComparison.field`

门禁规则：

- 字段必须在当前 `table_id` 对应 metadata 中存在
- 字段标识命中多个候选时会阻断查询，并返回候选字段；必须改用唯一 `global_alias` 或完整 `field_name`
- 模糊字段术语命中多个候选时会阻断查询，例如“销售额”“库存”“ACOS”等高频相似词
- 公式字段含 `summary_expression` / `detail_expression` / `formula_config` 时，禁止再传 `aggregation`
- 若 `metrics` 显式提供 `expr` 且没有 `field`，视为调用方已使用 metadata 中的公式表达式，跳过字段名解析

建议：当用户使用中文口语化字段名且有歧义时，先通过 `query_metadata(dataset=...)` 或 `opscli query metadata --dataset ...` 展示候选，再让用户确认口径。
