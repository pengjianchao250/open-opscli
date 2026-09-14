# 运行时数据源路由

开发期验证和线上运行是两条不同路径。开发期使用对应 Skill 获取少量真实样本和场景合同；线上站点统一通过 FastAPI 后端、标准 QueryGateway 或正式 opscli REST API 取数。

## 1. 总体数据流

```text
浏览器
→ 当前站点 FastAPI /api
→ route / service / client / repository
→ QueryGateway、正式 opscli REST 或 SQLite
```

浏览器不直连 OPS、opscli REST、Keepa 或 SellerSprite。跨来源组合和用户二次加工只在 FastAPI service 完成。

## 2. 身份与后端配置

- OPS 使用 AppHub 批准的当前 viewer 身份，通过 `Depends(get_query_gateway)` 注入。
- Keepa 和 SellerSprite 共用一个请求级 `ThirdPartyApiClient`，通过 `Depends(get_query_credentials)` 复用模板已校验的 `QueryCredentials`。
- Client 只根据 `QueryCredentials.mode` 重建下表允许的 Header，不自行解析第二套身份，不盲目透传浏览器 Header。

| 模式 | `QueryCredentials` 来源 | 向第三方数据服务发送的 Header |
| --- | --- | --- |
| `viewer` | `ops_token`、可信 `viewer_user` | `X-Ops-Token`、`X-User-Email`、`X-User-Id`、`X-User-Name` |
| `session` | `session_id`、可选 `jwt` | `X-Session-Id`、已有的可选 `Authorization: Bearer <ops-jwt>` |
| `local` | 显式开启的本机登录态 | 通过 `AuthClient.build_session_headers("ops")` 和 `AuthClient.build_request_auth("ops")` 提取 `X-Session-Id` 与可选 Bearer JWT |

- local 只存在于站点后端；远端不接收 local 标识、Cookie、`X-Opscli-Version` 或其他本机凭证。
- 身份字段缺失或不合法时快速失败，不允许在 `viewer > session > local` 之间回退，也不使用共享 Secret 兜底。
- 凭证不得进入 URL、请求体、前端、日志、SQLite、源码或异常文本。
- OPS Query 与第三方 Client 只读取 `OPSCLI_MCP_REST_API_BASE_URL`，不得读取共享 API Key、旧变量别名或第二套运行时配置。

部署环境显式注入：

| 环境 | `OPSCLI_MCP_REST_API_BASE_URL` |
| --- | --- |
| 生产 | `https://ops.mcp.xenkee.com` |
| 预发布 | `https://mcp.ops.aukeyit.com` |

`OPSCLI_MCP_REST_API_BASE_URL` 不得有代码默认值，也不得根据鉴权模式推断环境。该值必须是纯 origin，不得包含 `/api`、接口路径、查询参数或末尾 `/`。所有接口地址统一使用 `base_url.rstrip("/") + path` 拼接，不得分别定义 OPS、Keepa、SellerSprite Base URL，也不得进入 `VITE_*` 或其他前端构建变量。它只承载 `/api/v1/*` REST 调用，不用于 `/mcp`、`/sse`。

## 3. OPS

### 3.1 开发期验证

- 先读取 `references/ops-dataset-application-guide.md`，判定单次查询、引导查询、`viewer-live`、用户私有持久化、批准的系统同步或静态参考。
- 清晰需求使用 `$ops-dataset-query`。
- 缺参、模糊或有歧义的需求使用 `$ops-query-wizard`。
- 不凭记忆填写数据集、字段、聚合、公式或筛选枚举。
- 静态字段目录、历史授权目录和应用清单只形成 `candidate`；只有当前在线元数据和少量真实查询可以标记 `verified`。
- 样本只用于合同验证，不提交到源码。

### 3.2 运行期

OPS 使用标准模板的 `backend/core/auth.py` 和 `backend/clients/ops_query_client.py`。AppHub 线上由宿主注入 `X-Ops-Token`，默认模式为 `viewer-live`：

```text
浏览器请求
→ 站点 FastAPI
→ Depends(get_query_gateway)
→ ViewerQueryGateway
→ OPSCLI_MCP_REST_API_BASE_URL + /api/v1/query/simple
→ opscli-mcp 内部转发 OPS data-metrics
```

标准模板固定提供三种 Gateway：

