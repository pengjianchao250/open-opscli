# opscli 场景 API 产品化规划

## 目标

在保留 MCP 作为 Agent 原生入口的前提下，为网站、内部系统和自动化任务提供稳定的 HTTP API。REST 接口按业务场景设计，复用现有查询规划器、认证、凭证隔离、权限、配额和遥测，不把 MCP Tool 名称直接机械映射成 REST 路径。

## 当前实现（Phase 1）

- `GET /health/live`：进程存活检查。
- `POST /api/v1/query/flow`：自然语言取数场景入口。
- `GET /api/v1/keepa/scenarios`：列出 Keepa 可用场景。
- `POST /api/v1/keepa/run`：执行 Keepa 场景并返回统一任务结果。
- `GET /api/v1/seller-sprite/scenarios`：通过 Collector 列出卖家精灵场景。
- `GET /api/v1/seller-sprite/quota`：读取当前用户卖家精灵额度。
- `POST /api/v1/seller-sprite/jobs`：提交普通异步采集任务并返回 `202`。
- `GET /api/v1/seller-sprite/jobs/{job_id}`：读取单个普通任务状态。
- `GET /api/v1/seller-sprite/jobs/{job_id}/result`：直接读取普通任务的内联 JSON 结果。
- `POST /api/v1/seller-sprite/jobs/status`：批量读取普通任务状态。
- `GET /api/v1/seller-sprite/jobs/{job_id}/export`：JSON 任务直接返回内联结果，
  `xls/xlsx` 任务返回文件下载信息。
- `POST /api/v1/seller-sprite/listing-analysis/jobs`：提交 Listing Analysis 任务。
- `GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}`：读取 Listing Analysis 状态。
- `GET /api/v1/seller-sprite/listing-analysis/jobs/{job_id}/result`：读取 Listing Analysis 结果。
- MCP `/mcp`、`/sse`、`/messages` 与 REST 共用同一个 ASGI 进程和生命周期。
- 所有 HTTP 路由继续位于 `ApiKeyAuthMiddleware` 之后。
- REST 请求只接受场景合同字段，不接受 `session_id`、`jwt` 等内部认证参数。
- 查询执行通过线程池调用同步 `run_flow`，避免阻塞 FastAPI 事件循环。
- Keepa REST 执行复用 `keepa_run` 的 quota/telemetry 包装，不直接绕过 MCP 治理。
- Keepa REST 响应保留完整格式化 `data`，带有 `request_source=api` 和
  `response_mode=formatted_data`；该路径跳过导出文件上传，不要求调用方依赖 `export.url`。
- Keepa MCP/CLI 继续使用导出上传和 `data_preview` 摘要，避免完整历史数据进入 Agent 上下文。
- SellerSprite REST 只部署在通用 MCP FastAPI 网关，通过当前用户 API Key 调用
  Collector MCP；通用进程不启动 SellerSprite Scheduler，Collector 也不新增公开 REST 入口。
- SellerSprite REST 保持异步 Job 合同；`export_format=json` 的成功任务通过 API
  内联返回业务结果，不暴露或依赖下载 URL，`xls/xlsx` 才保留文件下载合同。
- SellerSprite 的 API 结果转换只位于 FastAPI 适配层；MCP Tool、Collector Scheduler、
  账号池、队列、权限、额度、任务所有权和现有 MCP 返回合同保持不变。

## 推荐架构

```text
网站 / 自动化客户端
        |
        v
  /api/v1/{scenario}
        |
        v
共享业务内核（规划器 / Service / QueryManager）
        ^
        |
  MCP Tool（Agent 原生协议）
```

REST 和 MCP 是两个适配器，共享业务内核的输入输出语义，但各自保留适合调用方的合同。这样可以让网站获得稳定版本化接口，也避免 MCP 会话、初始化和 JSON-RPC 细节泄漏到普通 HTTP 客户端。

## 分阶段路线

### Phase 1：共存与验证

- 完成 FastAPI 外壳、API Key 保护、健康检查和 `query_flow`。
- 验证 `/mcp`、`/sse` 生命周期、认证和现有 MCP 回归不受影响。
- 通过 OpenAPI 生成接口说明，记录响应合同 `{success, data, error}`。

### Phase 2：场景化扩展

- 从高频网站流程提炼独立场景，例如商品诊断、广告诊断、报表导出。
- 每个场景拥有独立的 `/api/v1/...` 请求模型、权限声明、配额维度和错误码。
- 共享同步业务通过线程池或任务队列执行；长任务返回任务 ID，并提供状态查询。

### Phase 3：产品化治理

- API Key 与用户、租户、来源站点绑定，支持轮换、过期和最小权限。
- 增加请求幂等键、速率限制、审计日志、指标和链路追踪。
- 对外发布 `/api/v1` 版本策略、错误码、SLO 和兼容性测试。
- 将 API 适配器部署在独立网关时，保留到共享业务内核的显式调用接口。

## 不采用的方案

- 不把所有 MCP Tool 自动生成成 REST：Tool 参数、MCP 会话和 Agent 交互语义不等于面向网站的产品合同。
- 不让浏览器提交 `session_id` 或 `jwt`：认证与凭证隔离由现有中间件和请求上下文负责。
- 不让 REST 直接绕过 MCP 的配额、权限和遥测切面：共享业务调用必须继续经过现有治理机制。

## 验收标准

- API 和 MCP 同时启动，任一协议的生命周期退出不会泄漏另一协议资源。
- 未携带或携带无效 API Key 时，REST 与 MCP 均返回未授权；远程校验故障返回 503。
- 同一用户通过 REST 和 MCP 查询时，使用相同的账号授权和凭证隔离目录。
- 场景 API 的同步/异步边界、错误码、配额和审计行为均有自动化测试。
