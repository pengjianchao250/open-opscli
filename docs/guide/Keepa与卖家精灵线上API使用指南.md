# Keepa 与卖家精灵线上 API 使用指南

> 文档日期：2026-09-14
>
> 适用范围：opscli 场景 REST API v1
>
> 线上地址：`https://ops.mcp.xenkee.com`

本文面向网站、内部服务和自动化任务调用方，说明 Keepa 与卖家精灵线上 REST API 的鉴权方式、接口路径、请求参数、异步任务流程、返回结构和错误处理。

## 1. 接入准备

### 1.1 环境变量

项目根目录 `.env` 使用以下配置：

```env
OPSCLI_REST_BASE_URL=https://ops.mcp.xenkee.com
OPSCLI_APPHUB_OPS_TOKEN=your_ops_token
OPSCLI_APPHUB_SESSION_ID=your_session_id
OPSCLI_APPHUB_USER_EMAIL=user@aukeys.com
```

Keepa 与 SellerSprite 使用同一个 REST Base URL 和 AppHub 登录态。不要把 Token、Session 或 Cookie 写入代码、日志、任务参数或版本库。

### 1.2 鉴权

推荐直接传 AppHub Session；viewer 环境也可传 OPS Token 与受信用户身份：

```http
X-Session-Id: <APPHUB_SESSION>
X-Ops-Token: <OPS_TOKEN>
X-User-Email: <USER_EMAIL>
Content-Type: application/json
Accept: application/json
```

存在 Session 时，服务端通过 `AuthClient.get_me()` 校验并解析身份，`X-User-Email` 可省略。没有 Session 时必须同时提供 `X-Ops-Token` 与可信的 `X-User-Email`；浏览器应使用 SDK 的 `credentials: include` 携带 `polarisUserToken` Cookie。`?api_key=` 和 MCP Bearer Key 只属于 `/mcp`、`/sse`，不再用于 REST。

PowerShell 公共变量：

```powershell
$baseUrl = $env:OPSCLI_REST_BASE_URL.TrimEnd('/')
$headers = @{
    "X-Session-Id" = $env:OPSCLI_APPHUB_SESSION_ID
    "X-Ops-Token" = $env:OPSCLI_APPHUB_OPS_TOKEN
    "X-User-Email" = $env:OPSCLI_APPHUB_USER_EMAIL
    Accept = "application/json"
    "Content-Type" = "application/json"
}
```

### 1.3 OPS 凭据与 Keepa 账号池

REST 认证与 MCP API Key 已分离。Keepa API Key 默认从 MySQL `api_credentials` 凭据池领取，不再通过当前 AppHub 用户的 OPS Token/Session 拉取集成账号。请求中的 OPS Token/Session 只用于用户身份治理和可选的导出文件上传。

SellerSprite 由通用 REST 网关代理到 Collector。浏览器仍只提交 AppHub 登录态；网关转发已验证用户身份和任务级 Session/JWT，Collector 显式信任该上游身份，不再要求单独的 Gateway Key。Collector MCP 端口必须通过防火墙、安全组、容器网络或反向代理限制为仅通用 opscli MCP 可访问，浏览器和公网不得直连。

REST 请求体不接受 `session_id`、`jwt`、`output_dir` 等内部字段，也不会在响应中返回 Session 或 JWT。`auth_mcp_login` 仅属于 MCP 客户端流程，不是 REST 前置步骤。

`OPSCLI_KEEPA_API_KEY` 仅作为 MySQL 凭据池不可用时的本地调试兜底。线上应在 `keepa` Provider 下配置主备账号，由服务端负责优先级选择、失败切换、额度状态和冷却时间回写；身份、每日调用额度与审计仍使用 AppHub principal。

## 2. 通用返回合同

业务接口统一使用以下信封：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

