# Rufus Skill MCP 与 opscli Rufus 功能差异调研

## 背景

本次调研目标是检查 `ops-amazon-rufus` Skill 中声明的 MCP 工具链，并对比 `opscli amazon-rufus` CLI 与 `opscli/amazon_rufus/` 服务层当前实现，识别功能差异、刻意收敛点和潜在不一致。

## 本地依据

- Skill 模板：`opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- Skill 工作流：`opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
- MCP 工具：`opscli/mcp/tools/amazon_rufus.py`
- MCP façade：`opscli/amazon_rufus/services/mcp_manager.py`
- CLI 命令：`opscli/amazon_rufus/commands/cli.py`
- 核心服务：`opscli/amazon_rufus/services/manager.py`
- MCP 模型：`opscli/amazon_rufus/domain/mcp_models.py`
- 约束测试：`tests/mcp/test_amazon_rufus_tools.py`、`tests/amazon_rufus/test_mcp_manager.py`、`tests/skills/test_ops_amazon_rufus_updater.py`

## 共同能力

MCP 与 CLI 的核心 Rufus 获取并不是两套实现。两者都复用 `RufusManager.get_backend()`，最终通过后端/headless 链路读取 Rufus 凭证、解析题库或临时问题、请求 Rufus streaming，并由 `AnswerReportWriter` 写入 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。

共同覆盖能力：

- 国家站点解析与 ASIN 商品页 URL 构造。
- 单题、多题、默认题库三种问题来源。
- 通过 `watch_login` 捕获 Amazon 登录态和 Rufus streaming 请求种子。
- 通过 `login_status` 判断是否具备 `can_get_backend`。
- 通过 `logout` 清理 Rufus 状态和工具管理的 Chrome profile。
- 报告写入 `output/amazon-rufus/`。

## MCP 暴露能力

当前 MCP 只注册 6 个 Rufus 工具；用户已明确要求后续 MCP 补齐 `platform-cookie get/save` 与 `curl save`。因此这里的“只注册 6 个”是现状，不再是目标状态。

| MCP 工具 | 对应服务 |
|---|---|
| `amazon_rufus_remote_consent_status` | `RufusMcpManager.remote_consent_status()` |
| `amazon_rufus_remote_consent_set` | `RufusMcpManager.remote_consent_set()` |
| `amazon_rufus_login_status` | `RufusMcpManager.login_status()` |
| `amazon_rufus_watch_login` | `RufusMcpManager.watch_login()` |
| `amazon_rufus_logout` | `RufusMcpManager.logout()` |
| `amazon_rufus_get` | `RufusMcpManager.get()` |

现状中 MCP 未暴露：

- `amazon_rufus_init`
- `amazon_rufus_get_remote`
- CDP 直接获取参数：`cdp_url`、`new_chrome`、`keep_chrome_open`
- 敏感输入：`cookie`、`curl`、`raw_curl`、`headers`、`payload_template`、`storage_state`
- 管理/调试类入口：平台 Cookie content 读写、手工 cookie 保存、手工 cURL 保存

目标调整后，MCP 需要新增受控工具：

| 目标 MCP 工具 | 对齐 CLI 命令 | 安全边界 |
|---|---|---|
| `amazon_rufus_platform_cookie_save` | `platform-cookie save` | 接收 `content`，保存后只返回平台、国家、状态、content 长度，不回显 content |
| `amazon_rufus_platform_cookie_get` | `platform-cookie get` | 默认返回摘要；如确需排障，可通过显式参数返回完整 content |
| `amazon_rufus_curl_save` | `curl save` | 接收 `raw_curl`，保存后只返回国家、ASIN、cookie/header 数量和 payload template 是否存在，不回显 cURL |

## CLI 暴露能力

CLI 暴露的命令明显多于 MCP：

| CLI 命令 | 是否在 MCP 暴露 | 说明 |
|---|---:|---|
| `get-backend` | 是，映射为 `amazon_rufus_get` | MCP 走安全 façade，CLI 有更多参数 |
| `watch-login` | 是 | 默认参数不同，见差异 |
| `logout` | 是 | MCP 隐藏 `cdp_url` |
| `login-status` | 是 | MCP 返回 allowlist 摘要 |
| `remote-consent status/set` | 是 | source 分别为 `opscli` 和 `mcp` |
| `init` | 否 | 打开站点供登录，属于本地 CDP 操作 |
| `save-state` | 否 | 捕获浏览器 storage state，MCP 不允许 Agent 直接保存 |
| `platform-cookie save/get` | 目标需支持 | 可读写 OPS 平台 Cookie content，必须受控暴露 |
| `cookie save/status` | 否 | 手工 Cookie 状态入口，Skill 文档明确不引导 |
| `curl save` | 目标需支持 | 手工 Copy-as-cURL 状态入口，必须受控暴露 |

## 关键差异

