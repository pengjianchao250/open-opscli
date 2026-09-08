# API 调用规范

> 版本：v1.0（2026-09-01）
> 适用范围：所有通过 HTTP 调用 opscli 服务端 REST API（`/api/v1/*`）的网站前端、业务系统与脚本；以及部署、扩展该服务的开发者。
> 配套文档：[API使用文档](OPSCLI_API使用文档.md)（端点逐个参考与示例）、[SDK调用规范](OPSCLI_SDK调用规范.md)（进程内 SDK 调用约束）。

---

## 1. 总则

opscli 服务端以 `opscli-mcp` 为唯一对外 HTTP 入口：**REST API 与 MCP 工具共用同一业务内核、同一套鉴权与治理**（QueryManager、quota/telemetry 中间件同源）。因此对 REST API 的约束与 MCP 工具一致，本规范将其细化为 HTTP 语义。

### 1.1 基本事实

| 项目 | 值 |
| ---- | -- |
| 协议 | HTTP/1.1（uvicorn ASGI），JSON 编码 |
| REST 前缀 | `/api/v1`（health 除外：`/health/live`） |
| MCP 端点 | `/mcp`（Streamable HTTP）、`/sse`（SSE），与 REST 同进程同端口 |
| 端点总数 | 15 个：query 12 + keepa 2 + health 1 |
| 鉴权 | API Key（传输层），见 §2 |
| OpenAPI | `/docs`（Swagger UI）、`/openapi.json` |
| CORS | 仅允许 `http://127.0.0.1:4173` / `http://localhost:4173`，方法 GET/POST/OPTIONS |

### 1.2 服务形态边界

- `opscli-mcp --transport http|sse|both`：REST + MCP 组合服务（唯一推荐形态）。
- `opscli-mcp` 不带 `--transport`（或值非法）：stdio MCP 模式，**无 REST API**。
- `opscli-collector-mcp` / `opscli-collector-monitor`：纯 MCP 服务，**不带 REST 路由**。
- 编程方式 `create_api_app()` 生成的是**无鉴权中间件**的裸 FastAPI 应用，只应用于内网自定义组装；对外服务必须外挂 `ApiKeyAuthMiddleware`（`wrap_mcp_app` 组合链已含）。

---

## 2. 鉴权规范（A-Auth）

### 2.1 API Key 显式传递

每个请求必须携带 API Key，按以下优先级提取（取到即停）：

1. Query Param：`?api_key=<key>`
2. `Authorization: Bearer <key>`
3. `X-MCP-Proxy-Auth: Bearer <key>`（MCP Inspector 代理场景）

规范要求：**浏览器/服务端调用一律使用 `Authorization` Header**；`?api_key=` 仅留给不支持自定义 Header 的客户端，且因其会进入访问日志，生产环境应避免。

### 2.2 两种鉴权模式

| 模式 | 启用方式 | 身份来源 | 适用 |
| ---- | -------- | -------- | ---- |
| 固定 Key（单用户） | 默认。Key 存于 `~/.config/opscli/mcp_api_key`，启动 banner 打印 | 该 Key 隔离凭证目录中已登录的账号（须先经 MCP auth 工具完成登录） | 个人部署、内网单团队 |
| 远程校验（多用户） | `--auth-verify-url <ops>/v1/mcp/verify-key` | OPS 后端校验返回的 `user_id` / `email` / `allowed_tools` | 产品化、多租户 |

**A-1 身份不接受自报**：调用方身份只来自传输层（远程校验模式的 transport 邮箱 / 固定 Key 模式的隔离凭证缓存），请求体里出现 `session_id`、`jwt`、`userEmail` 等身份字段会被 `extra="forbid"` 合同直接拒绝（422）。这是"授权显式调用"在 API 形态的表达：**凭证只进传输层一次，不随业务请求散播**。

**A-2 隔离**：每个 API Key（联合 MCP 客户端名）拥有独立凭证目录 `~/.config/opscli/credentials_by_key/<hash>/`，业务请求以该隔离目录内的登录态向后端取数。不同 Key 之间数据与登录态互不可见。

### 2.3 鉴权失败语义

| 场景 | 响应 |
| ---- | ---- |
| Key 缺失/无效 | `401`，body：`{"error":"Unauthorized","message":"Invalid or missing API Key","reason":"invalid_api_key"}`（注意：这是中间件层响应，**不是**统一信封） |
| 远程校验服务临时不可用（超时/5xx 且无可用缓存） | `503` + `Retry-After: 5`，应重试而非当作 Key 无效 |
| 通过传输层鉴权但该 Key 从未登录过业务账号 | 业务端点返回 `401` 统一信封 `authentication_required`，提示完成 opscli 账号授权 |