业务失败示例：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "错误说明"
  }
}
```

调用方必须同时检查 HTTP 状态码、响应体 `success` 和异步任务的 `data.state`。Keepa 的业务错误可能返回 HTTP 200 和 `success=false`，不能只根据 HTTP 200 判断成功。

## 3. 接口总览

| 方法 | 路径 | 说明 | 成功状态 |
| --- | --- | --- | --- |
| GET | `/health/live` | 服务存活检查 | 200 |
| POST | `/api/v1/auth/ensure` | 可选：检查当前 AppHub OPS 凭据 | 200 |
| GET | `/api/v1/keepa/scenarios` | Keepa 场景列表 | 200 |
| POST | `/api/v1/keepa/run` | 执行 Keepa 同步场景 | 200 |
| GET | `/api/v1/seller-sprite/scenarios` | 卖家精灵场景列表 | 200 |
| GET | `/api/v1/seller-sprite/quota` | 卖家精灵当前用户额度 | 200 |
| POST | `/api/v1/seller-sprite/jobs` | 提交普通异步任务 | 202 |
| GET | `/api/v1/seller-sprite/jobs/{job_id}` | 单任务状态 | 200 |
| POST | `/api/v1/seller-sprite/jobs/status` | 批量任务状态 | 200 |
| GET | `/api/v1/seller-sprite/jobs/{job_id}/result` | 读取 JSON 内联结果 | 200/202 |
| GET | `/api/v1/seller-sprite/jobs/{job_id}/export` | 读取 JSON 结果或 XLSX 下载信息 | 200/202 |
| POST | `/api/v1/seller-sprite/listing-analysis/jobs` | 提交 Listing Analysis | 202 |
| GET | `/api/v1/seller-sprite/listing-analysis/jobs/{job_id}` | Listing Analysis 状态 | 200 |
| GET | `/api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result` | Listing Analysis 结果 | 200/202 |

## 4. 健康检查与凭据预热

### 4.1 GET `/health/live`

```powershell
Invoke-RestMethod -Uri "$baseUrl/health/live" -Headers $headers -Method Get
```

响应：

```json
{"status": "live"}
```

该接口只表示网关进程可响应，不代表 Keepa 上游账号、卖家精灵 Collector 或浏览器 Worker 一定可用。

### 4.2 POST `/api/v1/auth/ensure`

该接口用于发布验收、故障诊断或提前预热 OPS Session/JWT。正常 Keepa 业务请求会自动执行相同的凭据保障逻辑，不要求调用方先调用本接口。

```powershell
$authStatus = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/auth/ensure" `
    -Headers $headers `
    -Method Post
```

成功响应：

```json
{
  "success": true,
  "data": {
    "authenticated": true,
    "refreshed": true
  },
  "error": null
}
```

`refreshed=true` 表示本次请求新建了 Session 或获取了新的 OPS JWT；`false` 表示直接复用了已有有效凭据。响应不会包含用户邮箱、凭据目录、Session ID 或 JWT。

凭据无法建立时返回 HTTP 502 和错误码 `OPS_CREDENTIAL_ENSURE_FAILED`。AppHub Session/Token 缺失、无效或无法解析身份时返回 HTTP 401。

## 5. Keepa API

Keepa REST 为同步调用。成功时直接在 `data.data` 返回完整格式化业务数据，不要求调用方再下载导出文件。

### 5.1 获取场景列表

#### GET `/api/v1/keepa/scenarios`

```powershell
Invoke-RestMethod -Uri "$baseUrl/api/v1/keepa/scenarios" -Headers $headers -Method Get
```

每个场景包含 `scenario_id`、`title`、`endpoint`、`required_params` 和 `description`。客户端应优先读取线上场景列表，不要假设本地文档一定与线上版本完全同步。

### 5.2 执行查询

#### POST `/api/v1/keepa/run`

