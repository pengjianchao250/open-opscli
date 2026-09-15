# opscli app 自动配置 MCP REST 环境变量需求定稿

> 日期：2026-09-13  
> 状态：已实施  
> 适用范围：`opscli app init` 以及 `opscli app push` 复用的仓库准备链路

## 1. 背景

AppHub 标准数据应用后端统一读取 `OPSCLI_MCP_REST_API_BASE_URL`，并通过该纯 origin 调用 opscli-mcp 的 `/api/v1/*` REST 接口。当前应用创建和 Git 初始化不会自动配置该变量，需要用户在 AppHub 配置页面手工补充，容易导致 Viewer、Keepa 或 SellerSprite 线上请求失败。

AppHub 已提供以下接口：

```text
GET /api/v1/apps/{app_id}/env
PUT /api/v1/apps/{app_id}/env
```

浏览器保存环境变量时，PUT 请求体包含完整的自定义 `env` 对象，因此客户端必须按全量保存语义处理，不能只提交新增键。

## 2. 目标

- 仓库初始化流程自动检查应用是否配置 `OPSCLI_MCP_REST_API_BASE_URL`。
- 缺失或为空时，根据当前 AppHub 控制面环境写入正确地址。
- 已存在非空值时不覆盖用户配置。
- 写入时保留所有已有自定义环境变量，不回写只读 `platform_env`。
- `init` 和 `push` 重复执行保持幂等。

## 3. 环境映射

| AppHub 控制面 origin | `OPSCLI_MCP_REST_API_BASE_URL` |
|---|---|
| `https://apphub.qa.aukeyit.com` | `https://mcp.ops.aukeyit.com` |
| `https://apphub.xenkee.com` | `https://ops.mcp.xenkee.com` |

映射只接受去除末尾 `/` 并转为小写后的精确 origin。不得通过域名是否包含 `qa`、`test` 或其他字符串推断环境。未知 AppHub 地址返回 `APPHUB-ENVIRONMENT-UNSUPPORTED`，不得默认写入预发布或生产地址。

生产 AppHub 正式域名为 `https://apphub.xenkee.com`；域名变化时必须同步更新该映射及测试。

## 4. 执行流程

共享仓库准备链路按以下顺序执行：

1. 读取或恢复本地应用绑定。
2. 调用应用详情和 Git 配置接口，校验大小写敏感的五位 `app_id`。
3. 根据 AppHub origin 解析期望的 MCP REST 地址。
4. GET 应用环境变量并严格校验 `env` 为字符串键值对象。
5. 目标变量已存在且非空时保留原值，不执行 PUT。
6. 目标变量缺失或为空时，将完整现有 `env` 与目标变量合并后 PUT。
7. 校验 PUT 返回的 `env`；响应未返回 `env` 时再次 GET 验证。
8. 确认目标变量和已有键均被保留后，继续 Git 凭据和本地仓库初始化。

环境变量配置放在本地 Git 修改之前，避免远端配置失败后留下部分初始化状态。`push` 复用同一准备链路，因此也能为历史项目补齐配置。

## 5. 已存在值处理

- 与当前环境期望值相同：返回 `runtime_env_status=existing`。
- 与当前环境期望值不同：返回 `runtime_env_status=mismatch_preserved`，保留用户值，不自动覆盖。
- 缺失或空值并成功写入：返回 `runtime_env_status=configured` 和 `runtime_env_updated=true`。

环境变量需要在应用下次发布或重启后生效；本功能不主动发布、重启或修改当前运行实例。

## 6. 鉴权与安全

- 复用 `AuthClient.get_token("ops")` 获取 Bearer JWT。
- 不发送浏览器 Cookie、CSRF Token、Origin、Referer 或 `Sec-Fetch-*` 请求头。
- 不记录 JWT、Cookie 或完整 Authorization Header。
- `platform_env` 为平台只读变量，只参与响应展示，不进入 PUT 请求体。

## 7. 并发限制

GET 后全量 PUT 存在并发覆盖窗口。当前客户端通过紧邻的读改写和写后验证降低风险，但不能提供服务端原子性。AppHub 后续宜提供单键 PATCH、ETag/If-Match 或环境变量 revision。

## 8. 验收标准

1. GET、PUT 路径精确使用大小写敏感的 `app_id`。
2. PUT 请求发送完整合并后的 `env`，保留已有键且不包含 `platform_env`。
3. 预发布和生产环境分别写入对应的 MCP REST 纯 origin。
4. 已存在非空配置不被覆盖，重复初始化不重复 PUT。
5. 未知 AppHub 环境、无效 env 响应和写后校验失败均明确停止。
6. 环境变量配置失败时不执行本地 Git 初始化或源码推送。
7. 不修改 Binding Schema、Git 凭据格式、应用模板或发布流程。