**A-3 重试纪律**：`401` 永不重试（先修 Key / 先登录）；`503`（含 `Retry-After`）按指示退避重试；`502` 代表上游取数后端失败，可带幂等语义重试；`422/400` 修改请求后才重试。

服务端对远程校验内置缓存：新鲜期 60 秒内不回源；临时故障时 300 秒宽限期内降级放行；后端明确判定无效（`valid=false`/401/403）立即生效不宽限。调用方不应假设校验即时吊销。

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
| 401 | 未认证（信封）/ API Key 无效（中间件裸响应） | `authentication_required` / `Unauthorized` |
| 404 | 目标资源不存在 | `DATASET_NOT_FOUND` |
| 422 | 请求体不符合合同（字段类型/长度/多余字段） | `VALIDATION_ERROR` |
| 502 | 上游（取数/Keepa 后端）执行失败 | `REMOTE_HTTP_ERROR` 等业务 code |
| 503 | 元数据未就绪 / 鉴权服务不可用 | `QUERY_METADATA_NOT_READY` / `auth_service_unavailable` |

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

1. **Key 保管**：`opscli mcp user add` / `rotate` 生成的 Key **只显示一次**，服务端仅存哈希。调用方须立即入密钥管理设施；禁止写进代码库、前端打包产物、日志。
2. **传输安全**：生产部署必须在 HTTPS 反向代理之后；`?api_key=` 形态会进代理访问日志，优先 Header。
3. **日志脱敏**：调用方上报问题时报文必须抹除 `api_key`；服务端日志不打印 Key 明文。
4. **CORS**：服务端仅放行本地原型来源；生产前端必须同域或经部署层代理，**不得**依赖放宽 CORS。
5. **权限白名单**：远程校验模式下后端可下发 `allowed_tools` / `permission_enabled` 做工具级管控；REST 端点与对应 MCP 工具受同一白名单约束，Key 被收缩权限后调用会失败，属预期行为。
6. **最小部署**：`--host 0.0.0.0` 仅应在容器/内网使用；对公网必须经网关并启用远程校验模式。

---

## 6. 服务端部署与扩展规范（A-Deploy）

### 6.1 启动

```bash
# 多用户（产品化，推荐）
opscli-mcp --transport both --host 0.0.0.0 --port 8765 \
  --auth-verify-url https://<ops-host>/v1/mcp/verify-key

# 单用户（内网）
opscli-mcp --transport http --port 8765   # 启动 banner 打印固定 API Key
```

`--auth-verify-url` 缺省时自动取 `config.ini` 的 `ops_url` 拼接 `/v1/mcp/verify-key`。

### 6.2 变更纪律

1. **合同变更必须走 schemas/**：新增端点先在 `opscli/api/schemas/` 定义 Pydantic 合同（`extra="forbid"`），路由只做 HTTP 转换；业务逻辑进 query 规划器或 Manager，**禁止**在路由层写业务。
2. **MCP 与 REST 同源**：为 MCP 工具新增的能力应同步暴露 REST 端点（或明确理由不暴露）；两端共享 `deps.py` 鉴权依赖与治理包装，禁止为 REST 另造一套鉴权。
3. **错误映射**：新增业务异常需在 `errors.py` 补状态码映射（能靠改请求解决 → 4xx；上游失败 → 502），并保持 code 与 domain 异常一致。
4. **破坏性合同变更**需升版本前缀（`/api/v2`），不改语义只加字段可原地演进（extra="forbid" 意味着删字段/改类型都是破坏性变更）。
5. 改动 `api/` 后必须跑 `tests/api/`（含鉴权边界、合同转换、错误映射）并核对 `/openapi.json` 路径数。

---

## 7. 客户端合规自查清单

对接/联调前逐项自查：

- [ ] 所有请求携带 API Key，且用 Header 方式（Query 形态仅限无 Header 能力的客户端）
- [ ] 判断成败依据 `success` 字段而非 HTTP 状态码（尤其 `/query/simple`）
- [ ] 依据 `error.code` + 状态码做分支，不解析 message 文本
- [ ] `401` 不重试、`503` 按 `Retry-After` 退避、`502` 幂等重试、`422/400` 改请求
- [ ] 读取 `truncated` / `total_count` 处理翻页，未假定一次拿全
- [ ] 请求体不含 `session_id` / `jwt` / `userEmail` 等身份与构造层字段
- [ ] Key 存于密钥设施，未进代码、日志、前端产物
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

> 全部端点（含公开端点）都要求有效的 API Key；"无需业务账号"仅指不要求该 Key 下已完成 opscli 登录。
