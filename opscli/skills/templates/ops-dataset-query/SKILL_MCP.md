---
name: ops-dataset-query
mcp-version: v1.0.0
description: 使用 MCP Tool 查询本地缓存的数据集与字段索引，执行数据查询（无状态模式）
---

# ops-dataset-query (MCP 无状态模式)

使用 MCP Tool 查询本地缓存的数据集与字段索引，通过 `query_build_and_run`、`query_run` 等 Tool 执行数据查询。**无状态模式**：服务器不保存用户 OAuth 凭证，所有认证信息由调用方传入。

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

> **【强制】每次调用 `query_*` 前，必须先确认已提供有效 `session_id`；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先调用 `auth_is_authenticated(session_id)` 检测 session 有效性
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失**：
  1. 调用 `auth_login_start()` 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- **若 `session_id` 过期**：
  1. 调用 `auth_login_start()` 重新发起 Device Flow
  2. 重复上述授权流程
- 只有认证状态确认正常后，才允许继续执行 `query_metadata`、`query_build`、`query_run`、`query_build_and_run`、`query_chart`、`skills_upgrade`

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

> **【强制】使用本 Skill 前，必须先阅读 `references/数据查询服务开发说明文档.md`**

- 若需求涉及 `innerWhere`、子查询数据集、`translate`、`dataComparison`、高级计算（`MOY` / `ACC` / `PPT`）、权限占位符、小计/总计、交叉表/透视表、多次查询等场景，**必须**回到该引用文档逐节核对后再生成 payload
- WHERE 操作符完整列表、聚合函数完整列表、请求体完整结构均在引用文档中，本文件不再赘述
- 若引用文档与仓库原文冲突，以仓库原文 `docs/design/数据查询服务开发说明文档.md` 为准

---

## 使用原则

- 本 Skill 只负责本地字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 MCP Tool 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `skills_upgrade(name="ops-dataset-query")` 再重试查询
- 字段搜索结果已按相关性排序（精确匹配 > 子串匹配 > 关键词匹配）
- `query_build` 适合常见聚合查询（select / groupBy / where / having / orderBy / limit / offset / dryRun）
- `query_run` 适合透传完整高级 payload（`innerWhere`、`joins`、`dataComparison`、`translate` 等复杂场景）
- `query_chart` 适合通过图表 UUID 直接获取图表结构或执行图表查询，无需手动构造 payload
- 所有查询工作流都必须以前置的 `session_id` 有效性检测作为起点

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
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config、detail_expression、summary_expression 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_type、dataset_category、data_source、main_dttm_col、inner_where_enabled、cache_timeout、description |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/数据查询服务开发说明文档.md` 附录。

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

> 完整聚合函数列表见 `references/数据查询服务开发说明文档.md` 第八章。

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

### `query_run`

读取本地 payload JSON 文件并转发至服务端执行查询。**需要认证**。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload_path` | string | 是 | 本地 payload 文件路径 |
| `session_id` | string | **是** | 用户授权后获得的 session_id |
| `jwt` | string | 否 | JWT，不传则自动用 session_id 换取 |

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
# → {chart_uuid: "4NQ5f66sU9", queries: [...]}
```

**获取并执行查询**：
```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
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

### 方案选择决策流程

```
用户需要比较两个时间段的数据？
├── YES → 需要按时间粒度（日/月）分组展示趋势？
│         ├── YES → 使用 MOY 高级计算（comparison 写在 select 字段内）
│         └── NO  → 需要当期 vs 对比期汇总对比？
│                   ├── YES → 使用 dataComparison（服务端一次 SQL，推荐首选）
│                   └── NO  → 普通聚合 query_build_and_run
└── NO  → 普通聚合 query_build_and_run
```

### dataComparison 数据对比

> 服务端将当期和对比期合并为**一次 SQL**（条件聚合），每个度量字段自动裂变为 4 个字段。

**字段裂变规则**（以别名 `total_price` 为例）：

| 裂变字段 | 含义 |
|---------|------|
| `total_price` | 当期值 |
| `last_total_price` | 对比期值 |
| `diff_total_price` | 绝对差值（当期 - 对比期） |
| `pct_total_price` | 变化率（差值 / ABS(对比期)），上期为 0 时返回 null |

