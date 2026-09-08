# 站点数据层合同

用于把页面需求转换为可实现、可测试的数据产品合同。只记录已经由项目证据或对应数据 Skill 验证的内容；未验证项必须明确标记。

## 1. 数据产品结构

每个数据产品至少声明来源执行、任务存储、原始数据存储和加工结果存储：

```json
{
  "product_key": "seller_sprite_competitor_analysis",
  "business_purpose": "查询竞品原始数据并生成当前用户分析结果",
  "consumers": ["competitor-page"],
  "source": "seller_sprite",
  "contract_status": "verified",
  "execution_mode": "async-job",
  "grain": ["site", "asin"],
  "natural_key": ["site", "asin"],
  "source_execution": {
    "auth": "backend-bearer-secret",
    "base_url_env": "OPSCLI_API_BASE_URL",
    "production_base_url": "https://ops.mcp.xenkee.com",
    "api_key_env": "OPSCLI_API_KEY",
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
  "site_api": "GET /api/competitors",
  "limitations": []
}
```

示例字段只表达合同形状，不代表真实 SellerSprite 场景或参数。实际场景、字段和口径必须由对应数据 Skill 验证后写入项目 data-spec。

## 2. 合同状态

| 状态 | 含义 |
| --- | --- |
| `draft` | 业务目标已识别，尚未验证真实来源 |
| `verified` | 来源、字段或场景、参数和少量样本已验证 |
| `blocked` | 正式端点、权限、返回格式或运行前置缺失 |
| `mock-only` | 只允许前端联调和测试，不代表线上可取数 |

不得用一个总状态覆盖所有数据产品。多来源产品要分别记录每个来源的状态。

## 3. 执行模式

- `viewer-live`：OPS 按当前访问用户权限查询。
- `sync-request`：Keepa 同步 REST 查询，成功后可写共享快照。
- `async-job`：SellerSprite 提交任务、保存 `job_id`、查询状态并读取结果。
- `hybrid`：OPS viewer 数据和允许共享的第三方快照在 service 中组合。

执行模式不决定存储归属。合同必须独立声明 `task_storage`、`source_storage` 和 `result_storage`。

## 4. 身份与存储范围

### 4.1 OPS 用户数据

OPS 原始数据受当前 viewer 权限影响。OPS 原始数据和基于 OPS 的加工结果如果持久化，必须使用：

```text
storage_scope = user-private
owner_identity_source = get_current_user
owner_key = owner_user_id
```

用户私有表的创建、读取、更新、删除、索引、唯一约束和幂等键都必须包含 `owner_user_id`。

### 4.2 第三方共享原始数据

Keepa 和 SellerSprite 成功返回的 JSON 原始业务数据可以写入 `third_party_source_snapshot`。共享前提是站点后端统一使用 `OPSCLI_API_BASE_URL`、`OPSCLI_API_KEY` 和同一个 `ThirdPartyApiClient`；生产根域名固定为 `https://ops.mcp.xenkee.com`，endpoint 只记录 `/api/v1/...` 固定路径，不重复保存完整域名。站点访问用户身份不作为上游调用凭证。

共享快照不得包含 API Key、Authorization、Session、JWT、Cookie、用户身份、完整敏感响应或非业务调用上下文。XLS/XLSX、二进制内容和临时下载 URL 不写入 SQLite。

### 4.3 用户私有行为和加工结果

以下内容使用 `user-private`：

- 用户查询历史和原始输入参数。
- 收藏、备注、筛选和个人配置。
- 用户对第三方快照生成的筛选、计算、打分和分析结果。
- OPS 与第三方数据组合形成的结果。

共享原始快照不表示用户行为和加工结果共享。

## 5. request_hash 合同

`request_hash` 只包含影响业务结果的规范化字段：

- Keepa：`scenario + site + params`。
- SellerSprite 普通任务：`scenario + site + period + page_size + params`。
- SellerSprite Listing Analysis：`asin + station + site`。

以下内容不得进入 `request_hash`：`job_id`、`wait`、`force`、`reserve_tokens`、`wait_seconds`、轮询次数、API Key 和当前站点用户身份。

共享快照和 SellerSprite 当前任务表都使用 `UNIQUE(provider, request_hash)`。用户查询历史使用包含 `owner_user_id` 的独立自然键。

## 6. SQLite 模型合同

### 6.1 第三方共享快照

`third_party_source_snapshot` 至少包含：

