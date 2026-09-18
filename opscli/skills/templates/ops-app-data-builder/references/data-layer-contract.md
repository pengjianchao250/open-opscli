# 站点数据层合同

用于把页面需求转换为可实现、可测试的数据产品合同。只记录已经由项目证据、当前在线元数据或对应数据 Skill 验证的内容；静态资料只能形成候选，未验证项必须明确标记。

## 1. 数据产品结构

每个数据产品至少声明来源执行、任务存储、原始数据存储和加工结果存储：

```json
{
  "product_key": "seller_sprite_competitor_analysis",
  "business_purpose": "查询竞品原始数据并生成当前用户分析结果",
  "consumers": ["competitor-page"],
  "source": "seller_sprite",
  "contract_status": "verified",
  "requires_real_data": true,
  "verification": {
    "attempted": true,
    "attempted_at": "2026-09-17T10:00:00+08:00",
    "method": "ops-seller-sprite",
    "outcome": "success",
    "row_count": 20,
    "shape_evidence": {
      "records_path": "$.data.result.rows[*]",
      "record_type": "array",
      "observed_fields": ["商品标题", "价格", "月销量"]
    }
  },
  "technical_contract": {
    "scenario": "verified_scenario",
    "site": "US",
    "period": "30d",
    "result_format": "json",
    "response_shape": {
      "records_path": "$.data.result.rows[*]",
      "record_type": "array",
      "columns_path": "$.data.result.columns"
    },
    "required_business_roles": ["title", "price", "estimated_sales_30d"],
    "fields": {
      "title": {
        "source_field": "商品标题",
        "source_path": "$.data.result.rows[*][0]",
        "result_field": "title",
        "data_type": "string"
      },
      "price": {
        "source_field": "价格",
        "source_path": "$.data.result.rows[*][1]",
        "result_field": "price",
        "data_type": "number"
      },
      "estimated_sales_30d": {
        "source_field": "月销量",
        "source_path": "$.data.result.rows[*][2]",
        "result_field": "estimated_sales_30d",
        "data_type": "integer"
      }
    },
    "projection_policy": {
      "validate_before_snapshot": true,
      "on_schema_mismatch": "degraded_preserve_snapshot"
    }
  },
  "execution_mode": "async-job",
  "grain": ["site", "asin"],
  "natural_key": ["site", "asin"],
  "source_execution": {
    "auth": "query-credentials",
    "credential_dependency": "get_query_credentials",
    "auth_modes": ["viewer", "session", "local"],
    "base_url_env": "OPSCLI_MCP_REST_API_BASE_URL",
    "production_base_url": "https://ops.mcp.xenkee.com",
    "prerelease_base_url": "https://mcp.ops.aukeyit.com",
    "submit_endpoint": "POST /api/v1/seller-sprite/jobs",
    "status_endpoint": "GET /api/v1/seller-sprite/jobs/{job_id}",
    "result_endpoint": "GET /api/v1/seller-sprite/jobs/{job_id}/result",
    "success_state": "succeeded",
    "result_format": "json"
  },
  "request_identity_fields": ["scenario", "site", "period", "page_size", "params"],
  "task_storage": {
    "storage_mode": "sqlite",
    "storage_scope": "user-private",
    "owner_identity_source": "get_current_user",
    "owner_key": "owner_user_id",
    "table": "third_party_async_job",
    "unique_key": ["owner_user_id", "provider", "request_hash"],
    "active_states": ["queued", "running"]
  },
  "source_storage": {
    "storage_mode": "sqlite",
    "storage_scope": "user-private",
    "owner_identity_source": "get_current_user",
    "owner_key": "owner_user_id",
    "table": "third_party_source_snapshot",
    "unique_key": ["owner_user_id", "provider", "request_hash"]
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

示例字段只表达合同形状，不代表真实 SellerSprite 场景或参数；`verified_scenario` 只能在项目中替换为对应 Skill 实际验证的正式场景。实际场景、字段和口径必须由对应数据 Skill 验证后写入项目 data-spec。

## 2. 合同状态

| 状态 | 含义 |
| --- | --- |
| `candidate` | 业务目标或候选来源已识别，尚未发起当前在线验证 |
| `verifying` | 正在调用正式数据源或执行合同给出的恢复流程 |
| `verified` | 来源、字段或场景、参数和少量样本已验证；零行结果也可属于本状态 |
| `degraded` | 已实际调用，但临时服务错误、超时或上游异常导致本轮未完成 |
| `blocked` | 正式能力不支持、权限缺失、业务口径无法确认或运行硬前置缺失 |
| `mock-only` | 只允许前端联调和测试，不代表线上可取数 |

不得用一个总状态覆盖所有数据产品。多来源产品要分别记录每个来源的状态、验证时间和证据。静态字段目录、历史授权目录和应用清单不能把 `candidate` 提升为 `verified`。没有真实查询尝试时不得从 `candidate` 直接变为最终 `blocked`；临时服务异常不得伪装成正式能力不支持。

### 2.1 开发期验证凭证

有真实数据需求的项目生成 `docs/ops-app/data-contracts.json`。该文件是开发期验证凭证，不是运行时配置权威源，使用固定结构：

- OPS-only 合同可以继续使用 `schema_version: "1.0"`。
- 只要包含 `contract_status: "verified"` 的 Keepa 或 SellerSprite 产品，就必须升级为 `schema_version: "1.1"`。
- 第三方验证凭证只保存 `shape_evidence.records_path`、`record_type` 和 `observed_fields`，不得保存真实商品行、导出结果或完整响应。

```json
{
  "schema_version": "1.0",
  "products": [
    {
      "product_key": "monthly_sales_trend",
      "source": "ops",
      "contract_status": "verified",
      "requires_real_data": true,
      "verification": {
        "attempted": true,
        "attempted_at": "2026-09-17T10:00:00+08:00",
        "method": "opscli query flow",
        "outcome": "zero_rows",
        "row_count": 0
      },
      "technical_contract": {
        "dataset_alias": "verified_dataset_alias",
        "table_id": "verified_table_id",
        "required_business_roles": ["month", "orders"],
        "fields": {
          "month": {
            "field_name": "verified_month_field",
            "role": "dimension",
            "result_alias": "month"
          },
          "orders": {
            "field_name": "verified_orders_field",
            "role": "metric",
            "aggregation": "sum",
            "result_alias": "orders"
          }
        }
      },
      "implementation_status": "verified",
      "implementation_artifacts": {
        "backend_api": ["backend/api/v1/sales.py"],
        "backend_service": ["backend/services/sales_service.py"],
        "backend_schema": ["backend/schemas/sales.py"],
        "frontend_consumer": ["frontend/src/api/sales.ts", "frontend/src/views/SalesView.vue"],
        "tests": ["tests/api/test_sales.py"],
        "openapi": ["docs/openapi.json"]
      }
    }
  ]
}
```

开发期按阶段运行：

```text
python <skill-dir>/scripts/validate_data_contracts.py docs/ops-app/data-contracts.json --mode draft
python <skill-dir>/scripts/validate_data_contracts.py docs/ops-app/data-contracts.json --mode contract
python <skill-dir>/scripts/validate_data_contracts.py docs/ops-app/data-contracts.json --mode delivery --project-root <project-directory>
```

凭证不得包含真实结果行、原始响应、Token、Cookie、JWT、Session ID、密码、Secret、API Key 或临时下载地址。OPS 技术合同必须用 `required_business_roles` 声明用户点名的全部维度、指标和必要筛选角色，且 `fields` 必须逐项覆盖。`verified` 必须记录真实调用尝试和技术合同；`degraded` 必须记录失败码、是否可重试和按规则产生的反馈 UUID；`blocked` 必须记录结构化 `blockers`，不得使用 `not_attempted`、`not_validated`、`service_error` 或 `timeout`。

`contract_status` 与 `implementation_status` 是两个独立维度。合同 `verified` 后，数据层仍可处于 `contract_verified_only`、`not_started`、`in_progress` 或 `implemented`；只有后端 API、service、Pydantic Schema、前端消费、测试和 OpenAPI 证据全部完成并通过验证后，才能写为 `implementation_status=verified`。`delivery` 模式会检查上述工件真实存在，并拒绝前端中的“等待真实数据合同”“仅用于布局验证”等占位文本。

### 2.2 OPS 取数模式

涉及 OPS 时先按 `references/ops-dataset-application-guide.md` 判定：

- `one-off-query`：退出数据层构建，交给查询 Skill。
- `guided-query`：先由 `$ops-query-wizard` 澄清。
- `viewer-live`：当前访问者实时查询。
- `viewer-private-persisted`：按可信 `owner_user_id` 保存用户私有历史或加工结果。
- `approved-system-sync`：仅有经过批准的系统运行时适配器时允许。
- `reference-only`：只形成候选，不生成运行时代码。

OPS 数据产品在 data-spec 中记录 `acquisition_mode`。Keepa 和 SellerSprite 继续使用各自的 `execution_mode`，但上游鉴权必须复用模板相同的 `viewer/session/local` 请求身份模式。

### 2.3 OPS 精确字段合同

每个 `verified` 的 OPS 数据产品必须记录并在后端业务代码中固化：

- 精确 `dataset_alias` 和 `table_id`。
- 每个业务角色对应的精确 `field_name`，以及它是维度、指标还是筛选字段。
- 指标聚合方式、筛选操作符、稳定结果别名、时间与币种口径。
- metadata 缺少字段、字段重复、字段角色变化或返回结构漂移时的稳定错误和停止策略。

正式查询字段只能来自当前身份在线 metadata 验证后的 `field_name`。`global_alias`、`verbose_name`、描述和中文名称只用于候选发现与人工审查；不得通过 `includes`、关键词打分、子串搜索或最相近字段回退决定正式数据集、字段或结果列。`validate_fields=true` 不能证明字段业务语义正确，不能替代本合同。

精确合同放在后端业务 service 或其相邻业务模块，并由 data-spec、Pydantic Schema、OpenAPI 和测试同步描述。前端只调用站点业务 API，不能读取 metadata 后自行选择字段或拼装通用 OPS 查询；响应解析只读取请求显式声明的稳定结果别名。

## 3. 执行模式

- `viewer-live`：OPS 按当前访问用户权限查询。
- `sync-request`：Keepa 同步 REST 查询，成功后可写当前用户私有快照。
- `async-job`：SellerSprite 提交任务、保存 `job_id`、查询状态并读取结果。
- `hybrid`：OPS viewer 数据和当前用户的第三方快照在 service 中组合。

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

### 4.2 OPS 批准的系统同步

标准模板不自动提供 OPS 无人值守系统身份。只有项目实际存在经过批准的运行时适配器，且身份、授权、白名单、确定性分页、批次、自然键、幂等、快照和失败恢复均有项目证据时，才允许生成系统同步实现。

缺少任一前置时将来源标记为 `blocked`。不得保存访问者 `X-Ops-Token`、使用某个 viewer 身份生成站点共享快照、自行创建系统账号或伪造 SDK Client。

### 4.3 第三方用户私有原始数据

Keepa 和 SellerSprite 成功返回的 JSON 原始业务数据可以写入 `third_party_source_snapshot`，但必须按 `owner_user_id` 隔离。站点后端的 OPS Query 与 `ThirdPartyApiClient` 只使用 `OPSCLI_MCP_REST_API_BASE_URL`；生产根域名为 `https://ops.mcp.xenkee.com`，预发布根域名为 `https://mcp.ops.aukeyit.com`，均由部署环境显式注入且不得设默认值。endpoint 只记录 `/api/v1/...` 固定路径，不重复保存完整域名。