| 字段 | 类型 | 必填 | 默认值 | 约束与说明 |
| --- | --- | --- | --- | --- |
| `scenario` | string | 是 | 无 | 1-64 字符，取值见场景表 |
| `params` | object | 否 | `{}` | 场景业务参数 |
| `site` | string | 否 | `US` | 2-8 字符，支持站点见下表 |
| `export_format` | string | 否 | `xls` | `xls`、`xlsx`、`json`；REST 均直接返回格式化数据 |
| `job_id` | string | 否 | 自动生成 | 1-128 字符，只允许字母、数字、点、下划线和连字符，首字符必须为字母或数字 |
| `reserve_tokens` | integer | 否 | 服务决定 | 大于等于 0，用于 Keepa token 预留 |
| `force` | boolean | 否 | `false` | 是否忽略可复用结果并强制执行 |
| `wait` | boolean | 否 | `false` | 是否等待执行完成；REST 通常建议传 `true` |

不允许额外字段。传入 `session_id`、`jwt`、`output_dir` 或路径穿越形式的 `job_id` 会返回 422。

支持站点：`US`、`GB`/`UK`、`DE`、`FR`、`JP`、`CA`、`IT`、`ES`、`IN`、`MX`、`BR`。

### 5.3 Keepa 场景参数

| `scenario` | 必填参数 | 常用可选参数 | 关键限制 |
| --- | --- | --- | --- |
| `product` | `asin`/`asins` 或 `code`/`codes` | `stats`、`offers`、`update`、`days`、`history`、`buybox`、`rating`、`videos`、`aplus`、`stock`、`only_live_offers`、`historical_variations`、`code_limit` | ASIN/code 二选一；最多 100 个；`offers` 为 20-100 |
| `product-search` | `keyword` 或 `term` | `stats`、`update`、`history`、`asins_only`、`rating` | 当前不支持 `page` |
| `product-finder` | `selection` 或至少一个顶层筛选字段 | `stats` | `selection` 必须是 JSON 对象，可含 `perPage`、`page`、`sort` |
| `category-search` | `keyword` 或 `term` | 无 | 按类目名称搜索 |
| `category-lookup` | `category` 或 `categories` | `parents` | 最多 10 个类目 ID |
| `seller` | `seller` 或 `sellers` | `storefront` | 最多 100 个；`storefront=true` 时只能查 1 个 seller |
| `seller-finder` | `selection` 或至少一个筛选字段 | `perPage`、`page`、`sort` 等 | `selection` 必须非空 |
| `top-seller` | 无 | 无 | 获取站点 Top Sellers，调用成本相对较高 |
| `bestsellers` | `category`、`productGroup` 或 `product_group` | `range`、`month`、`year`、`variations`、`sublist` | `range` 仅 0/30/90/180；`month/year` 成对且限过去 36 个完整自然月 |
| `deals` | `selection.priceTypes` | 其他 Deals selection 字段 | `priceTypes` 必须且只能包含 1 个支持索引 |
| `lightning-deals` | 无 | `asin`、`state` | 不传 ASIN 会查询完整列表，成本很高 |

`deals` 支持的 `selection.priceTypes[0]`：

```text
0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
16, 17, 18, 32, 33, 34, 35
```

### 5.4 Keepa 示例

商品详情：

```powershell
$body = @{
    scenario = "product"
    site = "US"
    params = @{ asin = "B003IEUAZK"; history = $false; stats = 30 }
    export_format = "json"
    wait = $true
} | ConvertTo-Json -Depth 10

$result = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/keepa/run" `
    -Headers $headers -Method Post -Body $body
