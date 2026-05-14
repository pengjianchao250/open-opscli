---
name: ops-dataset-query-mcp-simple
description: MCP 模式 — 简易版查询 Tool 详解（query_simple / query_build_and_run）
---

# MCP 简易版查询指南

本文档涵盖 MCP 模式下**简易版查询 Tool** 的详细说明与示例。

> **阅读前提**：先阅读 `references/simple-query-guide.md` 理解简化接口的通用参数结构。
>
> **文档引用顺序**：优先按本文档和 `simple-query-guide.md` 处理；**只有多次查询失败时**，才阅读 `references/data-query-service-dev-guide.md` 排查深层问题。

---

## Tool 说明

- **`query_simple`**（推荐）：基于简化参数直接执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。
- **`query_build_and_run`**：基于简化参数构造标准 query payload 并立即执行，一步返回数据结果。输入参数使用 CLI 风格字符串格式。

---

## 公式字段（Formula Field）处理规则

当 metric 字段的 metadata 中包含 `summary_expression` 或 `detail_expression` 时（如 ACOS、ROAS、平均单价等比率 / 占比指标），在 `metrics` 参数中需额外传入 `expr` 字段，指定服务端使用的完整公式表达式。

**选择规则**：
- **默认**（聚合 / 分组查询）：使用字段 metadata 中的 `summary_expression` 值
- **明细 / 详情查询**（用户提到"明细"、"详情"、"每一行"、"行级"等关键词时）：使用 `detail_expression` 值

**操作步骤**：
1. 先调用 `query_metadata` 获取字段 metadata，读取目标字段的 `summary_expression` 或 `detail_expression` 值
2. 将对应表达式字符串赋给 metric dict 中的 `expr` 字段
3. `aggregation`、`alias` 等字段照常传入；服务端识别到 `expr` 后以 `expr` 为准

**调用示例**（含公式字段 `acos`，默认聚合查询）：
```python
query_simple(
    table_id=15,
    dimensions=[{"field": "dev_team_name", "alias": "f_team"}],
    metrics=[
        {"field": "sp_total_spend_cny", "aggregation": "SUM", "alias": "f_sp_spend"},
        {
            "field": "acos",
            "aggregation": "SUM",
            "alias": "f_acos",
            "expr": "ROUND(total_spend_cny / sales_cny, 4)"   # ← summary_expression 的值
        }
    ],
    filters=[
        {"field": "platform_name", "operator": "=", "value": "Amazon"},
        {"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}
    ],
    order_by=[{"field": "f_sp_spend", "desc": True}],
    limit=200,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

**明细查询示例**（用户提到"明细"时，改用 `detail_expression`）：
```python
query_simple(
    table_id=15,
    metrics=[
        {
            "field": "days_on_hand",
            "alias": "f_days_on_hand",
            "expr": "ROUND(30 / (total_sell_qty / sell_avg_qty))"   # ← detail_expression 的值
            # 明细查询无需 aggregation
        }
    ],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}],
    limit=50,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

> ⚠️ **不传 `expr` 时的行为**：服务端仍会尝试自动识别公式字段并使用正确表达式，但显式传 `expr` 可以确保语义准确、避免版本差异导致的行为不一致。

---

## `query_simple`（推荐优先使用）

基于简化参数直接执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。**需要认证**。

> **⚠️ 参数命名约定（重要）**
>
> MCP Tool 参数使用 **snake_case** 命名（Python 风格）：
> - ✅ `table_id`、`data_comparison`、`order_by`
> - ❌ ~~`tableId`、`dataComparison`、`orderBy`~~（这些是 JSON payload 中的字段名，不是 MCP 参数名）
>
> 调用 MCP Tool 时，必须使用 snake_case 参数名，否则会报 `Missing required argument` 或 `Unexpected keyword argument` 错误。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table_id` | integer | **是** | 数据集 ID |
| `dimensions` | list[dict] | 否 | 维度列表，`{"field": "dept_name", "alias": "f_xxx", "format": "..."}` |
| `metrics` | list[dict] | 否 | 指标列表，`{"field": "...", "aggregation": "SUM", "alias": "...", "comparison": "MOY"}` |
| `filters` | list[dict] | 否 | 过滤条件，`{"field": "...", "operator": "in", "value": [...]}` |
| `data_comparison` | dict | 否 | 数据对比的对比周期，`{"field": "...", "startDate": "...", "endDate": "..."}`；启用时必须同时用 `filters` 传主周期日期 |
| `order_by` | list[dict] | 否 | 排序，`{"field": "f_xxx", "desc": true}` |
| `limit` | integer | 否 | 返回行数上限，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |

**调用示例**：
```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