`ThirdPartyApiClient` 通过 `get_query_credentials()` 复用模板 `QueryCredentials`。`viewer` 重建 `X-Ops-Token` 与可信 `X-User-*`，`session` 重建 `X-Session-Id` 与已有可选 Bearer JWT，`local` 通过 `AuthClient.build_session_headers("ops")` 和 `AuthClient.build_request_auth("ops")` 转换为标准 Session/JWT Header。禁止共享 API Key、Header 盲目透传、Cookie 上送、请求体凭证和模式回退。

`normalized_request_json` 与 `payload_json` 不得包含 Authorization、Session、JWT、Cookie、用户身份、完整敏感响应或非业务调用上下文。XLS/XLSX、二进制内容和临时下载 URL 不写入 SQLite。

### 4.4 用户私有行为和加工结果

以下内容使用 `user-private`：

- 用户查询历史和原始输入参数。
- 收藏、备注、筛选和个人配置。
- 用户对第三方快照生成的筛选、计算、打分和分析结果。
- OPS 与第三方数据组合形成的结果。

第三方原始快照、用户行为和加工结果都按用户隔离，但必须分表以保持原始合同与加工语义独立。

## 5. request_hash 合同

`request_hash` 只包含影响业务结果的规范化字段：

- Keepa：`scenario + site + params`。
- SellerSprite 普通任务：`scenario + site + period + page_size + params`。
- SellerSprite Listing Analysis：`asin + station + site`。