```

关键词搜索：

```json
{
  "scenario": "product-search",
  "site": "US",
  "params": {"keyword": "flashlight", "stats": 30, "asins_only": false},
  "export_format": "json",
  "wait": true
}
```

Product Finder：

```json
{
  "scenario": "product-finder",
  "site": "US",
  "params": {
    "stats": true,
    "selection": {
      "current_SALES_gte": 1,
      "current_SALES_lte": 5000,
      "perPage": 50,
      "page": 0
    }
  },
  "export_format": "json",
  "wait": true
}
```

Seller 店铺信息：

```json
{
  "scenario": "seller",
  "site": "US",
  "params": {"seller": "A2L77EE7U53NWQ", "storefront": true},
  "export_format": "json",
  "wait": true
}
```

Deals：

```json
{
  "scenario": "deals",
  "site": "US",
  "params": {"selection": {"priceTypes": [18], "page": 0}},
  "export_format": "json",
  "wait": true
}
```

### 5.5 Keepa 成功响应

```json
{
  "success": true,
  "data": {
    "job_id": "Keepa-Product-US-...",
    "scenario": "product",
    "site": "US",
    "row_count": 1,
    "data": [],
    "warnings": [],
    "request_source": "api",
    "response_mode": "formatted_data"
  },
  "error": null,
  "quota": {
    "service": "keepa",
    "limit": 400,
    "used": 1,
    "remaining": 399,
    "failures": 0,
    "reset_at": "2026-09-05T00:00:00+08:00"
  }
}
```

REST 模式返回完整 `data.data`，不会返回 MCP 模式的 `data_preview`；也不上传导出文件，因此通常没有 `data.export`。`quota` 是 opscli MCP 每日调用额度，不是 Keepa token 余额。

## 6. 卖家精灵 API

卖家精灵普通任务是异步流程：提交任务、保存 `job_id`、查询状态、读取结果。

### 6.1 获取场景列表

#### GET `/api/v1/seller-sprite/scenarios`

```powershell
$scenarios = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/seller-sprite/scenarios" `
    -Headers $headers -Method Get
```

客户端应在使用新增场景前查询此接口。当前线上验证返回 16 个场景：

```text
aba-research, aba-reverse, branddb, association-traffic,
competitor-lookup, product-research, keyword-comparison,
keyword-conversion-rate, keyword-miner, keyword-research,
keyword-reverse, real-time-bidding, traffic-source,
traffic-extend, market-research, listing-analysis
```

### 6.2 查询额度

#### GET `/api/v1/seller-sprite/quota`

普通账号示例：

```json
{
  "success": true,
  "data": {
    "service": "seller_sprite",
    "unlimited": false,
    "limit": 20,
    "used": 1,
    "remaining": 19,
    "failures": 0,
    "reset_at": "2026-09-05T00:00:00+08:00"
  },
  "error": null
}
```

专属账号返回 `unlimited=true`，此时 `limit`、`remaining` 和 `reset_at` 可以为 `null`，不能解释为额度耗尽。

### 6.3 提交普通任务

#### POST `/api/v1/seller-sprite/jobs`

| 字段 | 类型 | 必填 | 默认值 | 约束与说明 |
| --- | --- | --- | --- | --- |
| `scenario` | string | 是 | 无 | 1-64 字符；`listing-analysis` 必须使用专用接口 |
| `params` | object | 否 | `{}` | 场景业务参数 |
| `site` | string | 否 | `US` | 2-8 字符 |
| `period` | string | 否 | `30d` | 1-32 字符，如 `30d`、`nearly`、`2026-08`、ABA 周结束日 |
| `page_size` | integer | 否 | `100` | 1-100；部分场景固定使用 100 或只取第一页 |
| `export_format` | string | 否 | `xls` | `xls`、`xlsx`、`json` |
| `job_id` | string | 否 | 自动生成 | 规则与 Keepa `job_id` 相同 |

请求成功返回 HTTP 202。`state=queued` 或 `state=running` 只表示已受理，不表示采集完成。

禁止传入 `session_id`、`jwt`、`output_dir`、`mode`、`async_mode`、浏览器类型或调度参数。

### 6.4 卖家精灵场景参数

| `scenario` | 必填参数 | 常用可选参数 | 说明 |
| --- | --- | --- | --- |
| `competitor-lookup` | `keyword`、`brand`、`sellerName`、`asins` 四选一 | `node`、`category`、`nodeIdPath`、`nodeIdPaths` | 商品链接需先提取 ASIN；`asins` 是指定商品筛选，不是自动发现竞品 |
| `product-research` | 无 | `recommendationMode`、类目、销量、销售额、价格、评分、卖家、关键词筛选 | 选品筛选，数据月份使用顶层 `period` |
| `keyword-miner` | `keyword` | `filterRootWord`、`amazonChoice`、`includeHighFrequency` | 默认第一页 |
| `keyword-research` | 无 | `keywords`、`departments`、搜索量、增长率、购买率、均价、评分、PPC 范围 | 顶层 `period` 使用 `YYYY-MM`；只取第一页 100 条 |
| `aba-research` | `q`、`keywordOrAsin`、`keyword`、`asin` 四选一 | `reverseType`、`departments`、`rankGrowthType`、范围筛选、排序 | 默认最近完整周；固定第一页 100 条 |
| `branddb` | `text` | `feature`、`office`、`brandName`、`status`、`applicant`、`niceClass`、年份、排序、`ids` | 只支持 XLS/XLSX，最长等待约 120 秒，不自动重放 |
| `association-traffic` | `asins`，1-20 个 | `relations`、`orderField`、`desc` | 固定全部变体，第一页 100 条 |
| `traffic-extend` | `asins`，1-20 个 | `variantSelection` | `all`、`sell_well`、`current`；第一页 100 条 |
| `keyword-comparison` | `ownAsin` 1 个、`competitorAsins` 1-10 个 | `variantSelection` | 竞品不得包含自己的 ASIN；默认 `sell_well` |
| `keyword-conversion-rate` | `keywords`，1-1000 个词组 | 顶层 `period` | 周期只支持 `W` 或 `90D`；第一页 100 条 |
| `real-time-bidding` | `asin`，只能 1 个 | 无 | 读取最新已完成历史任务，合并 SP/SB/SBV 第一页 |
| `aba-reverse` | `asin`/`asins`，1-20 个 | `reverseType`、`orderField`、`orderDesc`、`conversionType`、`loadVariations` | 默认最近完整周；仅 XLS/XLSX；保留官网原始工作簿 |
| `keyword-reverse` | `asin` | `badges` | 从 ASIN 反查关键词 |
| `traffic-source` | `keyword` 或 `asin`/`asins` | `order`、`desc` | 查询关键词或 ASIN 的流量去向 |
| `market-research` | 无 | `departmentKeyword`、`category`、`node`、`topn`、新品月数、市场范围筛选 | 选市场和市场结构分析 |
| `listing-analysis` | `asin` | `station` | 不走普通 `/jobs`，必须使用 Listing Analysis 专用接口 |

完整字段、别名、枚举和页面口径以 [卖家精灵场景参数手册](../../opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md) 为准。

### 6.5 提交示例

指定 ASIN 查询：

```powershell
$body = @{
    scenario = "competitor-lookup"
    site = "US"
    period = "30d"
    params = @{ asins = @("B003IEUAZK") }
    page_size = 20
    export_format = "json"
} | ConvertTo-Json -Depth 10