- `provider`、`scenario`、`site`、`request_hash`。
- `normalized_request_json`、`payload_json`。
- `source_job_id`、`result_format`、`schema_version`。
- `source_fetched_at`、`expires_at`、`last_fetched_by_user_id`。

写入使用 `UPSERT`。只有 `source_fetched_at` 不早于现有记录的响应可以覆盖，失败不得清空最后有效快照。

### 6.2 SellerSprite 当前任务

`third_party_async_job` 至少包含：

- `provider`、`request_hash`、`job_id`、`job_type`。
- `state`、`stage`、`result_format`、`error_code`。
- `submitted_by_user_id`、`submitted_at`、`checked_at`、`completed_at`。

存在 `queued/running` 任务时复用原 `job_id`。终态任务需要刷新时更新当前任务记录；用户查询历史不得混入共享任务表。

### 6.3 用户加工结果

`user_processed_result` 至少包含 `owner_user_id`、`source_snapshot_id`、`product_key`、`processing_params_json`、`result_json`、`calculation_version`、`calculated_at` 和 `expires_at`。

## 7. 站点 API 合同

站点 API 统一位于 `/api`，前端不得感知上游系统地址、密钥或认证方式。每个 API 至少定义：

- 方法、路径、参数和 Pydantic 请求响应 Schema。
- 当前用户身份要求、存储范围和数据新鲜度。
- 同步结果、异步处理中和异步终态的稳定业务 code。
- 上游失败、无权限、空数据、分页、截断和超时映射。

SellerSprite 上游 HTTP 202 应映射为本站稳定的处理中响应。前端只轮询当前站点 API，不直连 SellerSprite。

OPS 路由必须通过 FastAPI `Depends(get_query_gateway)` 获取 `QueryGateway`。业务 service 通过参数接收 Gateway，不得自行解析 `X-Ops-Token`、`X-Session-Id`，也不得直接创建 `AuthClient`、`QueryManager` 或另一套 Viewer Client。

## 8. 第三方调用合同

### 8.1 Keepa

- 页面运行时只调用 `POST /api/v1/keepa/run`。
- 场景列表只用于开发期验证或新增场景确认。
- 同时检查 HTTP 状态和响应 `success`；HTTP 200 且 `success=false` 仍是失败。
- 网络请求在 SQLite 写事务外完成，成功解析后短事务写入。

### 8.2 SellerSprite

- 普通任务使用正式 jobs 提交、状态、批量状态、result 或 export 接口。
- Listing Analysis 使用独立三段式接口，不提交到普通 jobs。
- 保存每次提交返回的 `job_id`；pending 任务不得重新提交。
- `queued/running` 继续查询，`succeeded` 读取结果，`failed/cancelled` 停止轮询。
- 只有 JSON `data.result` 可以进入共享快照；文件导出保持导出型任务。
- 不调用 quota 接口参与业务流程，不处理额度检查、扣减、归属或账号调度。

## 9. 错误与日志合同

- HTTP 202 表示处理中，不表示完成。
- HTTP 401/403 映射为后端 Secret、上游身份或工具权限错误。
- HTTP 404 的 SellerSprite 任务不得继续假装 pending。
- HTTP 409 改走正确的 result/export 合同。
- HTTP 422 不原样重试；HTTP 502 仅有限重试；HTTP 503 遵循 `Retry-After`。
- 日志只记录时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count` 等必要元数据。

## 10. 测试合同

至少覆盖：

- OPS FakeGateway、dependency override 和 `owner_user_id` 隔离。
- Keepa 同步成功、HTTP 200 业务失败、并发 `UPSERT` 和旧响应不覆盖新快照。
- SellerSprite 提交、HTTP 202、pending `job_id` 复用、终态、JSON result 和 XLS/XLSX 边界。
- 用户查询历史、加工结果、越权读取、越权更新和并发刷新。
- 验证 Pydantic Schema 与前端类型的一致性，并保持 OpenAPI 合同同步。
- 测试不访问真实网络、真实账号、真实凭证或用户本地数据库。

## 11. data-spec.md 建议结构

```text
1. 页面与数据产品
2. 数据源和验证证据
3. 字段、粒度与业务口径
4. 执行模式与身份边界
5. source_execution 与 request_hash
6. task/source/result storage
7. 站点 API 与错误合同
8. 二次加工和用户隔离
9. SQLite 模型、迁移与清理
10. 新鲜度、分页、超时与重试
11. 环境变量与 Secret
12. Mock、测试和阻塞项
```

第一阶段只生成 Markdown 规范，不新增运行时 YAML；数据规范不得形成第二套配置权威源。
