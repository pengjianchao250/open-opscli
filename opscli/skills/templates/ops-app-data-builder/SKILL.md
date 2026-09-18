---
name: ops-app-data-builder
description: 用于 Codex 中为已绑定 AppHub 应用的标准模板项目构建真实业务数据层；复用模板 QueryGateway 验证 OPS、Keepa 或 SellerSprite 数据合同，并生成 FastAPI、前端 API、SQLite、测试和数据规范。未绑定项目、非标准模板、单次查询、纯静态页面和仅分析任务不使用本 Skill；只有会话提供 Dashboard 专用上下文与工具且目标是平台仪表盘对象时才转交 Dashboard Skill。
metadata:
  version: 0.1.18
---

# OPS 应用数据层构建

把自然语言页面需求转换为可审查、可测试、可部署的站点数据层。先验证真实数据合同，再基于标准模板的 QueryGateway、FastAPI、SQLite 和前端结构生成业务调用、加工、持久化、站点 API 和类型。

本 Skill 构建项目代码，不替代线上数据服务，不重建模板已有的鉴权和 QueryGateway 基础设施，也不让线上站点依赖 Skill 运行。

## 触发边界

使用本 Skill：

- 当前工作对象来自标准模板，并已通过 `opscli app create/init` 完成 AppHub 应用和 Git 仓库绑定。
- 页面需要 OPS、Keepa、SellerSprite 或这些来源的组合数据。
- 需求包含多个字段、跨来源组合、二次加工、数据新鲜度、SQLite 物化或站点专用 API。
- 需要为现有页面补齐 FastAPI client/service/repository/schema/API、前端 API/types、迁移或测试。
- 用户要求修复前端直连运营系统或第三方平台的取数方式。

不要使用本 Skill：

- 只需要一次临时查询或导出：使用对应数据查询 Skill。
- 业务范围、指标或维度尚不明确，且当前没有站点数据层交付目标：使用 `$ops-query-wizard`。
- 只搭建静态页面、交互或样式：继续使用 `$ops-app-build-spec`。
- 只分析一次真实数据结果，不修改站点：使用对应分析 Skill。
- 当前会话同时提供 `dashboard_session_get_context` 和 `dashboard-tools.v2`，页面上下文返回真实仪表盘对象，且用户要创建、修改或分析该对象：使用 Dashboard 专用 Skill，本 Skill 不调用 Dashboard 编辑工具。
- 当前项目缺少标准模板 QueryGateway、FastAPI 或 SQLite 结构：停止并提示重新执行标准初始化，不兼容旧数据层项目。

浏览器 URL、路由名、页面标题或用户口中的“Dashboard/看板”不能证明当前对象是 Dashboard 平台页面。普通 AppHub 仓库中的看板页面、`/#/dashboard` 路由及其源码开发，只要涉及持续真实取数，仍使用本 Skill。

不要为了触发本 Skill，把单次查询扩展成站点数据工程任务。

## 必要输入

- 项目根目录和当前 `AGENTS.md`。
- 根目录 `.opscli/app.json` 和 `app.yaml`；binding 必须包含有效 `app_id/slug`，且 `.opscli/app.json.app_id == app.yaml.app_id`，`app.yaml` 不含顶层 `name`。
- 已确认的页面业务需求、筛选范围、刷新要求和使用者范围。
- `docs/ops-app/project-spec.md`；存在时同时读取 assessment、migration-plan、development、deployment 和 data-spec。
- 标准模板中的 `backend/clients/ops_query_client.py`、`backend/core/auth.py`、`backend/services/query_service.py` 和 `backend/api/v1/query.py`。
- `app.yaml` 中的 `opscli.datasets` 数据集白名单。
- 已确认或待确认的取数模式、数据新鲜度、分页要求和使用者范围。
- 现有前端页面及 API 封装、FastAPI 路由/service/schema、SQLite model/repository/migration 和测试。

缺少业务范围时只询问会改变数据合同、权限或存储方案的关键问题。缺少 FastAPI 后端时可以完成数据规范和前端 Mock 合同，但不得创建未经 `ops-app-build-spec` 允许的后端占位服务。

## Reference 路由

