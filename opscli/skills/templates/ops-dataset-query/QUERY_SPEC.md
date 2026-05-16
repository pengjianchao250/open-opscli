# ops-dataset-query MCP 查询规范文档

> **AI Agent 必读**：执行任何 `query_*` MCP 工具之前，必须先阅读并理解本文档的全部铁律。
> 本文档由 `query_spec_must_read()` 工具返回，适用于通过 MCP Server 直接调用查询服务的场景。

---

## 一、规范铁律总览

> 以下铁律在所有查询场景下均适用，违反任意一条都会导致结果错误或查询失败。

| # | 铁律 | 核心要点 |
|---|------|---------|
| 1 | **认证前置** | 远端查询前必须确认已登录；HTTP/SSE 模式用 `auth_mcp_login()` 一步登录；session_id 可不传（自动加载） |
| 2 | **工具优先级** | `query_simple` > `query_build_and_run` > `query_build`+`query_run`；禁止跳级 |
| 3 | **公式字段禁止聚合** | 含 `summary_expression` 的字段（ACOS/ROAS 等）禁止额外传 `aggregation` |
| 4 | **dataComparison 必带主周期** | 使用数据对比时 `filters` 必须包含当前主周期日期；单独传 `dataComparison` 会报 `QS-EXE-005` |
| 5 | **先确认字段再构造参数** | 构造任何 query 参数前，先通过 `query_metadata` 确认字段存在 |
| 6 | **参数命名约定** | MCP 工具参数用 `snake_case`（`table_id`），JSON payload 用 `camelCase`（`tableId`），禁止混用 |
| 7 | **字段歧义必须澄清** | 用户术语匹配到 ≥2 个字段时，禁止静默选择，必须让用户确认 |
| 8 | **输出字段名不可改写** | 结果列名必须使用数据集定义的 `verbose_name`，禁止自行意译 |
| 9 | **本地数据初始化检查** | `data_state=placeholder` 时本地索引为空模板；执行搜索/查询前必须先 `skills_upgrade`（CLI）或 `skills_upgrade(name="ops-dataset-query")`（MCP）拉取远端数据 |
| 10 | **查询前意图澄清** | 构造任何查询参数前，必须先按第十四章字段歧义规则逐项检查；时间/人员/产品/币种/数据集存在歧义时，必须向用户确认，禁止猜测 |
| 11 | **查询闭环强制反馈** | 每次执行查询工具后，无论成功或失败，必须在后续 3 次工具调用内调用 `feedback_submit` 提交反馈；成功/降级 → `query_result`，工具报错 → `bug` |

> `query_simple` / `opscli query simple` 已内置字段歧义硬门禁：执行前会校验 dimensions、metrics、filters 和 dataComparison 中的字段引用。若字段不存在、模糊术语命中多个候选、或公式字段被额外传入 aggregation，会直接阻断查询并返回候选信息。

---

## 二、认证前置流程

> **规则**：`query_build` 和 `query_catalog(source="local")` 不需要认证；所有远端查询必须先确认已登录。
> **重要**：所有需要认证的工具均支持 **自动加载本地凭证**，已登录过的会话无需重复传入 `session_id`。

### 方式 A（推荐）：auth_mcp_login 一步登录

> 适用于 **HTTP/SSE 模式**（Claude Code、Cursor 等 MCP 客户端）。
> API Key 即身份，全程自动，**无需浏览器交互，无需 user_code**。

```python
# 调用一次即完成登录，凭证自动保存（按 API Key + Agent 名称双维度隔离）
result = auth_mcp_login()
# 成功返回：{ success: True, data: { status, session_id, email, expires_at, saved_locally } }
# 后续所有工具调用无需再传 session_id，自动从本地加载
```

### 标准认证检查

```python
# 检查是否已登录（session_id 可不传，自动从本地加载）
auth_is_authenticated()
# 返回 authenticated=true → 继续查询
# 返回 authenticated=false → 执行 auth_mcp_login（HTTP/SSE）或 Device Flow（stdio）
```

### 认证要求速查

| 操作 | 是否需要 session_id |
|------|-------------------|
| `query_build` | ❌ 不需要 |
| `query_catalog(source="local")` | ❌ 不需要 |
| `query_metadata`（无参数，本地列表） | ❌ 不需要 |
| `query_metadata(dataset="xxx")`（远端获取字段） | 自动加载（建议登录后调用） |
| `query_catalog()`（远端，默认） | 自动加载（建议登录后调用） |
| `query_simple` | 自动加载（未登录时报错） |
| `query_build_and_run` | 自动加载（未登录时报错） |
| `query_run` | 自动加载（未登录时报错） |
| `query_chart(run=True)` | 自动加载（未登录时报错） |

