# opscli API 使用文档

> 版本：v1.2（2026-09-14）｜适用：`aukeys-opscli >= 0.0.129`
> 本文面向**通过 HTTP 调用 opscli 服务端**的使用者。调用纪律与部署约束见 [API调用规范](../spec/API调用规范.md)；进程内 Python 调用见 [SDK使用文档](SDK使用文档.md)。

---

## 1. 服务简介

opscli 可以服务端形态运行：一条 `opscli-mcp` 命令同时提供 **REST API**（`/api/v1/*`，面向网站与业务系统）与 **MCP 端点**（`/mcp`、`/sse`，面向 AI Agent）。两者共用业务内核与治理，但 REST 使用 AppHub 身份，MCP 端点继续使用 MCP API Key。

当前 REST 能力：

- **query 取数全家桶（12 个端点）**：自然语言规划/取数、数据集元数据、语义目录、payload 构造与执行、图表查询；
- **Keepa 场景（2 个端点）**：场景清单与场景执行；
- **SellerSprite 场景**：场景/额度、普通异步任务与 Listing Analysis；
- **认证检查**：当前 AppHub OPS 凭据检查；
- **健康检查（1 个端点）**。

快速自检：服务启动后打开 `http://<host>:<port>/docs` 查看当前 Swagger 文档（`/openapi.json` 为机器可读合同）。

---

## 2. 启动服务

### 2.1 MCP 固定 Key 模式

```bash
opscli-mcp --transport both --host 0.0.0.0 --port 8765
```

启动输出：

```
[opscli-mcp] 服务已启动（模式：both）
[opscli-mcp] 固定 API Key: <自动生成或读取自 ~/.config/opscli/mcp_api_key>
[opscli-mcp] SSE: http://0.0.0.0:8765/sse
[opscli-mcp] Streamable HTTP: http://0.0.0.0:8765/mcp
```

CLI 参数：`--transport sse|http|both`（缺省为 stdio，**无 REST API**）、`--host`（默认 0.0.0.0）、`--port`（默认 8765）、`--auth-verify-url`。

### 2.2 MCP 远程校验模式

```bash
opscli-mcp --transport both --auth-verify-url https://<ops-host>/v1/mcp/verify-key
```

不传 `--auth-verify-url` 时会自动用 `config.ini` 的 `ops_url` 拼接。该参数只影响 `/mcp`、`/sse`，不参与 REST 鉴权。

### 2.3 准备 AppHub 登录态

REST 业务请求使用以下任一方式：

- Session：Cookie `polarisUserToken` 或 Header `X-Session-Id`，服务端调用 `AuthClient.get_me()` 校验身份；
- viewer：`X-Ops-Token` + `X-User-Email`，可选 `X-User-Id` / `X-User-Name`；
- 本地开发：显式设置 `LOCAL_AUTH_FALLBACK_ENABLED=true`，生产必须关闭。

SellerSprite 不需要额外配置 Collector Gateway Key。Collector 必须部署在受限网络中，仅允许通用 opscli MCP 访问；浏览器和公网不得直连 Collector。

---

## 3. 快速开始

```bash
BASE=http://127.0.0.1:8765
OPS_TOKEN=<你的-ops-token>
SESSION_ID=<你的-session-id>
USER_EMAIL=<你的邮箱>

# 1) 健康检查（无需 Key）
curl -s $BASE/health/live
# {"status":"live"}

# 2) 一句话取数：规划 + 执行一步完成
curl -s -X POST "$BASE/api/v1/query/flow" \
  -H "X-Ops-Token: $OPS_TOKEN" -H "X-Session-Id: $SESSION_ID" \
  -H "X-User-Email: $USER_EMAIL" -H "Content-Type: application/json" \
  -d '{"request": "近30天各站点销售额", "limit": 100}'
```

响应（统一信封）：

```json
{
  "success": true,
  "data": {
    "plan": { "...": "规划信息" },
    "result": { "rows": ["..."], "row_count_returned": 100, "total_count": 4521, "truncated": true }
  },
  "error": null
}
```

> `total_count > row_count_returned` 时需要按 `limit`/`offset` 翻页取全，不要假设一次拿全。

