# API 调用规范

> 版本：v1.2（2026-09-14）
> 适用范围：所有通过 HTTP 调用 opscli 服务端 REST API（`/api/v1/*`）的网站前端、业务系统与脚本；以及部署、扩展该服务的开发者。
> 配套文档：[API使用文档](OPSCLI_API使用文档.md)（端点逐个参考与示例）、[SDK调用规范](OPSCLI_SDK调用规范.md)（进程内 SDK 调用约束）。

---

## 1. 总则

opscli 服务端以 `opscli-mcp` 为唯一对外 HTTP 入口：REST API 与 MCP 工具共用同一业务内核和治理（QueryManager、quota/telemetry 中间件同源），但传输鉴权明确分离：`/api/v1/*` 使用 AppHub 身份，`/mcp`、`/sse` 继续使用 MCP API Key。

### 1.1 基本事实

| 项目 | 值 |
| ---- | -- |
| 协议 | HTTP/1.1（uvicorn ASGI），JSON 编码 |
| REST 前缀 | `/api/v1`（health 除外：`/health/live`） |
| MCP 端点 | `/mcp`（Streamable HTTP）、`/sse`（SSE），与 REST 同进程同端口 |
| 端点总数 | 15 个：query 12 + keepa 2 + health 1 |
| 鉴权 | REST：AppHub viewer/session；MCP：API Key，见 §2 |
| OpenAPI | `/docs`（Swagger UI）、`/openapi.json` |
| CORS | 本地原型 4173/4174 与受限私有网段来源，支持凭据 Cookie，方法 GET/POST/OPTIONS |

### 1.2 服务形态边界

- `opscli-mcp --transport http|sse|both`：REST + MCP 组合服务（唯一推荐形态）。
- `opscli-mcp` 不带 `--transport`（或值非法）：stdio MCP 模式，**无 REST API**。
- `opscli-collector-mcp` / `opscli-collector-monitor`：纯 MCP 服务，**不带 REST 路由**。
- `create_api_app()` 的业务路由已通过 FastAPI 依赖执行 AppHub 鉴权；`wrap_mcp_app()` 组合后，外层 `ApiKeyAuthMiddleware` 只保护 `/mcp`、`/sse`。

---

## 2. 鉴权规范（A-Auth）

### 2.1 REST AppHub 鉴权

业务 REST 请求使用以下任一模式：

| 模式 | 传递方式 | 服务端行为 |
| ---- | -------- | ---------- |
| session | Cookie `polarisUserToken` 或 Header `X-Session-Id`；可同时传 `X-Ops-Token`/Bearer JWT | 调用 `AuthClient.get_me(session_id=..., jwt=...)` 校验会话并解析身份 |
| viewer | `X-Ops-Token` + `X-User-Email`，可选 `X-User-Id` / `X-User-Name` | 复用 AppHub 受信 viewer 身份和 OPS Token |
| local | 仅本地开发显式设置 `LOCAL_AUTH_FALLBACK_ENABLED=true` | 使用 `OPSCLI_LOCAL_AUTH_*`，生产必须关闭 |

浏览器请求必须使用 `credentials: include`，以便跨端口原型携带 Cookie。推荐使用 `@aukeys/ops-mcp-api-sdk`，不要再调用 `/api/v1/mcp-api-keys/config`，也不要在浏览器获取或缓存 MCP API Key。

**A-1 身份不进入业务请求体**：`session_id`、`jwt`、`userEmail` 等身份字段不属于 REST 业务合同，出现时由 `extra="forbid"` 拒绝（422）。身份只通过 Header/Cookie 进入认证依赖。

**A-2 隔离**：REST 元数据缓存按已验证用户邮箱哈希隔离；请求级 Session/JWT 通过 context 注入业务内核，不写入 API Key 隔离凭证目录。

### 2.2 MCP API Key 鉴权

`/mcp`、`/sse` 保持既有 API Key 鉴权和远程校验行为，支持 Bearer、`?api_key=` 与 MCP Inspector 代理 Header。该凭证仅供 MCP 客户端使用，不得复用于 `/api/v1/*` 浏览器 REST 请求。

SellerSprite REST 由通用服务代理到 Collector。Collector 显式信任通用服务转发的已验证用户身份和任务级 Session/JWT，不再使用单独的 Gateway Key。该信任仅在 Collector 网络入口只允许通用 opscli MCP 访问时成立；浏览器、普通 MCP 客户端和公网不得直连 Collector。

### 2.3 鉴权失败语义

| 场景 | 响应 |
| ---- | ---- |
| AppHub Session 缺失、无效或已过期 | `401` 统一信封 `authentication_required` |
| viewer 缺 Token 或用户邮箱 | `401` 统一信封 `authentication_required` |
| SellerSprite Collector 地址未配置或服务不可达 | `503`，`COLLECTOR_MCP_CONFIG_MISSING` / `COLLECTOR_MCP_UNAVAILABLE` |
| MCP API Key 缺失/无效（仅 `/mcp`、`/sse`） | `401` 中间件裸响应，reason=`invalid_api_key` |

