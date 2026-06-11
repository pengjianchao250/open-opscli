# Rufus Skill MCP 与 CLI 差异架构说明

## 当前调用链

### MCP 主链路

```text
Agent
  -> amazon_rufus_get(...)
  -> RufusMcpManager.for_current_request(credential_dir)
  -> RufusMcpManager.get(RufusGetRequest)
  -> RufusManager.get_backend(include_upload_payload=False)
  -> RufusBackendSecretProvider.load()
  -> HeadlessRufusCaptureService / HeadlessRufusClient
  -> AnswerReportWriter.write()
  -> MCP-safe 摘要响应
```

MCP 的关键架构职责：

- 绑定当前 MCP 请求凭证目录。
- 限制 Agent 可传入字段。
- 不返回 cookie、headers、storage_state、seed_request、upload_payload、curl。
- 只返回本次 `report_path` 和摘要字段。

### 目标新增 MCP 调试链路

用户已确认 MCP 需要支持 `platform-cookie get/save` 与 `curl save`。新增链路应复用现有 `RufusManager`，但通过 `RufusMcpManager` 做参数收敛和返回脱敏：

```text
Agent
  -> amazon_rufus_platform_cookie_save(platform, country, content)
  -> RufusMcpManager.platform_cookie_save(...)
  -> RufusManager.save_platform_cookie(...)
  -> MCP-safe 保存摘要
```

```text
Agent
  -> amazon_rufus_platform_cookie_get(platform, country, include_content=false)
  -> RufusMcpManager.platform_cookie_get(...)
  -> RufusManager.get_platform_cookie(...)
  -> 默认 MCP-safe 状态摘要
```

```text
Agent
  -> amazon_rufus_curl_save(asin, country, raw_curl)
  -> RufusMcpManager.curl_save(...)
  -> RufusManager.save_curl(...)
  -> MCP-safe 保存摘要
```

这三个工具属于排障/初始化工具，不进入普通 `amazon_rufus_get` 主路径，也不改变 Skill 的默认获取流程。

### CLI 获取链路

```text
opscli amazon-rufus get-backend ...
  -> RufusManager()
  -> RufusManager.get_backend(include_upload_payload=CLI option)
  -> RufusBackendSecretProvider.load()
  -> HeadlessRufusCaptureService / HeadlessRufusClient
  -> AnswerReportWriter.write()
  -> stdout 输出报告路径文本
```

CLI 的关键架构职责：

- 面向本机用户和运维排障。
- 使用默认 `CONFIG_DIR` 与默认 AuthClient。
- 保留更多本地调试命令。
- 允许显式 `--submit-upload`。

## 功能矩阵

| 能力 | MCP | CLI | 说明 |
|---|---:|---:|---|
| 后端/headless 获取 Rufus | 支持 | 支持 | 共享 `get_backend` |
| 单题问题 | 支持 | 支持 | MCP `question`；CLI 单次 `-q` |
| 多题问题 | 支持 | 支持 | MCP `questions`；CLI 重复 `-q` |
| 默认题库 | 支持 | 支持 | 都可传 `skills_dir` |
| 写 Markdown 报告 | 支持 | 支持 | 都用 `AnswerReportWriter` |
| 登录态摘要 | 支持 | 支持 | MCP 返回字段更少 |
| 登录采集 | 支持 | 支持 | MCP 默认 `close_browser=True`，CLI 默认 False |
| logout | 支持 | 支持 | MCP 不暴露 `cdp_url` |
| remote consent | 支持 | 支持 | source 不同 |
| init 打开站点 | 不支持 | 支持 | CLI 本地 CDP 辅助 |
| save-state | 不支持 | 支持 | CLI 调试/迁移面 |
| platform-cookie get/save | 目标需支持 | 支持 | 受控敏感排障/初始化入口 |
| cookie save/status | 不支持 | 支持 | 手工状态入口 |
| curl save | 目标需支持 | 支持 | 手工 Copy-as-cURL 入口，返回必须脱敏 |
| upload payload 返回 | 不支持 | 部分支持 | MCP 固定关闭 |
| submit upload | 不支持 | 支持 | CLI `--submit-upload` |

## 安全边界

MCP 入口的安全边界仍是必要设计。新增工具只补齐用户明确要求的能力，不应把 CLI 调试面整体搬进 MCP。

允许新增：

- `amazon_rufus_platform_cookie_save(platform, country, content)`
- `amazon_rufus_platform_cookie_get(platform, country, include_content=false)`
- `amazon_rufus_curl_save(asin, country, raw_curl)`

仍不建议暴露：

- `cookie`
- `headers`
- `storage_state`
- `payload_template`
- `cookie save`
- `cookie status`
- `save-state`
- `init`
- `cdp_url`
- `new_chrome`
- `keep_chrome_open`

`raw_curl` 和 `content` 是新增工具必须接收的整体敏感输入，但服务层不得拆成 Agent 可单独传入的 `headers`、`payload_template`、`storage_state` 等参数。输出默认不回显敏感原文。

`amazon_rufus_platform_cookie_get` 的返回策略：

- 默认 `include_content=false`：只返回 `platform`、`country`、`status`、`message`、`content_length`、`has_content`。
- 显式 `include_content=true`：允许返回完整 `content`，仅用于排障。调用方不得写入报告、feedback 或普通用户回复。

## 风险点

1. `remote-consent` 多国家独立性

当前 `RemoteConsentStore` 单文件保存单国家偏好，与 Skill 中“不同国家站点授权偏好相互独立”的规则不完全一致。建议后续修复为国家维度文件或 map 结构，并补测试。

2. 新增 MCP 敏感工具的泄露风险

`platform-cookie get/save` 与 `curl save` 都会处理高敏感材料。实现时必须避免在 `_rufus_error()` 的 `call_params`、报告、feedback 和普通日志里写入 `content` 或 `raw_curl`。错误结构应只记录 `content_provided`、`content_length`、`raw_curl_provided`、`raw_curl_length`。

3. 编排逻辑分散

登录恢复、CLI fallback 白名单、历史报告禁止读取等规则主要存在于 Skill 文档，由 Agent 执行。MCP Tool 本身只完成单次工具动作。后续如果希望降低 Agent 误执行风险，可以考虑在服务层增加更强的状态机或守卫，但不要暴露敏感字段。

4. 输出契约不统一

MCP 成功返回结构化摘要；CLI `get-backend` 成功返回纯文本报告路径。Skill fallback 需要解析文本路径时容易脆弱。若后续需要更稳，可为 CLI 增加成功 JSON 输出选项，但保持默认兼容。

## 建议优先级

P0：实现 MCP `platform-cookie get/save` 与 `curl save` 的受控工具、MCP manager façade 和脱敏测试。

P1：补 `RemoteConsentStore` 多国家独立性测试并修复存储结构。

P2：为 CLI `get-backend --pretty` 或新增 `--json` 成功输出提供结构化 `report_path`，方便 fallback 稳定解析。

P3：考虑增加 Skill 编排级测试，覆盖一次登录恢复上限、平台 Cookie 401 分支和历史报告禁止兜底。