$submitted = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/seller-sprite/jobs" `
    -Headers $headers -Method Post -Body $body

$jobId = $submitted.data.job_id
```

成功受理示例：

```json
{
  "success": true,
  "data": {
    "job_id": "SellerSprite-CompetitorLookup-US-...",
    "scenario": "competitor-lookup",
    "site": "US",
    "period": "30d",
    "state": "queued",
    "stage": "queued",
    "position": 1,
    "row_count": null,
    "export": null,
    "error": null
  },
  "error": null,
  "quota": {}
}
```

关键词反查：

```json
{
  "scenario": "keyword-reverse",
  "site": "US",
  "period": "30d",
  "params": {"asin": "B0XXXXXXXX"},
  "page_size": 100,
  "export_format": "json"
}
```

关键词挖掘：

```json
{
  "scenario": "keyword-miner",
  "site": "US",
  "period": "30d",
  "params": {
    "keyword": "flashlight",
    "filterRootWord": 1,
    "amazonChoice": true
  },
  "page_size": 100,
  "export_format": "json"
}
```

流量词对比：

```json
{
  "scenario": "keyword-comparison",
  "site": "US",
  "period": "30d",
  "params": {
    "ownAsin": "B0AAAAAAAA",
    "competitorAsins": ["B0BBBBBBBB", "B0CCCCCCCC"],
    "variantSelection": "sell_well"
  },
  "page_size": 100,
  "export_format": "json"
}
```

### 6.6 查询单任务状态

#### GET `/api/v1/seller-sprite/jobs/{job_id}`

| 参数 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `wait_seconds` | integer | `0` | 0-30；服务端最多等待指定秒数后返回最新状态 |

```powershell
$status = Invoke-RestMethod `
    -Uri "$baseUrl/api/v1/seller-sprite/jobs/$jobId?wait_seconds=30" `
    -Headers $headers -Method Get