| 阶段 | 必须读取 |
| --- | --- |
| 判断 OPS 取数模式、候选来源和在线验证边界 | `references/ops-dataset-application-guide.md` |
| 拆解数据产品、定义接口和持久化 | `references/data-layer-contract.md` |
| 判断 OPS、Keepa、SellerSprite 运行时路径 | `references/runtime-source-routing.md` |

涉及 OPS 时三份 Reference 都要读取；只涉及 Keepa 或 SellerSprite 时读取后两份 Reference。

## 依赖路由

- OPS 需求清晰：使用 `$ops-dataset-query` 验证真实数据集、字段、口径和少量样本。
- OPS 需求缺参、模糊或有歧义：使用 `$ops-query-wizard` 完成澄清和合同验证。
- Keepa：使用 `$ops-keepa` 验证正式场景、参数、返回结构和少量样本。
- SellerSprite：使用 `$ops-seller-sprite` 验证开发期场景、参数、返回结构和少量样本。

依赖 Skill 负责认证、元数据、字段校验和真实查询。本 Skill 不凭记忆选择数据集、字段、聚合、公式、筛选枚举或第三方场景参数，也不复制其内部查询实现。静态字段资料、历史授权目录和应用清单只能形成 `candidate`，不能替代当前在线元数据或把合同标记为 `verified`。

对业务范围已经足以构造查询的真实数据产品，必须实际发起正式合同验证；不得在没有查询尝试的情况下直接生成最终 `blocked` 页面或固定返回 `blocked` 的业务 API。临时服务异常、超时和上游不可用应记录为 `degraded`，并继续完成不依赖该来源的其他模块。查询成功但零行仍是 `verified`，页面按“暂无数据”处理。

只获取足以验证合同的少量样本。真实结果、导出文件和凭证不得提交到站点源码。

Keepa 和 SellerSprite 的在线验证必须额外固化精确 `response_shape`、业务角色字段映射和脱敏 `shape_evidence`。包含已验证第三方产品时，`docs/ops-app/data-contracts.json` 使用 `schema_version: "1.1"`；OPS-only 合同继续兼容 1.0。验证处于 `degraded` 时只允许生成传输、任务、缓存和错误恢复基础设施，不得根据旧项目、历史样本或相似字段生成猜测的生产投影器。

## 工作流

### 0. 模板初始化门禁

在写入 assessment、data-spec、前后端、SQLite、测试或部署文件前，先确认：

1. 根目录存在 `.opscli/app.json`，项目已绑定 AppHub 应用和独立仓库。
2. 项目存在标准模板拉取后的 `backend/clients/ops_query_client.py`、`backend/core/auth.py`、`backend/services/query_service.py`、`backend/api/v1/query.py` 和 `app.yaml`。
3. binding 包含有效 `app_id` 和 `slug`，并且 `.opscli/app.json.app_id == app.yaml.app_id`、`app.yaml` 不含顶层 `name`；`.opscli/app.json` 未被 Git 跟踪。
4. 当前本地分支是 `master`（允许尚无首次提交的 unborn branch），且 `origin` 与 `.opscli/app.json.repo_url` 指向同一 AppHub 业务仓库；`origin/master` 存在时可作为远端基线，但不是开始数据层开发的前置条件。

如果目录仍是未初始化的全新空项目、只有 binding 而没有模板代码、缺少标准 QueryGateway 文件、当前分支不是 `master`、`origin` 不是 binding 对应的业务仓库，或项目身份不一致，立即停止代码生成并交回 `$ops-app-build-spec`。提示先完成或重新执行 `opscli app create`、`opscli app init` 和项目身份同步；本 Skill 不自行拉取模板、不兼容旧数据层结构，也不生成替代脚手架。

仅缺少 `origin/master` 不是阻塞条件。项目已完成 `opscli app create/init`、模板和身份检查通过，且本地处于尚无首次提交的 `master` 时，继续实现和验证业务代码。首次提交与推送属于源码交付阶段；未经项目规则要求的用户授权不得执行，也不得要求用户先提交或推送后才开始数据层开发。

#### 迁移覆盖矩阵协作

如果项目存在 `.opscli/migration/current.json`，说明当前数据工作属于迁移重构，必须读取当前任务的 `coverage-matrix.json`：

