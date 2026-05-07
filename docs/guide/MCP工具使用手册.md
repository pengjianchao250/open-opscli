# opscli MCP Tool 使用手册

本文档对应 `opscli` CLI 命令用例手册的 MCP 版本，覆盖全部 MCP Tool 的调用方式、参数说明与常见使用示例。

- 代码基线：`aukeys-opscli` `0.0.35`
- 入口方式：MCP Tool 调用（Python 函数风格）

---

## 1. Tool 总览

```text
opscli MCP Tools
├── auth
│   ├── auth_login_start
│   ├── auth_login_poll
│   ├── auth_get_token
│   ├── auth_check_token
│   ├── auth_is_authenticated
│   ├── auth_token_refresh
│   ├── auth_build_request_auth
│   ├── auth_logout
│   ├── auth_doctor
│   ├── auth_system_list
│   ├── auth_system_sync
│   ├── auth_system_add
│   └── auth_system_remove
├── amazon
│   ├── amazon_scrape
│   ├── amazon_payload
│   ├── amazon_search
│   ├── amazon_schema
│   └── amazon_history
├── query
│   ├── query_metadata
│   ├── query_catalog
│   ├── query_simple
│   ├── query_build
│   ├── query_run
│   ├── query_build_and_run
│   ├── query_chart
│   └── query_chart_doc
├── skills
│   ├── skills_list
│   ├── skills_install
│   ├── skills_status
│   └── skills_upgrade
└── knowledge (ChatGPT / OpenAI 兼容)
    ├── search
    └── fetch
```

---

## 2. 通用说明

### 2.1 输出风格

所有 MCP Tool 返回统一的 JSON 结构：

```json
{
  "success": true,
  "data": {...},
  "error": null
}
```

或错误时：

```json
{
  "success": false,
  "data": null,
  "error": "错误描述"
}
```

> **例外**：`search` 和 `fetch` 工具遵循 OpenAI Company Knowledge 标准格式，不使用上述结构（详见第 8 章）。

### 2.2 认证说明

| 认证需求 | 说明 |
|---------|------|
| **无需认证** | 纯本地操作，不访问远端 API |
| **服务端自动认证** | 服务端会从本地 CredentialStore 自动加载 session_id / JWT |
| **需显式传 session_id** | 服务端无法自动获取凭证，需调用方传入 |

**无状态设计原则**：
- 服务器不保存用户 OAuth 凭证，所有认证信息优先由调用方传入
- 调用方未传入时，服务器自动尝试从本地 CredentialStore 加载（与 CLI 共用加密存储）
- `session_id` 由调用方管理，可保存在 AI 对话上下文中

### 2.3 通用约定

- 所有参数都有默认值的可不传
- 列表类型参数（如 `dimensions`、`where_conditions`）传 Python 列表
- 布尔参数传 Python 布尔值（`True` / `False`）

---

## 3. 认证模块 `auth_*`

用于登录、退出、诊断、获取系统 JWT、维护系统注册表。

### 3.1 `auth_login_start`

发起 OAuth2 Device Flow 登录第一步，返回验证 URL、用户码和设备码。

**参数**

无。

**返回**

```json
{
  "success": true,
  "data": {
    "device_code": "abc123",
    "user_code": "ABCD-EFGH",
    "verification_url": "https://ops.api.qa.aukeyit.com/auth/device",
    "expires_in": 1800,
    "interval": 5
  }
}
```

**示例**

```python
auth_login_start()
```

---

### 3.2 `auth_login_poll`

轮询 Device Flow 授权状态。授权成功后自动保存到本地 CredentialStore。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_code` | string | 是 | `auth_login_start` 返回的设备码 |
| `timeout` | int | 否 | 单次轮询超时秒数，默认 10 |

**返回**

```json
{
  "success": true,
  "data": {
    "status": "authorized",
    "session_id": "860b0636485b5188a2b9b4ed5210e736",
    "email": "user@example.com",
    "saved_locally": true
  }
}
```

**示例**

```python
auth_login_poll(device_code="abc123")
```

---

### 3.3 `auth_is_authenticated`

检查 session_id 是否有效（尝试用其获取 JWT）。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 待检查的 Session ID（为空则自动加载本地保存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "authenticated": true,
    "source": "local"
  }
}
```