**简化参数结构**详见 `references/simple-query-guide.md`。

---

## `query_build_and_run`

基于简化参数构造标准 query payload 并立即执行，一步返回数据结果。**需要认证**。

参数使用 CLI 风格的字符串格式（与 `query_simple` 的 dict 格式不同）：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 二选一 | 数据集别名 |
| `table_id` | integer | 二选一 | 数据集表 ID |
| `dimensions` | string[] | 否 | 维度列表，格式 `field_name[:alias]` |
| `metrics` | string[] | 否 | 指标列表，格式 `field_name:aggregation[:alias]` |
| `where_conditions` | string[] | 否 | 筛选条件，格式 `field\|operator\|value_json` |
| `where_json` | string | 否 | where 条件 JSON 字符串 |
| `having_conditions` | string[] | 否 | having 条件 |
| `order_by` | string[] | 否 | 排序，格式 `expr[:asc\|desc]` |
| `limit` | integer | 否 | 返回行数上限，默认 20 |
| `offset` | integer | 否 | 偏移量，默认 0 |
| `dry_run` | boolean | 否 | 仅生成 SQL 不执行 |
| `data_comparison` | string | 否 | 数据对比，格式 `field,start_date,end_date` |
| `skills_dir` | string | 否 | 指定 Skill 目录 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

**典型用法**：
```python
query_build_and_run(
    table_id=1,
    dimensions=["date_id", "country_code"],
    metrics=["sales:SUM"],
    where_conditions=["date_id|>=|\"2026-01-01\""],
    limit=50,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

> 如果 `jwt` 未提供，服务器会自动用 `session_id` 向后端换取 JWT，无需调用方手动管理。

---

## dataComparison 简化调用示例

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    # 主周期放 filters；对比周期放 data_comparison
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```

## MOY 月环比简化调用示例

```python
query_simple(
    table_id=1,
    dimensions=[
        {"field": "dept_name", "alias": "f_dept"},
        {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}
    ],
    metrics=[
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"},
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_moy", "comparison": "MOY", "moyType": "MOM_MONTH"}
    ],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-04-22"]}],
    order_by=[{"field": "f_month", "desc": True}],
    limit=20,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回列：f_dept, f_month, f_fee_sum, f_fee_moy_prev, f_fee_moy_diff, f_fee_moy_pct
```

> `data_comparison` 不是独立日期过滤器。使用它时，`filters` 必须表示当前主查询周期，`data_comparison` 表示对比周期。不要只传 `data_comparison`；若 `query_simple` 返回 `QS-EXE-005 missing ')' at '{'` 等 SQL 解析错误，先补上主周期日期 `filters` 后重试，仍失败再降级为纯 `filters` 查询。

---

## 典型工作流（简易版）

### 探索数据集 → 构造 → 执行（已知数据集时）

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 通过本地索引确认字段名（search / fetch）
# 2. 必要时查看完整 metadata（query_metadata）

# 3. 使用简化接口构造并执行
query_simple(
    table_id=1,
    dimensions=[{"field": "date_id", "alias": "f_date"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    order_by=[{"field": "f_fee_sum", "desc": True}],
    limit=50,
    session_id="xxx"
)
```

### 环比查询（dataComparison — 简化接口）

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 使用简化接口执行 dataComparison 查询
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    # 主周期放 filters；对比周期放 data_comparison
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```