1. 只处理覆盖矩阵中 `dynamic=true` 的模块；一个动态模块对应一个明确的数据产品合同，不把多个语义不同的模块合并成模糊合同。
2. 开始取数前确认 `opscli app migrate verify-ui --target "<project-directory>" --json` 已通过，当前迁移阶段至少是 `data_integration`；UI 门禁未通过时停止数据代码生成并交回 `$ops-app-build-spec`。
3. 正式验证后把 `product_key`、合同状态、`implementation_status` 和证据回写到对应项的 `data_contract`。合同状态允许 `candidate`、`verified`、`degraded`、`blocked`、`deferred_attachment`；实现状态至少区分 `not_started`、`in_progress`、`implemented`、`verified`、`contract_verified_only`、`layout_only`、`blocked`。
4. 合同样例、FakeGateway 测试和线上真实查询必须分别记录；只有正式合同验证成功或成功零行可以写为 `verified`，本地测试成功不能替代真实数据证据。
5. `degraded`、`blocked` 和 `deferred_attachment` 必须写入证据与 `unblock_conditions` 数组，对应模块不能标记为 `已完成`。
6. 合同 `verified` 只表示上游技术合同已经确认；后端 API、service、Pydantic Schema、前端消费者、测试和 OpenAPI 证据全部完成后，`implementation_status` 才能写为 `verified`。仅完成合同验证时必须写为 `contract_verified_only`，只有布局时写为 `layout_only`。
7. 一个产品验证成功后继续处理覆盖矩阵中全部未阻塞动态项，不得提前结束；每批数据合同更新后执行 `opscli app migrate export --target "<project-directory>" --json`，完成全部动态模块后执行 `opscli app migrate verify-data --target "<project-directory>" --json`。

普通非迁移开发不存在 `.opscli/migration/current.json` 时，继续使用本 Skill 的常规 assessment、data-spec 和 `data-contracts.json` 工作流，不得为了使用迁移命令伪造迁移任务。

### 1. 读取项目证据

读取项目规范、标准模板前后端入口、API 调用、环境变量、数据库、迁移和测试，确认 QueryGateway 基线完整且未被破坏。

重点识别：

- 浏览器是否直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 是否有密钥进入 `VITE_*`、源码、静态产物或日志。
- `get_query_gateway` 是否仍按 `X-Ops-Token`、`X-Session-Id` 和本地开发回退选择 `ViewerQueryGateway`、`OpsQueryGateway`、`LocalQueryGateway`。
- 业务路由是否通过 FastAPI `Depends(get_query_gateway)` 获取 `QueryGateway`，而不是自行解析凭证。
- `app.yaml` 的 `opscli.datasets` 是否覆盖本次验证的数据集。
- SQLite 是否为单写实例、是否有迁移、持久卷和清理策略。
- 用户私有数据是否统一使用可信 `owner_user_id`，第三方原始数据、异步任务、用户查询历史、输入和加工结果是否都限定当前用户。
- SellerSprite 是否按当前 `owner_user_id` 保存并复用 pending `job_id`，是否存在跨用户复用任务或结果。
- 生产配置是否关闭本机登录态回退，测试是否使用 FakeGateway 和 dependency override。
- 需要本地运行验收时是否交回 `$ops-app-build-spec` 使用 `opscli app dev`，并以 `opscli app dev-status <project-root> --json` 的 `running=true`、`identity_verified=true` 和精确 `project_root` 证明服务属于当前项目；不得用旧浏览器标签页或单独 HTTP 200 代替项目身份校验。

将发现写入 `docs/ops-app/assessment.md`；保留其他工具或人员维护的内容。

### 2. 识别数据产品

按业务判断拆成有限、互不重复的数据产品，不按页面卡片或字段数量机械拆分。每个数据产品必须有明确用途、消费者和刷新要求。

示例名称：`sales_overview`、`inventory_risk`、`keepa_price_history`、`keyword_competition`、`product_operation_overview`。

涉及 OPS 时先读取 `references/ops-dataset-application-guide.md`，将需求判定为 `one-off-query`、`guided-query`、`viewer-live`、`viewer-private-persisted`、`approved-system-sync` 或 `reference-only`。单次查询退出本 Skill；需求仍有歧义时先使用 `$ops-query-wizard`；静态资料只用于候选发现。

再读取 `references/data-layer-contract.md`，为每个数据产品记录数据源、`acquisition_mode`、合同状态、粒度、自然键、执行模式、站点 API、加工规则、存储和测试。

### 3. 验证真实合同

按依赖路由验证每个来源。至少确认：