**示例**

```python
auth_is_authenticated()
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### 3.4 `auth_logout`

清除本地保存的 session 和 JWT（退出登录）。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | 否 | 系统别名，`"__all__"` 表示清除所有系统，默认 `"__all__"` |

**示例**

```python
auth_logout()
auth_logout(system="ops")
```

---

### 3.5 `auth_doctor`

检查 session 有效性与各系统 URL 连通性。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | 提供后额外检测 session 是否已认证（为空则自动加载本地保存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "authenticated": true,
    "session_id_present": true,
    "local_sessions": {
      "email": "user@example.com",
      "session_id_present": true,
      "tokens": ["ops", "polaris"]
    },
    "systems": [
      {"alias": "ops", "url": "https://ops.api.qa.aukeyit.com", "reachable": true, "error": null},
      {"alias": "polaris", "url": "https://bi.aukeys.com", "reachable": true, "error": null}
    ]
  }
}
```

**示例**

```python
auth_doctor()
auth_doctor(session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### 3.6 `auth_get_token`

获取指定系统的有效 JWT。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | 否 | 系统别名，默认 `"ops"` |
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "jwt": "eyJhbG...",
    "source": "remote",
    "cached": true
  }
}
```

**示例**

```python
auth_get_token()
auth_get_token(system="ops")
auth_get_token(system="polaris", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### 3.7 `auth_check_token`

检测 JWT 有效性及剩余有效时间（秒）。纯本地解析，不向后端发请求。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `jwt` | string | 否 | 待检测的 JWT（为空则检查本地缓存） |
| `system` | string | 否 | 系统别名（用于定位本地缓存的 JWT），默认 `"ops"` |

**返回**

```json
{
  "success": true,
  "data": {
    "valid": true,
    "expires_in": 3599,
    "source": "local"
  }
}
```

**示例**

```python
auth_check_token()
auth_check_token(system="ops")
auth_check_token(jwt="eyJhbG...")
```

---

### 3.8 `auth_token_refresh`

刷新指定系统 JWT 并保存到 CredentialStore。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | 否 | 系统别名，`"__all__"` 表示刷新所有系统，默认 `"__all__"` |
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "jwt": "eyJhbG...",
    "cached": true
  }
}
```

**示例**

```python
auth_token_refresh()
auth_token_refresh(system="ops")
auth_token_refresh(system="__all__")
```

---

### 3.9 `auth_system_list`

列出所有已注册系统（builtin / local / ops_sync）。**不需要认证**。

**参数**

无。

**示例**

```python
auth_system_list()
```

---

### 3.10 `auth_system_sync`

从 ops 后端同步系统列表。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |

**示例**

```python
auth_system_sync()
auth_system_sync(session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

### 3.11 `auth_system_add`

手动添加一个系统实例。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 系统展示别名 |
| `url` | string | 是 | 系统 Base URL |
| `key` | string | 否 | 系统唯一键；不传时由 `alias` 自动生成 |
| `token_endpoint` | string | 否 | Token 获取端点，默认 `"/api/auth/cli-token"` |

**示例**

```python
auth_system_add(alias="数据分析", url="http://analytics.cm")
auth_system_add(alias="财务系统", url="http://finance.cm", key="finance")
```

---

### 3.12 `auth_system_remove`

移除手动添加的系统；内置系统不可删除。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alias` | string | 是 | 要移除的系统别名 |

**示例**

```python
auth_system_remove(alias="数据分析")
```

---

### 3.13 `auth_build_request_auth`