> **说明**：所有工具的 `session_id` 参数均为**可选**。未传时自动从本地 CredentialStore 加载已保存的凭证。
> 首次使用或凭证失效时，运行 `auth_mcp_login()`（HTTP/SSE 模式）或 Device Flow 完成登录即可。

---

## 三、查询工具优先级（核心）

> **强制优先级**：从上到下依次尝试，只有高优先级工具确实无法满足需求时才降级。

```
① query_simple           ← 最优先，服务端自动处理所有技术细节
② query_build_and_run    ← 次优，CLI 风格字符串参数，构造并执行
③ query_build            ← 仅构造 payload（不执行，不需认证）
④ query_run              ← 最后手段，手写完整 payload
```

### 选择决策

```
需要执行查询？
  ├─ 普通聚合 / 环比 / MOY 趋势 → query_simple
  ├─ 需要先查看 payload 结构 → query_build，再 query_run
  └─ 复杂场景（无法用简化参数表达）→ query_build 或手写 payload + query_run

需要图表数据？
  └─ 有 chart_uuid → query_chart(run=True)
```

---

## 四、query_simple（推荐优先使用）

基于简化参数直接执行查询，服务端自动处理 `translate`、`MOY` 展开等所有技术细节。需要认证。

### 参数规范

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table_id` | integer | **是** | 数据集 ID |
| `dimensions` | list[dict\|str] | 否 | 维度列表 |
| `metrics` | list[dict\|str] | 否 | 指标列表 |
| `filters` | list[dict] | 否 | 过滤条件 |
| `data_comparison` | dict | 否 | 对比周期（必须同时传主周期 filters） |
| `order_by` | list[dict] | 否 | 排序 |
| `limit` | integer | 否 | 默认 20 |
| `offset` | integer | 否 | 默认 0 |
| `session_id` | string | 否 | 可选，不传时自动从本地凭证加载 |

> ⚠️ MCP 参数用 `snake_case`：`table_id` ✅，`tableId` ❌ → 报 `Unexpected keyword argument`

### 示例 1：普通聚合查询

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    order_by=[{"field": "f_fee_sum", "desc": True}],
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### 示例 2：数据对比（环比）

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    # 主周期放 filters，对比周期放 data_comparison，两者缺一不可
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回额外列：last_f_fee_sum（上期）、diff_f_fee_sum（差值）、pct_f_fee_sum（环比%）
```

### 示例 3：MOY 月环比趋势

```python
query_simple(
    table_id=1,
    dimensions=[
        {"field": "dept_name", "alias": "f_dept"},
        {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}  # 按月分组
    ],
    metrics=[
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"},
        # comparison=MOY 服务端展开为当期/上期/变化率三列
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_moy",
         "comparison": "MOY", "moyType": "MOM_MONTH"}
    ],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-04-22"]}],
    order_by=[{"field": "f_month", "desc": True}],
    limit=20,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
# 返回额外列：f_fee_moy_prev、f_fee_moy_diff、f_fee_moy_pct
```

### 示例 4：含公式字段（ACOS / ROAS 等）

```python
# 先调用 query_metadata 获取 summary_expression 的值
meta = query_metadata(dataset="ads_summary_d")
# 从返回中读取 acos 字段的 summary_expression，例如 "ROUND(total_spend_cny / sales_cny, 4)"

query_simple(
    table_id=15,
    dimensions=[{"field": "dev_team_name", "alias": "f_team"}],
    metrics=[
        {"field": "sp_total_spend_cny", "aggregation": "SUM", "alias": "f_sp_spend"},
        {
            "field": "acos",
            "alias": "f_acos",
            "expr": "ROUND(total_spend_cny / sales_cny, 4)"  # summary_expression 的值，不传 aggregation
        }
    ],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-10", "2026-05-09"]}],
    limit=200,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### dimensions / metrics 双格式支持

```python
# 字符串格式（兼容 query_build 习惯）
dimensions=["dept_name", "date_id:f_date"]
metrics=["price:SUM:f_price", "order_id:COUNT_DISTINCT:f_orders"]

# Dict 格式（推荐，支持 format / comparison / expr 等扩展字段）
dimensions=[{"field": "dept_name", "alias": "f_dept"},
            {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}]
metrics=[{"field": "price", "aggregation": "SUM", "alias": "f_price"},
         {"field": "acos", "alias": "f_acos", "expr": "<summary_expression>"}]
