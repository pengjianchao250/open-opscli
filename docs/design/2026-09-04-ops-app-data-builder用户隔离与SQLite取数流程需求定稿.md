# ops-app-data-builder 用户隔离与 SQLite 取数流程需求定稿

> 日期：2026-09-04  
> 状态：需求已确认并落地，专项验证通过  
> 范围：收敛 `ops-app-data-builder` 生成站点数据层时的用户取数、二次加工、SQLite 持久化和用户隔离规则；本阶段已同步 Skill、关联发布检查、测试和文档，不修改 `opscli app`、标准模板仓库或正式数据服务。

## 1. 背景

通过以下三个工具搭建和发布的站点：

- `opscli app`：负责应用创建、模板初始化、代码推送和 AppHub 发布；
- `ops-app-build-spec`：负责项目盘点、页面开发规范、数据需求路由和发布检查；
- `ops-app-data-builder`：负责真实数据合同验证、FastAPI 数据层、二次加工、SQLite 模型、前端 API、迁移和测试生成。

线上站点既需要从 OPS、Keepa、SellerSprite 等原始数据源获取数据，也需要使用 SQLite 保存站点业务数据和加工结果。根据《Keepa 与卖家精灵线上 API 使用指南》，Keepa 为同步 REST 查询，SellerSprite 为需要保存 `job_id`、轮询状态并读取结果的异步 REST 任务。现有规则只明确了 OPS Viewer 数据不得未隔离地写入共享 SQLite，但没有清楚区分“第三方原始业务数据”“异步任务状态”和“用户二次加工结果”，容易产生以下歧义：

1. 用户录入、收藏、备注和个人配置是否需要隔离；
2. 用户触发的 Keepa 查询结果是否可以被其他用户直接复用；
3. 二次加工结果写入 SQLite 后，其他用户是否会读到；
4. A、B 用户同时访问且 OPS 权限不同时，最终页面数据应根据谁的权限生成；
5. SellerSprite 任务处于 `queued` 或 `running` 时是否会被重复提交；
6. “不写共享 SQLite”是否被误解为“不能使用 SQLite”。

## 2. 最终原则

### 2.1 SQLite 仍是站点正式存储

本次调整不取消 SQLite，也不要求每个用户创建独立数据库文件。线上站点仍使用平台持久化卷中的单个数据库文件：

```text
/data/app.db
```

所有用户物理上共用一个 SQLite 文件。用户私有数据通过用户归属字段实现逻辑隔离；第三方原始业务数据按站点共享快照存储。

### 2.2 OPS 数据按用户隔离

OPS 原始数据受当前访问用户权限影响，OPS 原始数据和基于 OPS 数据生成的二次加工结果如果持久化，均使用：

```text
storage_scope = user-private
owner_user_id = current_user.user_id
```

所有创建、读取、更新和删除操作都必须限定当前用户。

### 2.3 第三方原始业务数据站点共享

Keepa、SellerSprite 等第三方查询返回的原始业务数据使用：

```text
storage_scope = site-shared
```