构造统一请求认证参数（JWT Bearer + Session Cookie）。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `system` | string | 否 | 目标系统别名，默认 `"ops"` |
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |
| `jwt` | string | 否 | 已有 JWT（为空则自动加载本地缓存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "headers": {"Authorization": "Bearer eyJhbG..."},
    "cookies": {"ops_session": "860b0636485b5188a2b9b4ed5210e736"}
  }
}
```

**示例**

```python
auth_build_request_auth()
auth_build_request_auth(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
```

---

## 4. Amazon 模块 `amazon_*`

用于 Amazon 商品抓取、本地历史保存、标准 payload 构造和搜索结果抓取。

> 前置依赖：`pip install opscli[amazon] && playwright install chromium`
>
> amazon 工具组仅在 `playwright` 已安装时才会注册到 MCP Server。

### 4.1 `amazon_scrape`

抓取单个 Amazon 商品快照。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `asin` | string | 是 | - | 目标 ASIN（10 位字母数字） |
| `zip_code` | string | 否 | `"10001"` | 美国邮编，用于稳定价格口径 |
| `save_history` | bool | 否 | `True` | 是否将快照追加写入本地历史文件 |
| `include_raw` | bool | 否 | `False` | 是否在返回结果中包含原始抓取字段 |

**返回**

```json
{
  "success": true,
  "data": {
    "snapshot": {
      "asin": "B09LCJPZ1P",
      "product_name": "...",
      "price_amount": 29.99,
      "rating_value": 4.5,
      "review_count_value": 1234,
      ...
    },
    "history_path": "/Users/you/.config/opscli/amazon/history/B09LCJPZ1P.jsonl"
  }
}
```

**示例**

```python
amazon_scrape(asin="B09LCJPZ1P")
amazon_scrape(asin="B09LCJPZ1P", zip_code="10001", include_raw=True)
amazon_scrape(asin="B09LCJPZ1P", save_history=False)
```

---

### 4.2 `amazon_payload`

抓取商品并构造标准 ops 提交 payload。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `asin` | string | 是 | - | 目标 ASIN |
| `zip_code` | string | 否 | `"10001"` | 美国邮编 |
| `save_history` | bool | 否 | `True` | 是否保存本地历史 |

**返回**

```json
{
  "success": true,
  "data": {
    "payload": {
      "source": "opscli.amazon",
      "snapshot": {...}
    },
    "history_path": "/Users/you/.config/opscli/amazon/history/B09LCJPZ1P.jsonl"
  }
}
```

**示例**

```python
amazon_payload(asin="B09LCJPZ1P")
amazon_payload(asin="B09LCJPZ1P", zip_code="10001")
```

---

### 4.3 `amazon_search`

按关键词抓取 Amazon 搜索结果页。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `keyword` | string | 是 | - | 搜索关键词 |
| `zip_code` | string | 否 | `"10001"` | 美国邮编 |
| `limit` | int | 否 | `10` | 最大结果数（1~50） |

**返回**

```json
{
  "success": true,
  "data": {
    "keyword": "usb c cable",
    "zip_code": "10001",
    "count": 10,
    "results": [
      {"asin": "B09XXX", "title": "...", "price_amount": 9.99, "rank": 1, ...},
      ...
    ]
  }
}
```

**示例**

```python
amazon_search(keyword="usb c cable")
amazon_search(keyword="usb c cable", zip_code="10001", limit=5)
```

---

### 4.4 `amazon_schema`

输出 Amazon 抓取数据模型与提交 payload 的字段结构。**不需要网络**。

**参数**

无。

**示例**

```python
amazon_schema()
```

---

### 4.5 `amazon_history`

读取某个 ASIN 的本地历史快照。**不需要网络**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asin` | string | 是 | 目标 ASIN |

**返回**

```json
{
  "success": true,
  "data": {
    "asin": "B09LCJPZ1P",
    "count": 3,
    "records": [
      {"collected_at": "2026-04-01 10:00:00", "price_amount": 29.99, ...},
      ...
    ]
  }
}
```

**示例**

```python
amazon_history(asin="B09LCJPZ1P")
```

---

## 5. 查询模块 `query_*`

用于读取数据集元数据、构造查询 payload、执行远端查询。

### 5.1 `query_metadata`

读取指定数据集的查询元数据。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset` | string | 否 | 数据集别名（与 `table_id` 二选一） |
| `table_id` | int | 否 | 数据集表 ID（与 `dataset` 二选一） |
| `skills_dir` | string | 否 | 指定 Skill 安装根目录 |

**示例**

```python
query_metadata(dataset="sales_order_d")
query_metadata(table_id=12345)
query_metadata(dataset="sales_order_d", skills_dir="/Users/mask/.config/opencode/skills")
```

---

### 5.2 `query_catalog`

读取数据集业务语义索引（dataset catalog）。默认远端优先，远端失败时回退本地缓存。

返回完整的 catalog JSON 结构，包含 version、intent_count、intents 数组和 query_strategy。用于自然语言需求匹配 intents 后选出候选数据集。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 自定义 Skills 目录（用于读取本地缓存 catalog） |
| `source` | string | 否 | 数据来源：remote（默认）或 local |
| `fallback_local` | boolean | 否 | source=remote 时，远端失败是否回退本地缓存 |
| `session_id` | string | 否 | OAuth Session ID |
| `jwt` | string | 否 | JWT Token |

**示例**

```python
query_catalog()
query_catalog(source="local")
query_catalog(source="remote", fallback_local=False)
query_catalog(skills_dir="/Users/mask/.config/opencode/skills")
```

---

### 5.3 `query_simple`

基于简化参数直接执行查询。服务端自动处理 `innerWhere`、`translate`、`MOY` 展开等技术细节。**需要认证**。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `table_id` | integer | **是** | - | 数据集 ID |
| `dimensions` | list[dict] | 否 | - | 维度列表，`{"field": "ds_xxx.name", "alias": "f_xxx", "format": "..."}` |
| `metrics` | list[dict] | 否 | - | 指标列表，`{"field": "...", "aggregation": "SUM", "alias": "...", "comparison": "MOY"}` |
| `filters` | list[dict] | 否 | - | 过滤条件，`{"field": "...", "operator": "in", "value": [...]}` |
| `data_comparison` | dict | 否 | - | 数据对比，`{"field": "...", "startDate": "...", "endDate": "..."}` |
| `order_by` | list[dict] | 否 | - | 排序规则，`{"field": "f_xxx", "desc": true}` |
| `limit` | integer | 否 | 20 | 返回行数限制 |
| `offset` | integer | 否 | 0 | 分页偏移 |
| `dry_run` | boolean | 否 | false | 是否仅验证不执行 |
| `skills_dir` | string | 否 | - | 自定义 Skills 目录 |
| `session_id` | string | 否 | - | OAuth Session ID |
| `jwt` | string | 否 | - | JWT Token |

**调用示例**

```python
# 普通聚合查询
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    limit=10,
    session_id="xxx"
)

