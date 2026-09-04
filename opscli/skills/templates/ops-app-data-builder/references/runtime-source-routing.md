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
- Keepa 和 SellerSprite 使用站点后端 Secret：`OPSCLI_API_BASE_URL`、`OPSCLI_API_KEY`。
- 第三方 Client 使用 Bearer Header，不把 Key 放进 URL、请求体、前端、日志或 SQLite。
- 不引入 `OPSCLI_SELLER_SPRITE_E2E_BASE_URL`、`OPSCLI_SELLER_SPRITE_E2E_API_KEY` 或第二套运行时配置。
- 站点访问用户身份只用于本地用户数据归属，不作为第三方 API 调用凭证。

## 3. OPS

### 3.1 开发期验证

- 清晰需求使用 `$ops-dataset-query`。
- 缺参、模糊或有歧义的需求使用 `$ops-query-wizard`。
- 不凭记忆填写数据集、字段、聚合、公式或筛选枚举。
- 样本只用于合同验证，不提交到源码。

### 3.2 运行期

OPS 使用标准模板的 `backend/core/auth.py` 和 `backend/clients/ops_query_client.py`。AppHub 线上由宿主注入 `X-Ops-Token`，默认模式为 `viewer-live`：

```text
浏览器请求
→ 站点 FastAPI
→ Depends(get_query_gateway)
→ ViewerQueryGateway
→ OPS data-metrics
```

标准模板固定提供三种 Gateway：

| 模式 | 触发条件 | Gateway | 用途 |
| --- | --- | --- | --- |
| viewer | `X-Ops-Token` 和宿主用户头 | `ViewerQueryGateway` | AppHub 线上正式运行 |
| session | `X-Session-Id` 和可选 OPS JWT | `OpsQueryGateway` | 显式无状态开发或受控调用 |
| local | 无上述 Header 且显式开启本地回退 | `LocalQueryGateway` | 仅本地开发 |

业务 API 必须通过 `Depends(get_query_gateway)` 获取 `QueryGateway`，service 通过参数接收 Gateway。允许调用的模板合同为 `list_datasets`、`get_dataset_metadata`、`build_simple` 和 `build_simple_and_run`；不得绕过 Gateway 直接创建 `AuthClient`、`QueryManager` 或拼装 viewer 请求。

OPS 原始数据和基于 OPS 的加工结果如果持久化，必须写入带 `owner_user_id` 的用户私有表。列表、读取、更新、删除、索引和唯一约束都限定当前用户。测试使用 FakeGateway 和 FastAPI dependency override，不访问真实网络或本机凭证。

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

Client 必须：

- 显式使用 JSON 业务结果。
- 同时检查 HTTP 状态和统一响应信封的 `success`、`data`、`error`。
- HTTP 200 且 `success=false` 仍按失败处理。
- 按 `error.code` 分支，不解析 message 文本。
- 为请求设置显式超时，只对幂等且允许重试的上游失败做有限重试。
- 以规范化后的 `scenario + site + params` 生成 `request_hash`；`job_id`、`wait`、`force`、`reserve_tokens` 和身份字段不进入哈希。

Keepa 可以实时调用，也可以按新鲜度写入 `third_party_source_snapshot`。多用户同时首次查询相同数据时允许分别执行；成功响应通过 `UNIQUE(provider, request_hash)` 和 `UPSERT` 最终保留一条共享快照。只有较新的 `source_fetched_at` 可以覆盖，失败不得清空最后有效快照。

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
→ JSON data.result 写入共享快照
→ failed/cancelled：停止轮询并返回稳定错误
```

任务提交成功的 HTTP 202 只表示已受理。站点 API 将 pending 映射为本站稳定的处理中响应，前端只轮询当前站点 `/api`。

普通任务的 `request_hash` 由 `scenario + site + period + page_size + params` 生成。`third_party_async_job` 使用 `UNIQUE(provider, request_hash)` 保存当前或最近任务；存在 `queued/running` 任务时复用原 `job_id`。

### 5.3 Listing Analysis

Listing Analysis 使用独立三段式接口：

```text
POST /api/v1/seller-sprite/listing-analysis/jobs
GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}
GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result
```

不得把 `listing-analysis` 提交到普通 jobs。其 `request_hash` 由 `asin + station + site` 生成。任务未完成时保留原 `job_id`，不得因等待时间较长而重复提交。

### 5.4 JSON 与导出边界

- JSON 任务成功后读取 `data.result` 并写入共享快照。
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

## 6. 共享快照与用户隔离

- `third_party_source_snapshot` 使用 `provider + request_hash` 唯一，保存清理后的 JSON 原始业务数据。
- `last_fetched_by_user_id`、`submitted_by_user_id` 只用于内部审计，不参与共享结果读取权限。
- 用户查询历史、输入参数、收藏、备注、筛选和个人配置写入带 `owner_user_id` 的用户私有表。
- 用户基于第三方数据生成的计算、打分、分析结果以及 OPS + 第三方组合结果按用户隔离。
- 网络调用发生在 SQLite 写事务外，成功解析后使用短事务写入。

## 7. 通用错误处理

调用方同时检查 HTTP 状态码、响应 `success` 和异步 `state`：

- HTTP 202：处理中，不代表完成。
- HTTP 401/403：后端 Secret、上游身份或工具权限错误。
- HTTP 404：SellerSprite 任务不存在或当前 API Key 不可见，不能继续假装 pending。
- HTTP 409：结果格式接口使用错误，改走正式 result/export 合同。
- HTTP 422：请求合同错误，不原样重试。
- HTTP 502：上游失败，只允许有限重试。
- HTTP 503：遵循 `Retry-After` 退避。

任何失败都不得清空最后有效共享快照。日志只记录时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count` 等必要元数据，不记录凭证或完整敏感响应。

## 8. 混合来源

OPS + 第三方的默认组合模式为 `hybrid`：

- OPS 按当前 viewer 查询，持久化时按 `owner_user_id` 隔离。
- Keepa 或 SellerSprite 读取允许共享的 JSON 快照，失效时按各自同步或异步流程刷新。
- service 按已验证的站点、ASIN、时间和币种规则组合。
- 最终加工结果按当前用户隔离，repository 不接收未隔离的 OPS viewer 数据。

任一来源失败时，是否允许部分结果必须在 data-spec 和 API Schema 中明确，不能静默返回旧数据或伪装完整结果。
