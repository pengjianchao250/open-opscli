---
name: ops-dataset-query-mcp-advanced
description: MCP 模式 — 完整版查询 Tool 详解（query_build / query_run / query_chart / 降级方案 / MCP 辅助脚本）
---

# MCP 完整版查询指南

本文档涵盖 MCP 模式下所有**完整版/高级查询 Tool** 和 **MCP 辅助脚本** 的详细说明与示例。

> **阅读前提**：确保已阅读 `references/simple-query-guide.md` 和 `references/mcp-simple-guide.md`，确认简化接口确实无法满足需求。
>
> **文档引用顺序**：本文档配合 `references/data-query-service-dev-guide.md` 使用（多次失败时参考）。
>
> **【强制禁用】涉及 `innerWhere` 的数据集（子查询类型，`inner_where_enabled=true`）禁止使用 `query_run`，无论需求多复杂都只能使用 `query_simple`。**

---

## 完整版查询 Tool 说明

- **`query_build`**：基于简化参数构造**标准完整 query payload**（含 select/where/groupBy 等），不执行查询。**不需要认证**。输出的是完整版 payload 结构，供 `query_run` 使用。
- **`query_run`**：读取本地 payload JSON 文件并转发至服务端执行查询。仅当简化接口和 `query_build` 均无法满足需求时使用。
- **`query_chart`**：通过 `chart_uuid` 获取图表查询结构，可选立即执行所有查询并合并输出结果。涉及多 query、小计/总计等复杂场景。

---

## `query_build`

基于简化参数构造标准完整 query payload（不执行查询）。**不需要认证**。

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
| `output_path` | string | 否 | 将 payload 写入本地文件路径 |
| `skills_dir` | string | 否 | 指定 Skill 目录 |

**参数格式**：

```python
# dimension：field_name|global_alias|verbose_name[:alias]
query_build(
    table_id=1,
    dimensions=["date_id", "country_id:country"],
    metrics=["order_cost:sum:total_cost", "order_id:count_distinct:order_count"],
    where_conditions=["date_id|>=|\"2024-01-01\""],
    order_by=["total_cost:desc"],
    limit=50,
    output_path="/tmp/query.json",
    skills_dir="/Users/mask/.config/opencode/skills"
)
```

> 完整聚合函数列表见 `references/data-query-service-dev-guide.md` 第八章。

**公式指标特殊规则**：
- 如果字段 metadata 中包含 `formula_config` / `summary_expression` / `detail_expression`，该指标应按公式字段处理
- 手写 payload 时，聚合 / 分组查询应直接使用完整公式表达式结构，不额外传 `aggregation`
- 使用 `query_build` 时，仍然可以传 `global_alias|verbose_name:aggregation[:alias]`，Tool 会根据 metadata 自动展开为完整表达式 payload
- 明细查询：使用 `detail_expression`
- 聚合 / 分组查询：使用 `summary_expression`

**常见易错对照**：
- 普通求和指标：`price:sum` 或手写 `{ "expr": "ds_xxx.price", "alias": "f_price", "aggregation": "SUM" }`
- 公式占比指标：手写 `{ "expr": "ROUND(SUM(dsp)/SUM(price), 4)", "alias": "f_yZZfW7cNu8nYMGCS" }`
- 错误写法：`sell_qty_days:sum`、`avg_original_price_cny:sum` 这类公式字段继续套普通聚合

---

## `query_run`