# 数据对比（环比）
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
    session_id="xxx"
)

# MOY 月环比趋势
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
    session_id="xxx"
)
```

> 完整简化参数说明见 `opscli/skills/templates/ops-dataset-query/references/simple-query-guide.md`。

---

### 5.4 `query_build`

基于简化参数构造标准 query payload（不执行查询）。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `dataset` | string | 否 | - | 数据集别名 |
| `table_id` | int | 否 | - | 表 ID |
| `dimensions` | list[str] | 否 | - | 维度字段列表，如 `["date_id", "country_id:country"]` |
| `metrics` | list[str] | 否 | - | 指标字段列表，如 `["order_cost:sum:total_cost"]` |
| `where_conditions` | list[str] | 否 | - | 条件列表，如 `["date_id|>=|\"2024-01-01\""]` |
| `where_json` | string | 否 | - | 条件 JSON 字符串（与 `where_conditions` 二选一） |
| `having_conditions` | list[str] | 否 | - | HAVING 条件列表 |
| `order_by` | list[str] | 否 | - | 排序列表，如 `["total_cost:desc"]` |
| `limit` | int | 否 | `20` | 返回条数 |
| `offset` | int | 否 | `0` | 偏移量 |
| `dry_run` | bool | 否 | `False` | 仅生成 SQL，不执行 |
| `data_comparison` | string | 否 | - | 数据对比，如 `"date_id,2026-03-01,2026-03-22"` |
| `output_path` | string | 否 | - | 将 payload 写入文件路径 |
| `skills_dir` | string | 否 | - | 指定 Skill 目录 |

**示例**

```python
query_build(
    dataset="sales_order_d",
    dimensions=["date_id"],
    metrics=["gmv:sum"],
    limit=20
)