相同第三方查询条件只在 SQLite 中保留一份共享快照，所有站点用户均通过 FastAPI 业务 API 使用该快照。该规则的当前前提是站点后端使用同一组 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL` 和 `OPSCLI_THIRD_PARTY_DATA_API_KEY` 调用第三方服务；站点访问用户身份与上游 API Key 身份是两个不同概念。

共享的是清理后的 JSON 业务 payload，不包含用户身份、API Key、完整鉴权头、Session、JWT、Cookie、本地路径或其他非业务调用上下文。XLS/XLSX 文件、二进制内容和临时下载 URL 不作为共享业务快照写入 SQLite。

### 2.4 用户行为和二次加工结果按用户隔离

以下数据默认使用 `user-private`：

- 用户查询历史和查询参数；
- 用户收藏、备注、筛选和个人配置；
- 用户对第三方原始数据进行筛选、计算、打分后产生的结果；
- OPS 与第三方数据组合形成的结果；
- 其他包含用户输入、用户 OPS 权限数据或个人业务规则的数据。

第三方原始业务数据是否共享，不改变用户二次加工结果必须通过 `owner_user_id` 隔离的规则。

## 3. “共享 SQLite”的准确含义

需要区分两个概念：

1. **共享数据库文件**：A、B 用户访问同一个站点时，后端使用同一个 `/data/app.db`。
2. **共享业务记录**：表中没有用户归属条件，A 写入后 B 也可以读取。

未隔离表：

```text
processed_result
- id
- result_json
- updated_at
```

用户隔离表：

```text
processed_result
- id
- owner_user_id
- owner_user_email
- result_json
- source_fetched_at
- calculated_at
- expires_at
```

其中 `owner_user_id` 是权限归属主键，`owner_user_email` 仅作为可选审计和展示字段。

> 用户数据可以写入 SQLite，但不能以所有用户共享的方式存储和读取。

## 4. 两个取数阶段

站点可能包含两个数据访问阶段，但不代表每次页面访问都会重复执行两次远端取数。

### 4.1 原始数据源取数

站点 FastAPI 后端从正式运行时入口获取原始数据：

```text
OPS：当前用户 Viewer 身份 → QueryGateway → OPS
Keepa：站点后端 Secret → /api/v1/keepa/run
SellerSprite：站点后端 Secret → 提交异步任务 → 保存 job_id → 查询状态 → 读取结果
```

Keepa 和 SellerSprite 共用后端 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`、`OPSCLI_THIRD_PARTY_DATA_API_KEY`，通过 `Authorization: Bearer <API_KEY>` 调用。站点访问用户身份只用于本地用户数据归属，不传给第三方 API 作为调用凭证。

### 4.2 应用数据读取

前端不能直接访问 SQLite。前端只请求当前站点 `/api`，由 FastAPI 查询 SQLite：

```text
前端
→ 当前站点 FastAPI /api
→ FastAPI repository / db
→ SQLite
→ FastAPI 返回前端
```

准确流程是：FastAPI 从原始数据源取数；Keepa 同步返回成功数据后写入共享快照，SellerSprite 先持久化异步 `job_id` 和上游任务状态，任务成功并读取 JSON 结果后再写入共享快照；用户二次加工结果按需写入用户私有表。前端后续统一通过 FastAPI 读取相应数据。

## 5. 推荐运行流程

### 5.1 第三方共享快照存在且未过期

```text
用户请求第三方数据
→ FastAPI 根据规范化后的第三方业务查询参数生成 request_hash
→ 按 provider + request_hash 查询共享 SQLite
→ 快照存在且未过期
→ 直接返回共享 JSON 原始业务数据，或继续生成当前用户的加工结果
```

### 5.2 Keepa 同步查询

```text
Keepa 共享快照不存在或已过期
→ POST /api/v1/keepa/run
→ 同时检查 HTTP 状态码和响应 success
→ 成功时读取 data.data
→ 清理凭证和非业务调用上下文
→ 使用 provider + request_hash UPSERT 共享快照
→ 返回原始数据，或继续生成当前用户的加工结果
```

Keepa 网络请求必须在 SQLite 写事务外完成。业务失败即使返回 HTTP 200，也不能写入共享快照；失败不得清空最后一份有效快照。

### 5.3 SellerSprite 异步任务

```text
SellerSprite 共享快照不存在或已过期
→ 按 provider + request_hash 查询 third_party_async_job
→ 已有 queued/running 任务：复用现有 job_id，不重复提交
→ 没有活动任务：提交正式 SellerSprite jobs 接口
→ 保存 job_id、state、stage 和提交时间
→ 查询任务状态
→ succeeded：读取 JSON result 并 UPSERT 共享快照
→ failed/cancelled：记录稳定错误，不覆盖有效快照
```

普通任务使用 `/api/v1/seller-sprite/jobs`，Listing Analysis 使用独立的 `/api/v1/seller-sprite/listing-analysis/jobs`。任务状态为 `queued` 或 `running` 时只允许继续查询状态或结果，不得重新提交相同请求。

### 5.4 SellerSprite 轮询与恢复