```

### filters 操作符

| 操作符 | 示例 |
|--------|------|
| `=` / `!=` | `{"field": "platform", "operator": "=", "value": "Amazon"}` |
| `>` / `>=` / `<` / `<=` | `{"field": "date_id", "operator": ">=", "value": "2026-01-01"}` |
| `in` / `not in` | `{"field": "platform", "operator": "in", "value": ["Amazon", "Walmart"]}` |
| `between` | `{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-30"]}` |

---

## 五、query_build_and_run（构造并执行）

CLI 风格字符串参数，构造标准 payload 并立即执行。需要认证。

```python
query_build_and_run(
    table_id=1,
    dimensions=["date_id", "country_code"],
    metrics=["price:SUM:f_price", "order_id:COUNT_DISTINCT:f_orders"],
    where_conditions=["date_id|>=|\"2026-01-01\"", "platform|=|\"Amazon\""],
    order_by=["f_price:desc"],
    limit=50,
    # session_id 可不传，自动从本地凭证加载
)
```

### where_conditions 格式

```
格式：field|operator|value_json
示例：
  "date_id|>=|\"2026-01-01\""              # 字符串值需 JSON 转义引号
  "price|>|100"                            # 数值直接写
  "platform|in|[\"Amazon\",\"Walmart\"]"   # 数组值
操作符：=  !=  >  >=  <  <=  in  not in
```

### data_comparison 格式（字符串）

```
格式：field,start_date,end_date
示例："date_id,2026-03-01,2026-03-22"
```

---

## 六、query_build（仅构造 payload，不执行）

不需要认证。用于生成完整的 payload JSON 文件，再交给 `query_run` 执行。

```python
query_build(
    table_id=1,
    dimensions=["date_id", "country_id:country"],
    metrics=["order_cost:sum:total_cost", "order_id:count_distinct:order_count"],
    where_conditions=["date_id|>=|\"2024-01-01\""],
    order_by=["total_cost:desc"],
    limit=50,
    output_path="/tmp/query.json"   # 可选，写入文件
)
# → 返回 payload 结构，并写入 /tmp/query.json
```

**公式字段规则**：传 `global_alias` 或 `verbose_name`，Tool 自动根据 metadata 展开为完整公式表达式，无需手动处理。

---

## 七、query_run（手写完整 payload 执行）

```python
# 先用 query_build 生成 payload 文件，再调用 query_run 执行
query_run(
    payload_path="/tmp/query.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### 手写 payload 的必填字段

```json
{
  "tableId": 1,
  "query": {
    "select": [
      {
        "expr": "ds_xxx.dept_name",
        "alias": "f_dept"
      },
      {
        "expr": "ds_xxx.price",
        "alias": "f_price",
        "aggregation": "SUM"
      }
    ],
    "groupBy": ["f_dept"],
    "where": {
      "operator": "AND",
      "conditions": [
        {"field": "ds_xxx.date_id", "operator": "gte", "value": "2026-01-01"}
      ]
    },
    "orderBy": [{"expr": "f_price", "direction": "desc"}],
    "limit": 20,
    "offset": 0
  }
}
```

> 常见错误：`{"global_alias": "f_dept"}` 缺少 `expr` 字段 → 422 报错。`expr` 和 `alias` 均为必填。

---

## 八、query_chart（图表查询）

通过图表 UUID 获取图表结构或执行所有子查询。需要认证。

```python
# 仅获取图表结构（不执行）
query_chart(
    chart_uuid="4NQ5f66sU9",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)

# 获取并执行所有子查询
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

### run=True 返回结构

```json
{
  "chart_uuid": "4NQ5f66sU9",
  "queries": [
    {
      "index": 0,
      "table_id": 1,
      "payload": {},
      "result": {"data": [], "total": 150},
      "error": null
    }
  ],
  "merged": {
    "rows": [],
    "meta": {"rowCount": 150, "queryCount": 3, "successCount": 3}
  }
}
```

> 图表含多个 query 时，每个独立执行，单个失败不中断其他 query。

---

## 九、辅助工具（query_metadata / query_catalog）

> **两者用途完全不同，禁止混用**：
> - `query_metadata`：获取数据集字段信息，或查看所有可用数据集列表 → **"有哪些数据集/字段"**
> - `query_catalog`：将 NL 需求与预定义业务意图（intents）匹配，识别目标数据集 → **"这个需求该用哪个数据集"**（catalog 不返回数据集列表）

### query_metadata — 获取数据集字段信息

```python
# 获取所有数据集列表（本地，不需要认证）
query_metadata()

# 获取指定数据集完整字段（远端优先，自动回退本地）
query_metadata(dataset="sales_order_d")
query_metadata(table_id=123)
```

返回字段包含：`field_name`、`verbose_name`、`global_alias`、`field_type`、`summary_expression`、`detail_expression`、`formula_config`

> 查询公式字段前必须调用此接口获取 `summary_expression`，不能靠猜测。

### query_catalog — 数据集意图匹配

```python
# 远端获取（默认），失败自动回退本地
query_catalog()

# 仅本地缓存（不需要认证）
query_catalog(source="local")
```

**返回结构**：
```json
{
  "version": "v1.0.0",
  "intent_count": 15,
  "intents": [
    {
      "use_case": "销售订单分析",
      "keywords": ["订单", "销售额", "出库"],
      "scenario": "查看某时段内的销售订单汇总数据",
      "priority": 1,
      "dataset_alias": "sales_order_d",
      "table_id": 1,
      "default_filters": {},
      "comparison_strategy": "dataComparison"
    }
  ]
}
```

> **强制**：用户未指定数据集时，必须先调用 `query_catalog()` 做意图匹配，禁止跳过直接猜数据集。

---

## 十、字段确认流程（强制）

> 构造任何查询参数前必须执行，禁止凭印象直接使用字段名。

```
1. query_metadata(dataset="<alias>") 确认字段存在及其类型
   → 返回字段列表，确认 field_name / verbose_name / global_alias

2. 确认是否为公式字段：
   → 字段的 summary_expression 非空 → 公式字段，构造时不传 aggregation，传 expr
   → summary_expression 为空 → 普通字段，正常传 aggregation

3. 字段在 metadata 中不存在时：
   → 检查 dataset_alias 是否拼写正确
   → 通过 query_metadata() 列出所有可用数据集确认
   → 若字段确实不存在，明确告知用户，禁止猜字段名继续查
```

---

## 十一、dataComparison 与 MOY 趋势规范

### 比较类查询优先级（强制）

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 汇总对比（环比/同比） | `data_comparison`（服务端一次 SQL） |
| ② 次优 | 按时间粒度的趋势对比 | `metrics.comparison=MOY`（服务端窗口函数） |
| ③ 兜底 | ①② 均不可用时 | 多次 `query_simple` + 客户端合并 |

> 禁止跳过高优先级直接多次调用 Tool 在客户端合并结果。

### dataComparison 必须同时传主周期

```python
# ✅ 正确：同时传主周期 filters 和对比周期 data_comparison
query_simple(
    table_id=1,
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    ...
)

# ❌ 错误：只传 data_comparison，没有主周期 filters → QS-EXE-005
query_simple(
    table_id=1,
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}
)
```

### "近 N 天"日期精确推算铁律

```
结束日期 = 今天
起始日期 = 今天 - (N - 1) 天      ← 注意是 N-1，不是 N

近30天（今天=5月11日）→ 起始=4月12日，范围 [4.12, 5.11]，共30天
❌ 常见错误：起始=4月11日（多算一天）
❌ 常见错误：往前推"3个月"（月份天数不固定）
```

> **"近 N 天"默认包含今天**。用户未明确说明时按此理解，但必须在回复中明示该假设（"以下统计范围包含今天"），让用户有机会纠正。

### 月份天数不对等处理规则

不同月份天数不同（28/29/30/31），跨月对比时必须处理口径差异：

| 场景 | 处理规则 |
|------|---------|
| 完整月对比 | 使用完整自然月，告知用户天数差异；如用户关注趋势，建议用日均值 |
| 同期对比（本月 1~N 日 vs 上月 1~N 日） | 使用**相同天数**，不可用完整月 |
| 本月前 N 天 vs 上月完整月 | **必须澄清**：天数严重不对等，提供两方案：A) 用上月同期 N 天、B) 计算日均值 |

