# Rufus MCP Sensitive Tools Proposal

## 背景

`opscli amazon-rufus` CLI 已支持 `platform-cookie get/save` 与 `curl save`，但 Rufus MCP 当前只暴露默认获取、登录态检查、登录采集、登出和远程授权偏好工具。用户已确认 MCP 也需要支持平台 Cookie content 读写与 Copy-as-cURL 保存，用于 Rufus 排障和初始化。

## 目标

- 新增 `amazon_rufus_platform_cookie_save` MCP Tool，对齐 CLI `opscli amazon-rufus platform-cookie save`。
- 新增 `amazon_rufus_platform_cookie_get` MCP Tool，对齐 CLI `opscli amazon-rufus platform-cookie get`。
- 新增 `amazon_rufus_curl_save` MCP Tool，对齐 CLI `opscli amazon-rufus curl save`。
- 所有新增工具默认返回 MCP-safe 摘要，避免 content、raw cURL、cookie、headers、payload、storage_state 进入普通响应。
- 错误结构中的 `call_params` 只记录布尔值和长度，不记录原始敏感输入。

## 非目标

- 不新增 `cookie save/status`、`save-state`、`init` 或 CDP 直接参数。
- 不修改 `amazon_rufus_get` 默认获取链路。
- 不修改 CLI 行为。
- 不处理 `RemoteConsentStore` 多国家偏好存储结构。

## 设计

### MCP Tools

```text
amazon_rufus_platform_cookie_save(platform, country, content)
amazon_rufus_platform_cookie_get(platform, country, include_content=false)
amazon_rufus_curl_save(asin, country, raw_curl)
```

`platform_cookie_get` 默认不返回完整 content，只返回状态、消息、长度和是否存在内容。显式 `include_content=true` 时允许返回 content，用于人工排障；调用方仍不得写入报告或普通最终回复。

### Manager façade

新增方法放在 `RufusMcpManager`：

- `platform_cookie_save(...)`
- `platform_cookie_get(...)`
- `curl_save(...)`

这些方法复用现有 `RufusManager.save_platform_cookie()`、`RufusManager.get_platform_cookie()` 和 `RufusManager.save_curl()`，再通过 allowlist 构造响应。

### 安全规则

- save 工具不回显 `content` 或 `raw_curl`。
- get 工具默认不回显 `content`。
- `_rufus_error()` 的 call params 不包含敏感原文。
- 不暴露 `headers`、`payload_template`、`storage_state` 等拆分敏感参数。

## 验收

- MCP tool list 包含 3 个新增工具。
- `platform_cookie_save` 与 `curl_save` 成功响应不包含原文。
- `platform_cookie_get(include_content=false)` 不返回 content。
- `platform_cookie_get(include_content=true)` 可返回 content。
- 新增工具失败时 `call_params` 不包含 content/raw_curl 原文。
- Rufus MCP 相关测试通过。