1. 能力边界不同

MCP 是 Agent-facing 安全子集；CLI 是本机运维、调试和 fallback 工具面。现在需要把部分 CLI 调试能力提升为 MCP 受控能力，但不能把 CLI 参数面原样搬入 MCP。`platform-cookie get/save` 与 `curl save` 应作为显式排障/初始化工具存在，不进入普通 Rufus 获取主路径。

2. 返回结构不同

MCP 成功响应统一为 `_ok(data)`，`amazon_rufus_get` 只返回 `report_path`、ASIN、国家、问题数、答案数和下一步提示。CLI 状态类命令返回 `{success, command, data, error}`；`get-backend` 成功时只输出“Rufus 答案报告已保存：<path>”，不是结构化 JSON。

3. 敏感字段处理不同

MCP façade 通过 allowlist 和 `_SENSITIVE_KEYS` 阻止 `cookie`、`headers`、`storage_state`、`seed_request`、`upload_payload`、`curl` 等字段出现在 MCP 返回中，并且 `RufusGetRequest.to_backend_kwargs()` 固定 `include_upload_payload=False`。CLI `get-backend` 默认 `include_upload_payload=True`，并支持 `--submit-upload`，但成功时仍只写报告路径文本。

4. 参数面不同

MCP `amazon_rufus_get` 只接受 ASIN、国家、单题、多题、`skills_dir`、timeout。CLI `get-backend` 额外支持 `--upload-payload/--no-upload-payload`、`--submit-upload`、`--pretty`。MCP `watch_login` 可传 `chrome_path`、`launch_if_needed`、`close_browser`，但不暴露 `cdp_url`；CLI `watch-login` 暴露 `cdp_url`。

新增 MCP 工具的参数面应保持最小：

- `amazon_rufus_platform_cookie_save(platform, country, content)`
- `amazon_rufus_platform_cookie_get(platform, country, include_content=false)`
- `amazon_rufus_curl_save(asin, country, raw_curl)`

`include_content=false` 是推荐默认值；只有明确排障时才返回 content。`raw_curl` 和 `content` 只允许作为工具入参进入服务层，不允许进入报告、feedback、日志或普通回复。

5. 默认行为不同

MCP `amazon_rufus_watch_login()` 默认 `close_browser=True`。CLI `watch-login` 默认 `close_browser=False`，但 Skill fallback 文档要求 CLI 调用必须显式加 `--close-browser`。

6. 凭证隔离不同

MCP 通过 `_get_credential_dir()` 将当前请求凭证目录传给 `RufusMcpManager.for_current_request()`，HTTP/SSE 模式下按当前 MCP 用户/Agent 隔离 AuthClient 与 remote consent 存储。CLI 使用默认 `CONFIG_DIR` 下的本机用户配置。

7. 错误恢复不在工具内部自动完成

Skill 文档要求对 `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR` 做一次 `logout -> watch_login -> get` 恢复；对 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 走 `watch_login`。这些是 Agent/Skill 编排规则，不是 `amazon_rufus_get` 或 CLI `get-backend` 内部自动重试逻辑。

8. 远程授权偏好存在实现不一致风险

Skill 文档要求不同国家站点授权偏好相互独立；当前 `RemoteConsentStore._path()` 使用单个 `remote-consent.json`，文件内只保存一个 `country`。这意味着保存 DE 后再查 US 会返回 `unknown`，并不能同时保留多国家偏好。MCP 与 CLI 共享该 store，所以这是 Skill 需求与实现层的差异，不是 MCP 与 CLI 之间的差异。

## 测试覆盖结论

已运行：

```text
uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_mcp_manager.py" "tests/skills/test_ops_amazon_rufus_updater.py"
```

结果：31 passed。

测试已覆盖：

- MCP 只暴露 6 个 Rufus 工具。
- MCP 不暴露旧/敏感工具与 CDP 获取参数。
- MCP 返回过滤敏感字段。
- MCP `get` 写报告且不返回 upload payload。
- Skill 模板不包含 CLI 调试入口，如 `curl save`、`cookie save`、`save-state`。

测试缺口：

- 需要新增 MCP 工具暴露测试：`amazon_rufus_platform_cookie_save`、`amazon_rufus_platform_cookie_get`、`amazon_rufus_curl_save`。
- 需要新增 MCP 工具 schema 测试，确保新增工具不引入 `headers`、`payload_template`、`storage_state` 等可拆散敏感材料的参数。
- 需要新增 MCP 返回脱敏测试，确认 `platform_cookie_save` 与 `curl_save` 不回显 content/cURL；`platform_cookie_get` 默认不返回 content。
- 未看到多国家 `remote-consent` 独立保存测试。
- 未看到 CLI `get-backend` 成功输出结构与 MCP 输出结构的契约对齐测试。
- 未看到 Skill 编排层对一次登录恢复上限的端到端测试。