- 数据集或场景的真实名称与可用状态。
- 维度、指标、筛选、时间字段、粒度和口径。
- 请求参数、响应结构、分页、截断、空值和数据量。
- 同步/异步执行方式、正式端点、统一响应信封、任务状态和 JSON/XLS 结果边界。
- 当前身份、站点、币种、时区和额度边界。
- 自然键、可重复执行语义和数据新鲜度。
- 候选来源的 `candidate/verified/blocked` 状态、验证时间和在线证据。
- OPS 合同的精确 `dataset_alias`、`table_id`，以及每个业务角色对应的精确 `field_name`、维度或指标角色、聚合方式和稳定结果别名。
- Keepa 和 SellerSprite 合同的精确 `response_shape.records_path`、`record_type`，SellerSprite `columns + rows` 的 `columns_path`，以及每个业务角色的 `source_field`、`source_path`、`result_field` 和 `data_type`。
- 第三方 `verification.shape_evidence` 只记录记录路径、容器类型和已观察字段名，并与技术合同逐项一致。

无法验证的字段不得写成已确认合同。清晰需求必须先进入 `verifying` 并实际调用对应 Skill；只有正式能力不支持、权限缺失、业务口径无法确认或运行时硬前置缺失，才可标记 `blocked`。服务异常和超时标记 `degraded`，不得用 `not_attempted`、`not_validated`、`service_error` 或 `timeout` 充当结构性阻塞。部分来源阻塞时保留已验证部分，并在 data-spec 中逐项标记状态。

查询构造只使用在线元数据验证后的精确 `field_name`。`global_alias`、`verbose_name`、描述和中文业务名称只能帮助发现候选，不能进入正式字段选择；禁止使用 `includes`、关键词打分、子串搜索或“最相近字段”回退。精确字段缺失、重复或角色不符时必须快速失败，不能静默换字段。`validate_fields=true` 只证明字段引用可被查询服务接受，不证明字段符合业务语义，不能替代数据合同验证。

### 4. 选择执行与存储模式

- `viewer-live`：当前访问用户权限相关的 OPS 数据，请求时查询；持久化时必须按 `owner_user_id` 隔离。
- `viewer-private-persisted`：保存当前用户查询历史、收藏、筛选或加工结果；所有读写、索引和唯一约束均按可信 `owner_user_id` 隔离。
- `approved-system-sync`：仅项目实际存在经过批准的 OPS 系统运行时适配器，且身份、授权、分页、批次、幂等和失败恢复合同完整时允许；否则标记 `blocked`，不生成无人值守同步、系统账号或伪适配器。
- `sync-request`：Keepa 等同步 REST 来源；当前用户私有快照失效时调用上游，成功后短事务 `UPSERT`。
- `async-job`：SellerSprite 等异步 REST 来源；按当前用户保存 `job_id` 和正式任务状态，pending 时只复用该用户任务，成功后读取 JSON 结果。
- `hybrid`：OPS viewer 数据与当前用户的第三方快照由 service 在请求时组合，原始和加工结果都按用户隔离。

网络请求在数据库事务外完成。SellerSprite 的 pending 任务不得重新提交。

执行方式与存储范围分开决定。合同分别声明 `source_execution`、`task_storage`、`source_storage` 和 `result_storage`；不得仅因查询耗时就把 viewer 数据写入共享库，第三方原始数据、异步任务和加工结果都必须按当前用户隔离。

### 5. 生成数据规范

创建或更新 `docs/ops-app/data-spec.md`，至少包含：

- 页面与数据产品映射。
- 取数模式、来源候选、`candidate/verified/blocked` 状态和在线验证证据。
- 字段、粒度、时间、筛选与口径。
- 精确 `dataset_alias`、`table_id`、业务角色到 `field_name` 的映射、字段角色、聚合方式、结果别名，以及字段漂移时的失败策略。
- 第三方 `response_shape`、`shape_evidence`、业务角色字段映射和 `projection_policy`；`validate_before_snapshot` 必须为 `true`，结构漂移策略必须为 `degraded_preserve_snapshot`。
- 执行模式、身份边界和数据流。
- FastAPI API、Pydantic 合同和前端类型。
- 二次加工、`owner_user_id`、`request_hash`、异步任务、SQLite 表、迁移和清理策略。
- 数据新鲜度、分页、额度、超时和错误处理。
- 环境变量、Mock、测试、阻塞项和待接入边界。