---

## 4. 鉴权

- Session 模式优先使用 Cookie `polarisUserToken`，其次 `X-Session-Id`；可同时携带 `X-Ops-Token`；
- viewer 模式要求 `X-Ops-Token + X-User-Email`，用户身份头必须来自可信 AppHub 宿主；
- 请求体中传 `session_id` / `jwt` / `userEmail` 会被合同直接拒绝（422）；
- AppHub 登录态缺失、无效或过期 → `401` 信封 `authentication_required`；
- MCP API Key 只用于 `/mcp`、`/sse`。

---

## 5. 统一响应信封

```json
// 成功
{"success": true, "data": ..., "error": null}
// 失败
{"success": false, "data": null, "error": {"code": "INVALID_PAYLOAD", "message": "..."}}
```

三条使用纪律：

1. **必须检查 `success` 字段**：`/api/v1/query/simple`（`run=true`）在取数后端内层失败时返回 **HTTP 200 + `success=false`**，错误明细在 `error`；
2. 分支只依据 `error.code` 与状态码，不要解析 `message` 文本（内部异常会被脱敏为通用文案）；
3. `/health/live` 是唯一无信封端点。

错误码速查：

| HTTP | code | 含义 / 处理 |
| ---- | ---- | ----------- |
| 400 | `INVALID_PAYLOAD` | 参数不合法，修正请求 |
| 401 | `authentication_required` | 完成 opscli 账号授权（见 §2.3） |
| 404 | `DATASET_NOT_FOUND` | 数据集别名/表 ID 不存在 |
| 422 | `VALIDATION_ERROR` | 请求体不符合合同（多余字段、超长、类型错误），message 含逐字段原因 |
| 502 | `REMOTE_HTTP_ERROR` 等 | 上游玩数/Keepa 后端失败，可稍后重试 |
| 503 | `QUERY_METADATA_NOT_READY` | 元数据未就绪，稍后重试 |

---

## 6. 端点参考

### 6.1 健康检查

#### `GET /health/live`（公开）

```bash
curl -s http://127.0.0.1:8765/health/live   # {"status":"live"}（无信封）
```

### 6.2 query 取数（前缀 `/api/v1`，均需业务账号）

#### `POST /query/plan` — 自然语言 → 规划合同（只规划不执行）

| 字段 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| request | string | 是 | 自然语言需求（1~4000 字） |
| requested_fields | list[string] | 否 | 期望字段提示（≤100） |
| top_n | int | 否 | Top N 类问题（1~50） |

```bash
curl -s -X POST $BASE/api/v1/query/plan -H "X-Ops-Token: $OPS_TOKEN" \
  -H "X-Session-Id: $SESSION_ID" -H "X-User-Email: $USER_EMAIL" \
  -H "Content-Type: application/json" \
  -d '{"request":"近7天美国站点广告花费Top10的ASIN","top_n":10}'
```

返回 `query_plan_model_contract_v2` 规划合同（data 内含选中的数据集、维度、指标、筛选），可将其转成 payload 后走 `/query/run`。

#### `POST /query/flow` — 一句话取数（规划 + 执行一体化）

| 字段 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| request | string | 是 | 自然语言需求 |
| requested_fields | list[string] | 否 | 期望字段提示 |
| limit | int | 否 | 行数上限（1~10000） |
| order_by | list[{field, desc}] | 否 | 结果排序 |
| offset | int | 否 | 翻页偏移 |

多币种问题会逐项执行并合并返回。**推荐业务系统首选此端点**（一次调用拿到结果），AI Agent 侧等价 MCP 工具为 `query_flow`。

#### `GET /query/preferences` — 当前用户的图表字段偏好

无参数。返回该账号在 BI 系统中保存的维度/指标偏好列表。

#### `GET /query/metadata` — 数据集元数据

| Query 参数 | 说明 |
| ---------- | ---- |
| dataset | 数据集别名或名称（与 table_id 二选一） |
| table_id | 数据集表 ID（≥1） |
| all_fields | `true` 返回全量授权数据集全部字段（带用户级缓存，1 小时） |

