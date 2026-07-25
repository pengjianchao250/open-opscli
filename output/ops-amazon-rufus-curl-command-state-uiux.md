# ops-amazon-rufus cURL 命令态 UIUX

## 范围

本需求不涉及前端页面、图标库、字体系统、设计 token 或组件生态变更。UIUX 关注 CLI/MCP 文案、可见输出和敏感信息边界。

## 交互原则

1. Agent 用户不需要理解或复制 `curl` 字段。
2. MCP 常规流程仍只暴露 `amazon_rufus_login_status`、`amazon_rufus_watch_login`、`amazon_rufus_get` 等脱敏工具。
3. `curl` 命令仅在服务层和平台 Cookie content 内部流转，不展示给 Agent 对话、报告或 MCP 输出。
4. 旧结构不兼容时，提示用户重新执行登录采集，而不是展示旧 content 或要求用户手工修 JSON。

## CLI 可见输出

`opscli amazon-rufus curl save ... --pretty` 成功输出继续保持摘要：

```json
{
  "success": true,
  "command": "amazon-rufus curl save",
  "data": {
    "country": "US",
    "asin": "B0TEST1234",
    "saved": true,
    "cookie_count": 3,
    "header_count": 3,
    "has_curl": true,
    "has_payload_template": true
  },
  "error": null
}
```

不输出：

1. `curl`
2. Cookie 值
3. headers
4. payload template
5. `storage_state`
6. seed request
7. 平台 Cookie content

## MCP 可见输出

`amazon_rufus_login_status(country)` 仍只返回：

```json
{
  "country": "US",
  "status": "ready",
  "has_login_state": true,
  "can_get_backend": true,
  "session_cookie_count": 3,
  "has_streaming_request": true
}
```

当旧结构存在但新 `curl` 缺失时：

```json
{
  "country": "US",
  "status": "invalid",
  "has_login_state": false,
  "can_get_backend": false,
  "session_cookie_count": 0,
  "has_streaming_request": false
}
```

建议 Agent 提示：

```text
当前 Rufus 登录态需要重新采集。请确认允许后，我会调用 amazon_rufus_watch_login 重新打开登录窗口并保存新的 cURL 命令态。
```

## 文档提示

`ops-amazon-rufus` README 和 reference 应补充：

1. 内部保存状态已切换为浏览器 Copy-as-cURL 风格命令态。
2. 旧 `curl_data` 或旧 `storage_state` content 不再作为可用后端凭证。
3. 用户无需手工查看或输出该 cURL 命令。
4. 重新登录采集是升级后的推荐恢复方式。

## 安全边界

所有可见输出都必须继续禁止以下字段：

```text
OPS JWT
session ID
Amazon Cookie header
平台 Cookie content
headers
payload
storage_state
curl
curl_data
seed request
upload payload
```

## 验收

1. CLI 和 MCP 输出中不存在 `curl ` 命令。
2. Agent 文案不要求用户粘贴 cookie、headers、payload 或平台 Cookie content。
3. 旧结构失效时的用户路径只有重新采集或重新保存 Copy-as-cURL。
4. 报告文件仍只包含 Rufus 答案和必要的业务上下文。