query_build(
    dataset="sales_order_d",
    dimensions=["date_id", "shop_id"],
    metrics=["gmv:sum:total_gmv", "order_cnt:sum"],
    where_conditions=["country_code|=|\"US\"", "date_id|between|[\"2026-03-01\",\"2026-03-31\"]"],
    order_by=["total_gmv:desc"],
    limit=100,
    output_path="/tmp/payload.json"
)

query_build(
    dataset="sales_order_d",
    dimensions=["date_id"],
    metrics=["gmv:sum"],
    data_comparison="date_id,2026-03-01,2026-03-22"
)
```

---

### 5.5 `query_run`

读取本地 payload JSON 文件并转发至服务端执行查询。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payload_path` | string | 是 | 本地 payload JSON 文件路径 |
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |
| `jwt` | string | 否 | 已有 JWT（为空则自动加载本地缓存的） |

**示例**

```python
query_run(payload_path="/tmp/payload.json")
query_run(
    payload_path="/tmp/payload.json",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

---

### 5.6 `query_build_and_run`

构造 query payload 并立即执行，一步返回数据结果。

**参数**

与 `query_build` 相同，外加：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |
| `jwt` | string | 否 | 已有 JWT（为空则自动加载本地缓存的） |

**示例**

```python
query_build_and_run(
    dataset="sales_order_d",
    dimensions=["date_id"],
    metrics=["gmv:sum"],
    limit=20
)

query_build_and_run(
    dataset="sales_order_d",
    dimensions=["dept_name"],
    metrics=["price:sum:total_price", "order_qty:sum:total_qty"],
    where_conditions=["date_id|>=|\"2026-04-01\""],
    data_comparison="date_id,2026-03-01,2026-03-22"
)
```

---

### 5.7 `query_chart`

通过 `chart_uuid` 获取图表查询结构，可选立即执行所有查询。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `chart_uuid` | string | 是 | - | 图表 UUID |
| `run` | bool | 否 | `False` | 获取后立即执行所有查询并合并输出 |
| `dry_run` | bool | 否 | `False` | 仅生成 SQL，不执行查询（需配合 `run=True`） |
| `session_id` | string | 否 | - | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |
| `jwt` | string | 否 | - | 已有 JWT（为空则自动加载本地缓存的） |

**说明**

- `run=False` 时，仅返回图表的查询结构（可能包含多个 query）。
- `run=True` 时，依次执行图表下的所有 query，并自动合并结果。
- 每个 query 独立执行，某个 query 失败不会中断其余 query。
- 合并结果中，每行数据会附加 `_query_index` 字段标识来源 query 序号。

**示例**

仅查看图表结构：

```python
query_chart(chart_uuid="4NQ5f66sU9")
```

获取并执行：

```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

仅生成 SQL：

```python
query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True,
    dry_run=True,
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

**返回结构（`run=True` 时）**

```json
{
  "success": true,
  "data": {
    "chart_uuid": "4NQ5f66sU9",
    "queries": [
      {
        "index": 0,
        "table_id": 1,
        "data_source": "doris_analytics",
        "payload": {...},
        "result": {...},
        "error": null
      }
    ],
    "merged": {
      "rows": [{"_query_index": 0, ...}],
      "meta": {"rowCount": 150, "queryCount": 3, "successCount": 3}
    }
  }
}
```

---

### 5.8 `query_chart_doc`

通过 `chart_uuid` 生成图表 API 调用 Markdown 文档，包含查询结构、字段映射、过滤规则与样例。**需要认证**。

文档包含七大章节：使用方式、关键术语、图表概览、API 调用流程、字段明细表、过滤规则、查询拆解与样例。适合 Skill / AI Agent 直接消费。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chart_uuid` | string | 是 | 图表唯一标识 |
| `output_path` | string | 否 | 将 Markdown 写入指定文件路径 |
| `session_id` | string | 否 | OAuth 授权后的 Session ID（为空则自动加载本地保存的） |
| `jwt` | string | 否 | 已有 JWT（为空则自动加载本地缓存的） |