以下内容不得进入 `request_hash`：`job_id`、`wait`、`force`、`reserve_tokens`、`wait_seconds`、轮询次数、API Key 和当前站点用户身份。

第三方快照和 SellerSprite 当前任务表都使用 `UNIQUE(owner_user_id, provider, request_hash)`。用户身份不进入 `request_hash`，只进入数据库唯一键与归属过滤。

## 6. SQLite 模型合同

### 6.1 第三方用户私有快照

`third_party_source_snapshot` 至少包含：

- `owner_user_id`、`provider`、`scenario`、`site`、`request_hash`。
- `normalized_request_json`、`payload_json`。
- `source_job_id`、`result_format`、`schema_version`。
- `source_fetched_at`、`expires_at`。

写入使用 `UPSERT`。只有 `source_fetched_at` 不早于现有记录的响应可以覆盖，失败不得清空最后有效快照。

### 6.2 SellerSprite 当前任务

`third_party_async_job` 至少包含：

- `owner_user_id`、`provider`、`request_hash`、`job_id`、`job_type`。
- `state`、`stage`、`result_format`、`error_code`。
- `submitted_at`、`checked_at`、`completed_at`。

存在 `queued/running` 任务时只复用当前用户原 `job_id`。终态任务需要刷新时更新当前用户任务记录；用户查询历史不得混入异步任务表。