```

| `state` | 含义 | 调用方动作 |
| --- | --- | --- |
| `queued` | 已入队，等待 Worker | 保留 `job_id`，继续查询 |
| `running` | 正在采集 | 保留 `job_id`，继续查询 |
| `succeeded` | 成功终态 | 读取 result 或 export |
| `failed` | 失败终态 | 读取 `data.error`，停止轮询 |
| `cancelled` | 已取消终态 | 停止轮询 |

推荐使用 `wait_seconds=30`，同一轮最多连续调用 3-4 次，总等待预算 90-120 秒。等待到期不代表任务失败，也不会取消任务。

### 6.7 批量查询状态

#### POST `/api/v1/seller-sprite/jobs/status`

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `job_ids` | string[] | 是 | 无 | 1-50 个任务 ID |
| `wait_seconds` | integer | 否 | `0` | 0-30 |

```json
{
  "job_ids": ["SellerSprite-Job-1", "SellerSprite-Job-2"],
  "wait_seconds": 30
}
```

多个 pending 任务应优先使用批量接口，避免逐个轮询造成不必要的请求量。

### 6.8 读取 JSON 结果

#### GET `/api/v1/seller-sprite/jobs/{job_id}/result`

支持 `wait_seconds=0-30`。

- 任务仍在执行：HTTP 202，返回最新状态。
- JSON 任务成功：HTTP 200，业务结果位于 `data.result`。
- 任务失败：检查 `state` 和 `error`。
- XLS/XLSX 任务调用该接口：HTTP 409，错误码 `SELLER_SPRITE_RESULT_FORMAT_NOT_JSON`。

成功示例：

```json
{
  "success": true,
  "data": {
    "job_id": "SellerSprite-...",
    "scenario": "competitor-lookup",
    "site": "US",
    "period": "30d",
    "state": "succeeded",
    "stage": "finished",
    "ready": null,
    "row_count": 1,
    "result": []
  },
  "error": null
}
```

### 6.9 读取导出

#### GET `/api/v1/seller-sprite/jobs/{job_id}/export`

- JSON 任务：直接返回与 `/result` 相同的内联业务结果，不返回冗余 JSON 下载链接。
- XLS/XLSX 任务：返回文件格式、文件名、MIME 类型和 HTTPS 下载 URL。
- 任务仍在执行：HTTP 202。

XLSX 导出信息示例：

```json
{
  "success": true,
  "data": {
    "format": "xlsx",
    "filename": "SellerSprite-KeywordReverse-US-....xlsx",
    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "url": "https://..."
  },
  "error": null
}
```

### 6.10 Listing Analysis

Listing Analysis 是独立三段式流程，通常需要 3 分钟以上。不要把 `listing-analysis` 提交给普通 `/jobs`。

#### 提交

POST `/api/v1/seller-sprite/listing-analysis/jobs`

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `asin` | string | 是 | 无 | 必须是 10 位字母数字 |
| `station` | string | 否 | `GLOBAL` | 1-16 字符 |
| `site` | string | 否 | `US` | 2-8 字符 |
| `export_format` | string | 否 | `json` | `xls`、`xlsx`、`json` |
| `job_id` | string | 否 | 自动生成 | 规则与普通任务相同 |

```json
{
  "asin": "B0XXXXXXXX",
  "station": "GLOBAL",
  "site": "US",
  "export_format": "json"
}
```

全景 Listing Analysis 通常会消耗卖家精灵 10 次额度，不要因为等待时间较长而重复提交同一 ASIN。

#### 查询状态

GET `/api/v1/seller-sprite/listing-analysis/jobs/{job_id}`

#### 读取结果

GET `/api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result?export_format=json`

`export_format=json` 时返回内联业务结果；XLS/XLSX 时返回文件合同。未完成时保留原 `job_id` 继续查询，不重新提交。

## 7. 推荐轮询实现

```powershell
for ($attempt = 1; $attempt -le 4; $attempt++) {
    $response = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/seller-sprite/jobs/$jobId?wait_seconds=30" `
        -Headers $headers -Method Get

    if (-not $response.success) {
        throw "$($response.error.code): $($response.error.message)"
    }

    $state = $response.data.state
    if ($state -eq "succeeded") { break }
    if ($state -in @("failed", "cancelled")) {
        throw "SellerSprite task ended with state=$state"
    }
}