```bash
curl -s "$BASE/api/v1/query/metadata?dataset=ds_xxx" -H "X-Session-Id: $SESSION_ID"
curl -s "$BASE/api/v1/query/metadata?all_fields=true" -H "X-Session-Id: $SESSION_ID"
```

返回维度/指标字段列表、`select_columns`、`filter_configs` 等，是构造查询前的必读信息。

#### `GET /query/catalog` — 数据集业务语义索引

| Query 参数 | 说明 |
| ---------- | ---- |
| source | `remote`（默认）/ `local` |
| fallback_local | 远端失败是否回退本地（默认 true） |

#### `POST /query/intents/match` — 自然语言匹配语义目录意图

```json
{"query": "各站点销售额", "source": "remote", "fallback_local": true}
```

#### `POST /query/run` — 执行完整 query payload

| 字段 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| payload | object | 是 | `query_spec` 规范的完整查询 JSON |
| intent_code / selection_source / match_record_id | | 否 | 归因三元组（可选） |
| timeout | int | 否 | 执行超时（1~300 秒） |

`payload` 中 **禁止手写** `userEmail`、`query.from.table/permission/database`（服务端校验直接拒绝）；这些字段应从 `/query/build`、`/query/simple` 或 plan 合同转换得到。可先 `GET /charts/{uuid}` 拿到现成结构参考。

#### `POST /query/build` — 简化参数构造标准 payload（可立即执行）

| 字段 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| dataset | string | 与 table_id 二选一 | 数据集别名 |
| table_id | int | 同上 | 数据集表 ID |
| dimensions | list[string] | 否 | `field_name\|global_alias\|verbose_name[:alias]` |
| metrics | list[string] | 否 | `field_name\|global_alias\|verbose_name:aggregation[:alias]` |
| where | list[object] | 否 | 结构化筛选条件（≤100） |
| having | list[string] | 否 | `expr\|operator\|value_json` |
| order_by | list[string] | 否 | 排序（≤50） |
| limit / offset | int | 否 | 默认 20 / 0（limit ≤500000） |
| dry_run | bool | 否 | 只构造不执行 |
| data_comparison | string | 否 | `field,start_date,end_date` |
| global_currency | string | 否 | USD/GBP/CAD/EUR/JPY/CNY |
| run | bool | 否 | 构造后立即执行（默认 false） |
| timeout | int | 否 | 1~300 秒 |

#### `POST /query/simple` — simple query 构造 + 可选执行（AI 取数常用）

```json
{
  "table_id": 35,
  "payload": {
    "dimensions": [{"field": "site_name"}],
    "metrics": [{"field": "sales", "aggregation": "sum"}],
    "filters": [{"field": "date_id", "operator": ">=", "value": "2026-08-01"}],
    "limit": 100
  },
  "run": true,
  "timeout": 180
}
```

- `table_id` 必填；`payload` 内键与 CLI `--payload` JSON 同构（snake_case），未知键忽略；
- 顶层 `global_currency` 优先于 `payload.global_currency`；
- `run=true` 时自带字段校验，且**注意 §5 纪律 1**：内层失败是 HTTP 200 + `success=false`；
- 归因字段（intent_code / selection_source / match_record_id）可选。

#### `GET /charts/{chart_uuid}` — 图表查询结构（不执行）

返回该 BI 图表保存的全部子查询结构（新旧格式已归一化），可直接转成 payload 执行。

#### `POST /charts/{chart_uuid}/run` — 执行图表全部子查询并合并

```json
{"dry_run": false, "timeout": 180}
```

#### `GET /charts/{chart_uuid}/doc` — 生成该图表的 API 调用 Markdown 文档

返回 `data.markdown`，可直接作为对接文档使用（不写服务端文件）。

### 6.3 keepa（前缀 `/api/v1`）

#### `GET /keepa/scenarios` — 场景清单（公开，无需业务账号）

返回可执行场景定义，用于探测场景名与参数要求。

#### `POST /keepa/run` — 执行 Keepa 场景