**A-3 重试纪律**：REST `401` 先刷新 AppHub 登录态，不自动重放业务请求；`503` 按指示退避；`502` 仅在业务幂等时重试；`422/400` 修改请求后才重试。MCP Key 远程校验缓存策略只影响 `/mcp`、`/sse`。

---

## 3. 统一信封规范（A-Envelope）

### 3.1 响应形态

所有 REST 端点（`/health/live` 除外）返回统一信封，与 MCP 工具结构一致：

```json
// 成功
{"success": true, "data": <业务数据>, "error": null}
// 失败
{"success": false, "data": null, "error": {"code": "<错误码>", "message": "<可读原因>"}}
```

例外（务必区分）：

1. **`GET /health/live`** 返回裸 `{"status": "live"}`，无信封。
2. **`POST /api/v1/query/simple`（run=true）的内层失败**：取数后端可能在 HTTP 200 内返回执行失败，此时外层保持 200 但 `success=false`、`data` 为部分结果、`error` 携带明细。

**E-1 必须检查 `success` 字段**：调用方不得只看 HTTP 状态码判断成败，这是本 API 最重要的一条调用纪律。

### 3.2 状态码语义

| 状态码 | 含义 | 典型 code |
| ------ | ---- | --------- |
| 200 | 成功（检查 success 字段） | — |
| 400 | 请求参数不合法 | `INVALID_PAYLOAD` |
| 401 | AppHub 未认证；MCP 端点也可能是 API Key 无效 | `authentication_required` / `Unauthorized` |
| 404 | 目标资源不存在 | `DATASET_NOT_FOUND` |
| 422 | 请求体不符合合同（字段类型/长度/多余字段） | `VALIDATION_ERROR` |
| 502 | 上游（取数/Keepa 后端）执行失败 | `REMOTE_HTTP_ERROR` 等业务 code |
| 503 | 元数据未就绪 / Collector 配置或服务不可用 | `QUERY_METADATA_NOT_READY` / `COLLECTOR_MCP_UNAVAILABLE` |

### 3.3 错误信息边界

服务端只透出可据以修正请求的业务错误（`QueryError` / `ValueError` 家族原文）；其余内部异常统一脱敏为"查询服务执行失败，请稍后重试"。调用方**不应**解析 message 做程序分支，分支只依据 `error.code` 与状态码。

---

## 4. 请求合同规范（A-Contract）

### 4.1 合同原则（服务端已强制）

1. **`extra="forbid"`**：未知字段一律 422。新增客户端字段前先确认合同版本，禁止"先传了再说"。
2. **无本地路径概念**：CLI 的 `--payload <file>`、`--query-file`、`--result-file`、`--output`、`skills_dir` 等落盘/本地路径参数**不进** REST 合同；文件内容以 JSON 请求体直传，结果以全量 JSON 响应返回。
3. **结构化优先**：CLI 为绕开 Shell 转义设计的字符串简写（如 `where_json` 内联 JSON、`"field,2026-03-01,2026-03-22"` 对比串）在 REST 侧为原生结构（`where: list[dict]`、`data_comparison` 对象）；`/query/build` 例外沿用 `having: list[str]`（`expr|operator|value_json`）与 dimensions/metrics 标识串（`field_name|global_alias|verbose_name[:alias][:aggregation]`）。
4. **显式上限**（超限 422）：

| 参数 | 上限 | 说明 |
| ---- | ---- | ---- |
| `timeout` | 300 秒 | 查询执行占用服务端连接的上限，不允许无限拉长 |
| `limit` | 500000 | 取数引擎硬上限 |
| 字符串长度 | 各合同不一（如 `request` ≤4000） | 见 `/openapi.json` |
| 列表长度 | 一般 ≤100（order_by ≤50） | 见 `/openapi.json` |

### 4.2 分页与大结果集

- 结果集可能远大于单次返回（服务端单页不足 `totalCount` 时自动补齐一次，最多 5000 行），响应中包含 `row_count_returned` / `total_count` / `truncated` 披露字段。
- **P-1**：调用方必须读取 `truncated` / `total_count` 判断是否完整；需要全量时用 `offset`/`limit`（或 `query/run` payload 内的等价字段）循环翻页，`offset` 步长等于已取行数。
- **P-2**：禁止以"反复全量拉取 + 本地过滤"替代服务端 where 条件。

### 4.3 幂等与额度（keepa）

- `POST /api/v1/keepa/run` 受与 MCP 相同的日额度治理（quota_wrap）：额度占用失败会退回；响应附带 `quota` 字段。
- `job_id` 由调用方提供时承担幂等语义：同一 `job_id` 重复提交不会重复扣额度/重复执行。长任务用 `wait=false` 提交 + 轮询模式（参考 MCP `keepa job-status`）。
- `GET /api/v1/keepa/scenarios` 是公开端点（无需业务账号），可用于探测场景清单。