- 站点后端保存每次提交返回的 `job_id`。
- 站点 API 可以将上游 HTTP 202 映射为本站稳定的“处理中”响应，由前端轮询当前站点 `/api`，前端不直连 SellerSprite。
- 单次状态查询可以使用 `wait_seconds=0-30`，客户端超时必须大于 `wait_seconds`。
- 同一轮轮询预算结束后仍为 pending 时保留 `job_id`，后续请求或已有合规后台任务继续查询，不重新提交。
- 多个 pending 任务需要集中续查时优先使用批量状态接口，不逐个高频轮询。

### 5.5 多用户并发原则

Keepa 是同步查询。A、B、C 同时首次查询相同数据时可以分别获得响应，并使用相同的 `provider + request_hash` 写入共享快照；SQLite 最终只保留一条记录，且只有 `source_fetched_at` 不早于现有记录的结果才允许覆盖。

SellerSprite 是异步任务。同一查询存在 `queued` 或 `running` 任务时，后续用户复用现有 `job_id`，不能按 Keepa 的方式再次提交。这里只持久化并遵循上游正式任务状态，不建设独立分布式任务平台。

### 5.6 用户二次加工

```text
读取共享第三方原始快照
→ 结合当前用户输入、筛选、业务规则或 OPS 权限数据
→ FastAPI service 完成二次加工
→ 按 owner_user_id 写入用户私有表
→ 返回当前用户结果
```

不需要持久化的实时加工仍可在请求内直接完成并返回。

## 6. 原始数据、异步任务与加工结果存储

第三方原始业务数据、SellerSprite 异步任务和用户加工结果分开存储：

```text
third_party_source_snapshot
- provider
- scenario
- marketplace
- request_hash
- normalized_request_json
- payload_json
- source_job_id
- result_format
- source_fetched_at
- expires_at
- last_fetched_by_user_id
- schema_version

third_party_async_job
- provider
- request_hash
- job_id
- job_type
- state
- stage
- result_format
- submitted_by_user_id
- submitted_at
- checked_at
- completed_at
- error_code

user_processed_result
- owner_user_id
- source_snapshot_id
- product_key
- processing_params_json
- result_json
- calculation_version
- calculated_at
- expires_at
```

`normalized_request_json` 只保存用于标识第三方原始数据的规范化业务查询字段，不保存用户身份、用户侧查询历史或非业务调用上下文。`source_job_id` 用于追踪产生当前快照的 Keepa 或 SellerSprite 任务编号。

`third_party_async_job` 只保存 SellerSprite 正式异步任务合同和必要状态。`submitted_by_user_id` 以及共享快照中的 `last_fetched_by_user_id` 均仅用于内部审计，不作为共享结果读取权限条件。如果业务需要保存 A、B、C 各自的查询历史和原始输入参数，应单独创建按 `owner_user_id` 隔离的查询记录表，不在共享快照或异步任务表中保存用户列表。

`third_party_async_job` 使用 `UNIQUE(provider, request_hash)` 保存当前或最近一次任务。存在 `queued/running` 任务时复用原 `job_id`；终态任务需要重新刷新时更新同一记录为新的 `job_id`，不把用户查询历史混入共享任务表。

只有成功完成的 JSON 业务结果可以写入 `payload_json`。XLS/XLSX 文件、二进制内容和临时下载 URL 不得写入 SQLite；仅支持文件导出的 SellerSprite 场景应作为导出型任务处理，不能伪装成 SQLite JSON 数据产品。

OPS 原始数据和 OPS 加工结果仍按用户隔离。第三方原始快照可以被多个用户复用，但任何包含用户输入、筛选条件、个人规则或 OPS 权限数据的加工结果都必须按用户隔离。

## 7. 数据源运行规则

### 7.1 OPS

OPS 原始数据按当前访问用户权限获取：

```text
AppHub 注入当前用户 X-Ops-Token 和 X-User-* Header
→ FastAPI Depends(get_query_gateway)
→ ViewerQueryGateway
→ OPS
```

持久化时：

```text
OPS 原始或加工结果
→ owner_user_id = current_user.user_id
→ 写入当前用户记录
```

