---
name: ops-dataset-query-cli-simple
description: CLI 模式 — 简易版查询命令详解（opscli query simple）
---

# CLI 简易版查询指南

本文档涵盖 CLI 模式下**简易版查询命令** `opscli query simple` 的详细说明与示例。

> **阅读前提**：先阅读 `references/simple-query-guide.md` 理解简化接口的通用参数结构。
>
> **文档引用顺序**：优先按本文档和 `simple-query-guide.md` 处理；**只有多次查询失败时**，才阅读 `references/data-query-service-dev-guide.md` 排查深层问题。

---

## 命令说明

- **`opscli query simple`**（推荐）：基于简化参数构造并执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。普通聚合、数据对比、MOY 趋势等场景优先使用。

---

## `opscli query simple`（推荐优先使用）

基于简化参数构造并执行查询。服务端自动处理 `translate`、`MOY` 展开等技术细节。

```
选项：
  --table-id INTEGER   数据集 ID（必填）
  --payload TEXT       简化查询 JSON 文件路径（与 --json 二选一）
  --json TEXT          简化查询 JSON 字符串（与 --payload 二选一）
  --output TEXT        将 payload 写入指定文件
  --run                构造后立即执行查询
  --pretty             格式化 JSON 输出
```

> **【强制】`--payload` 与 `--json` 互斥**：两者只能使用其中一个，不可同时传入。
> - `--payload`：从文件读取 JSON（适合复杂/多行查询）
> - `--json`：直接传入 JSON 字符串（适合简单查询）
> - 同时传入时 CLI 会报错

```bash
# 正确：使用 --json 内联传入
opscli query simple --table-id 1 \
  --json '{"dimensions":[{"field":"dept_name","alias":"f_dept"}],"metrics":[{"field":"fi_first_leg_trailer_fee","aggregation":"SUM","alias":"f_fee_sum"}],"filters":[{"field":"date_id","operator":"between","value":["2026-04-01","2026-04-22"]}],"limit":10}' \
  --run --pretty

# 正确：使用 --payload 从文件读取
opscli query simple --table-id 1 \
  --payload /tmp/simple.json \
  --run --pretty
```

**简化参数结构**详见 `references/simple-query-guide.md`。

---

## 公式字段（Formula Field）处理规则

当 metric 字段的 metadata 中包含 `summary_expression` 或 `detail_expression` 时（如 ACOS、ROAS、平均单价等比率 / 占比指标），在 `metrics` JSON 中需额外传入 `expr` 字段，指定服务端使用的完整公式表达式。

**选择规则**：
- **默认**（聚合 / 分组查询）：使用字段 metadata 中的 `summary_expression` 值
- **明细 / 详情查询**（用户提到"明细"、"详情"、"每一行"、"行级"等关键词时）：使用 `detail_expression` 值

**操作步骤**：
1. 先执行 `opscli query metadata --dataset <alias> --pretty` 获取字段 metadata，读取目标字段的 `summary_expression` 或 `detail_expression` 值
2. 将对应表达式字符串赋给 metric 对象的 `expr` 字段
3. `aggregation`、`alias` 等字段照常传入；服务端识别到 `expr` 后以 `expr` 为准

**示例**（含公式字段 `acos`，默认聚合查询）：

```bash
opscli query simple --table-id 15 \
  --json '{
    "dimensions": [{"field": "dev_team_name", "alias": "f_team"}],
    "metrics": [
      {"field": "sp_total_spend_cny", "aggregation": "SUM", "alias": "f_sp_spend"},
      {
        "field": "acos",
        "aggregation": "SUM",
        "alias": "f_acos",
        "expr": "ROUND(total_spend_cny / sales_cny, 4)"
      }
    ],
    "filters": [
      {"field": "platform_name", "operator": "=", "value": "Amazon"},
      {"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}
    ],
    "orderBy": [{"field": "f_sp_spend", "desc": true}],
    "limit": 200
  }' \
  --run --pretty
```

**明细查询示例**（用户提到"明细"时，改用 `detail_expression`）：

```bash
opscli query simple --table-id 15 \
  --json '{
    "metrics": [
      {
        "field": "days_on_hand",
        "alias": "f_days_on_hand",
        "expr": "ROUND(30 / (total_sell_qty / sell_avg_qty))"
      }
    ],
    "filters": [
      {"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}
    ],
    "limit": 50
  }' \
  --run --pretty
```

> ⚠️ **不传 `expr` 时的行为**：服务端仍会尝试自动识别公式字段并使用正确表达式，但显式传 `expr` 可以确保语义准确、避免版本差异导致的行为不一致。

---

## 典型工作流（简易版）

### 探索数据集 → 构造 → 执行（已知数据集时）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 通过本地索引确认字段名
# 2. 查看完整 metadata（获取 table_id 和字段信息）
opscli query metadata --dataset sales_order_d --pretty

# 3. 使用简化接口构造并执行
opscli query simple \
  --table-id 1 \
  --json '{
    "dimensions": [{"field": "date_id", "alias": "f_date"}],
    "metrics": [{"field": "order_cost", "aggregation": "SUM", "alias": "f_total_cost"}],
    "filters": [{"field": "date_id", "operator": "between", "value": ["2024-01-01", "2024-12-31"]}],
    "orderBy": [{"field": "f_total_cost", "desc": true}],
    "limit": 50
  }' \
  --run --pretty
```

### 环比查询（MOY 月环比 — 简化接口）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 使用简化接口执行 MOY 查询（1 行 metrics 声明，服务端自动展开为 3 列）
opscli query simple --table-id 1 \
  --json '{
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
    "orderBy": [{"field": "f_month", "desc": true}],
    "limit": 20
  }' \
  --run --pretty

# 返回列：f_dept, f_month, f_fee_sum, f_fee_moy_prev, f_fee_moy_diff, f_fee_moy_pct
```

### 环比查询（dataComparison — 简化接口）

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 使用简化接口执行 dataComparison 查询
opscli query simple --table-id 1 \
  --json '{
    "dimensions": [{"field": "dept_name", "alias": "f_dept"}],
    "metrics": [{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    "filters": [{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    "dataComparison": {"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    "limit": 10
  }' \
  --run --pretty

# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```

> 完整简化参数说明见 `references/simple-query-guide.md`。