if ($response.data.state -eq "succeeded") {
    $result = Invoke-RestMethod `
        -Uri "$baseUrl/api/v1/seller-sprite/jobs/$jobId/result" `
        -Headers $headers -Method Get
}
```

关键规则：

- 保存每次提交返回的 `job_id`。
- pending 任务不得重新提交。
- 状态查询和结果读取不重复消耗场景调用额度。
- 轮询预算结束仍为 pending 时，持久化 `job_id`，由后台任务稍后续查。
- 客户端超时应大于 `wait_seconds`，推荐至少 45-60 秒。

## 8. HTTP 状态与错误处理

| HTTP 状态 | 常见含义 | 建议处理 |
| --- | --- | --- |
| 200 | 查询成功，或业务信封已返回 | 继续检查 `success` 和任务 `state` |
| 202 | 卖家精灵任务已受理或仍在执行 | 保存 `job_id`，稍后查询 |
| 401 | AppHub Session/Token 缺失、无效或身份不完整 | 刷新 AppHub 登录态并重试 |
| 403 | 当前 AppHub 用户没有业务权限 | 联系管理员调整权限 |
| 404 | `job_id` 不存在或不属于当前用户 | 检查任务 ID 和当前 AppHub 用户 |
| 409 | 用 JSON result 接口读取 XLS/XLSX 任务 | 改用 `/export` |
| 422 | 请求字段、类型、范围或场景参数无效 | 修正请求，不要原样重试 |
| 502 | 上游接口、Collector 调用或结果转换失败 | 记录错误码和任务 ID，有限重试或联系管理员 |
| 503 | Collector 配置缺失、不可达或模块未就绪 | 检查 `error.code`、Collector 地址及模块状态 |

常见错误码：

| 错误码 | 含义 |
| --- | --- |
| `authentication_required` | 当前请求没有有效 AppHub 用户身份 |
| `OPS_CREDENTIAL_ENSURE_FAILED` | 服务端自动建立 OPS Session/JWT 失败，可用预热接口复现并诊断 |
| `KEEPA_CONFIG_ERROR` | Keepa 参数、MySQL 凭据池配置或可用账号缺失 |
| `KEEPA_API_ERROR` | Keepa 上游请求失败 |
| `COLLECTOR_MCP_CONFIG_MISSING` | 卖家精灵 Collector 配置缺失 |
| `COLLECTOR_MCP_UNAVAILABLE` | Collector 不可用 |
| `COLLECTOR_MCP_CALL_FAILED` | 网关调用 Collector 异常 |
| `QUEUE_DATABASE_UNAVAILABLE` | 卖家精灵任务队列不可用 |
| `SELLER_SPRITE_TASK_NOT_FOUND` | 任务不存在或当前用户不可见 |
| `SELLER_SPRITE_RESULT_FORMAT_NOT_JSON` | 当前任务不是 JSON 格式 |
| `SELLER_SPRITE_RESULT_INVALID` | Collector 返回的结果结构无效 |

建议日志只记录请求时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count`。

禁止记录 OPS Token、Session、JWT、Cookie、Collector 内部 Key、MCP API Key、卖家精灵账号密码和完整敏感业务响应。

### SellerSprite REST 502/503 预发布排查