### 时间表述边界定义

| 表述 | 默认理解 | 必须澄清的场景 |
|------|---------|-------------|
| 近 N 天 | 包含今天，起始 = 今天-(N-1) | 月份对比天数不对等时 |
| 本月 | 当前自然月 | 月初时用户可能实际想查上月 |
| 上月 | 上一自然月 | 跨年时确认年份（1月的"上月"为去年12月） |
| **最近一个月** | 歧义（近30天 vs 当月？） | **必须确认** |
| 本周 | 周一至今天 | 用户可能想要完整周 |
| 上周 | 上周一至上周日 | — |
| **最近一周** | 近7天滚动（≠"上周"） | 与"上周"含义不同，需确认 |
| 上个月同期 | 上月 1 日~同日 | 需确认具体日期范围 |

---

## 十二、公式字段处理铁律

> **铁律**：含 `summary_expression` 或 `formula_config` 的字段（如 ACOS、ROAS、毛利率等），禁止额外传 `aggregation`。

### 判断与处理方式

```python
# 1. 获取字段信息
fields = query_metadata(dataset="ads_summary_d")["data"]["fields"]

# 2. 找到目标字段，判断是否为公式字段
for f in fields:
    if f.get("summary_expression") or f.get("formula_config"):
        # 公式字段：传 expr，不传 aggregation
        pass

# 3. 构造 metric 参数
# ✅ 正确：公式字段
{"field": "acos", "alias": "f_acos", "expr": "ROUND(total_spend_cny / sales_cny, 4)"}

# ❌ 错误：公式字段套 SUM，导致二次聚合（把每行的 ACOS 百分比加在一起）
{"field": "acos", "aggregation": "SUM", "alias": "f_acos"}
```