**调用示例**：
```python
query_build_and_run(
    table_id=1104,
    dimensions=["dept_name"],
    metrics=["price:sum:total_price", "order_qty:sum:total_qty"],
    where_conditions=["date_id|>=|\"2026-04-01\""],
    data_comparison="date_id,2026-03-01,2026-03-22",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

**适用场景**：当期（如本月 1-22 日） vs 对比期（如上月同期 1-22 日）的汇总数据对比，**同期天数对等**。

---

### MOY 同环比（高级计算）

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

**`cacl_type` 字段语义**：

| `cacl_type` | 字段值含义 | 说明 |
|-------------|-----------|------|
| `ORIGINAL` | **上期值（LAG）** | 不是当期原始值！是前一期的聚合结果 |
| `COMPARE` | 当期 − 上期 | 正数=增长，负数=下滑 |
| `PERCENT` | (当期 − 上期) / ABS(上期) | 环比变化率，上期为 0 时返回 null |

> 💡 当期实际值 = `ORIGINAL 字段值` + `COMPARE 字段值`

**适用场景**：按月/日/周分组的趋势图、时序对比。注意 MOY 用整个历史周期做 LAG，与 `dataComparison` 的同期对比不同。

---

### ACC 累加计算

> 按时间序列滚动累计（Running Total），适合 YTD 累计销售额等场景。

---

### PPT 占比计算

> 当前维度指标值 ÷ 全局总量，适合各部门销售额占比等场景。

---

### 降级方案：多次查询客户端合并

> **仅在 dataComparison 和 MOY 均无法满足需求时使用**。

```python
# 当期查询
result_cur = query_build_and_run(
    table_id=1104,
    dimensions=["dept_name"],
    metrics=["price:sum:total_price"],
    where_conditions=["date_id|>=|\"2026-04-01\"", "date_id|<=|\"2026-04-22\""],
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 对比期查询
result_prev = query_build_and_run(
    table_id=1104,
    dimensions=["dept_name"],
    metrics=["price:sum:total_price"],
    where_conditions=["date_id|>=|\"2026-03-01\"", "date_id|<=|\"2026-03-22\""],
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

### 探索数据集 → 构造 → 执行

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 通过本地索引确认数据集和字段名
# 2. 查看完整 metadata
query_metadata(dataset="sales_order_d", skills_dir="/Users/mask/.config/opencode/skills")

# 3. 构造并执行
query_build_and_run(
    dataset="sales_order_d",
    dimensions=["date_id"],
    metrics=["order_cost:sum:total_cost"],
    where_conditions=["date_id|>=|\"2024-01-01\""],
    order_by=["total_cost:desc"],
    limit=50,
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)
```

### 手写高级 payload → 执行

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 按引用文档规范手写 payload（含 innerWhere / dataComparison 等）
#    保存到 /tmp/advanced_query.json

# 2. 执行
query_run(
    payload_path="/tmp/advanced_query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### 环比查询（dataComparison，推荐首选）

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 构造并执行 dataComparison 查询
query_build_and_run(
    table_id=1104,
    dimensions=["dept_name"],
    metrics=["price:sum:total_price", "order_qty:sum:total_qty"],
    where_conditions=["date_id|>=|\"2026-04-01\""],
    data_comparison="date_id,2026-03-01,2026-03-22",
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)
# 响应自动包含：total_price / last_total_price / diff_total_price / pct_total_price
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

**推荐流程**：本地索引确认字段名 → `query_metadata` 查看完整 metadata → `query_build_and_run` 或手写 payload + `query_run`

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

详细规则见 `references/数据查询服务开发说明文档.md`，核心章节：

| 场景 | 参考章节 |
|------|---------|
| innerWhere、子查询数据集 | 第三章 数据集类型详解 |
| WHERE 操作符、嵌套条件、translate | 第五章 WHERE 条件构建指南 |
| dataComparison 数据对比 | 第六章 |
| 多次查询（交叉表/透视表/堆叠图） | 第七章 |
| SELECT 字段、聚合函数、高级计算(MOY/ACC/PPT) | 第八章 |
| 权限占位符 | 第四章 |
| 分页与排序 | 第九章 |

**使用建议**：
- 普通聚合优先使用 `query_build_and_run`
- 涉及上述高级场景时，先阅读引用文档，再手写 payload + `query_run`