建议同时记录 `dataset_alias`、`query_hash`、`calculation_version`、`source_fetched_at` 和 `expires_at`。无法可靠判断旧权限缓存是否仍有效时，应保持实时查询或使用较短有效期，不得假设权限长期不变。

### 7.2 Keepa

Keepa 原始取数使用站点后端 Secret，不使用用户 OPS 权限：

```text
FastAPI
→ OPSCLI_THIRD_PARTY_DATA_API_BASE_URL + OPSCLI_THIRD_PARTY_DATA_API_KEY
→ /api/v1/keepa/run
```

后端使用 Bearer Header，不能把 API Key 放入 URL、请求体、日志或 SQLite。运行时业务查询只调用 `POST /api/v1/keepa/run`；`GET /api/v1/keepa/scenarios` 仅用于开发期合同验证或新增场景确认，不生成页面运行时场景发现逻辑。

站点调用时显式使用 JSON 结果并按需求决定 `wait`、`force` 和超时。`request_hash` 由规范化后的 `scenario + site + params` 生成，不包含 `job_id`、`wait`、`force`、`reserve_tokens`、API Key 或当前站点用户身份。

调用方必须同时检查 HTTP 状态码和响应信封 `success`。只有成功响应中的 `data.data` 可以写入 `third_party_source_snapshot`；业务失败即使返回 HTTP 200，也不得覆盖或清空最后一份有效快照。用户基于 Keepa 数据生成的筛选、计算、打分和分析结果写入带 `owner_user_id` 的用户私有表。

### 7.3 SellerSprite

SellerSprite 已提供正式异步 REST API，站点后端与 Keepa 共用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL` 和 `OPSCLI_THIRD_PARTY_DATA_API_KEY`：

```text
场景确认：GET /api/v1/seller-sprite/scenarios
普通任务提交：POST /api/v1/seller-sprite/jobs
单任务状态：GET /api/v1/seller-sprite/jobs/{job_id}
批量任务状态：POST /api/v1/seller-sprite/jobs/status
JSON 结果：GET /api/v1/seller-sprite/jobs/{job_id}/result
导出信息：GET /api/v1/seller-sprite/jobs/{job_id}/export
Listing Analysis：独立 listing-analysis/jobs 三段式接口
```

`GET /api/v1/seller-sprite/scenarios` 用于开发期验证正式场景和参数。运行时只调用 data-spec 已验证并声明的场景，不凭记忆生成场景名称、参数、枚举或接口路径。

普通任务的 `request_hash` 由规范化后的 `scenario + site + period + page_size + params` 生成；Listing Analysis 由 `asin + station + site` 生成。`job_id`、API Key、轮询次数、`wait_seconds` 和当前站点用户身份不进入 `request_hash`。

提交成功返回 HTTP 202 和 `job_id`。站点必须保存 `job_id` 并遵循 `queued/running/succeeded/failed/cancelled` 状态；pending 任务不得重新提交。JSON 任务成功后读取 `data.result` 并写入共享快照，XLS/XLSX 任务只按导出合同处理，不把文件或临时下载 URL 写入 SQLite。

本需求不调用 `/api/v1/seller-sprite/quota` 参与站点业务流程，也不处理额度检查、扣减、归属或账号调度。

### 7.4 通用响应与错误处理

调用方必须同时检查 HTTP 状态码、响应信封 `success` 和异步任务 `data.state`：

- HTTP 200 不代表业务一定成功，Keepa 仍需检查 `success=false`；
- HTTP 202 表示 SellerSprite 任务已受理或仍在执行，不表示结果已完成；
- HTTP 401/403 视为后端 Secret、上游身份或工具权限问题，不映射为空数据；
- HTTP 404 的 SellerSprite `job_id` 可能不存在或不属于当前 API Key，不能继续假装任务 pending；
- HTTP 409 表示结果格式接口使用错误，应改走正式 export 合同；
- HTTP 422 为请求合同错误，不原样重试；
- HTTP 502 只允许有限重试，HTTP 503 遵循 `Retry-After` 退避；
- SellerSprite `failed` 或 `cancelled` 为终态，停止轮询并保留稳定错误码；
- 任何失败都不得清空或覆盖最后一份有效共享快照。

日志只记录请求时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count` 等必要元数据，不记录 API Key、Authorization、Session、JWT、Cookie、账号密码或完整敏感业务响应。

