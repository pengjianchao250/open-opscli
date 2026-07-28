# Rufus MCP 标准架构对齐 PRD

日期：2026-06-10

## 背景

项目内其他 MCP 工具不是通过 CLI 或 Python 脚本执行，而是通过 FastMCP 注册 Python 函数，再由函数调用内部 manager/service/client。

Rufus MCP 当前已经 MCP-only，但 `opscli/mcp/tools/amazon_rufus.py` 仍承担了较多适配职责。为了与 Keepa、SellerSprite、Query 的架构一致，需要把 MCP-specific 编排下沉到 Rufus 服务层。

## 目标

1. 保持 Skill 运行期全程 MCP-only。
2. 让 `opscli/mcp/tools/amazon_rufus.py` 成为薄 Tool 层。
3. 新增 Rufus MCP/API façade，承接 MCP 响应脱敏、报告写入、请求模型和凭证注入。
4. 保持 CLI 可用，但 CLI 不是 Skill fallback，也不是 MCP Tool 的执行路径。
5. 继续禁止敏感 Rufus 状态进入 MCP 参数、响应、报告和对话。

## 非目标

1. 不删除 `opscli amazon-rufus` CLI。
2. 不改成 MCP 调用 `opscli amazon-rufus ...`。
3. 不新增公开的 `platform_cookie_get` MCP Tool。
4. 不新增账号池、远端异步 job 或浏览器托管能力。
5. 不改变现有 OPS 平台 Cookie API 契约。

## 用户与场景

### Agent 用户

通过 `ops-amazon-rufus` Skill 运行 Rufus 问答，期望：

- 自动检查 MCP/OPS 登录。
- 必要时通过 MCP Tool 打开 Amazon 登录采集。
- 获取 Rufus 回答并得到本次 `report_path`。
- 不接触 cookie、headers、storage_state 等敏感字段。

### 开发者

维护 Rufus MCP 时，期望：

- Tool 层足够薄，测试成本低。
- 业务逻辑集中在 service 层。
- CLI 和 MCP 共享底层能力，但输出边界清晰。
- 新增测试不用 monkeypatch 太多 Tool 内部函数。

## 功能需求

### FR-1：MCP Tool 薄入口

`opscli/mcp/tools/amazon_rufus.py` 只保留：

- Tool 函数签名和 docstring。
- request 对象构造。
- `_ok/_err` 包装。
- `register(mcp)` 注册列表。
- 必要的 JSON 参数兼容解析。

不再保留：

- 多个 `_build_*_payload`。
- `AnswerReportWriter` 直接调用。
- `RemoteConsentStore` 直接工厂。
- `RufusTransportClient` 直接工厂。
- 复杂 manager 创建逻辑。

### FR-2：新增 Rufus MCP façade

新增 `RufusMcpManager`，建议路径：

```text
opscli/amazon_rufus/services/mcp_manager.py
```

职责：

- 基于当前 MCP 凭证目录创建 `AuthClient`、`RufusTransportClient`、`RufusManager`。
- 创建隔离的 `RemoteConsentStore`。
- 调用 `RufusManager` 执行底层业务。
- 统一生成 MCP-safe result。
- 写入 Rufus 报告并只返回 `report_path` 与计数摘要。
- 统一过滤敏感字段。

### FR-3：新增 request/result 模型

新增或扩展 domain model：

```text
RufusGetRequest
RufusWatchLoginRequest
RufusLogoutRequest
RufusRemoteConsentRequest
RufusMcpResponse
```

要求：

- 请求模型只包含 MCP 允许暴露的字段。
- 结果模型必须有 `to_dict()`。
- 不允许结果模型包含 cookie、headers、payload、seed request、storage_state。

### FR-4：保持现有工具语义

现有 MCP Tool 名称不变：

- `amazon_rufus_remote_consent_status`
- `amazon_rufus_remote_consent_set`
- `amazon_rufus_login_status`
- `amazon_rufus_watch_login`
- `amazon_rufus_logout`
- `amazon_rufus_get`

入参保持兼容，避免破坏 Skill 文档和已有测试。

### FR-5：错误边界保持稳定

必须继续保持：

- `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 表示 OPS/MCP 鉴权失败。
- 该错误不触发 Amazon 登录采集恢复。
- `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR` 才进入一次登录采集恢复。

### FR-6：测试可维护

测试分层：

- `tests/mcp/test_amazon_rufus_tools.py`：工具注册、schema、Tool 到 façade 的参数传递。
- `tests/amazon_rufus/test_mcp_manager.py`：脱敏、报告写入、凭证隔离、错误映射。
- 原 `test_core.py`：保留底层 `RufusManager` 行为测试。

## 验收标准

1. `rg "subprocess|opscli amazon-rufus|CliRunner" opscli/mcp/tools/amazon_rufus.py` 不存在业务 CLI 调用。
2. `amazon_rufus.py` 不直接 import `AnswerReportWriter`、`RemoteConsentStore`、`RufusTransportClient`。
3. `amazon_rufus.py` 的 Tool 函数只构造 request 并调用 `RufusMcpManager`。
4. MCP schema 中仍不出现：
   - `cookie`
   - `headers`
   - `payload_template`
   - `raw_curl`
   - `storage_state`
   - `seed_request`
5. 所有 Rufus MCP 成功响应不包含敏感字段。
6. 现有 Skill 文档无需恢复 CLI fallback。
7. 定向测试通过：
   - `tests/mcp/test_amazon_rufus_tools.py`
   - 新增 `tests/amazon_rufus/test_mcp_manager.py`
   - `tests/amazon_rufus/test_transport.py`
   - `tests/skills/test_ops_amazon_rufus_updater.py`

## 优先级

P0：

- 引入 `RufusMcpManager`。
- Tool 层瘦身。
- 迁移报告写入和脱敏逻辑。
- 保持现有 Tool 名称和 schema。

P1：

- 引入完整 request/result dataclass。
- 拆分 MCP manager 单测。
- 把 `amazon_rufus.py` 内部 helper 降到最少。

P2：

- 后续考虑异步 job/polling，解决长时间登录采集和多题请求的宿主超时问题。