| 模式 | 触发条件 | Gateway | 用途 |
| --- | --- | --- | --- |
| viewer | `X-Ops-Token` 和宿主用户头 | `ViewerQueryGateway` | AppHub 线上正式运行 |
| session | `X-Session-Id` 和可选 OPS JWT | `OpsQueryGateway` | 显式无状态开发或受控调用 |
| local | 无上述 Header 且显式开启本地回退 | `LocalQueryGateway` | 仅本地开发 |

业务 API 必须通过 `Depends(get_query_gateway)` 获取 `QueryGateway`，service 通过参数接收 Gateway。允许调用的模板合同为 `list_datasets`、`get_dataset_metadata`、`build_simple` 和 `build_simple_and_run`；不得绕过 Gateway 直接创建 `AuthClient`、`QueryManager` 或拼装 viewer 请求。

viewer Gateway 的远端合同固定为 `GET /api/v1/query/metadata` 与 `POST /api/v1/query/simple`。`build_simple` 使用 `run=false`，`build_simple_and_run` 使用 `run=true`；同时检查 HTTP 状态和 `{success,data,error}`，HTTP 200、`success=false` 仍按查询内层失败处理。禁止生成 `/v1/data-metrics/viewer/query-metadata` 或 `/v1/data-metrics/viewer/cli-query/simple`。

OPS 原始数据和基于 OPS 的加工结果如果持久化，必须写入带 `owner_user_id` 的用户私有表。列表、读取、更新、删除、索引和唯一约束都限定当前用户。测试使用 FakeGateway 和 FastAPI dependency override，不访问真实网络或本机凭证。

### 3.3 批准的系统同步

页面、API 或数据库需要统一固定同步时，必须先确认项目实际提供经过批准的 OPS 系统运行时适配器。标准模板的 `ViewerQueryGateway`、`OpsQueryGateway` 和 `LocalQueryGateway` 都不能被推断为无人值守共享同步身份。

允许实现前必须具备身份与授权证据、`app.yaml.opscli.datasets` 白名单、确定性分页、断点续传、批次状态、自然键、幂等写入、快照语义和失败恢复合同。缺少任一前置时在 data-spec 标记 `blocked`，不得保存或复用访问者 `X-Ops-Token`，不得自行创建系统账号、定时任务或不存在的 SDK Client。

## 4. Keepa

### 4.1 开发期验证

使用 `$ops-keepa` 验证正式场景、参数和少量返回样本。场景列表只用于合同验证或新增场景确认，不生成页面运行时动态场景发现逻辑。

### 4.2 运行期

站点后端只通过正式同步接口调用 Keepa：

```text
浏览器
→ 站点 /api
→ 后端 ThirdPartyApiClient
→ POST /api/v1/keepa/run
```

完整地址由当前环境的 `OPSCLI_MCP_REST_API_BASE_URL` 与固定路径 `/api/v1/keepa/run` 拼接，不在代码中硬编码环境域名。

Client 必须：

- 显式使用 JSON 业务结果。
- 同时检查 HTTP 状态和统一响应信封的 `success`、`data`、`error`。
- HTTP 200 且 `success=false` 仍按失败处理。
- 按 `error.code` 分支，不解析 message 文本。
- 为请求设置显式超时，只对幂等且允许重试的上游失败做有限重试。
- 以规范化后的 `scenario + site + params` 生成 `request_hash`；`job_id`、`wait`、`force`、`reserve_tokens`、凭证和用户身份不进入哈希。

Keepa 可以实时调用，也可以按新鲜度写入 `third_party_source_snapshot`。成功响应通过 `UNIQUE(owner_user_id, provider, request_hash)` 和 `UPSERT` 保存为当前用户私有快照。只有同一用户较新的 `source_fetched_at` 可以覆盖，失败不得清空该用户最后有效快照。

## 5. SellerSprite

### 5.1 开发期验证

使用 `$ops-seller-sprite` 验证正式场景、参数、返回结构和少量样本。新增场景先确认正式场景列表和参数手册，不凭 SDK、CLI、MCP 或旧项目实现猜测 REST 合同。

### 5.2 普通异步任务

正式普通任务流程：

```text
POST /api/v1/seller-sprite/jobs
→ 保存 job_id、state、stage
→ GET /api/v1/seller-sprite/jobs/{job_id}
  或 POST /api/v1/seller-sprite/jobs/status
→ queued/running：继续查询，不重新提交
→ succeeded：GET /api/v1/seller-sprite/jobs/{job_id}/result
→ JSON data.result 写入当前用户私有快照
→ failed/cancelled：停止轮询并返回稳定错误
```