**返回**

```json
{
  "success": true,
  "data": {
    "chart_uuid": "jSNuhm54uY",
    "markdown": "# 图表查询 API 开发文档\n...",
    "query_count": 3,
    "dataset_aliases": ["sales_order_d"],
    "dataset_count": 1,
    "output_path": "/tmp/chart_api_doc.md"
  },
  "error": null
}
```

**示例**

生成文档（Markdown 在返回数据中）：

```python
query_chart_doc(
    chart_uuid="jSNuhm54uY",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

生成文档并写入本地文件：

```python
query_chart_doc(
    chart_uuid="jSNuhm54uY",
    output_path="/tmp/chart_api_doc.md",
    session_id="860b0636485b5188a2b9b4ed5210e736"
)
```

---

## 6. Skill 模块 `skills_*`

用于扫描已安装 Skill、安装内置模板、查看状态、升级远端版本。

### 6.1 `skills_list`

列出当前环境中已安装的所有 Skill。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录（覆盖默认自动检测路径） |

**示例**

```python
skills_list()
skills_list(skills_dir="/Users/mask/.config/opencode/skills")
```

---

### 6.2 `skills_status`

查询 Skill 安装状态，包含本地版本与远端最新版本对比。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skills_dir` | string | 否 | 指定扫描目录 |

**示例**

```python
skills_status()
skills_status(skills_dir="/Users/mask/.config/opencode/skills")
```

---

### 6.3 `skills_install`

从内置模板安装 Skill。**纯本地操作，不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Skill 名称（如 `ops-auth`、`ops-dataset-query`） |
| `skills_dir` | string | 否 | 安装到指定目录 |
| `runtime` | string | 否 | 目标运行时：`claude` / `openclaw` / `codex` / `opencode` |
| `force` | bool | 否 | 是否覆盖已有安装，默认 `False` |

**示例**

```python
skills_install(name="ops-auth")
skills_install(name="ops-dataset-query")
skills_install(name="ops-auth", runtime="claude")
skills_install(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills", force=True)
```

---

### 6.4 `skills_upgrade`

升级指定 Skill 到远端最新版本（当前仅 `ops-dataset-query` 支持远端升级）。

**参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 否 | `"ops-dataset-query"` | Skill 名称 |
| `skills_dir` | string | 否 | - | 指定扫描目录 |
| `force` | bool | 否 | `False` | 强制重新拉取（即使版本号相同） |

**示例**

```python
skills_upgrade()
skills_upgrade(name="ops-dataset-query")
skills_upgrade(name="ops-dataset-query", force=True)
skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")
```

---

## 7. 常见组合用例

### 7.1 首次完成认证并查询数据

```python
# 1. 发起 Device Flow
auth_login_start()
# -> 获取 verification_url 和 user_code，提示用户浏览器授权

# 2. 轮询授权状态
auth_login_poll(device_code="abc123")
# -> 获取 session_id，保存到对话上下文

# 3. 安装 ops-dataset-query Skill
skills_install(name="ops-dataset-query")

# 4. 查看数据集 metadata
query_metadata(dataset="sales_order_d")

# 5. 构造并执行查询
query_build_and_run(
    dataset="sales_order_d",
    dimensions=["date_id"],
    metrics=["gmv:sum"],
    limit=20
)
```

### 7.2 检查并刷新某个系统的 Token

