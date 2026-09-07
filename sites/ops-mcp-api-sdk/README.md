# OPS MCP API JavaScript SDK

该 SDK 供 OPS 系统同源页面调用 opscli MCP 提供的 REST API。业务代码无需填写或读取 MCP API Key，SDK 会复用 OPS 登录信息完成换取，并自动写入业务请求的 `Authorization` Header。

## 推荐用法

```js
import {
  configureOpsMcpApi,
  opsMcpApi,
} from "@aukeys/ops-mcp-api-sdk";

// 只在应用入口初始化一次。
configureOpsMcpApi({
  apiBaseUrl: import.meta.env.DEV
    ? "http://127.0.0.1:8765"
    : undefined,
});

const result = await opsMcpApi.requestJson("/api/v1/keepa/scenarios");
```

`opsMcpApi` 的对象引用不会因配置变化而改变。其他业务模块只需导入并使用 `opsMcpApi`，不需要区分或替换 `localClient`、`productionClient`。

默认实例执行以下流程：

1. 请求发生时读取 `localStorage.OPERATION_TOKEN`。
2. 使用 `Authorization: Bearer <OPERATION_TOKEN>` 和同源 Cookie 请求 `/api/v1/mcp-api-keys/config`。
3. 从 `data.api` 或兼容的 `data.http.mcpServers["BI运营系统"].url` 中取得 MCP API 地址与 Key。
4. Key 仅缓存在页面内存，业务请求自动使用 `Authorization: Bearer <MCP_API_KEY>`。

## 统一配置

```js
import { configureOpsMcpApi } from "@aukeys/ops-mcp-api-sdk";

configureOpsMcpApi({
  timeoutMs: 20_000,
  allowedConfigOrigins: [location.origin],
  allowedApiOrigins: ["https://ops.mcp.xenkee.com"],
});
```

本地调试时直接覆盖 API 地址：

```js
configureOpsMcpApi({
  apiBaseUrl: "http://127.0.0.1:8765",
});
```

HTTPS OPS 页面可能被浏览器禁止访问 HTTP localhost。此时应使用 HTTPS 本地地址，或通过 OPS 同源开发代理转发：

```js
configureOpsMcpApi({
  apiBaseUrl: "https://127.0.0.1:8765",
});
```

其他环境同样通过 `apiBaseUrl` 覆盖：

```js
configureOpsMcpApi({
  apiBaseUrl: "https://mcp-api.example.com",
  configEndpoint: "/api/v1/mcp-api-keys/config",
  operationTokenProvider: () => localStorage.getItem("OPERATION_TOKEN"),
});
```

地址选择规则只有一条：未传 `apiBaseUrl` 时使用配置接口返回的地址；传入时使用显式地址。环境判断由站点构建配置负责，SDK 不再维护重复的环境枚举。

## 独立实例

只有测试、多账号或同一页面同时访问多个 MCP 环境时，才需要创建独立实例：

```js
import { createOpsMcpApiClient } from "@aukeys/ops-mcp-api-sdk";

const isolatedClient = createOpsMcpApiClient({
  apiBaseUrl: "https://another-mcp.example.com",
});
```

## 客户端接口

- `request(path, init?)`：返回原始 `Response`。
- `requestJson(path, init?)`：返回解析后的 JSON。
- `warmup()`：提前完成凭证换取。
- `invalidateCredentials()`：清除当前实例的内存凭证。

SDK 只接受以 `/` 开头的相对业务路径，避免调用方意外把 API Key 发送到其他来源。收到明确的 `401 {"reason":"invalid_api_key"}` 时会重新换取 Key 并重试一次；不会为普通网络错误、5xx、403 或 `authentication_required` 自动重试。

浏览器环境下，配置换取地址默认必须与当前页面同源。如确需跨来源换取，必须通过 `allowedConfigOrigins` 显式声明可信来源；该配置只放行 OPS Token Header，不会把同源 Cookie 改为跨站发送。

## 错误处理

```js
import { OpsMcpApiError } from "@aukeys/ops-mcp-api-sdk";

try {
  await opsMcpApi.requestJson("/api/v1/keepa/scenarios");
} catch (error) {
  if (error instanceof OpsMcpApiError && error.code === "OPS_LOGIN_REQUIRED") {
    // 跳转到 OPS 登录流程。
  }
}
```

主要错误码：`OPS_LOGIN_REQUIRED`、`CONFIG_FETCH_FAILED`、`CONFIG_INVALID`、`MCP_API_KEY_MISSING`、`TARGET_ORIGIN_NOT_ALLOWED`、`REQUEST_TIMEOUT`、`REQUEST_FAILED`、`API_KEY_REJECTED`、`PERMISSION_DENIED`、`BROWSER_ENV_REQUIRED`、`RESPONSE_INVALID_JSON`。

## 安全约束

- MCP API Key 不导出、不写入 localStorage、sessionStorage、日志或事件。
- SDK 可减少业务代码误用 Key，但无法防止同源恶意脚本或 XSS 读取页面内存和网络请求。
- OPS 页面必须与存放 `OPERATION_TOKEN` 的页面完全同源，即协议、主机和端口全部一致；不同子域名不能共享 localStorage。