---

## 5. 安全规范（A-Security）

1. **凭证保管**：REST Token、Session 与 Cookie 不得进入日志、业务请求体或前端打包产物；MCP API Key 继续按既有密钥规范保管。
2. **传输安全**：生产部署必须在 HTTPS 反向代理之后；浏览器 Cookie 应由 AppHub 域策略控制。
3. **Collector 网络隔离**：Collector 的 MCP 端口只能由通用 opscli MCP 访问，禁止浏览器、普通客户端或公网直连；网络策略是可信上游身份头的安全边界。
4. **CORS**：服务端仅放行本地原型来源；生产前端必须同域或经部署层代理，**不得**依赖放宽 CORS。
5. **身份来源**：viewer Header 只能由受信 AppHub 宿主或同等网关注入；对公网不得允许任意客户端自报 `X-User-*`。
6. **最小部署**：`--host 0.0.0.0` 仅应在容器/内网使用；公网必须经 AppHub/受信网关，并关闭 local fallback。

---

## 6. 服务端部署与扩展规范（A-Deploy）

### 6.1 启动

```bash
# REST 使用 AppHub；MCP 端点继续按原参数校验 API Key
opscli-mcp --transport both --host 0.0.0.0 --port 8765
```

`--auth-verify-url` 仅控制 `/mcp`、`/sse` 的 MCP Key 远程校验。SellerSprite REST 不需要额外 Gateway Key，但部署必须通过防火墙、安全组、容器网络或反向代理访问控制，确保 Collector 只接受通用 opscli MCP 的连接。

### 6.2 变更纪律

1. **合同变更必须走 schemas/**：新增端点先在 `opscli/api/schemas/` 定义 Pydantic 合同（`extra="forbid"`），路由只做 HTTP 转换；业务逻辑进 query 规划器或 Manager，**禁止**在路由层写业务。
2. **MCP 与 REST 同源业务、分离鉴权**：两端共享业务实现和治理包装；REST 统一依赖 `require_apphub_principal`，MCP 保留 `ApiKeyAuthMiddleware`，禁止互相复用凭证。
3. **错误映射**：新增业务异常需在 `errors.py` 补状态码映射（能靠改请求解决 → 4xx；上游失败 → 502），并保持 code 与 domain 异常一致。
4. **破坏性合同变更**需升版本前缀（`/api/v2`），不改语义只加字段可原地演进（extra="forbid" 意味着删字段/改类型都是破坏性变更）。
5. 改动 `api/` 后必须跑 `tests/api/`（含鉴权边界、合同转换、错误映射）并核对 `/openapi.json` 路径数。

---

## 7. 客户端合规自查清单

对接/联调前逐项自查：

- [ ] REST 已携带 AppHub Session，或可信的 `X-Ops-Token + X-User-*`
- [ ] 判断成败依据 `success` 字段而非 HTTP 状态码（尤其 `/query/simple`）
- [ ] 依据 `error.code` + 状态码做分支，不解析 message 文本
- [ ] `401` 不重试、`503` 按 `Retry-After` 退避、`502` 幂等重试、`422/400` 改请求
- [ ] 读取 `truncated` / `total_count` 处理翻页，未假定一次拿全
- [ ] 请求体不含 `session_id` / `jwt` / `userEmail` 等身份与构造层字段
- [ ] Token/Session/Cookie/内部 Key 未进业务参数、日志或前端产物
- [ ] `timeout` ≤ 300、`limit` ≤ 500000 等显式上限已在客户端约束

---

## 附：端点与鉴权要求速查

| 端点 | 方法 | 业务账号要求 |
| ---- | ---- | ------------ |
| `/health/live` | GET | 无（裸响应） |
| `/api/v1/query/plan` | POST | 需已授权 |
| `/api/v1/query/flow` | POST | 需已授权 |
| `/api/v1/query/preferences` | GET | 需已授权 |
| `/api/v1/query/metadata` | GET | 需已授权 |
| `/api/v1/query/catalog` | GET | 需已授权 |
| `/api/v1/query/intents/match` | POST | 需已授权 |
| `/api/v1/query/run` | POST | 需已授权 |
| `/api/v1/query/build` | POST | 需已授权 |
| `/api/v1/query/simple` | POST | 需已授权 |
| `/api/v1/charts/{uuid}` | GET | 需已授权 |
| `/api/v1/charts/{uuid}/run` | POST | 需已授权 |
| `/api/v1/charts/{uuid}/doc` | GET | 需已授权 |
| `/api/v1/keepa/scenarios` | GET | 无 |
| `/api/v1/keepa/run` | POST | 需已授权 |

> `/api/v1/keepa/scenarios` 与健康检查公开；其余 REST 端点要求 AppHub 身份。`/mcp`、`/sse` 继续要求 MCP API Key。
