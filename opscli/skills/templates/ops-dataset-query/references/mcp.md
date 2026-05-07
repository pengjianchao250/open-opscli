---
name: ops-dataset-query
description: 使用 MCP Tool 查询本地缓存的数据集与字段索引，执行数据查询（无状态模式）
---

# ops-dataset-query (MCP 无状态模式)

使用 MCP Tool 查询本地缓存的数据集与字段索引，通过 `query_simple`、`query_build_and_run`、`query_run` 等 Tool 执行数据查询。**无状态模式**：服务器不保存用户 OAuth 凭证，所有认证信息由调用方传入。

---

## ChatGPT / OpenAI 兼容工具

本 Skill 同时提供 OpenAI [Company Knowledge](https://openai.com/index/introducing-company-knowledge/) 标准工具，无需认证即可搜索本地数据知识库：

| 工具 | 用途 | 参数 | 返回 |
|------|------|------|------|
| `search` | 搜索数据集和字段 | `query: str` | `{"results": [{"id", "title", "url"}]}` |
| `fetch` | 获取详细信息 | `id: str` | `{"id", "title", "text", "url", "metadata"}` |

**使用场景**：
- ChatGPT 用户通过自然语言搜索可用数据集
- Deep Research 引用本地数据作为知识源
- 无需 Device Flow 即可浏览数据字典

**search 示例**：
```python
search(query="订单")  # 返回所有与"订单"相关的数据集和字段
```

**fetch 示例**：
```python
fetch(id="dataset:sales_order_d")  # 返回该数据集的详细 metadata
fetch(id="field:sales_order_d.order_cost")  # 返回该字段的详细信息
```

---

## 调用前置要求

> **认证按动作触发**：本地知识检索不要求登录；涉及远端查询执行、图表运行或升级时，必须确认有效 `session_id`。

- 本地只读动作可直接执行：`search`、`fetch`、`query_catalog`、`query_metadata`
- 远端动作前先调用 `auth_is_authenticated(session_id)` 检测 session 有效性：`query_simple`、`query_build_and_run`、`query_run`、`query_chart(run=True)`、`skills_upgrade`
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失**：
  1. 调用 `auth_login_start()` 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- **若 `session_id` 过期**：
  1. 调用 `auth_login_start()` 重新发起 Device Flow
  2. 重复上述授权流程
- 只有认证状态确认正常后，才允许继续执行远端动作

**标准前置流程（MCP Tool 调用）**：

```python
# 1. 先检查 session 是否有效
auth_is_authenticated(session_id="xxx")

# 2. 如 session_id 缺失或过期，重新授权
auth_login_start()                     # 获取 device_code / user_code
auth_login_poll(device_code="xxx")     # 轮询直到 authorized，获取新 session_id

# 3. 登录后再次确认
auth_is_authenticated(session_id="新session_id")
```

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

- 若需求涉及 `innerWhere`、子查询数据集、`translate`、`dataComparison`、高级计算（`MOY` / `ACC` / `PPT`）、权限占位符、小计/总计、交叉表/透视表、多次查询等场景，**必须**回到该引用文档逐节核对后再生成 payload
- WHERE 操作符完整列表、聚合函数完整列表、请求体完整结构均在引用文档中，本文件不再赘述
- 若引用文档与仓库原文冲突，以仓库原文 `docs/design/data-query-service-dev-guide.md` 为准

---

## 使用原则

- 本 Skill 只负责本地字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 MCP Tool 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期或字段不存在时，先执行 `skills_upgrade(name="ops-dataset-query")` 再重试查询
- 字段搜索结果已按相关性排序（精确匹配 > 子串匹配 > 关键词匹配）
- **`query_simple` 优先**：普通聚合、数据对比、MOY 趋势、子查询等场景，优先使用简化接口（详见 `references/simple-query-guide.md`）
- `query_build` 适合基于 `--dimension`/`--metric` 参数快速构造标准 query payload
- `query_run` 适合透传完整高级 payload（仅当简化接口不满足需求时使用）
- `query_chart` 适合通过图表 UUID 直接获取图表结构或执行图表查询，无需手动构造 payload
- 所有查询工作流都必须以前置的 `session_id` 有效性检测作为起点

---

## 【强制】字段存在性检查

> 在 MCP 模式下，构造任何 query 参数前，必须先确认目标数据集和字段真实存在；**搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级**。

标准顺序：

1. 先用本地索引或知识工具确认目标 `dataset_alias`
2. 再确认目标字段是否存在于本地字段索引
3. 如需进一步确认公式字段、聚合方式、表达式结构，再调用 `query_metadata(dataset=...)`
4. 如果数据集或字段不存在，先检查本地数据是否为空/placeholder；为空时执行 `skills_upgrade(name="ops-dataset-query")`
5. 升级后重新执行字段检查
6. 若升级后仍不存在，明确告知用户当前本地索引和 metadata 中没有该字段，不要猜字段名继续查

**【强制】搜索结果为空时的处理流程**：

> 当 `search()` 返回空列表时，不要直接告知用户"找不到"。先确认本地数据是否为空/placeholder；为空时升级本地数据再重试。

```python
# 搜索返回空结果时
search(query="广告")
# 返回: {"results": []}

# 如果本地数据为空/placeholder，立即升级本地数据
skills_upgrade(name="ops-dataset-query")

# 升级后重新搜索
search(query="广告")
# 如果仍然为空，再告知用户
```

推荐检查方式：

```python
# 1. 先确认数据集或字段是否存在
search(query="sales_order_d")
search(query="order_cost")

# 2. 读取详细字段信息
fetch(id="field:sales_order_d.order_cost")

# 3. 再看完整 metadata
query_metadata(dataset="sales_order_d")

# 4. 字段不存在时先升级
skills_upgrade(name="ops-dataset-query")
```

判断原则：

- `search` / `fetch` / 本地脚本结果里都找不到目标字段时，不要直接构造 payload
- 优先接受这几类命中：`field_name`、`global_alias`、`verbose_name`
- 公式字段必须额外看 `query_metadata`，不能只看索引名称就推断表达式
- `query_metadata` 与本地索引同时都缺失时，才可判定当前 Skill 数据未覆盖或字段确实不可用

### 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案，禁止跳过高优先级直接多次调用 Tool 后在客户端合并结果**。

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `query_run` + 客户端合并 |

> `comparison`（MOY/ACC/PPT）写在 `select` 字段内部可正常透传。

---

## 本地数据文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `data/VERSION.json` | 版本号 | `{"name": "ops-dataset-query", "version": "v1.x.x"}` |
| `data/dataset_catalog.json` | 业务语义索引 | version、intent_count、intents（使用案例/关键词/场景/优先级/数据集映射）、query_strategy |
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config、detail_expression、summary_expression 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_type、dataset_category、data_source、main_dttm_col、inner_where_enabled、cache_timeout、description |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/data-query-service-dev-guide.md` 附录。

---

## 辅助脚本（优先使用）

以下脚本位于 `scripts/` 目录，**不依赖 opscli，可直接运行**，是操作本地数据的首选工具。

### `search.py` — 本地字段搜索

命令行关键词搜索本地字段索引，支持按数据集过滤和限制返回数量。

**用法**：
```bash
python scripts/search.py <keyword> [--dataset <dataset_alias>] [-n <limit>]
```

**示例**：
```bash
# 搜索含 "price" 的字段
python scripts/search.py price

# 在指定数据集内搜索
python scripts/search.py price --dataset sales_order_d

# 限制返回 5 条
python scripts/search.py price -n 5
```

**输出**：JSON 数组，每项包含字段完整信息（dataset_alias、field_name、verbose_name、global_alias、field_type 等）。

---

### `core.py` — 底层工具函数库

提供 CSV 加载、行过滤、搜索打分、数值转换与格式化等基础能力，仅依赖 Python 标准库。

**核心函数**：

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `load_csv_rows(path)` | `Path` | `list[dict]` | 加载 CSV 为字典列表（utf-8-sig 编码，兼容 BOM） |
| `filter_rows_by_dataset(rows, dataset)` | `list[dict]`, `str \| None` | `list[dict]` | 按 dataset_alias 过滤行 |
| `search_rows(rows, keyword, limit=10)` | `list[dict]`, `str`, `int` | `list[dict]` | 按关键词搜索并返回相关性排序结果 |
| `to_float(v)` | `Any` | `float` | 安全转换查询结果为 float，失败返回 0.0 |
| `safe_pct(cur, prev)` | `float`, `float` | `float \| None` | 计算环比变化率（小数形式），除零保护 |
| `format_pct(value)` | `float \| None` | `str` | 格式化变化率为可读字符串，如 "+12.34%" / "N/A" |

**使用方式**：作为模块导入
```python
from pathlib import Path
from scripts.core import load_csv_rows, search_rows, to_float, safe_pct, format_pct

# 加载本地字段索引
rows = load_csv_rows(Path("data/dataset_fields.csv"))

# 搜索字段
results = search_rows(rows, "order_price", limit=10)

# 数值转换与环比计算
current = to_float("1234.56")
previous = to_float("1000.00")
pct = safe_pct(current, previous)      # 0.23456
print(format_pct(pct))                 # +23.46%
```

**特点**：
- 无任何外部依赖，标准库即可运行
- `search_rows` 采用加权打分排序：精确匹配 > 子串匹配 > token 匹配
- `to_float` / `safe_pct` / `format_pct` 专用于处理查询结果中的数值与百分比计算

---

### MCP 环境辅助脚本（无状态模式，不依赖 opscli）

以下脚本位于 `scripts/` 目录，**专为 MCP 无状态模式设计**，零 opscli 依赖，仅通过文件输入/输出与 MCP Tool 配合。

#### `query_mcp.py` — 本地 Payload 构造器

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

#### `chart_map_mcp.py` — chart 字段映射

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

#### `chart_analyze_mcp.py` — 图表异常检测

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

#### `excel_export_mcp.py` — 图表数据 Excel 导出

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

#### `updater_mcp.py` — 本地状态检查

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

## MCP Tool 调用参考

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

读取本地数据集业务语义索引（dataset catalog）。**不需要认证**。用于自然语言需求匹配 intents 后选出候选数据集。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |

**调用示例**：
```python
query_catalog()
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

### `query_build`

基于简化参数构造标准 query payload（不执行查询）。**不需要认证**。

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

### `query_simple`（推荐优先使用）

基于简化参数直接执行查询。服务端自动处理 `innerWhere`、`translate`、`MOY` 展开等技术细节。**需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table_id` | integer | **是** | 数据集 ID |
| `dimensions` | list[dict] | 否 | 维度列表，`{"field": "dept_name", "alias": "f_xxx", "format": "..."}` |
| `metrics` | list[dict] | 否 | 指标列表，`{"field": "...", "aggregation": "SUM", "alias": "...", "comparison": "MOY"}` |
| `filters` | list[dict] | 否 | 过滤条件，`{"field": "...", "operator": "in", "value": [...]}` |
| `data_comparison` | dict | 否 | 数据对比，`{"field": "...", "startDate": "...", "endDate": "..."}` |
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

### `query_run`

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

### `query_build_and_run`

构造 query payload 并立即执行，一步返回数据结果。**需要认证**。

参数包含 `query_build` 的全部参数（不含 `output_path`），外加：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
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
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)
```

> 如果 `jwt` 未提供，服务器会自动用 `session_id` 向后端换取 JWT，无需调用方手动管理。

---

### `query_chart`

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

## MCP 认证工具速查

### 检查 session 有效性
```python
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: true}
```

### 获取 JWT
```python
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: "eyJhbG..."}
```

### 检查 JWT 有效期
```python
auth_check_token(jwt="eyJhbG...")
# → {success: true, data: {valid: true, expires_in: 86399}}
```

### 刷新 JWT
```python
auth_token_refresh(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

## 数据对比与高级计算

**使用优先级**：
1. **`query_simple`**（推荐）：普通聚合、数据对比、MOY 趋势、子查询等场景
2. **`query_build_and_run`**：基于 `dimensions`/`metrics` 参数快速构造标准 query payload
3. **`query_run`**：仅当简化接口无法满足需求时，手写完整 payload 透传

> 简化接口完整说明见 **`references/simple-query-guide.md`**。
> 完整 query payload 规范（innerWhere / translate / 权限占位符等）见 **`references/data-query-service-dev-guide.md`**。

### dataComparison 简化调用示例

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```

### MOY 月环比简化调用示例

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

### 降级方案：多次查询客户端合并（MCP 示例）

> **仅在简化接口和 dataComparison 均无法满足需求时使用**。

```python
# 当期查询
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

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `skills_upgrade(name="ops-dataset-query")` |
| dataset_alias 不存在 | 检查拼写或 `skills_upgrade` 同步最新数据集 |
| 字段映射全部失败 | 手动执行 `skills_upgrade(name="ops-dataset-query", force=True)` |
| 未登录 / session 无效 | 调用 `ops-auth` Skill，执行 `auth_login_start()` → 浏览器授权 → `auth_login_poll()` |
| Token 过期 | `auth_token_refresh(session_id)`；如 session 也过期则重新 Device Flow 授权 |
| payload 文件不存在 | 先 `query_build` 生成 |
| chart_uuid 不存在或已删除 | 确认图表 ID 正确，或检查该图表是否有访问权限 |
| 图表查询执行失败 | 查看返回的 `error` 字段获取具体错误信息，常见原因：数据集权限不足、字段已变更 |

---

## 典型工作流

### 探索数据集 → 构造 → 执行（简化接口）

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 通过本地索引确认数据集和字段名
# 2. 查看完整 metadata
query_metadata(dataset="sales_order_d", skills_dir="/Users/mask/.config/opencode/skills")

# 3. 使用简化接口构造并执行
query_simple(
    table_id=1,
    dimensions=[{"field": "date_id", "alias": "f_date"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    order_by=[{"field": "f_fee_sum", "desc": True}],
    limit=50,
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)
```

### 手写高级 payload → 执行（备用）

> 仅当简化接口无法满足需求时使用（如复杂的 `joins`、`union`、自定义子查询等）。

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 按 data-query-service-dev-guide.md 规范手写完整 payload
#    保存到 /tmp/advanced_query.json

# 2. 执行
query_run(
    payload_path="/tmp/advanced_query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
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
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回列：f_dept, f_fee_sum, last_f_fee_sum, diff_f_fee_sum, pct_f_fee_sum
```

### 数据更新 → 重新查询

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 检查版本状态
skills_status(skills_dir="/Users/mask/.config/opencode/skills")

# 2. 升级到最新
skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")

# 3. 重新查询
query_metadata(dataset="sales_order_d", skills_dir="/Users/mask/.config/opencode/skills")
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

---

## 安装与管理

```python
# 0. 先检查 session（skills_install / skills_upgrade 需要认证）
auth_is_authenticated(session_id="xxx")

# 安装
skills_install(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")

# 强制重装
skills_install(name="ops-dataset-query", force=True, skills_dir="/Users/mask/.config/opencode/skills")

# 查看版本
skills_status(skills_dir="/Users/mask/.config/opencode/skills")

# 升级
skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")
```

---

## 字段搜索（本地索引）

本 Skill 内置本地字段索引，可用于辅助确认 `dataset_alias`、`field_name`、`verbose_name`。

**推荐流程**：本地索引确认字段名 → `query_metadata` 查看完整 metadata → **`query_simple`**（优先）或 `query_build_and_run` / 手写 payload + `query_run`

**搜索排序策略（相关性从高到低）：**

| 匹配类型 | 分值 |
|---------|------|
| `field_name` 精确匹配 | 120 |
| `verbose_name` 精确匹配 | 100 |
| `field_name` 子串匹配 | 60 |
| `verbose_name` 子串匹配 | 45 |
| `dataset_alias` 精确匹配 | 40 |
| `description` 子串匹配 | 10 |

---



## 高级查询说明

**使用优先级**：
1. **`query_simple`**（推荐）：普通聚合、数据对比、MOY 趋势、子查询等场景，服务端自动处理技术细节
2. **`query_build_and_run`**：基于 `dimensions`/`metrics` 参数快速构造标准 query payload
3. **`query_run`**：仅当简化接口无法满足需求时，手写完整 payload 透传

> 简化接口完整说明见 **`references/simple-query-guide.md`**。
> 完整 query payload 规范（innerWhere / translate / 权限占位符等）见 **`references/data-query-service-dev-guide.md`**。
