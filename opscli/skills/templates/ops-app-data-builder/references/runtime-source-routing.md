# 运行时数据源路由

开发期验证和线上运行是两条不同路径。开发期可以使用对应 Skill 获取少量真实样本；线上站点统一使用标准模板提供的 QueryGateway，不兼容旧数据层或自定义运行时适配器。

## 1. 总体数据流

```text
浏览器
→ 当前站点 FastAPI /api
→ Depends(get_query_gateway)
→ QueryGateway / service / repository
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

约束：

- token 和 session 只由 `backend/core/auth.py` 从批准的请求 Header 解析，不从请求体接收。
- 线上业务只使用 `ViewerQueryGateway`，不使用 `AuthClient`、本地 opscli 登录态或个人 session 代替应用运行时通道。
- `LocalQueryGateway` 只允许在本地开发且 `LOCAL_AUTH_FALLBACK_ENABLED=true` 时使用，生产必须关闭。
- 每个正式 OPS 数据集必须加入 `app.yaml` 的 `opscli.datasets` 白名单。
- 测试使用 FakeGateway 和 FastAPI dependency override，不构造真实 Gateway，不访问真实网络或本机凭证。
- 不把完整 token 传给前端、日志、SQLite 或下游非 OPS 服务。
- 默认不缓存或物化未按用户隔离的 viewer 结果。
- 缺少标准 QueryGateway 文件、类或方法时停止生成并提示重新执行标准模板初始化，不兼容旧适配器。

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

当前正式 REST API 文档未声明 SellerSprite 端点，标准模板也未提供 SellerSprite Gateway。因此默认状态为 `blocked` 或 `mock-only`，不得生成伪造的正式调用代码。

禁止：

- 读取本机或个人 Cookie。
- 在站点进程中执行 opscli CLI。
- 运行时临时连接 MCP。
- 固化 session、JWT 或个人账号。
- 由前端直连 SellerSprite。

不复用旧项目或私有 SellerSprite 适配器；保持阻塞并说明平台需要在标准模板或正式 REST API 中补齐运行时入口。

## 5. 混合来源

OPS + Keepa 的默认组合模式为 `hybrid`：

- OPS 按当前 viewer 实时查询。
- Keepa 读取允许共享的 SQLite 快照或由后端实时调用。
- service 按已验证的站点、ASIN、时间和币种规则组合。
- repository 不接收未隔离的 OPS viewer 数据。

任一来源失败时，是否允许部分结果必须在 data-spec 和 API schema 中明确，不能静默返回旧数据或伪装完整结果。