## 8. 身份来源与 CRUD 约束

标准模板已经提供：

```python
CurrentUser
get_current_user
```

用户身份必须由 FastAPI 依赖从 AppHub 批准的请求通道中获取。业务接口不得从请求体、query 参数或前端状态接受用户自报身份。以下 CRUD 约束适用于用户查询历史、用户配置、OPS 持久化结果和用户二次加工结果，不适用于第三方共享原始快照。

### 8.1 创建

```text
owner_user_id = current_user.user_id
```

前端不得指定或覆盖 `owner_user_id`。

### 8.2 列表

```sql
WHERE owner_user_id = :current_user_id
```

### 8.3 单条读取

```sql
WHERE public_id = :public_id
  AND owner_user_id = :current_user_id
```

### 8.4 更新和删除

更新和删除必须同时限定记录 ID 和当前用户 ID。其他用户的记录对当前用户表现为不存在，避免泄露记录存在性。

### 8.5 索引和唯一约束

用户业务表的索引、唯一约束和幂等键必须包含用户归属，例如：

```text
UNIQUE(owner_user_id, filter_name)
INDEX(owner_user_id, created_at)
```

防止 A、B 用户使用相同业务名称或相同查询参数时互相冲突。

## 9. 多用户场景

### 9.1 A、B 的 OPS 权限不同

```text
A 请求
→ 使用 A 的 Viewer 身份查询 OPS
→ 加工 A 的结果
→ 写入 owner_user_id=A
→ 只返回给 A

B 请求
→ 使用 B 的 Viewer 身份查询 OPS
→ 加工 B 的结果
→ 写入 owner_user_id=B
→ 只返回给 B
```

A、B 同时访问时，每个 OPS 请求独立使用各自身份。A 的刷新只能更新 `owner_user_id=A` 的私有结果，B 不能读取或覆盖 A 的记录。

### 9.2 A、B、C 同时首次查询相同 Keepa 数据

```text
A 查询同一 ASIN → 同步获取原始数据 → UPSERT
B 查询同一 ASIN → 同步获取原始数据 → UPSERT
C 查询同一 ASIN → 同步获取原始数据 → UPSERT
```

Keepa 为同步查询，本次允许三位用户分别执行请求。三份成功响应使用相同的 `provider + request_hash` 写入共享表，SQLite 最终只保留一条共享原始快照。`last_fetched_by_user_id` 保存最后一次成功写入者，仅供内部审计。

### 9.3 A、B、C 查询相同 SellerSprite 数据

```text
A 首次查询 → 提交异步任务 → 保存 job_id 和 queued/running 状态
B 查询相同 request_hash → 复用现有 job_id → 查询状态
C 查询相同 request_hash → 复用现有 job_id → 查询状态
任务 succeeded → 读取 JSON result → UPSERT 一条共享快照
```

SellerSprite pending 任务不得重复提交。A、B、C 可以分别保存自己的用户查询历史，但共享异步任务和成功后的原始业务快照。任务提交者不拥有共享结果的排他读取权限。

### 9.4 用户加工相同第三方快照

A、B、C 可以引用同一条 `third_party_source_snapshot`，但分别生成：

```text
A 加工结果 → owner_user_id=A
B 加工结果 → owner_user_id=B
C 加工结果 → owner_user_id=C
```

第三方原始数据共享不意味着查询历史、输入参数和二次加工结果共享。

## 10. 数据产品合同调整

一个数据产品可能同时包含第三方执行方式、异步任务状态、共享原始数据和用户私有加工结果，因此合同必须分别记录来源执行、任务存储、来源存储和结果存储：

