---
name: query-patterns
description: 数据对比与高级计算通用参考（CLI / MCP 共享）
---

# 数据对比与高级计算

> 本文档为 CLI 模式和 MCP 模式共享的查询知识参考。
> 模式特定的调用示例请参见 `cli.md` 或 `mcp.md`。

---

## 高级查询说明

详细规则见 `references/data-query-service-dev-guide.md`，核心章节：

| 场景 | 参考章节 |
|------|---------|
| innerWhere、子查询数据集 | 第三章 数据集类型详解 |
| WHERE 操作符、嵌套条件、translate | 第五章 WHERE 条件构建指南 |
| dataComparison 数据对比 | 第六章 |
| 多次查询（交叉表/透视表/堆叠图） | 第七章 |
| SELECT 字段、聚合函数、高级计算(MOY/ACC/PPT) | 第八章 |
| 权限占位符 | 第四章 |
| 分页与排序 | 第九章 |

---

## 方案选择决策流程

```
用户需要比较两个时间段的数据？
├── YES → 需要按时间粒度（日/月）分组展示趋势？
│         ├── YES → 使用 MOY 高级计算（comparison 写在 select 字段内）
│         └── NO  → 需要当期 vs 对比期汇总对比？
│                   ├── YES → 使用 dataComparison（服务端一次 SQL，推荐首选）
│                   └── NO  → 普通聚合查询
└── NO  → 普通聚合查询
```

---

## dataComparison 数据对比

> 服务端将当期和对比期合并为**一次 SQL**（条件聚合），每个度量字段自动裂变为 4 个字段。

**字段裂变规则**（以别名 `total_price` 为例）：

| 裂变字段 | 含义 |
|---------|------|
| `total_price` | 当期值 |
| `last_total_price` | 对比期值 |
| `diff_total_price` | 绝对差值（当期 - 对比期） |
| `pct_total_price` | 变化率（差值 / ABS(对比期)），上期为 0 时返回 null |

**payload 核心结构**：

```json
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "ds_xxx.price", "alias": "total_price", "aggregation": "SUM"},
      {"expr": "ds_xxx.order_qty", "alias": "total_qty", "aggregation": "SUM"}
    ],
    "groupBy": ["dept_name"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-04-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [{"expr": "total_price", "desc": true}],
    "limit": 50,
    "offset": 0
  },
  "dataComparison": {
    "switch": true,
    "field": "ds_xxx.date_id",
    "startDate": "2026-03-01",
    "endDate": "2026-03-22"
  }
}
```

**适用场景**：当期（如本月 1-22 日） vs 对比期（如上月同期 1-22 日）的汇总数据对比，**同期天数对等**，适合月度/季度环比汇总看板。

---

## MOY 同环比（高级计算）

> 服务端通过窗口函数 `LAG()` 计算，**`comparison` 字段写在 `select` 内部**。

**前提条件**：`groupBy` 中**必须同时包含日期维度和其他业务维度**。

**type 枚举速查**：

| 类型 | `type` 值 | groupBy 日期格式 |
|------|-----------|----------------|
| 月环比 | `MOM_MONTH` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m')` |
| 日环比 | `MOM_DAY` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |
| 周环比 | `MOM_WEEK` | `DATE_FORMAT(ds_xxx.date_id, '%x-%v')` |
| 月同比 | `YOY_MONTH` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |
| 年同比 | `YOY_YEAR` | `DATE_FORMAT(ds_xxx.date_id, '%Y-%m-%d')` |

**`cacl_type` 字段语义**（重要，容易误解）：

| `cacl_type` | 字段值含义 | 说明 |
|-------------|-----------|------|
| `ORIGINAL` | **上期值（LAG）** | 不是当期原始值！是前一期的聚合结果 |
| `COMPARE` | 当期 - 上期 | 正数=增长，负数=下滑 |
| `PERCENT` | (当期 - 上期) / ABS(上期) | 环比变化率，上期为 0 时返回 null |

> 当期实际值 = `ORIGINAL 字段值` + `COMPARE 字段值`

**完整 payload 示例（月环比，按部门）**：

```json
{
  "tableId": 1104,
  "query": {
    "select": [
      {"expr": "ds_xxx.dept_name", "alias": "dept_name"},
      {"expr": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')", "alias": "month"},
      {
        "expr": "ds_xxx.price",
        "alias": "price_prev",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "ORIGINAL",
          "aggregation": "SUM"
        }
      },
      {
        "expr": "ds_xxx.price",
        "alias": "price_diff",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "COMPARE",
          "aggregation": "SUM"
        }
      },
      {
        "expr": "ds_xxx.price",
        "alias": "price_pct",
        "comparison": "MOY",
        "params": {
          "date": "DATE_FORMAT(ds_xxx.date_id, '%Y-%m')",
          "dim": ["dept_name"],
          "type": "MOM_MONTH",
          "cacl_type": "PERCENT",
          "aggregation": "SUM"
        }
      }
    ],
    "groupBy": ["dept_name", "month"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-03-01"},
        {"field": "ds_xxx.date_id", "operator": "lte", "value": "2026-04-22"}
      ]
    },
    "orderBy": [
      {"expr": "month", "desc": true},
      {"expr": "price_diff", "desc": true}
    ],
    "limit": 100,
    "offset": 0
  }
}
```

**结果读取说明**：
- 当月行（如 `2026-04`）：`price_prev` = 上月值，`price_diff` = 本月增减，`price_pct` = 环比率
- 上月行（如 `2026-03`）：`price_prev` = 上上月值，其他同理
- WHERE 范围需覆盖**当期 + 对比期**（至少两个完整粒度），否则最早一期 `price_prev` 为 NULL

**适用场景**：按月/日/周分组的趋势图、时序对比；注意 MOY 用整个历史周期做 LAG，与 `dataComparison` 的同期对比不同，**月中查询时本月 vs 上月完整月存在天数不等的偏差**。

---

## ACC 累加计算

> 按时间序列滚动累计（Running Total），适合 YTD 累计销售额等场景。

```json
{
  "expr": "ds_xxx.price",
  "alias": "price_acc",
  "comparison": "ACC",
  "params": {
    "dim": [],
    "aggregation": "SUM"
  }
}
```

> `dim` 当前固定传空数组 `[]`，暂不支持分组累加。

---

## PPT 占比计算

> 当前维度指标值 / 全局总量，适合各部门销售额占比等场景。

```json
{
  "expr": "ds_xxx.price",
  "alias": "price_ppt",
  "comparison": "PPT",
  "params": {
    "dim": [],
    "aggregation": "SUM"
  }
}
```