更新并重启通用 opscli MCP/REST 网关后，复现失败接口，在**通用网关服务日志**中搜索
`Collector MCP proxy failed`。该日志使用 WARNING 级别，无需打开全局 DEBUG。
按请求时间和 `tool` 找到对应记录，读取行尾 `diagnostic` JSON：

| 字段 | 排查用途 |
| --- | --- |
| `stage` | `configuration`、`identity`、`arguments`、`remote_call` 或 `remote_result`，区分失败边界 |
| `gateway_version`、`collector_target` | 核对网关版本和实际下游主机/端口/路径；目标不含用户名、密码、查询串和 fragment |
| `auth_mode` | 对比 `remote` MCP Key 路径与 `apphub_session` / `apphub_viewer` REST 路径 |
| `identity_forwarded`、`api_key_forwarded` | 是否实际构造了可信身份头或 Bearer 头 |
| `session_forwarded`、`jwt_forwarded` | 实际工具参数是否携带任务凭证；场景列表等只读工具为 false 属正常情况 |
| `elapsed_ms`、`downstream_status` | 调用耗时，以及从 HTTP 异常提取的下游状态；无法取得时状态为 null |
| `remote_code`、`remote_message` | 远端错误码和脱敏摘要，摘要最多 1024 字符；缺失值为 `-` |

日志只描述网关侧观测：`remote_call` 覆盖 MCP 初始化、工具调用和会话清理，
`identity_forwarded=true` 不代表 Collector 已接受身份。若摘要仍是通用的工具失败提示，
按同一时间和工具名查 Collector 服务端异常日志。HTTP 响应合同保持不变，不回传远端原始正文。

先对同一 Collector 地址使用 MCP Key 与可信 AppHub 身份对照调用 `seller_sprite_scenarios`，
再调用 REST `/api/v1/seller-sprite/scenarios`；三条路径都成功后，复现原任务或结果接口。
可信身份对照只能在获准访问 Collector 的内部网关环境执行。

## 9. 线上验收记录

2026-09-04 使用 `.env` 中配置的线上地址和 API Key 完成以下真实验证。该记录发生在本次自动凭据保障增强部署前：

| 检查项 | 结果 |
| --- | --- |
| `/health/live` | HTTP 200，`status=live` |
| Keepa 场景列表 | HTTP 200，返回 11 个场景 |
| Keepa `product` 查询 | 初始化 OPS 登录态后 HTTP 200，`success=true`，返回 1 行 |
| 卖家精灵场景列表 | HTTP 200，返回 16 个场景 |
| 卖家精灵额度 | HTTP 200，测试用户为专属账号，`unlimited=true` |
| 卖家精灵 `competitor-lookup` 提交 | HTTP 202，成功进入队列 |
| 卖家精灵任务状态 | 约 25 秒进入 `succeeded`，返回 1 行 |
| 卖家精灵 JSON result | HTTP 200，`data.result` 可正常读取 |

增强前，Keepa 首次真实请求因该 API Key 的 OPS 登录态未初始化而返回 `KEEPA_CONFIG_ERROR`；手工调用 MCP `auth_mcp_login` 后相同请求成功。增强版本部署后，新 API Key 的首次 Keepa 请求应在访问 Keepa 上游前静默建立凭据，不再要求人工初始化；发布验收时可先调用 `/api/v1/auth/ensure` 确认该流程。

## 10. 代码与参数来源

- REST 请求模型和 Keepa 路由：[`opscli/api/app.py`](../../opscli/api/app.py)
- 卖家精灵 REST 路由：[`opscli/api/seller_sprite.py`](../../opscli/api/seller_sprite.py)
- Keepa 场景注册表：[`opscli/keepa/api/scenarios.py`](../../opscli/keepa/api/scenarios.py)
- 卖家精灵完整参数手册：[`SCENARIO_PARAMS_ZH.md`](../../opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md)
- 场景 API 产品化边界：[`场景API产品化规划.md`](../plans/场景API产品化规划.md)

线上能力可能先于本地文档更新。调用新增场景前，应以 `/api/v1/keepa/scenarios` 和 `/api/v1/seller-sprite/scenarios` 的实际响应为准。