- **聚合/分组查询**：使用字段的 `summary_expression`
- **明细/行级查询**（用户说"明细"/"每一行"）：使用字段的 `detail_expression`

---

## 十三、错误处理速查

| 场景 | 错误码/现象 | 解决方式 |
|------|-----------|---------|
| 缺少主周期 filters | `QS-EXE-005 missing ')' at '{'` | 补上主周期日期 filters 后重试 |
| 手写 payload 缺 expr | 422 Unprocessable Entity | `query.select.*.expr` 和 `alias` 均为必填 |
| dataset_alias 不存在 | 查询报错 / 返回空 | 先 `query_metadata()` 查看所有可用数据集 |
| 未登录 / 本地无凭证 | auth 报错 / authenticated=false | HTTP/SSE：`auth_mcp_login()`；stdio：Device Flow |
| Token 过期 | 401 Unauthorized | `auth_token_refresh()` 刷新（session_id 可不传） |
| chart_uuid 不存在 | 404 | 确认图表 ID 正确，检查访问权限 |
| MCP 参数用了 camelCase | `Unexpected keyword argument` | 改用 snake_case：`table_id` 而非 `tableId` |
| catalog default_filters 返回 0 行 | 无错误码 | 去掉 default_filters 后重试 |

---

## 十四、数据集与字段歧义澄清规则

> **核心原则**：不确定就问，禁止猜测。任何可能产生歧义的情况都必须向用户确认。

### 数据集选择（铁律）

```
用户未明确指定数据集 →
  先用 query_catalog() 做意图匹配
  匹配到 0 个 → 告知用户，请用户明确指定
  匹配到 1 个 → 告知用户将使用该数据集，确认后执行
  匹配到 ≥2 个 → 列出所有候选（名称 + 粒度 + 适用场景）让用户选择
```

用户明确指定数据集名称时，若在 `query_metadata()` 中模糊匹配到 ≥2 个相似名称，仍需列出让用户确认。

### 字段匹配两级优先级（铁律）

```
用户说"查 xxx 指标"
  ↓
第一级：精确匹配（verbose_name 或 field_name 完全等于用户术语）
  精确匹配到 1 个 → 直接使用，跳过模糊匹配
  精确匹配到 ≥2 个 → 列出精确匹配的候选项让用户选择
  精确匹配到 0 个 → 进入第二级
  ↓
第二级：模糊匹配（verbose_name / field_name 包含用户术语）
  模糊匹配到 0 个 → 告知用户无此字段，列出相近字段
  模糊匹配到 1 个 → 直接使用（告知用户将使用该字段）
  模糊匹配到 ≥2 个 → 【强制】列出所有候选项及各自含义，让用户选择
```

> **关键区别**：用户说"销售额"且 verbose_name 中恰好有字段叫"销售额"时，直接精确命中，**不需要**再列出"交易额（自发货）"等模糊匹配结果。只有无精确匹配时才进入模糊匹配阶段。

**字段歧义澄清模板**：
> "您说的'{术语}'匹配到 {N} 个字段，请确认要使用哪一个：
> 1. `字段名` — 含义说明（所属数据集：xxx）
> 2. `字段名` — 含义说明（所属数据集：xxx）"

### 常见歧义类型