### 6.3 用户加工结果

`user_processed_result` 至少包含 `owner_user_id`、`source_snapshot_id`、`product_key`、`processing_params_json`、`result_json`、`calculation_version`、`calculated_at` 和 `expires_at`。

## 7. 站点 API 合同

站点 API 统一位于 `/api`，前端不得感知上游系统地址、凭证或认证方式。每个 API 至少定义：

- 方法、路径、参数和 Pydantic 请求响应 Schema。
- 当前用户身份要求、存储范围和数据新鲜度。
- 同步结果、异步处理中和异步终态的稳定业务 code。
- 上游失败、无权限、空数据、分页、截断和超时映射。

SellerSprite 上游 HTTP 202 应映射为本站稳定的处理中响应。前端只轮询当前站点 API，不直连 SellerSprite。

OPS 路由必须通过 FastAPI `Depends(get_query_gateway)` 获取 `QueryGateway`。业务 service 通过参数接收 Gateway，不得自行解析 `X-Ops-Token`、`X-Session-Id`，也不得直接创建 `AuthClient`、`QueryManager` 或另一套 Viewer Client。

## 8. 第三方调用合同

- 请求级 `ThirdPartyApiClient` 通过 `Depends(get_query_credentials)` 接收已校验的 `QueryCredentials`。
- 三种模式只发送已定义的 Session/JWT 或 viewer Header，不传 Cookie，不从请求体接受身份，不跨模式回退。
- 只读取 `OPSCLI_MCP_REST_API_BASE_URL`；生产/预发布显式注入，代码不设置环境默认值。

### 8.1 Keepa

- 页面运行时只调用 `POST /api/v1/keepa/run`。
- 场景列表只用于开发期验证或新增场景确认。
- 正式商品结果按 `$.data.data[*]` 对象记录验证；标题、当前价、BSR 等页面字段必须绑定已观察到的精确字段名，例如 `title`、`currentAmazonPrice`、`currentSalesRank`。
- 同时检查 HTTP 状态和响应 `success`；HTTP 200 且 `success=false` 仍是失败。
- HTTP 和业务状态成功后，先按 `response_shape` 提取并投影记录，再校验 `required_business_roles`；只有投影校验通过才允许短事务写入快照。
- 路径或字段漂移时使用 `degraded_preserve_snapshot`，不得清空或覆盖最后有效快照。

### 8.2 SellerSprite