```python
# 1. 检查 session 有效性
auth_is_authenticated()

# 2. 检查 JWT 有效期
auth_check_token(system="ops")

# 3. 刷新 Token
auth_token_refresh(system="ops")

# 4. 获取新 Token
auth_get_token(system="ops")
```

### 7.3 抓取 Amazon 商品并查看历史

```python
# 1. 抓取商品
amazon_scrape(asin="B09LCJPZ1P", include_raw=True)

# 2. 构造提交 payload
amazon_payload(asin="B09LCJPZ1P")

# 3. 查看历史
amazon_history(asin="B09LCJPZ1P")
```

### 7.4 检查 Skill 是否有更新

```python
# 1. 列出已安装 Skill
skills_list()

# 2. 检查版本状态
skills_status()

# 3. 执行升级
skills_upgrade(name="ops-dataset-query")
```

### 7.5 图表查询与异常检测

```python
# 1. 获取并执行图表查询
result = query_chart(
    chart_uuid="4NQ5f66sU9",
    run=True
)

# 2. 保存结果到文件（供本地脚本处理）
# -> 保存到 /tmp/chart_result.json

# 3. 使用本地脚本进行字段映射
# python scripts/chart_map_mcp.py --input /tmp/chart_result.json --pretty

# 4. 使用本地脚本进行异常检测
# python scripts/chart_analyze_mcp.py --input /tmp/chart_result.json --pretty

# 5. 导出为 Excel
# python scripts/excel_export_mcp.py --input /tmp/chart_result.json --output /tmp/output.xlsx
```

### 7.6 使用业务语义索引定位数据集

```python
# 1. 读取 catalog（业务语义索引）
query_catalog()

# 2. 根据 catalog 中的 intents 匹配用户需求，确定 dataset_alias 和 table_id

# 3. 获取 metadata 确认字段
query_metadata(dataset="sales_order_d")

# 4. 使用 query_simple 执行查询
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "gmv", "aggregation": "SUM", "alias": "f_gmv"}],
    limit=20
)
```

### 7.7 使用 search/fetch 搜索数据集（OpenAI 兼容）

```python
# 1. 搜索数据集和字段
search(query="销售订单")

# 2. 获取数据集详细信息
fetch(id="dataset:sales_order_d")

# 3. 获取字段详细信息
fetch(id="field:sales_order_d.gmv")
```

---

## 8. Knowledge 模块（ChatGPT / OpenAI 兼容）

为兼容 OpenAI Company Knowledge、Deep Research 和 MCP Connectors 而实现的标准工具。

> 这两个工具遵循 OpenAI Company Knowledge 标准格式，不使用 `success/data/error` 统一结构。

### 8.1 `search`

在本地数据集和字段索引中搜索，返回匹配结果列表。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词（自然语言或字段名/数据集名） |

**返回**

```json
{
  "results": [
    {"id": "dataset:sales_order_d", "title": "销售订单日报", "url": "opscli://dataset/sales_order_d"},
    {"id": "field:sales_order_d.gmv", "title": "GMV", "url": "opscli://field/sales_order_d.gmv"},
    ...
  ]
}
```

**示例**

```python
search(query="销售订单")
search(query="gmv")
search(query="退款 退货")
```

---

### 8.2 `fetch`

获取指定数据集或字段的详细信息。**不需要认证**。

**参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 资源唯一标识（由 `search` 工具返回的 `id` 字段），格式：`dataset:{alias}` 或 `field:{dataset.field_name}` |

**返回**

```json
{
  "id": "dataset:sales_order_d",
  "title": "销售订单日报",
  "text": "数据集: sales_order_d\n维度字段 (15个): date_id (日期), ...\n指标字段 (8个): gmv (GMV), ...",
  "url": "opscli://dataset/sales_order_d",
  "metadata": {
    "type": "dataset",
    "table_id": 1,
    "dataset_type": "table",
    "dimensions_count": 15,
    "metrics_count": 8
  }
}
```

**示例**

```python
fetch(id="dataset:sales_order_d")
fetch(id="field:sales_order_d.gmv")
```

---

