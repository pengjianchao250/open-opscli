# 运行时数据源路由

开发期验证和线上运行是两条不同路径。开发期可以使用对应 Skill 获取少量真实样本；线上站点只能使用项目中明确批准的后端运行时入口。

## 1. 总体数据流

```text
浏览器
→ 当前站点 FastAPI /api
→ client / service / repository
→ 已批准的数据源运行时入口
```

浏览器不直连 OPS、opscli REST、Keepa 或 SellerSprite。跨来源组合只在 FastAPI service 完成。

## 2. OPS

### 2.1 开发期验证

- 清晰需求使用 `$ops-dataset-query`。
- 缺参、模糊或有歧义的需求使用 `$ops-query-wizard`。
- 不凭记忆填写数据集、字段、聚合、公式或筛选枚举。
- 样本只用于合同验证，不提交到源码。

### 2.2 运行期

OPS 使用应用宿主注入的 `x-ops-token` 受信通道，默认模式为 `viewer-live`：

```text
浏览器请求
→ 站点 FastAPI
→ 项目实际提供的 OPS 应用运行时适配器
→ OPS data-metrics
```

实现前必须在当前项目或正式模板中检查适配器的真实导入路径、构造参数、查询方法、错误类型和响应合同。规范文档将该能力称为 `OpsClient`，但不得仅根据名称生成未经验证的导入和方法调用。

约束：

- token 只从批准的请求依赖读取，不从请求体接收。
- 不使用 `AuthClient`、本地 opscli 登录态或个人 session 代替应用运行时通道。
- 不把完整 token 传给前端、日志、SQLite 或下游非 OPS 服务。
- 默认不缓存或物化未按用户隔离的 viewer 结果。
- 若适配器不存在或无法检查，生成 schema、Mock 和 data-spec，正式调用代码保持阻塞。

## 3. Keepa

### 3.1 开发期验证

使用 `$ops-keepa` 获取正式场景、验证参数和少量返回样本。不得把本地 Keepa Key 或导出文件复制到站点。

### 3.2 运行期

站点后端通过正式 opscli REST API 调用 Keepa：

```text
浏览器
→ 站点 /api
→ 后端 OpscliApiClient
→ /api/v1/keepa/scenarios 或 /api/v1/keepa/run
```

后端配置：

```text
OPSCLI_API_BASE_URL
OPSCLI_API_KEY
```

`.env.example` 只声明变量名和安全占位值，真实值由部署 Secret 注入。

Client 必须：

- 使用 Bearer API Key Header，不把 Key 放进 URL 或请求体。
- 同时检查 HTTP 状态和统一响应信封的 `success`、`data`、`error`。
- 按 `error.code` 分支，不解析 message 文本。
- 为请求设置显式超时；只对幂等且允许重试的上游失败做有限重试。
- 处理场景返回中的分页、截断、总量和额度信息。
- 对可重复执行任务使用稳定 `job_id`；不得猜测未在正式 API 文档声明的任务状态或下载端点。

当前正式文档只声明 Keepa scenarios 和 run。需求依赖其他端点时必须标记阻塞，不能根据 CLI/MCP 能力推断 REST 路径。

Keepa 可以实时调用，也可以按业务新鲜度物化到 SQLite。物化时网络请求在事务外，成功解析后批量短事务写入；失败不得清空最后一份有效快照。

## 4. SellerSprite

### 4.1 开发期验证

使用 `$ops-seller-sprite` 验证场景、参数、返回结构和少量样本，可以据此生成：

- Pydantic Schema 和前端类型。
- FastAPI 站点 API 合同。
- Mock fixture 和接口测试。
- SQLite 表、自然键、索引和迁移设计。
- data-spec 中的待接入说明。

### 4.2 第一阶段运行期

当前正式 REST API 文档未声明 SellerSprite 端点，本轮也不修改 `opscli/app/sdk`。因此默认状态为 `blocked` 或 `mock-only`，不得生成伪造的正式调用代码。

禁止：

- 读取本机或个人 Cookie。
- 在站点进程中执行 opscli CLI。
- 运行时临时连接 MCP。
- 固化 session、JWT 或个人账号。
- 由前端直连 SellerSprite。

如果当前项目已经存在经过批准且可检查的 SellerSprite 运行时适配器，可以复用其真实合同；否则保持阻塞并说明平台需要补齐的正式入口。

## 5. 混合来源

OPS + Keepa 的默认组合模式为 `hybrid`：

- OPS 按当前 viewer 实时查询。
- Keepa 读取允许共享的 SQLite 快照或由后端实时调用。
- service 按已验证的站点、ASIN、时间和币种规则组合。
- repository 不接收未隔离的 OPS viewer 数据。

任一来源失败时，是否允许部分结果必须在 data-spec 和 API schema 中明确，不能静默返回旧数据或伪装完整结果。