同时更新 `project-spec.md` 的数据层摘要；初始化或迁移任务还要同步更新 migration-plan、development 和 deployment。第一阶段不创建第二个运行时 YAML 权威源。

有真实数据需求时，同时生成 `docs/ops-app/data-contracts.json` 作为开发期验证凭证。开发中使用 `--mode draft`，完成上游合同验证后使用 `--mode contract`，最终交付前运行 `scripts/validate_data_contracts.py <path> --mode delivery --project-root <project-directory>`。`delivery` 要求每个真实数据产品同时满足 `contract_status=verified` 和 `implementation_status=verified`，并检查后端 API、service、Pydantic Schema、前端消费者、测试和 OpenAPI 工件真实存在；前端工件不得保留“等待真实数据合同”“仅用于布局验证”等占位文本。该凭证不得保存真实结果行、原始响应、凭证、完整 Header 或下载 URL。校验器不属于运行时查询路径，也不替代在线元数据验证。

### 6. 生成或改造项目代码

遵循标准模板结构，只创建有实际职责的文件：

```text
backend/api/v1/              FastAPI 路由和请求协议
backend/clients/             模板 QueryGateway 与第三方 API Client
backend/services/            跨来源编排和二次加工
backend/repositories/        SQLite 访问；需要时创建
backend/schemas/             Pydantic 请求与响应合同
backend/models/              持久化模型
migrations/                  Alembic 迁移
tests/                       数据合同、接口和异常测试
frontend/src/api/            当前站点 /api Client
frontend/src/types/          与 Pydantic 对齐的前端类型
```

后端路由只做协议转换、参数校验和错误映射；网络调用与业务加工进入 client/service；SQLite 访问进入 repository/db。跨来源组合必须在 service 完成，不得放到浏览器。

OPS 业务查询的精确数据集与字段合同必须在后端业务 service 或其相邻的站点业务模块中声明和校验。前端不得读取 OPS metadata 后自行选择数据集、判断字段语义、拼装通用查询或承担跨行聚合；前端只调用站点业务 API 并消费 Pydantic/OpenAPI 定义的业务结果。查询结果只读取请求中显式声明的稳定结果别名，不按相似列名猜测返回值。

Keepa 和 SellerSprite 共用一个请求级 `ThirdPartyApiClient`。Client 通过 `Depends(get_query_credentials)` 复用模板已校验的 `QueryCredentials`，不得重写 `backend/core/auth.py`、自行解析第二套身份或盲目透传浏览器 Header。`viewer` 模式只发送 `X-Ops-Token` 与可信 `X-User-Email/Id/Name`；`session` 模式发送 `X-Session-Id` 与已有的可选 Bearer JWT；`local` 模式只在 Client 内通过 `AuthClient.build_session_headers("ops")` 和 `AuthClient.build_request_auth("ops")` 提取标准 Session/JWT Header，不向远端发送 local 标识、Cookie 或其他本机凭证。三种模式身份不完整时快速失败，禁止跨模式回退。

OPS Query 与第三方 Client 只读取 `OPSCLI_MCP_REST_API_BASE_URL`。生产环境显式注入 `https://ops.mcp.xenkee.com`，预发布环境显式注入 `https://mcp.ops.aukeyit.com`；配置不得有环境默认值，必须是纯 origin，不得包含 `/api`、接口路径、查询参数或末尾 `/`。所有 REST 接口地址统一使用 `base_url.rstrip("/") + path` 拼接，不得为 OPS、Keepa 或 SellerSprite 增设独立 Base URL，也不得读取共享 API Key 或旧变量别名。OPS viewer 固定调用 `GET /api/v1/query/metadata` 与 `POST /api/v1/query/simple`；Keepa 页面运行时只调用 `POST /api/v1/keepa/run`。SellerSprite 使用正式普通 jobs 或 Listing Analysis 专用异步接口，按当前用户保存并复用 `queued/running` 任务的 `job_id`；只有 `succeeded` 的 JSON 结果写入当前用户私有快照。

用户私有表的创建、列表、读取、更新、删除、索引和唯一约束都必须包含当前 `owner_user_id`。`third_party_source_snapshot` 和 `third_party_async_job` 都使用 `UNIQUE(owner_user_id, provider, request_hash)`；用户身份不进入只描述业务参数的 `request_hash`。