- 普通任务使用正式 jobs 提交、状态、批量状态、result 或 export 接口。
- Listing Analysis 使用独立三段式接口，不提交到普通 jobs。
- JSON 场景必须记录精确 `response_shape`。对于 `columns + rows` 结构，声明 `columns_path`、`records_path` 和 `record_type: "array"`，并用在线返回的正式列名建立字段映射。
- 保存每次提交返回的 `job_id`；pending 任务不得重新提交。
- `queued/running` 继续查询，`succeeded` 读取结果，`failed/cancelled` 停止轮询。
- 只有完成字段投影与必填角色校验的 JSON 结果可以进入当前用户私有快照；文件导出保持导出型任务。
- 不调用 quota 接口参与业务流程，不处理额度检查、扣减、归属或账号调度。

### 8.3 第三方投影与降级

- `technical_contract.response_shape`、`fields` 和 `projection_policy` 必须与在线验证得到的 `verification.shape_evidence` 一致。
- `projection_policy.validate_before_snapshot` 固定为 `true`，`on_schema_mismatch` 固定为 `degraded_preserve_snapshot`。
- 在线验证为 `degraded` 时可以生成请求、任务、缓存和错误处理基础设施，但不得依据旧项目、相似字段或历史样本猜测正式生产字段投影。

## 9. 错误与日志合同

- HTTP 202 表示处理中，不表示完成。
- HTTP 401/403 映射为当前请求身份无效、过期或无工具权限，不切换模式重试。
- HTTP 404 的 SellerSprite 任务不得继续假装 pending。
- HTTP 409 改走正确的 result/export 合同。
- HTTP 422 不原样重试；HTTP 502 仅有限重试；HTTP 503 遵循 `Retry-After`。
- OPS viewer 单次查询 `limit` 按已验证 REST 合同不超过 `50000`；需要更多数据时使用确定性分页并检查 `truncated`、`total_count`，不得把 SDK 或旧文档中的更大上限直接用于 viewer。
- OPS HTTP 200 内层失败必须保留 `error.code` 和 `details.errors`。业务 service 复用模板 `extract_inner_error()` 或等价结构化解析；前端错误归一化优先展示安全的 `data.inner_error.message`。当顶层仅为“请求验证失败”时，不得丢失 `LIMIT_TOO_LARGE`、字段名、实际值和允许上限等可行动原因。
- 日志只记录时间、耗时、`scenario`、`site`、`job_id`、HTTP 状态、`success`、`state`、`error.code` 和 `row_count` 等必要元数据。

## 10. 测试合同

至少覆盖：

- OPS FakeGateway、dependency override 和 `owner_user_id` 隔离。
- OPS 精确数据集与字段合同，包含字段缺失、重复、角色变化和 metadata 漂移的快速失败。
- OPS 泛化顶层消息与结构化详细原因并存时，断言 `LIMIT_TOO_LARGE` 等具体原因能够到达站点 API 和前端提示。
- 使用接近真实 metadata 的相似字段干扰，例如 `asin/parent_asin`、`order_qty/orders`、`price/ads_sales_cny`，证明代码不会按关键词或相似度误选字段。
- Keepa 同步成功、HTTP 200 业务失败、并发 `UPSERT` 和旧响应不覆盖新快照。
- SellerSprite 提交、HTTP 202、pending `job_id` 复用、终态、JSON result 和 XLS/XLSX 边界。
- 用户查询历史、加工结果、越权读取、越权更新和并发刷新。
- 验证 Pydantic Schema 与前端类型的一致性，并保持 OpenAPI 合同同步。
- 测试不访问真实网络、真实账号、真实凭证或用户本地数据库。

## 11. data-spec.md 建议结构

```text
1. 页面与数据产品
2. OPS acquisition_mode 与选择原因
3. 候选来源、candidate/verifying/verified/degraded/blocked 状态和在线验证证据
4. 精确 dataset_alias、table_id、field_name、字段角色、聚合、结果别名、粒度、自然键、快照与业务口径
5. 执行模式与身份边界
6. source_execution 与 request_hash
7. task/source/result storage
8. 站点 API 与错误合同
9. 二次加工和用户隔离
10. SQLite 模型、迁移与清理
11. 新鲜度、分页、截断、超时与重试
12. 环境变量与 Secret
13. Mock、测试、降级和阻塞项
14. `data-contracts.json` 与交付校验结果
```

第一阶段只生成 Markdown 规范，不新增运行时 YAML；数据规范不得形成第二套配置权威源。