## 9. 认证状态速查

| Tool | 需要认证 | 认证方式 |
|------|---------|---------|
| `auth_login_start` | 否 | - |
| `auth_login_poll` | 否 | - |
| `auth_is_authenticated` | 否 | 可传 session_id 检查 |
| `auth_logout` | 否 | - |
| `auth_doctor` | 否 | 可传 session_id 额外检测 |
| `auth_get_token` | 服务端自动 | 可传 session_id |
| `auth_check_token` | 否 | 纯本地解析 |
| `auth_token_refresh` | 服务端自动 | 可传 session_id |
| `auth_system_list` | 否 | - |
| `auth_system_sync` | 服务端自动 | 可传 session_id |
| `auth_system_add` | 否 | - |
| `auth_system_remove` | 否 | - |
| `auth_build_request_auth` | 服务端自动 | 可传 session_id / jwt |
| `amazon_scrape` | 否 | - |
| `amazon_payload` | 否 | - |
| `amazon_search` | 否 | - |
| `amazon_schema` | 否 | - |
| `amazon_history` | 否 | - |
| `query_metadata` | 否 | - |
| `query_catalog` | 否 | - |
| `query_simple` | **是** | 可传 session_id / jwt |
| `query_build` | 否 | - |
| `query_run` | **是** | 可传 session_id / jwt |
| `query_build_and_run` | **是** | 可传 session_id / jwt |
| `query_chart`（run=False） | 否 | - |
| `query_chart`（run=True） | **是** | 可传 session_id / jwt |
| `query_chart_doc` | **是** | 可传 session_id / jwt |
| `skills_list` | 否 | - |
| `skills_install` | 否 | - |
| `skills_status` | 服务端自动 | 涉及远端 API |
| `skills_upgrade` | 服务端自动 | 涉及远端 API |
| `search` | 否 | - |
| `fetch` | 否 | - |

---

## 10. 快速索引

| 模块 | Tool | 对应 CLI 命令 |
|------|------|--------------|
| 认证 | `auth_login_start` / `auth_login_poll` | `opscli auth login` |
| 认证 | `auth_logout` | `opscli auth logout` |
| 认证 | `auth_doctor` | `opscli auth doctor` |
| 认证 | `auth_is_authenticated` | `opscli auth token status` |
| 认证 | `auth_get_token` | `opscli auth token get` |
| 认证 | `auth_check_token` | `opscli auth token check` |
| 认证 | `auth_token_refresh` | `opscli auth token refresh` |
| 认证 | `auth_system_list` | `opscli auth system list` |
| 认证 | `auth_system_sync` | `opscli auth system sync` |
| 认证 | `auth_system_add` | `opscli auth system add` |
| 认证 | `auth_system_remove` | `opscli auth system remove` |
| 认证 | `auth_build_request_auth` | （CLI 无直接对应） |
| Amazon | `amazon_scrape` | `opscli amazon scrape` |
| Amazon | `amazon_payload` | `opscli amazon payload` |
| Amazon | `amazon_search` | `opscli amazon search` |
| Amazon | `amazon_schema` | `opscli amazon schema` |
| Amazon | `amazon_history` | `opscli amazon history` |
| 查询 | `query_metadata` | `opscli query metadata` |
| 查询 | `query_catalog` | `opscli query catalog` |
| 查询 | `query_simple` | `opscli query simple` |
| 查询 | `query_build` | `opscli query build` |
| 查询 | `query_run` | `opscli query run` |
| 查询 | `query_build_and_run` | `opscli query build --run` |
| 查询 | `query_chart` | `opscli query chart` |
| 查询 | `query_chart_doc` | `opscli query chart-doc` |
| Skills | `skills_list` | `opscli skills list` |
| Skills | `skills_install` | `opscli skills install` |
| Skills | `skills_status` | `opscli skills status` |
| Skills | `skills_upgrade` | `opscli skills upgrade` |
| Knowledge | `search` | （CLI 无直接对应） |
| Knowledge | `fetch` | （CLI 无直接对应） |
