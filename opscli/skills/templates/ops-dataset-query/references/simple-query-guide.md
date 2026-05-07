---
name: ops-dataset-query
description: 简化查询接口指南 — 7 个纯业务概念完成数据查询
---

# 简化查询接口指南

本指南面向 AI Agent / Skill 开发者，介绍如何通过**极简业务语义参数**完成数据查询，无需理解 `innerWhere`、`translate`、`cacl_type` 等技术实现细节。

服务端 `SimpleQueryBuilder` 会自动将这些简化参数转换为完整 Query Payload 并执行。

---

## 何时使用简化接口

- ✅ 普通聚合查询（按维度分组 + 指标聚合）
- ✅ 数据对比（环比/同比，dataComparison）
- ✅ 趋势分析（MOY 月环比/年同比）
- ✅ 子查询类型数据集（inner_where_enabled=true）
- ✅ 需要 translate 自动转换的维度过滤

**向后兼容**：完整 query 接口仍然可用，复杂场景可继续手写 payload。

---

## 7 个核心概念

| 概念 | 说明 | 必填 |
|------|------|------|
| `tableId` | 数据集 ID | 是 |
| `dimensions` | 维度字段列表（分组依据） | 否 |
| `metrics` | 指标字段列表（聚合计算） | 否 |
| `filters` | 过滤条件（统一列表，不分 where/innerWhere） | 否 |
| `dataComparison` | 数据对比（环比/同比） | 否 |
| `orderBy` | 排序规则 | 否 |
| `limit` / `offset` | 分页 | 否（默认 limit=20） |

> 不需要理解的概念（服务端自动处理）：`innerWhere`、`translate`、`from`、`field_name` vs `bc.` 前缀、`cacl_type`、`params.dim/date`

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
  ],
  "metrics": [
    {"field": "price", "aggregation": "SUM", "alias": "f_price_sum"},
    {"field": "price", "aggregation": "SUM", "alias": "f_price_moy", "comparison": "MOY", "moyType": "MOM_MONTH"}
  ],
  "filters": [
    {"field": "platform_name", "operator": "in", "value": ["Amazon"]},
    {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
  ],
  "dataComparison": {
    "field": "date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  },
  "orderBy": [
    {"field": "f_price_sum", "desc": true}
  ],
  "metrics": [
    {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}
  ],
  "filters": [
    {"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}
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

> 服务端自动将 `platform_name` 条件放入 `innerWhere[1]`，日期条件放入外层 `where`。

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

```python
# 构造并执行简化查询
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

## 与完整 Query 的映射关系

| 简化参数 | 完整 Query 对应 |
|----------|----------------|
| `dimensions` | `query.select`（无 aggregation 的字段）+ `query.groupBy` |
| `metrics` | `query.select`（带 aggregation 的字段） |
| `metrics.comparison=MOY` | 展开为 3 个 `select` 项（`cacl_type`: ORIGINAL/COMPARE/PERCENT） |
| `filters` | `query.where`（日期条件）+ `query.innerWhere[1]`（业务条件，子查询时） |
| `filters`（含 translate 字段） | 自动添加 `translate` 字段 |
| `dataComparison` | 顶层 `dataComparison`（`switch: true`） |
| `orderBy` | `query.orderBy` |
| `limit` / `offset` | `query.limit` / `query.offset` |

---

## 向后兼容说明

- 完整 query 接口（`opscli query run`、`query_run`）仍然可用
- 简化接口不满足需求时，可手写完整 payload 透传
- `opscli query build`（基于 `--dimension`/`--metric` 参数）与简化接口并存，按需选择

---

## 错误处理

| 场景 | 错误码 | 解决方式 |
|------|--------|----------|
| 字段不存在 | 400 | 检查 `field` 是否为正确的 origin_name |
| 无数据集权限 | 403 | 确认用户有该数据集访问权限 |
| 缺少必填 alias | 400 | dimension / metric 必须提供 `alias` |
| 不支持 comparison 类型 | 400 | 仅支持 `MOY`、`ACC`、`PPT` |
| `dataComparison` SQL 解析错误 | `QS-EXE-005` 等 | 先检查是否缺少主周期日期 `filters`；缺少时补上当前周期日期过滤后重试，仍失败再降级为纯 `filters` 查询 |

---

## 字段命名约定速查

| 类型 | 格式 | 示例 |
|------|------|------|
| origin_name | `数据集别名.field_name`（服务端自动拼接） | `ds_d35ac6f3910c.dept_name` |
| global_alias | `f_` 前缀随机字符串 | `f_520fb9a831ccd52a` |
| verbose_name | 中文业务名 | `部门名称` |

> 构造简化参数时，`field` 使用 **origin_name**，`alias` 使用 **global_alias**。