| 字段 | 类型 | 必填 | 说明 |
| ---- | ---- | ---- | ---- |
| scenario | string | 是 | 场景名（见 scenarios） |
| params | object | 否 | 场景参数 |
| site | string | 否 | 站点，默认 `US` |
| export_format | string | 否 | `xls`（默认）/ `xlsx` / `json` |
| job_id | string | 否 | 幂等 ID（`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`） |
| reserve_tokens | int | 否 | 预留 Token |
| force | bool | 否 | 忽略额度保护强制执行 |
| wait | bool | 否 | 等待任务完成（长任务建议 false + 轮询 job 状态） |

```bash
curl -s -X POST $BASE/api/v1/keepa/run -H "X-Ops-Token: $OPS_TOKEN" \
  -H "X-Session-Id: $SESSION_ID" -H "X-User-Email: $USER_EMAIL" \
  -H "Content-Type: application/json" \
  -d '{"scenario":"product_lookup","params":{"asin":"B0XXXXXXX"},"site":"US","export_format":"json"}'
```

响应即 Keepa MCP 工具的统一合同，额外附 `quota`（当日额度占用）；受与 MCP 相同的日额度治理，失败自动退回额度。导出文件获取方式与 MCP `keepa export` 一致。

---

## 7. 典型对接流程

### 7.1 业务系统一句话取数（最短路径）

```
/query/flow（request + limit） → 检查 success / truncated → 翻页（offset）或结束
```

### 7.2 精确控制查询（三步）

```
GET /query/metadata?dataset=xxx        # 读字段，确定维度/指标标识
POST /query/build（run=false）          # 构造 payload，先检查合法性
POST /query/run（payload）              # 执行；大结果集按 offset 翻页
```

### 7.3 BI 图表数据直连

```
GET /charts/{uuid}                     # 拿子查询结构（可缓存）
POST /charts/{uuid}/run（dry_run 可先验证 SQL）
```

### 7.4 错误处理伪代码

```python
resp = http.post(
    url,
    json=body,
    headers={"X-Session-Id": session_id, "X-Ops-Token": ops_token},
    timeout=310,
)
if resp.status_code == 503:
    wait_and_retry(delay=resp.headers.get("Retry-After", 5))
elif resp.status_code in (400, 422, 404):
    fix_request(resp.json()["error"]["message"])   # 修改请求，不可原样重试
elif resp.status_code == 401:
    refresh_apphub_login()                          # 不原样重放业务请求
elif resp.status_code == 502:
    retry_with_backoff()                            # 上游失败，可幂等重试
envelope = resp.json()
if not envelope["success"]:            # 200 也可能失败（query/simple 内层失败）
    handle(envelope["error"])
data = envelope["data"]
if data.get("truncated"):
    paginate(offset=data["row_count_returned"])
```

---

## 8. 常见问题

**Q：REST 返回 401 `authentication_required` 怎么处理？**
当前 AppHub Session/Token 缺失、无效或已过期，刷新 AppHub 登录态后重新发起请求。MCP Key 的裸 `Unauthorized` 只会出现在 `/mcp`、`/sse`。

**Q：请求返回 422 说某字段不允许？**
合同是 `extra="forbid"`：只接受 OpenAPI 文档中列出的字段。传了 MCP 工具的参数（如 `session_id`）、CLI 专属参数（如 `skills_dir`）都会被拒。以 `/docs` 的合同为准。

**Q：为什么 HTTP 200 却失败了？**
`/query/simple`（`run=true`）的内层失败语义：取数服务在 200 信封内返回执行失败。检查 `success` 与 `error` 字段。

**Q：查询一直超时？**
REST 侧 `timeout` 上限 300 秒。大数据量建议：缩小时间窗、减少维度粒度、分页拉取；服务端默认执行超时 120 秒，可按请求传 `timeout` 调整（≤300）。

**Q：能拿到和 CLI 完全一致的数据吗？**
能。REST、MCP、CLI 共用同一 `QueryManager` 和业务实现；REST 与 MCP 使用不同传输鉴权，但解析到同一账号时查询结果一致。

**Q：其他服务（opscli-collector-mcp 等）有 REST API 吗？**
没有。REST API 仅在 `opscli-mcp` 上；collector 系列是纯 MCP 服务。stdio 模式下也没有 REST API。