OPS 业务路由必须通过 `Depends(get_query_gateway)` 获取 `QueryGateway`，service 通过参数接收 Gateway 并调用 `list_datasets`、`get_dataset_metadata`、`build_simple` 或 `build_simple_and_run`。不得在业务模块重新创建 `AuthClient`、`QueryManager`、`ViewerQueryGateway` 或第二套 Header 解析。

每个真实 OPS 数据集必须同步加入 `app.yaml` 的 `opscli.datasets` 白名单。测试必须使用 FakeGateway 和 FastAPI dependency override，不访问真实网络、本机 opscli 登录态或用户数据库。

### 7. 验证

从最小相关测试开始，再运行项目已有的类型检查、构建和后端测试。完成前确认：

- 前端只调用当前站点 `/api`。
- OPS 使用标准模板 `QueryGateway`；线上 `ViewerQueryGateway` 携带 `X-Ops-Token` 与可信 `X-User-*` 调用 opscli-mcp REST 的 `/api/v1/query/metadata` 和 `/api/v1/query/simple`，不得生成 `/v1/data-metrics/viewer/*`。
- 业务路由通过 `Depends(get_query_gateway)` 注入 Gateway，未自行解析身份或创建 `AuthClient`。
- `app.yaml.opscli.datasets` 已包含所有正式 OPS 数据集。
- OPS 查询只使用已验证的精确 `dataset_alias`、`table_id` 和 `field_name`；不存在关键词打分、`includes`、子串搜索、`global_alias` 查询回退或最相近字段替换。
- 精确字段缺失、重复、维度/指标角色不符或 metadata 漂移时快速失败，并返回稳定业务错误。
- OPS 内层失败复用模板 `extract_inner_error()`；前端优先展示 `data.inner_error.message` 等安全详细原因，不把 `LIMIT_TOO_LARGE`、字段缺失等错误降级成“请求验证失败”。
- 测试通过 FakeGateway 和 dependency override 隔离真实 SDK、凭证与网络。
- OPS viewer 数据未写入未隔离的共享 SQLite。
- OPS 原始和加工结果持久化时按 `owner_user_id` 隔离。
- OPS、Keepa 和 SellerSprite 共用 `OPSCLI_MCP_REST_API_BASE_URL`；生产值为 `https://ops.mcp.xenkee.com`，预发布值为 `https://mcp.ops.aukeyit.com`，未出现默认环境或 provider 专属 Base URL。
- `OPSCLI_MCP_REST_API_BASE_URL` 只包含纯根域名，统一通过 `base_url.rstrip("/") + path` 拼接固定 `/api/v1/*` REST 路径；不存在重复 `/api/api`、双斜杠或 `/mcp`、`/sse`。
- `ThirdPartyApiClient` 只从已校验的 `QueryCredentials` 重建三模式允许的 Header，不读取共享 API Key，不透传 Cookie，不在模式间回退。
- `third_party_source_snapshot` 和 `third_party_async_job` 的读写、UPSERT、索引与 pending 复用都包含 `owner_user_id`。
- Keepa 同时检查 HTTP 状态和响应 `success`，失败不清空最后有效快照。
- SellerSprite pending 任务复用 `job_id`，`failed/cancelled` 停止轮询，HTTP 202 不被当作完成。
- Keepa 正式商品记录按 `$.data.data[*]` 对象结构投影；SellerSprite `columns + rows` 按已验证列名投影，不按旧路径、列序或相似字段回退。
- 第三方响应先完成字段投影和必填业务角色校验，再保存快照；结构不匹配时返回 `degraded` 并保留最后有效快照。
- JSON 原始业务数据与用户加工结果分表；XLS/XLSX、二进制和临时下载 URL 未写入 SQLite。
- 网络调用发生在 SQLite 事务外，写入使用短事务和批量操作。
- Pydantic Schema、OpenAPI 和前端类型一致。
- OPS 测试使用接近真实 metadata 的字段结构，并加入 `asin/parent_asin`、`order_qty/orders`、`price/ads_sales_cny` 等相似字段干扰，证明正式字段不会被误选。
- 测试覆盖成功、空数据、零行、字段缺失、字段漂移、上游失败、泛化消息下的结构化详细原因、分页/截断、Keepa 并发写入、SellerSprite pending 复用和用户权限边界。
- 项目中没有真实业务数据文件、凭证或完整鉴权头。