普通任务提交地址由当前环境 Base URL 与 `/api/v1/seller-sprite/jobs` 拼接；状态与结果接口继续在同一 Base URL 下拼接对应固定路径。

任务提交成功的 HTTP 202 只表示已受理。站点 API 将 pending 映射为本站稳定的处理中响应，前端只轮询当前站点 `/api`。

普通任务的 `request_hash` 由 `scenario + site + period + page_size + params` 生成。`third_party_async_job` 使用 `UNIQUE(owner_user_id, provider, request_hash)` 保存当前用户当前或最近任务；存在 `queued/running` 任务时只复用该用户原 `job_id`。

### 5.3 Listing Analysis

Listing Analysis 使用独立三段式接口：

```text
POST /api/v1/seller-sprite/listing-analysis/jobs
GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}
GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result
```

Listing Analysis 提交地址由当前环境 Base URL 与 `/api/v1/seller-sprite/listing-analysis/jobs` 拼接。

不得把 `listing-analysis` 提交到普通 jobs。其 `request_hash` 由 `asin + station + site` 生成。任务未完成时保留原 `job_id`，不得因等待时间较长而重复提交。

### 5.4 JSON 与导出边界

- JSON 任务成功后读取 `data.result` 并写入当前用户私有快照。
- JSON 任务不得持久化冗余下载 URL。
- XLS/XLSX 任务通过正式 export 合同返回文件信息。
- XLS/XLSX、二进制内容和临时下载 URL 不写入 SQLite。
- 仅支持文件导出的场景应标记为导出型任务；页面要求 SQLite JSON 数据时标记阻塞或调整需求。

### 5.5 轮询与恢复

- `wait_seconds` 只控制单次状态查询等待，客户端超时必须更长。
- 同一轮轮询预算结束后仍为 pending 时持久化 `job_id`，由后续请求或已有合规后台任务续查。
- 多个 pending 任务需要集中续查时优先使用批量状态接口。
- 不自建分布式锁、租约或独立调度平台，只持久化正式任务状态。
- 不调用 quota 接口参与业务流程，不处理额度检查、扣减、归属或账号调度。

## 6. 第三方数据用户隔离

- `third_party_source_snapshot` 使用 `owner_user_id + provider + request_hash` 唯一，保存当前用户清理后的 JSON 原始业务数据。
- `third_party_async_job` 使用相同用户边界；提交、状态查询、结果读取和 pending `job_id` 复用都必须带当前 `owner_user_id`。
- 用户查询历史、输入参数、收藏、备注、筛选和个人配置写入带 `owner_user_id` 的用户私有表。
- 用户基于第三方数据生成的计算、打分、分析结果以及 OPS + 第三方组合结果按用户隔离。
- `request_hash` 只包含业务参数，不包含 `owner_user_id` 或任何凭证；用户身份只进入数据库唯一键和归属查询。
- 网络调用发生在 SQLite 写事务外，成功解析后使用短事务写入。

## 7. 通用错误处理

调用方同时检查 HTTP 状态码、响应 `success` 和异步 `state`：

- HTTP 202：处理中，不代表完成。
- HTTP 401/403：当前请求身份无效、过期或无工具权限；不切换鉴权模式重试。
- HTTP 404：SellerSprite 任务不存在或当前用户不可见，不能继续假装 pending。
- HTTP 409：结果格式接口使用错误，改走正式 result/export 合同。
- HTTP 422：请求合同错误，不原样重试。
- HTTP 502：上游失败，只允许有限重试。
- HTTP 503：遵循 `Retry-After` 退避。

任何失败都不得清空当前用户最后有效快照。日志只记录时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count` 等必要元数据，不记录凭证、完整 Header 或敏感响应。

## 8. 混合来源

OPS + 第三方的默认组合模式为 `hybrid`：

- OPS 按当前 viewer 查询，持久化时按 `owner_user_id` 隔离。
- Keepa 或 SellerSprite 只读取当前用户的 JSON 快照，失效时按各自同步或异步流程刷新。
- service 按已验证的站点、ASIN、时间和币种规则组合。
- 最终加工结果按当前用户隔离，repository 不接收未隔离的 OPS viewer 数据。

任一来源失败时，是否允许部分结果必须在 data-spec 和 API Schema 中明确，不能静默返回旧数据或伪装完整结果。