读取本地 payload JSON 文件并转发至服务端执行查询。仅当简化接口无法满足需求时使用。**需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload_path` | string | 是 | 本地 payload 文件路径 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

> **【强制】手写 payload 的 `query.select` 结构要求**
>
> 服务端校验规则：`query.select.*.expr` 和 `query.select.*.alias` 为**必填字段**。
>
> - `expr`：字段表达式，格式为 `数据集别名.字段名`（如 `ds_d35ac6f3910c.dept_name`），或完整公式
> - `alias`：输出列名，建议使用 `global_alias`（如 `f_520fb9a831ccd52a`）或自定义英文标识
> - `aggregation`：聚合方式（如 `SUM`、`COUNT`），指标字段需提供，维度字段不传
>
> **正确**：`{"expr": "ds_xxx.dept_name", "alias": "f_dept"}`
> **错误**：`{"global_alias": "f_dept"}` — 缺少 `expr`，会导致 422
>
> **建议**：优先使用 `query_build_and_run` 或 `query_simple` 自动构造 payload，避免手写出错。

**调用示例**：
```python
query_run(
    payload_path="/tmp/query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

---

## `query_chart`

通过 `chart_uuid` 获取图表查询结构，可选立即执行所有查询并合并输出结果。**需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chart_uuid` | string | **是** | 图表 UUID（如 `4NQ5f66sU9`） |
| `run` | boolean | 否 | 获取后立即执行所有查询并合并输出，默认 `false` |
| `dry_run` | boolean | 否 | 仅生成 SQL，不执行查询，默认 `false` |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

**仅获取图表结构**：
```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# → {chart_uuid: "4NQ5f66sU9", datasets: [...], queries: [...]}
```

**获取并执行查询**：
```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

**返回结构**（`run=False` 时）：
```python
{
    "chart_uuid": "4NQ5f66sU9",
    "datasets": [
        {
            "dataset_alias": "ds_xxx",
            "tableId": 1,
            "dataSource": "doris_analytics",
            "filterable_fields": [...],
            "fields": [...],
        }
    ],
    "queries": [
        {
            "query_index": 0,
            "dataset_alias": "ds_xxx",
            "tableId": 1,
            "dataSource": "doris_analytics",
            "query": {...},
            "field_mappings": [...],
        }
    ]
}
```

**返回结构**（`run=True` 时）：
```python
{
    "chart_uuid": "4NQ5f66sU9",
    "queries": [
        {
            "index": 0,
            "table_id": 1,
            "data_source": "doris_analytics",
            "payload": {...},      # 构造的查询 payload
            "result": {...},       # 成功时的查询结果
            "error": {...},        # 失败时的错误信息
        }
    ],
    "merged": {
        "rows": [...],             # 所有 rows 扁平合并（加 _query_index）
        "meta": {
            "rowCount": 150,
            "queryCount": 3,
            "successCount": 3
        }
    }
}
```

> 推荐把 `datasets` 视为公共字段语义层，把 `queries` 视为执行层；Skill 应优先消费服务端字段语义，避免重复做本地推断。
>
> 当图表包含多个 query 时，每个 query 独立执行，失败时记录错误但不中断后续 query。

---

## 辅助 Tool 详情

以下 Tool 用于数据集/字段检索和意图分析，**不直接执行数据查询**。

### `query_metadata`

读取指定数据集的 query metadata（字段定义、可用聚合方式等）。**不需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 二选一 | dataset_alias |
| `table_id` | integer | 二选一 | table_id |
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |

**调用示例**：
```python
query_metadata(dataset="sales_order_d")
query_metadata(table_id=123, skills_dir="/Users/mask/.config/opencode/skills")
```

---

### `query_catalog`

读取数据集业务语义索引（dataset catalog）。默认远端优先，远端失败时回退本地缓存；用于自然语言需求匹配 intents 后选出候选数据集。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |
| `source` | string | 否 | 数据来源：`remote`（默认）或 `local` |
| `fallback_local` | boolean | 否 | source=remote 时，远端失败是否回退本地缓存，默认 true |
| `session_id` | string | 否 | OAuth 授权后的 Session ID |
| `jwt` | string | 否 | 已有 JWT |

**调用示例**：
```python
query_catalog()
query_catalog(source="local")
query_catalog(source="remote", fallback_local=False)
query_catalog(skills_dir="/Users/mask/.config/opencode/skills")
```

**返回结构**：
```json
{
  "success": true,
  "data": {
    "version": "v1.0.0",
    "intent_count": 15,
    "intents": [
      {
        "use_case": "销售订单分析",
        "keywords": ["订单", "销售额", "出库"],
        "scenario": "查看某时段内的销售订单汇总数据",
        "priority": 1,
        "dataset_alias": "sales_order_d"
      }
    ],
    "query_strategy": {}
  }
}
```

---

## MCP 环境辅助脚本（无状态模式）

以下脚本位于 `scripts/` 目录，**专为 MCP 无状态模式设计**，零 opscli 依赖，仅通过文件输入/输出与 MCP Tool 配合。

### `query_mcp.py` — 本地 Payload 构造器

使用本地 CSV 索引将简化参数转换为标准 query payload JSON 文件，供 `query_run` 使用。

**特点**：
- 字段别名解析（`global_alias > field_name > verbose_name`）
- 字段歧义自动消歧（优先选取原始字段）
- 支持 `data_comparison` 自动构造 `dataComparison` 对象

**子命令**：

```bash
# build：构造 payload 并写入 JSON 文件
python scripts/query_mcp.py build \
  --dataset sales_order_d \
  --dimension date_id \
  --metric "order_cost:sum:total_cost" \
  --where "date_id|>=|\"2024-01-01\"" \
  --order-by "total_cost:desc" \
  --output /tmp/query.json

# 附带 dataComparison 环比
python scripts/query_mcp.py build \
  --dataset sales_order_d \
  --dimension dept_name \
  --metric "price:sum:total_price" \
  --where "date_id|>=|\"2026-04-01\"" \
  --data-comparison "date_id,2026-03-01,2026-03-22" \
  --output /tmp/query.json

# metadata：查看本地数据集 metadata（无需认证）
python scripts/query_mcp.py metadata --dataset sales_order_d --pretty
```

**输出**（`build` 成功时）：
```json
{
  "success": true,
  "data": {
    "output": "/tmp/query.json",
    "payload": {
      "tableId": 1,
      "query": {
        "select": [...],
        "groupBy": [...],
        "where": {...},
        "orderBy": [...],
        "limit": 20,
        "offset": 0
      }
    }
  }
}
```

**配合 MCP Tool 使用**：
```python
# 1. 先用 query_mcp.py 构造 payload JSON（无需认证）
# 2. 再通过 query_run 执行查询（需要认证）
query_run(
    payload_path="/tmp/query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

---

### `chart_map_mcp.py` — chart 字段映射

将 MCP `query_chart` 返回的 chart 结果中的 `global_alias` / `query_alias` 映射为可读的 `verbose_name` / `field_name`。

**用法**：
```bash
# 仅映射查询结构
python scripts/chart_map_mcp.py --input /tmp/chart_result.json --pretty

# 映射查询结构 + 结果行数据列名
python scripts/chart_map_mcp.py --input /tmp/chart_result.json --map-results --pretty

# 映射为 field_name
python scripts/chart_map_mcp.py --input /tmp/chart_result.json --map-to field_name --pretty
```

**输入来源**：先通过 MCP `query_chart` 获取并保存为 JSON：
```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# → 保存到 /tmp/chart_result.json
```

**输出**：每条 query 添加 `_mapping` 字段，包含 `dataset_alias`、`dataset_info`、`field_mappings`（含 `alias`、`expr`、`mapped_name`、`field_info`）。映射时优先使用服务端返回的字段语义，本地 CSV 仅在缺失时兜底。

---

### `chart_analyze_mcp.py` — 图表异常检测

对 chart 查询结果执行 5 类异常规则检测，输出结构化 JSON 报告。

**用法**：
```bash
# 仅分析当期数据
python scripts/chart_analyze_mcp.py --input /tmp/chart_result.json --pretty

# 附带 dataComparison 环比数据（增强趋势检测）
python scripts/chart_analyze_mcp.py \
  --input /tmp/chart_result.json \
  --dc-input /tmp/dc_result.json \
  --pretty
```

**输入来源**：
- `--input`：MCP `query_chart(chart_uuid="...", run=True)` 结果
- `--dc-input`：MCP `query_build_and_run(..., data_comparison="...")` 结果

**检测规则**：
| 规则 | 触发条件 |
|------|---------|
| `negative_margin` | 毛利率 < 0 |
| `profit_drop` | 毛利环比下降 > 30% |
| `revenue_cliff` | 原价金额环比下降 > 20% |
| `ad_roi_decline` | 广告费上升 + 毛利下降 |
| `zero_orders` | 当期订单量归零（对比期 > 0） |

**输出**：包含 `summary`（汇总统计）、`anomalies`（异常列表，按 severity 排序）、`findings`（人类可读关键发现）。

---

### `excel_export_mcp.py` — 图表数据 Excel 导出

从 chart 查询结果中提取明细、小计、总计数据，按透视表格式写入 Excel。

**前置依赖**：`pip install openpyxl`

**用法**：
```bash
python scripts/excel_export_mcp.py \
  --input /tmp/chart_result.json \
  --output /tmp/output.xlsx \
  --sheet-name 销售数据
```

**格式规范**：
- 表头：蓝色背景（4472C4）白色粗体字，冻结首行
- 明细行：数值列千分位格式，百分比列 0.00% 格式
- 小计行：灰色背景（D9E2F3），粗体字
- 总计行：深蓝背景白色粗体字
- 负值：红色字体（FF0000）
- 列宽：自适应（最大 50 字符）

**输出**：
```json
{
  "success": true,
  "output": "/tmp/output.xlsx",
  "rows": 150,
  "columns": ["日期", "部门", "销售额", "订单量"]
}
```

---

### `updater_mcp.py` — 本地状态检查

检查本地数据文件完整性，更新操作需通过 MCP `skills_upgrade` 执行。

**用法**：
```bash
python scripts/updater_mcp.py --check --pretty
```

**输出**：
```json
{
  "success": true,
  "data": {
    "data_dir": "/Users/mask/.config/opencode/skills/ops-dataset-query/data",
    "version": "v1.2.3",
    "data_state": "ready",
    "healthy": true,
    "summary": {
      "datasets_csv_count": 12,
      "fields_csv_count": 345,
      "catalog_intent_count": 20,
      "metadata_dataset_count": 12,
      "metadata_field_count": 345
    },
    "files": {
      "VERSION.json": {"exists": true, "version": "v1.2.3", "data_state": "ready"},
      "datasets.csv": {"exists": true, "size": 12345, "row_count": 12},
      "dataset_fields.csv": {"exists": true, "size": 67890, "row_count": 345},
      "dataset_catalog.json": {"exists": true, "size": 2345, "intent_count": 20},
      "query_metadata.json": {"exists": true, "size": 4567, "dataset_count": 12, "field_count": 345}
    }
  },
  "mcp_hint": "如需更新，调用 skills_upgrade(name='ops-dataset-query')"
}
```

`healthy=false` 且 `data_state=placeholder_or_empty` 表示当前只有模板占位数据，应先调用 `skills_upgrade(name="ops-dataset-query")` 后再重试搜索或查询。

---

## 降级方案：多次查询客户端合并（MCP 示例）

> **仅在 dataComparison 和 MOY 均无法满足需求时使用**。
> 此方案降级回 `query_simple`（简易接口），通过多次调用后在客户端合并结果。

```python
# 当期查询（降级使用 query_simple）
result_cur = query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 对比期查询
result_prev = query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-03-22"]}],
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 客户端合并（AI 在对话中处理）
```

---

## 典型工作流（完整版）

### 手写高级 payload → 执行（备用）

> 仅当简化接口无法满足需求时使用（如复杂的 `joins`、`union`、自定义子查询等）。
>
> **【强制禁用】涉及 `innerWhere` 的数据集（子查询类型，`inner_where_enabled=true`）禁止使用 `query_run`，无论需求多复杂都只能使用 `query_simple`。**

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 按文档规范手写完整 payload（多次失败时才参考 data-query-service-dev-guide.md）
#    保存到 /tmp/advanced_query.json

# 2. 执行
query_run(
    payload_path="/tmp/advanced_query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### 图表查询（通过 chart_uuid）

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 获取图表结构
query_chart(
    chart_uuid="4NQ5f66sU9",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 2. 获取并执行图表查询
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```