```json
{
  "product_key": "seller_sprite_competitor_analysis",
  "source": "seller_sprite",
  "execution_mode": "async-job",
  "source_execution": {
    "auth": "backend-bearer-secret",
    "submit_endpoint": "POST /api/v1/seller-sprite/jobs",
    "status_endpoint": "GET /api/v1/seller-sprite/jobs/{job_id}",
    "result_endpoint": "GET /api/v1/seller-sprite/jobs/{job_id}/result",
    "success_state": "succeeded",
    "result_format": "json"
  },
  "request_identity_fields": ["scenario", "site", "period", "page_size", "params"],
  "task_storage": {
    "storage_mode": "sqlite",
    "storage_scope": "site-shared",
    "table": "third_party_async_job",
    "unique_key": ["provider", "request_hash"],
    "active_states": ["queued", "running"]
  },
  "source_storage": {
    "storage_mode": "sqlite",
    "storage_scope": "site-shared",
    "table": "third_party_source_snapshot",
    "unique_key": ["provider", "request_hash"]
  },
  "result_storage": {
    "storage_mode": "sqlite",
    "storage_scope": "user-private",
    "owner_identity_source": "get_current_user",
    "owner_key": "owner_user_id",
    "table": "user_processed_result"
  },
  "freshness": "15m",
  "site_api": "GET /api/competitors"
}
```

| 字段 | 说明 |
| --- | --- |
| `execution_mode` | 原始数据如何获取，例如 `viewer-live`、`sync-request`、`async-job`、`hybrid` |
| `source_execution` | 上游鉴权、正式端点、同步/异步行为、成功条件和结果格式 |
| `request_identity_fields` | 参与规范化和生成 `request_hash` 的业务字段，不包含身份或执行控制字段 |
| `task_storage` | 异步任务的 `job_id`、状态和恢复合同；同步来源为 `null` |
| `source_storage` | 原始数据如何持久化；第三方原始业务数据使用共享快照 |
| `result_storage` | 二次加工结果如何持久化；用户结果使用 `user-private` |
| `unique_key` | 第三方共享快照唯一键，固定包含 `provider` 和 `request_hash` |
| `owner_identity_source` | 用户私有结果的可信身份来源，固定为 `get_current_user` |
| `owner_key` | 用户私有结果的归属字段，固定为 `owner_user_id` |

`task_storage`、`source_storage` 和 `result_storage` 不得合并为一个 `storage_scope`。SellerSprite 任务状态、第三方原始业务数据和用户二次加工结果具有不同职责；OPS 原始和加工数据仍按用户隔离。

Keepa 合同使用 `execution_mode=sync-request`、`task_storage=null`，并以 `scenario + site + params` 生成 `request_hash`。SellerSprite 普通任务使用 `execution_mode=async-job`，Listing Analysis 必须声明专用提交、状态和结果端点。仅支持 XLS/XLSX 的场景必须声明为导出型任务，不得声明为 SQLite JSON 快照。

## 11. ops-app-data-builder 修改方案

### 11.1 Skill 主流程

修改 `opscli/skills/templates/ops-app-data-builder/SKILL.md`：

1. 明确 OPS 原始和加工数据按用户隔离；
2. 明确 Keepa 使用同步 `/api/v1/keepa/run`，SellerSprite 使用正式异步 jobs 和 listing-analysis 接口；
3. 明确第三方成功 JSON 原始业务数据写入站点共享快照，XLS/XLSX 和临时下载 URL 不进入 SQLite；
4. 明确用户查询历史、输入参数和二次加工结果按用户隔离；
5. 第三方共享快照使用规范化业务参数生成 `request_hash`，通过唯一约束和 `UPSERT` 去重；
6. Keepa 并发成功响应允许写同一共享快照，SellerSprite pending 任务必须复用现有 `job_id`；
7. 增加 `third_party_async_job` 合同并持久化正式上游状态，不建设独立分布式任务平台；
8. 要求用户私有 API 使用 `Depends(get_current_user)`，身份不能由请求体或前端传入；
9. 增加统一响应信封、HTTP 202、任务终态、重试和最后有效快照保护规则；
10. 发布检查同时覆盖异步任务、第三方共享原始数据和用户私有加工结果。

### 11.2 数据合同 Reference