| 歧义类型 | 检测方式 | 处理 |
|---------|---------|------|
| 同名多角色（人员/组织） | metadata 中 verbose_name 含"人员/小组/团队"且 ≥2 个 | 列出所有角色让用户确认 |
| 组织层级歧义 | 存在多级组织维度（大组 → 小组 → 个人） | 向用户确认要查哪个层级 |
| 原币 vs CNY | 同时存在 `xxx` 和 `xxx_cny` 字段 | 默认 CNY，告知用户 |
| SKU/ASIN 多变体 | field_name 含 SKU/ASIN 且 ≥2 个 | 列出所有变体（渠道SKU/公司SKU/父公司SKU）让用户选 |
| 产品标识缩写歧义 | 用户使用"SP"等缩写 | 根据语境判断（广告指标→广告类型，产品管理→产品编码）；无法判断时澄清 |
| 公式指标跨数据集口径不同 | 相同 field_name 出现在 ≥2 个 table_id | 说明各数据集的计算口径差异，让用户选择 |
| 综合 vs 细分数据集 | catalog intents 命中多个 priority 相近的数据集 | 问用户要全貌（综合）还是细分详情 |
| 库存多子类 | 含"库存"且存在 ≥3 个变体字段 | 列出所有变体让用户选择，不得默认选"总库存" |
| 分类体系歧义 | 存在多套分类体系（内部品类 vs 平台类目） | 确认用哪套体系 |

### 人员/组织澄清模板

当查询中包含人名或组织名（如"查张三的数据"、"xxx组的销量"），且 metadata 中存在 ≥2 组同概念但不同语义的维度字段时：

> "请问'{名称}'属于哪种角色类型？数据集中存在以下同名字段维度：
> 1. `字段A` — 角色A（如销售人员）
> 2. `字段B` — 角色B（如开发人员）
> 我需要确认按哪个维度过滤。"

### 产品标识缩写歧义规则

| 缩写 | 可能含义 | 判断依据 |
|------|---------|---------|
| SP | SPU（产品编码） vs Sponsored Products（广告类型） | 涉及广告指标 → 广告类型；涉及产品管理 → 产品编码；无法判断时澄清 |
| SD | Standard Dimension vs Sponsored Display 广告 | 同上逻辑 |
| SB | 同类歧义 | 同上逻辑 |

### 币种规则

- 用户未指定币种时，**默认使用 CNY（人民币）版本**，并在输出中明示
- 用户明确说"美金"/"USD"/"原币"时使用对应版本

### 时间范围规则

详见第十一章。简要速查：

| 表述 | 默认理解 | 必须澄清 |
|------|---------|---------|
| 近 N 天 | 包含今天，起始 = 今天-(N-1) | 月份对比天数不对等时 |
| 本月 | 当前自然月 | 月初时用户可能想查上月 |
| 上月 | 上一自然月 | 1 月的上月是去年 12 月 |
| **最近一个月** | 歧义 | **必须确认** |
| 本周 | 周一至今天 | 用户可能想要完整周 |
| **最近一周** | 近7天（≠上周） | 与"上周"不同，需确认 |

---

## 十五、输出结果规范

> **铁律**：输出列名必须使用数据集定义的 `verbose_name`，禁止自行意译或美化。

```
✅ 正确：| 广告费 | 广告销量 | ACOS |
❌ 错误：| 广告花费 | 广告销售数量 | 广告成本占比 |

✅ 正确：| 订单量 |
❌ 错误：| 订单数量 |（即使意思相近也禁止修改）
```

---

## 十六、查询前自检清单

```
□ 认证：是否已登录？（auth_is_authenticated，不传 session_id 自动检查本地凭证）
□ 认证：未登录时 → HTTP/SSE 模式执行 auth_mcp_login()；stdio 模式执行 Device Flow
□ 时间：日期范围是否明确？近 N 天是否用 N-1 推算起始日期？"最近一个月"是否已澄清？
□ 月份天数：跨月对比时天数是否对等？本月前N天 vs 上月完整月 → 澄清
□ 数据集：是否唯一确认？（query_catalog 意图匹配 → 用户确认）
□ 数据集名称：用户关键词匹配到 ≥2 个相似数据集 → 列出让用户选
□ 字段：是否通过 query_metadata 确认字段存在？
□ 字段匹配：是否有 ≥2 个精确/模糊匹配 → 禁止静默选择，让用户确认
□ 字段跨表：同一 field_name 出现在多个数据集 → 澄清口径差异
□ 公式字段：summary_expression 非空 → 不传 aggregation，传 expr
□ dataComparison：是否同时带了主周期 filters？
□ 参数命名：MCP 参数是否用了 snake_case？（table_id 不是 tableId）
□ 人员/组织歧义：查询含人名/组织名 → 检查是否存在 ≥2 组同概念维度字段
□ 产品标识歧义：涉及 SKU/ASIN → 是否存在多个变体字段
□ 币种歧义：存在 xxx_cny 版本 → 默认 CNY，告知用户
□ 库存查询：指定具体产品查库存 → 默认不加时间聚合，查最新快照
□ 输出列名：是否使用了原始 verbose_name？禁止意译
□ catalog default_filters：是否已验证可用（返回 0 行时去掉重试）
□ 闭环：查询完成后是否已调用 feedbackSubmit 提交结果反馈？
```

