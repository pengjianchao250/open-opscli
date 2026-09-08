# OPS MCP REST API JavaScript SDK

该 SDK 供 AppHub 页面调用 opscli 提供的 REST API。REST 与 MCP 传输鉴权已经分离：浏览器请求直接复用 AppHub 登录态，`/mcp`、`/sse` 继续由 MCP 客户端使用 MCP API Key。

## 用法

```js
import { configureOpsMcpApi, opsMcpApi } from "@aukeys/ops-mcp-api-sdk";

configureOpsMcpApi({
  apiBaseUrl: import.meta.env.DEV ? "http://127.0.0.1:8765" : undefined,
});

const result = await opsMcpApi.requestJson("/api/v1/keepa/scenarios");
```

默认情况下 SDK 每次请求会：

1. 从 `localStorage.OPERATION_TOKEN` 读取 AppHub/OPS Token，并发送 `X-Ops-Token`。
2. 从 `localStorage.OPERATION_USER_TOKEN` 或 `OPS_SESSION_ID` 读取 Session，并发送 `X-Session-Id`。
3. 从 `OPERATION_USER_INFO`、`USER_INFO`、`userInfo` 或 JWT payload 解析用户，发送 `X-User-*`。
4. 使用 `credentials: "include"`，让浏览器同时携带 `polarisUserToken` Cookie。

不再调用 `/api/v1/mcp-api-keys/config`，也不会在浏览器中获取、缓存或发送 MCP API Key。
SDK 会移除调用方遗留的 `Authorization`、`X-MCP-API-Key`、`X-MCP-Proxy-Auth`，并拒绝带 `api_key` 查询参数的 REST 路径。

## 自定义认证来源

```js
configureOpsMcpApi({
  apiBaseUrl: "https://mcp-api.example.com",
  operationTokenProvider: () => localStorage.getItem("OPERATION_TOKEN"),
  sessionIdProvider: () => localStorage.getItem("OPERATION_USER_TOKEN"),
  currentUserProvider: () => ({
    email: "user@aukeys.com",
    id: "user-id",
    name: "User Name",
  }),
  allowedApiOrigins: ["https://mcp-api.example.com"],
});
```

只要存在 Session，服务端会调用 `AuthClient.get_me()` 校验并解析用户；没有 Session 时，viewer 模式要求 Token 和用户身份头同时存在。本地开发回退由服务端 `LOCAL_AUTH_FALLBACK_ENABLED=true` 控制，不由 SDK 静默开启。

## 接口

- `request(path, init?)`：返回原始 `Response`。
- `requestJson(path, init?)`：返回解析后的 JSON。
- `warmup()`：本地校验 API 地址和登录态，不发网络请求。
- `invalidateCredentials()`：保留兼容接口；SDK 不缓存凭证。

SDK 只接受以 `/` 开头的相对业务路径。401 `authentication_required` 映射为 `OPS_LOGIN_REQUIRED`，403 映射为 `PERMISSION_DENIED`，不会自动刷新或重试认证失败请求。

主要错误码：`OPS_LOGIN_REQUIRED`、`TARGET_ORIGIN_NOT_ALLOWED`、`REQUEST_TIMEOUT`、`REQUEST_FAILED`、`PERMISSION_DENIED`、`BROWSER_ENV_REQUIRED`、`RESPONSE_INVALID_JSON`。
