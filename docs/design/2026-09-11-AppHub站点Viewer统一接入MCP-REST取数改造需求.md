# AppHub 站点 Viewer 统一接入 MCP REST 取数改造需求

> 日期：2026-09-11  
> 状态：待实施  
> 适用范围：`open-opscli` 中 AppHub 建站相关 Skill、合同和测试，以及当前验证站点 `test-zzz-121`  
> 非目标：本轮不修改共享模板仓库，不修改公共 Query CLI、MCP Tool、Keepa、SellerSprite 核心实现
>
> 2026-09-13 补充：后续需求已要求 `opscli app` 在仓库准备期间自动配置 `OPSCLI_MCP_REST_API_BASE_URL`。本文件第 4.1 节“不改变 create/init/push 语义”的约束已由 `2026-09-13-opscli-app自动配置MCP-REST环境变量需求定稿.md` 取代。

## 1. 背景

当前 AppHub 标准站点的 `ViewerQueryGateway` 将 `OPSCLI_OPS_URL` 与以下路径拼接：

```text
/v1/data-metrics/viewer/query-metadata
/v1/data-metrics/viewer/cli-query/simple
```

QA 环境没有提供上述 Viewer 专用端点，因此线上 Viewer 请求返回 404。本地请求能够成功，是因为本地开启了 `LOCAL_AUTH_FALLBACK_ENABLED`，实际使用本机 opscli 登录态和 `LocalQueryGateway`，没有覆盖线上 Viewer 链路。

已确认 opscli-mcp 对外提供正式 AppHub REST 接口：

```text
GET  /api/v1/query/metadata
POST /api/v1/query/simple
```

`POST /api/v1/query/simple` 在服务内部通过 `QueryManager` 转发到原始 OPS 地址：

```text
POST /api/v1/data-metrics/cli-query/simple
```

AppHub 业务站点应依赖 opscli-mcp 的稳定 REST 合同，而不是自行维护原始 OPS 路径、Bearer 转换和业务错误解析。

## 2. 目标链路

```text
浏览器
→ 当前站点相对路径 /api/*
→ 当前站点 FastAPI
→ OPSCLI_MCP_REST_API_BASE_URL + /api/v1/query/simple
→ opscli-mcp QueryManager
→ OPSCLI_OPS_URL + /v1/data-metrics/cli-query/simple
```

Viewer 模式由 AppHub 网关注入 `X-Ops-Token`、`X-User-Email` 和可选的 `X-User-Id`、`X-User-Name`。当前站点只从已校验的请求级 `QueryCredentials` 重建这些 Header，不转发 Cookie、浏览器 Authorization 或其他请求头。

## 3. 环境变量合同

删除旧名称：

```env
OPSCLI_THIRD_PARTY_DATA_API_BASE_URL
```

统一使用：

```env
OPSCLI_MCP_REST_API_BASE_URL=https://mcp.ops.aukeyit.com
```

该变量是 opscli-mcp 服务上 `/api/v1/*` REST API 的纯 origin，供 OPS Query、Keepa 和 SellerSprite共用。不得包含 `/api`、接口路径、查询参数、片段、用户名、密码或末尾 `/`，不得用于 `/mcp`、`/sse`，也不得使用 MCP API Key。

保留 `OPSCLI_OPS_URL` 和 `OPSCLI_OPS_SYSTEM_URL` 原有职责。本次采用原子切换：代码、Skill 和部署环境同时改用新变量，不保留旧变量兼容回退。

## 4. open-opscli 修改范围

### 4.1 删除孤立实现

删除未被任何命令、服务或测试引用，且依赖不存在异常类型的 `opscli/app/transport/third_party_contract.py`，不改变 `opscli app create/init/push` 语义。

### 4.2 更新建站 Skills

- Viewer 模式统一调用 opscli-mcp REST Query API。
- OPS 查询固定使用 `/api/v1/query/simple`，Metadata 固定使用 `/api/v1/query/metadata`。
- OPS、Keepa、SellerSprite 共用 `OPSCLI_MCP_REST_API_BASE_URL`。
- 禁止生成 `/v1/data-metrics/viewer/*`。
- 明确 REST `/api/v1/*` 与 MCP `/mcp`、`/sse` 的协议和鉴权边界。
- 更新版本号、Reference、静态合同测试和 eval 文案。

### 4.3 opscli-mcp 服务边界

现有 `/api/v1/query/simple`、`/api/v1/query/metadata` 及其内部 OPS 转发逻辑不改。只补充或加强 AppHub Viewer 合同测试时，不修改公共 Query CLI、MCP Tool 或 QueryManager 行为。

## 5. 当前站点修改范围

- `ViewerQueryGateway` 改用 `settings.opscli_mcp_rest_api_base_url`。
- Metadata 调用 `/api/v1/query/metadata`。
- Simple Query 调用 `/api/v1/query/simple`，分别使用 `run=false/true`。
- 按 opscli REST `QuerySimpleRequest` 构造外层请求体。
- 请求只发送 Viewer Token和可信用户 Header。
- 成功时返回 `data`，保持现有 Gateway 返回结构。
- HTTP 200、`success=false` 时保留查询内层失败；HTTP 非 2xx 或非查询内层失败按 `error.code` 映射为站点错误。
- Keepa 和 SellerSprite 改读新 Base URL，endpoint、Header 白名单、用户隔离和存储逻辑不变。
- 更新 `.env.example`、本地 `.env`、`backend/CLAUDE.md`、`docs/apphub-contract.md`、变更记录和测试。
- 不修改前端、SQLite、Alembic、`app.yaml` 或站点公开 API。

## 6. 本轮明确不修改

共享模板目录 `E:/wwwroot/localProjects/codex-custom-sites-all/template` 本轮不修改。当前站点在预发布完成真实 Viewer 验证后，再单独创建模板同步任务。

## 7. 验收标准

1. 当前站点本地模式继续正常。
2. Viewer 请求地址为 `OPSCLI_MCP_REST_API_BASE_URL + /api/v1/query/simple`。
3. Viewer 请求只包含允许的 `X-Ops-Token` 与 `X-User-*`，不包含 Cookie。
4. Metadata 使用 `/api/v1/query/metadata`。
5. HTTP 200、`success=false` 不被误判为成功数据。
6. Keepa 和 SellerSprite 仅发生环境变量重命名，原有测试继续通过。
7. 两个建站 Skill 不再包含旧变量或 `/data-metrics/viewer/*` 合同。
8. 当前站点后端测试、前端测试和前端生产构建通过。
9. 本轮没有修改共享模板或公共 Query/MCP/第三方核心实现。
