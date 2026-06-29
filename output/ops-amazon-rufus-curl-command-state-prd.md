# ops-amazon-rufus cURL 命令态 PRD

## 目标

将 Rufus 登录态中用于后端/headless 请求的 cURL 参数保存为浏览器 Copy-as-cURL 风格命令字符串。远端 `/v1/platform-cookies` 的 `content` 必须直接保存该 streaming cURL 命令态；消费端不再兼容旧 `curl_data` 对象和旧字段 fallback。

## 用户价值

1. 保存内容更贴近浏览器复制出来的 cURL，排查时能直接识别请求形态。
2. 平台 Cookie content 中不再维护两套等价字段，状态结构更简单。
3. 旧结构兼容代码删除后，Rufus 后端凭证来源更单一，减少“状态看似可用但请求材料不一致”的问题。

## 功能需求

### FR1 远端 content 直接保存 canonical cURL

当 `amazon_rufus_watch_login` 捕获到 `/rufus/cl/streaming` 请求，或 `opscli amazon-rufus curl save` 保存 Copy-as-cURL 时，远端平台 Cookie `content` 必须直接等于 cURL 命令字符串：

```text
curl 'https://www.amazon.com/rufus/cl/streaming?tabId=tab-1' -H 'content-type: application/json' -H 'cookie: session-id=abc' --data-raw '{"queryContext":{"query":""},"pageContext":{"targetUrl":"https://www.amazon.com/dp/B0TEST1234","targetPageMetadata":[{"type":"ASIN","value":"B0TEST1234"}]}}'
```

验收：

1. 远端 `content` 为字符串，且 `strip()` 后以 `curl ` 开头。
2. `curl` 命令不包含 shell 续行反斜杠。
3. `curl` 命令使用 `-H 'cookie: ...'` 表达 Cookie，贴近浏览器 Copy-as-cURL。
4. 远端 `content` 不再是包含 `curl` 字段的 JSON 包装；本地 fallback 文件可保留 JSON record。
5. 不再保存 `curl_data` 字段。

### FR2 消费端只解析 `curl`

`RufusBackendSecretProvider.load(country)` 必须只从 cURL 命令获取 URL、headers、cookies、payload template。远端裸 cURL 由 `RufusBrowserStateStore._load_remote()` 包装为内部 `record["curl"]` 结构；历史 JSON record 只有包含新 `curl` 字段时才可继续读取。

验收：

1. cURL 缺失、为空或无法解析时，返回 `RUFUS_SECRET_NOT_READY`。
2. 旧 `curl_data` 对象存在但 `curl` 缺失时，不再成功加载。
3. 旧顶层 `streaming_url`、`headers`、`payload_template` 和 `storage_state` 不再作为后端请求凭证 fallback。

### FR3 登录态状态和后端可用性一致

`RufusManager.login_status(country)` 的 `can_get_backend` 必须基于 `curl` 是否可解析为有效 Rufus streaming 请求。

验收：

1. `curl` 可解析且包含 Cookie 时，`can_get_backend=true`。
2. 只有旧 `storage_state` 或旧 `curl_data` 时，`can_get_backend=false` 或 `status=invalid`。
3. 返回值仍只包含脱敏摘要，不返回 `curl`、cookie、headers、payload 或 seed request。

### FR4 CLI 和 MCP 输出继续脱敏

所有 CLI/MCP 成功或失败输出不得包含：

1. `curl`
2. Cookie 值
3. headers
4. payload template
5. `storage_state`
6. seed request 原文
7. 平台 Cookie content

### FR5 旧凭证结构不兼容

本次变更明确不做旧状态迁移。只有旧 `curl_data` 或仅 `storage_state` 的 content 用户需要重新登录采集或重新保存 Copy-as-cURL；历史 JSON record 如已包含新 `curl` 字段，可作为过渡格式读取。

验收：

1. 测试覆盖旧 `curl_data` 不再被 `RufusBackendSecretProvider` 接受。
2. 文档提示需要重新采集登录态。

## 非目标

1. 不新增 MCP 入参，不允许 Agent 直接传 cookie、headers、payload 或 raw cURL。
2. 不在 skill 模板目录新增 Rufus 获取脚本。
3. 不改变默认题库、报告格式和问题来源选择。
4. 不实现旧状态自动迁移。

## 成功标准

1. 新保存 content 直接使用 `curl` 命令字符串作为唯一后端请求材料。
2. `amazon_rufus_get` 能通过裸 cURL content 完成 Rufus 请求。
3. 旧 `curl_data` / `storage_state` 凭证测试明确失败，证明旧凭证兼容分支已移除。
4. `tests/amazon_rufus/test_core.py`、`tests/amazon_rufus/test_mcp_manager.py`、`tests/mcp/test_amazon_rufus_tools.py` 相关测试通过。
5. CLI/MCP 输出不泄露敏感字段。