修改 `opscli/skills/templates/ops-app-data-builder/references/data-layer-contract.md`：

1. 将单一存储范围拆为 `task_storage`、`source_storage` 和 `result_storage`；
2. 增加 `source_execution`、`request_identity_fields`、同步/异步模式和正式端点合同；
3. 增加第三方共享快照的 `request_hash`、唯一约束、`UPSERT`、更新时间和过期清理合同；
4. 增加 SellerSprite `job_id`、状态、轮询、结果读取和 pending 恢复合同；
5. 增加 JSON 结果与 XLS/XLSX 导出型任务边界；
6. 增加用户加工结果的 `owner_user_id`、索引、唯一约束和 CRUD 合同；
7. 增加共享快照敏感字段清理和失败保留最后有效快照要求；
8. 增加 Keepa 并发写入、SellerSprite pending 复用和用户结果隔离测试合同。

### 11.3 运行时路由 Reference

修改 `opscli/skills/templates/ops-app-data-builder/references/runtime-source-routing.md`：

1. OPS 按当前用户权限取数，原始和加工结果持久化时按当前用户隔离；
2. Keepa 运行时只调用 `POST /api/v1/keepa/run`，场景接口仅用于开发期合同验证；
3. SellerSprite 接入正式异步 REST，区分普通 jobs 和 Listing Analysis 专用接口；
4. Keepa 和 SellerSprite 共用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`、`OPSCLI_THIRD_PARTY_DATA_API_KEY`，不兼容旧环境变量别名；
5. SellerSprite 保存并复用 pending `job_id`，成功 JSON 结果写共享快照；
6. OPS 与第三方混合来源的最终加工结果按当前用户隔离；
7. 补充统一错误映射、有限重试、日志脱敏和有效快照保护。

### 11.4 测试和版本

修改：

- `tests/skills/test_ops_app_data_builder_skill.py`；
- `opscli/skills/templates/ops-app-data-builder/data/VERSION.json`；
- `opscli/skills/templates/ops-app-data-builder/agents/openai.yaml`。

增加用户隔离、Keepa 同步调用、SellerSprite 异步任务、pending 复用、JSON/XLS 边界和错误映射合同断言，并将版本从 `v0.1.3` 升级为 `v0.1.4`。

## 12. 需要同步的关联规则

为避免 `ops-app-build-spec` 与 `ops-app-data-builder` 的发布检查发生漂移，本轮同步修改：

- `opscli/skills/templates/ops-app-build-spec/SKILL.md`；
- `opscli/skills/templates/ops-app-build-spec/references/data-access-standard.md`；
- `tests/skills/test_ops_app_build_spec_skill.py`。

同步内容只限用户隔离和 SQLite 发布检查，不修改建站入口、模板先行、AppHub、Git 或发布流程。

## 13. 文档同步范围

本轮同步更新：

- `docs/design/2026-09-02-ops-app-data-builder需求与设计.md`；
- `docs/plans/2026-09-02-ops-app-data-builder落地计划.md`；
- `docs/change-log-pending.md`。

本需求定稿文档保留为本轮规则的决策依据。

## 14. 不修改范围

本次不修改：

- `opscli/app` 命令和 AppHub API；
- 应用创建、模板拉取、Git push、release 和 SSE 流程；
- `OPSCLI_APPHUB_URL` 和模板仓库环境配置；
- `opscli/auth/config.py`；
- OPS、Keepa 和 SellerSprite 的正式服务端能力；
- Keepa、SellerSprite 等第三方服务的用户额度检查、额度扣减、额度归属或账号调度；
- 第三方查询的分布式锁、租约、独立调度平台或自建复杂状态机；SellerSprite 正式返回的任务状态和 `job_id` 持久化属于本需求范围；
- 每个用户一个独立 SQLite 文件；
- 多写实例、分布式数据库或平台级行权限系统。

## 15. 模板兼容性

当前标准模板已经提供 `CurrentUser`、`get_current_user`、`X-User-Id` 和 `X-User-Email`，可以支撑本次用户隔离规则，不需要修改 `opscli app`。

模板现有示例主要以规范化 `user_email` 作为归属条件，而本次新业务表建议统一使用：

```text
owner_user_id：权限归属主键
owner_user_email：可选审计字段
```

本轮只调整 `open-opscli` 中的 Skill 生成规范，不自动修改外部 `builder-site-template` 仓库。若后续要求模板示例与新生成规范完全一致，应作为模板仓库的独立变更处理。

## 16. 验收标准

本轮落地必须满足：

1. Skill 明确 SQLite 仍是正式存储，禁止表述为“用户数据不能写 SQLite”；
2. OPS 原始数据和基于 OPS 的加工结果持久化时按 `owner_user_id` 隔离；
3. Keepa 和 SellerSprite 共用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`、`OPSCLI_THIRD_PARTY_DATA_API_KEY`，不兼容旧环境变量别名；
4. Keepa 页面运行时只调用 `POST /api/v1/keepa/run`，并同时检查 HTTP 状态码和响应 `success`；
5. SellerSprite 使用正式异步 REST，普通任务和 Listing Analysis 使用各自正确的提交、状态和结果端点；
6. Keepa、SellerSprite 场景列表只用于开发期合同验证或新增场景确认，不生成页面运行时动态场景发现；
7. Keepa 和 SellerSprite 成功 JSON 原始业务数据使用 `site-shared` 共享快照；
8. XLS/XLSX 文件、二进制内容和临时下载 URL 不写入 SQLite；
9. 第三方用户查询历史、查询参数、收藏、备注和二次加工结果使用 `user-private`；
10. OPS 与第三方数据组合形成的结果使用 `user-private`；
11. 第三方共享快照使用 `provider + request_hash` 唯一约束和 `UPSERT` 去重；
12. Keepa 多用户同步并发查询允许分别执行，最终只保留一条共享快照；
13. SellerSprite 保存 `job_id` 和正式任务状态，同一 `request_hash` 存在 `queued/running` 任务时不得重复提交；
14. SellerSprite 只有 `succeeded` 的 JSON 结果可以写共享快照，`failed/cancelled` 必须停止轮询；
15. 只有 `source_fetched_at` 不早于现有记录的响应允许覆盖共享快照；
16. `last_fetched_by_user_id` 和 `submitted_by_user_id` 仅用于内部审计，不参与共享结果读取权限判断；
17. HTTP 202、401、403、404、409、422、502、503 和业务错误具有稳定映射，任何失败不得清空最后有效快照；
18. 共享快照、日志和源码不保存 API Key、Authorization、Session、JWT、Cookie、账号密码或完整敏感响应；
19. 用户私有 API 通过 `get_current_user` 获取可信身份，用户私有表的 CRUD、索引和唯一约束均限定当前用户；
20. 前端只调用当前站点 `/api`，网络取数发生在 SQLite 写事务外；
21. 不调用 SellerSprite quota 接口参与业务流程，不处理额度检查、扣减、归属或账号调度；
22. `ops-app-data-builder` 和 `ops-app-build-spec` 契约测试通过，且不影响 `opscli app create/init/push` 和其他 opscli 功能。

## 17. 当前落地状态

本轮已完成以下落地：

- `ops-app-data-builder` 已升级到 `v0.1.4`，补齐 OPS 用户隔离、Keepa 同步共享快照、SellerSprite 异步任务、用户加工结果和错误处理合同；
- `ops-app-build-spec` 已升级到 `v0.0.5`，同步用户隔离、第三方共享快照和发布检查规则；
- 已更新两个 Skill 的 Reference、发行清单、静态 eval 和契约测试；
- 已同步更新 2026-09-02 需求设计和落地计划；
- 未修改 `opscli app`、AppHub、标准模板仓库、正式数据服务和全局认证配置。

专项验证结果：

- `tests/skills/test_ops_app_data_builder_skill.py`：`10 passed`；
- `ops-app-build-spec` 元数据、真实数据路由和安装声明专项测试：`3 passed`；
- `ops-app-data-builder`、`ops-app-build-spec` 均通过 Skill Creator `quick_validate.py`；
- `scripts/check_skill_release_manifest.py` 校验通过。