未运行的验证不得写成已通过。

## 硬边界

- 不生成或引用 `opscli.app.sdk.OpsClient`，不新增 opscli REST 端点。
- 不重写 `backend/clients/ops_query_client.py` 和 `backend/core/auth.py` 的鉴权基础设施。
- 不在 OPS 业务模块直接创建 `AuthClient`、`QueryManager` 或自行解析 `X-Ops-Token`、`X-Session-Id`；第三方 local 模式仅允许请求级 `ThirdPartyApiClient` 通过 `AuthClient` 标准方法构造 Session/JWT Header。
- 不让前端直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 不让前端根据 OPS metadata、显示名、描述或相似度选择正式数据集和字段，也不让前端承担应由业务 service 完成的聚合与口径解释。
- 不用 `includes`、关键词打分、子串搜索、`global_alias` 回退或最相近字段替换生成正式 OPS 查询。
- 不在站点中执行 opscli CLI 子进程或临时连接 MCP 作为线上取数路径。
- 除显式开启的第三方 local 模式通过 `AuthClient` 标准方法读取本机登录态外，不读取 Cookie、Keychain 或凭证文件；任何模式都不得把 Cookie 发送给第三方数据服务。
- 不把 API Key、JWT、Cookie、完整鉴权头或真实账号写入源码、前端、SQLite、日志或文档。
- OPS 与第三方数据 REST API 只读取 `OPSCLI_MCP_REST_API_BASE_URL`，不读取共享 API Key，不兼容旧变量别名或第二套配置合同。
- 第三方数据 API 的 viewer、session、local 身份不允许跨模式回退，也不得从请求体接受凭证或用户身份。
- 不从请求体接受用户自报身份；OPS 身份只能来自批准的宿主请求通道。
- 不把未按用户隔离的 OPS viewer 结果写入共享 SQLite。
- 不用 SQLite 保存 XLS/XLSX、大文件、大型 BLOB、临时下载 URL 或高频任务队列。
- 不调用 SellerSprite quota 接口参与站点业务流程，不处理额度检查、扣减、归属或账号调度。
- 不为 SellerSprite 自建分布式锁、租约或独立调度平台；只持久化正式 `job_id` 和上游任务状态。
- 不伪造不存在的 SDK 类、导入路径、REST 端点、轮询端点或认证协议。
- 不生成无人值守 OPS 同步任务；Keepa 定时同步只复用项目已有且合规的调度入口。
- 不创建运行时数据 YAML 或另一套配置权威源。

## 阻塞规则

- 项目缺少标准模板 QueryGateway 文件或签名不完整：停止数据层生成并提示重新执行标准模板初始化，不兼容旧适配器或旧数据层项目。
- Keepa 需求依赖 `/api/v1/keepa/run` 未声明的运行时端点或返回字段：不得猜测路径，标记待平台补齐。
- SellerSprite 场景或参数未通过正式场景合同验证：停止该数据产品，不凭 SDK、CLI 或旧项目实现猜测 REST 合同。
- SellerSprite 仅支持 XLS/XLSX 导出而页面需要 SQLite JSON 数据产品：标记阻塞或改为明确的导出型任务，不把文件伪装成 JSON 快照。
- 依赖 Skill 返回正式能力不支持、权限缺失或运行硬前置缺失：将对应数据产品标记为 `blocked`，不影响其他数据产品继续交付。
- 依赖 Skill 已实际调用但遇到认证外的临时错误、超时或上游不可用：按反馈规则处理并标记 `degraded`，继续完成其他模块，不得改写成“尚未完成在线验证”。
- 需要多写实例、跨服务共享数据库或高频持续写入：停止 SQLite 方案并提示联系 IT。

## 完成交付

最终回复只报告：数据产品、合同状态、实现状态、已验证来源、生成或修改的代码与文档、执行模式、验证结果、降级项、阻塞项和用户下一步。不得把 Mock 写成真实接入，不得把合同验证样本写成线上数据，不得把 `contract_verified_only`、`layout_only` 或固定 `blocked` API 描述成业务取数完成。迁移任务还必须以 `opscli app migrate status` 的 `delivery_ready` 为准；为 `false` 时明确写“阶段性预览，尚未交付”。
