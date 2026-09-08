# 真实业务数据访问规范

当页面需要 OPS、Keepa、SellerSprite 或其组合数据时，`ops-app-build-spec` 只负责识别、记录和路由，具体合同验证与代码生成交给 `$ops-app-data-builder`。

## 1. 识别真实数据需求

出现以下任一情况即进入数据层流程：

- 页面需要销售、库存、广告、流量、利润等 OPS 数据。
- 页面需要 Keepa 或 SellerSprite 第三方数据。
- 需要多个字段、跨来源 join、指标计算、标签或异常识别。
- 需要站点专用数据库、缓存、快照、新鲜度或同步记录。
- 现有前端直连 OPS、opscli REST 或第三方平台。

只展示静态 Mock、纯 UI 或一次性临时查询不进入站点数据层构建。

## 2. 盘点要求

在 `docs/ops-app/assessment.md` 记录：

- 页面与真实数据用途。
- 已识别的数据源和现有调用路径。
- 前端直连、浏览器密钥、用户身份自报、CLI 子进程或 MCP 运行时依赖。
- 现有 FastAPI client/service/repository/schema/API 和 SQLite 迁移。
- 项目是否实际提供经过批准的 OPS 应用运行时适配器。
- SellerSprite 是否使用正式异步 REST，是否保存 pending `job_id`，是否把任务状态和用户加工结果混入共享快照。

不读取或输出真实凭证、Cookie、完整鉴权头和业务数据文件。

## 3. 委托边界

确认项目属于受支持技术栈后，使用 `$ops-app-data-builder`：

```text
识别真实数据需求
→ 读取本规范
→ 传递项目根目录、页面需求和已确认范围
→ ops-app-data-builder 验证合同并生成数据层
```

页面、API 或数据库需要持续取数时，由 `$ops-app-data-builder` 判定 `viewer-live`、用户私有持久化或经过批准的系统同步。缺少批准的系统运行时适配器时，固定同步必须标记为 `blocked`，不得复用访问者身份建立共享数据。

`ops-app-build-spec` 不选择或猜测数据集、字段、聚合、筛选、第三方场景或运行时方法签名，也不复制数据 Skill 的规则。

如果当前只是 `检查` 模式，只记录数据需求和违规风险，不修改数据层代码。

## 4. 统一架构

```text
浏览器
→ 当前站点 /api
→ FastAPI route
→ service
→ client / repository
→ OPS 应用运行时适配器、正式 opscli REST 或 SQLite
```

- 前端不得直连 OPS、opscli REST、Keepa 或 SellerSprite。
- 前端不得持有 API Key、JWT、Cookie 或完整鉴权头。
- 跨来源组合和二次加工在 service 完成。
- SQLite 分开保存第三方共享原始数据、SellerSprite 异步任务和带 `owner_user_id` 的用户私有结果。
- 网络调用不得放在 SQLite 写事务内。

## 5. 数据源基线

### OPS

- 开发期通过 `ops-dataset-query` 或 `ops-query-wizard` 验证真实合同。
- 运行期复用当前项目实际提供的 OPS 应用运行时适配器和 `x-ops-token` 受信通道。
- 默认按访问者实时取数（`viewer-live`），不把未隔离结果写入共享 SQLite。
- 找不到真实适配器时阻止生成正式调用，不猜导入路径。

### Keepa

- 开发期通过 `ops-keepa` 验证场景和样本。
- 页面运行期由站点后端调用正式 `POST /api/v1/keepa/run`；场景列表只用于开发期合同验证。
- 后端配置使用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`，后端 Secret 使用 `OPSCLI_THIRD_PARTY_DATA_API_KEY`；不得进入 `VITE_*`，不得回退读取旧变量名。
- 同时检查 HTTP 状态和响应 `success`；失败不清空最后有效共享快照。
- 多用户同步并发查询可以分别执行，成功 JSON 结果通过 `provider + request_hash` `UPSERT` 为一条共享快照。

### SellerSprite

- 开发期通过 `ops-seller-sprite` 验证合同。
- 运行期使用正式普通 jobs 或 Listing Analysis 专用异步接口，后端配置与 Keepa 共用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`、`OPSCLI_THIRD_PARTY_DATA_API_KEY`。
- 保存 `job_id` 和 `queued/running/succeeded/failed/cancelled` 状态；pending 任务复用原 `job_id`，不得重复提交。
- 只有成功 JSON 结果进入第三方共享快照；XLS/XLSX、二进制和临时下载 URL 不写入 SQLite。
- 用户查询历史、输入、收藏、备注和二次加工结果写入带 `owner_user_id` 的用户私有表。
- 不调用 quota 接口参与站点业务流程，不处理额度检查、扣减、归属或账号调度。

## 6. 项目文档

有真实数据需求时必须生成或更新：

- `docs/ops-app/data-spec.md`：数据产品、合同、执行模式、站点 API、加工、存储、安全、测试和阻塞项。
- `docs/ops-app/project-spec.md`：数据层摘要和前后端边界。
- `docs/ops-app/migration-plan.md`：接口、加工和存储映射。
- `docs/ops-app/development.md`：Mock、联调和安全环境变量。
- `docs/ops-app/deployment.md`：第三方 Secret、SQLite 持久化和运行时前置条件。

第一阶段不增加运行时数据 YAML。

## 7. 发布检查

- 浏览器只请求当前站点 `/api`。
- `VITE_*`、源码、镜像、Compose、日志和数据库中没有密钥或完整 token。
- OPS 身份不来自请求体，viewer 数据未写入未隔离共享库。
- Mock、测试替身和本地回退不得被描述成线上真实接入。
- OPS 原始和加工结果持久化时按 `owner_user_id` 隔离。
- Keepa 只使用正式同步 REST 和后端 Secret，HTTP 200 业务失败不会覆盖有效快照。
- SellerSprite 使用正式异步 REST，pending `job_id` 被复用，终态和 HTTP 202 映射正确。
- 第三方 JSON 原始数据、异步任务和用户私有加工结果分表；XLS/XLSX 和临时下载 URL 不进入 SQLite。
- 只使用 `OPSCLI_THIRD_PARTY_DATA_API_BASE_URL`、`OPSCLI_THIRD_PARTY_DATA_API_KEY`，不兼容旧变量别名。
- SQLite 只有一个写入实例、使用持久卷和迁移。
- 项目中没有真实查询结果、导出文件、Cookie 或本机绝对路径。
- data-spec 与实际代码、Pydantic Schema 和前端类型一致。