---

## 十七、典型工作流速查

### 工作流 A：已知数据集，直接查询

```
1. auth_is_authenticated()                      # session_id 不传，自动检查本地凭证
   → authenticated=false：
       HTTP/SSE 模式 → auth_mcp_login()         # 一步登录，自动保存凭证
       stdio 模式    → auth_login_start() + auth_login_poll()

2. query_metadata(dataset="<alias>")
   → 确认目标字段存在
   → 检查是否为公式字段（summary_expression 非空）

3. query_simple(...) 执行查询                   # session_id 可不传，自动加载

4. 输出结果（使用 verbose_name 作为列名）

5. feedbackSubmit 提交查询反馈
   - feedback_type="bug | feature | data_issue | ux | docs | query_result |other"
   - title="查询内容简述"
   - content="结果摘要（行数、关键指标范围）"
```

### 工作流 B：用户未指定数据集

```
1. auth_is_authenticated()                      # 自动检查本地凭证
   → authenticated=false → 先完成登录（见工作流 A 步骤 1）

2. query_catalog() 做意图匹配
   → 匹配到多个：列出候选，等用户选择
   → 匹配到 1 个：告知用户确认

3. query_metadata(dataset="<确认的 alias>") 校验目标字段

4. query_simple(...) 执行查询                   # session_id 可不传，自动加载

5. feedbackSubmit 提交查询反馈
```

### 工作流 C：图表数据分析

```
1. auth_is_authenticated()                      # 自动检查本地凭证
   → authenticated=false → 先完成登录

2. query_chart(chart_uuid="...", run=True)      # session_id 可不传，自动加载
   → 获取图表所有子查询结果

3. 分析 merged.rows 中的数据
   → 注意 _query_index 字段区分多个子查询

4.（可选）需要环比时：
   query_simple(..., data_comparison={...})     # session_id 可不传，自动加载
   → 对比当期与上期数据

5. feedbackSubmit 提交查询反馈
```

### 工作流 D：降级方案（dataComparison 和 MOY 均不可用时）

```python
# 当期查询
result_cur = query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "price", "aggregation": "SUM", "alias": "f_price"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    session_id="..."
)

# 对比期查询
result_prev = query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "price", "aggregation": "SUM", "alias": "f_price"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-03-22"]}],
    session_id="..."
)

# 在对话中按 f_dept 匹配两组结果，计算差值和变化率

# 5. feedbackSubmit 提交查询反馈
```

---

## 十八、库存数据查询规则

### 指定产品的库存查询默认不聚合

**核心原则**：当用户查询涉及某个具体产品的库存字段时（可售库存、在途库存、海外仓库存等），查询目的是了解**当前最新库存状况**，而非历史汇总统计，因此**默认不做时间聚合**。

**触发条件**（满足任一即触发）：
- 查询中指定了具体产品标识：ASIN、渠道 SKU、公司 SKU、父公司 SKU 等
- 查询意图明显是针对某个已知产品的库存状况

**处理规则**：
- **默认不加时间聚合**：维度中不应包含日期聚合字段（如"年-月"、"年-周"等），直接查最新明细数据
- **默认查最新快照**：自动匹配最近一次库存快照日期，而非一段历史时间范围
- **用户明确要求历史趋势时例外**：如"近30天可售库存变化"、"库龄分布"，则按正常趋势/聚合查询处理
- **用户未指定库存类型时**：库存有 ≥3 个变体字段（可售/在途/海外仓/国内仓等），列出所有变体让用户选择，不得默认选"总库存"

**示例 1** — 用户说"查 ASIN B0XXXXX 的库存"：
```
维度：ASIN
指标：库存数量（最新快照值）
过滤：ASIN = B0XXXXX
不做：按日期维度聚合
```

**示例 2** — 用户说"查 ASIN B0XXXXX 近30天的可售库存变化"：
```
维度：日期
指标：可售库存数量
过滤：ASIN = B0XXXXX，日期范围 = 近30天
（用户明确要求趋势，按正常趋势查询处理）
```

---

---

## 十九、查询闭环强制规则

> **铁律**：每次执行 `query_*` 系列工具后，无论查询成功或失败，都必须在后续 3 次工具调用内完成一次 `feedbackSubmit`。

### 强制执行清单（MUST-CHECK）

每次完成查询后，必须依次检查：

```
□ 步骤1：skillsList（确认技能状态）
□ 步骤2：query_spec_must_read（读取规范，获取最新规则）
□ 步骤3：执行查询（query_simple / query_build_and_run / query_chart）
□ 步骤4：feedbackSubmit 提交结果反馈
□ 步骤5：确认 feedback 状态为 "new" 或 "submitted"
```

### 反馈提交参数规范

**成功场景示例**：

```python
feedbackSubmit(
    feedback_type="query_result",
    title="各SKU库存查询 - 即时综合数据集（table_id=1）",
    content="查询成功，返回 20 行。平台库存 500~2000，海外仓库存 100~800。",
    source="mcp",
    payload={
        "actual": "查询返回 20 行，平台库存 500~2000，海外仓库存 100~800",
        "expected": "按渠道SKU查询即时库存快照（平台库存/海外仓库存/国内库存/在途库存）"
    },
    execution_summary={
        "summary": "通过 query_simple 查询即时综合数据集（table_id=1），按渠道SKU维度获取库存快照，查询成功。",
        "successful_calls": [
            {"tool": "query_simple", "result": "success, 20 rows, 1200ms"}
        ],
        "failed_calls": [],
        "final_resolution": "查询成功，结果已输出给用户。"
    }
)
```

**失败 / 降级场景示例**（`severity="medium"`，失败尤其重要）：

```python
feedbackSubmit(
    feedback_type="query_result",
    severity="medium",
    title="广告数据-dataComparison对比列缺失（table_id=15）",
    content="查询返回成功但缺少对比列（last_*/diff_*/pct_*），最终通过两次独立查询手动完成对比。",
    source="mcp",
    payload={
        "actual": "返回结果缺少 last_f_spend/diff_f_spend/pct_f_spend 等对比列",
        "expected": "query_simple 传入 data_comparison 参数后，返回结果应包含 last_*/diff_*/pct_* 对比列"
    },
    execution_summary={
        "summary": "通过 query_simple 查询 advertising_list_set（table_id=15），使用 dataComparison 参数进行2月 vs 1月对比。dataComparison 参数传入成功但对比列未返回，最终通过两次独立查询手动完成对比分析。",
        "failed_calls": [
            {
                "tool": "query_simple",
                "reason": "推测：table_id=15 为 sql 类型数据集，dataComparison 逻辑未正确拼接到子查询 SQL 中",
                "call_params": {
                    "table_id": 15,
                    "filters": [{"field": "date_id", "operator": "between", "value": ["2026-02-01", "2026-02-28"]}],
                    "data_comparison": {"field": "date_id", "startDate": "2026-01-01", "endDate": "2026-01-31"}
                },
                "error_message": "无报错，但返回结果缺少 last_*/diff_*/pct_* 对比列",
                "fix_suggestion": "检查 SimpleQueryBuilder 对 sql 类型数据集的 dataComparison 处理逻辑；临时方案：分别查询两个时间段在客户端合并对比"
            }
        ],
        "successful_calls": [
            {"tool": "query_simple（2月数据）", "result": "success, 2 rows, 1205ms"},
            {"tool": "query_simple（1月数据）", "result": "success, 2 rows, 1348ms"}
        ],
        "final_resolution": "通过分别查询1月和2月数据，在客户端手动完成环比计算和对比分析。"
    }
)
```

### 违规后果

| 违规行为 | 后果 |
|---------|------|
| 查询后未调用 feedbackSubmit | 流程不完整，系统无法记录查询历史 |
| 连续 3 次查询均未提交反馈 | 视为严重流程违规，需人工审查 |

### 闭环检查点（Post-Hook 自动触发规则）

如果未来 query 工具支持 post-hook 机制，以下规则将自动生效：

```
query_simple 执行成功            → 自动触发 feedbackSubmit
                                   参数自动注入：feedback_type=query_result
                                                source=mcp
                                                execution_summary 自动从本次查询结果提取
query_build_and_run 执行成功     → 同上
query_chart(run=True) 执行成功   → 同上
```

在 post-hook 机制上线前，AI Agent 必须手动在每次查询完成后调用 `feedbackSubmit`。

---

*本规范文档由 `query_spec_must_read()` MCP 工具返回，适用于通过 MCP Server 直接调用查询服务的场景。*
