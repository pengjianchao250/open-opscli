# Rufus MCP 标准架构对齐调研

日期：2026-06-10

## 目标

本调研回答一个具体问题：`amazon_rufus` MCP 如何改造成与项目中其他 MCP 工具一致的架构。

这里的“同样的架构”不是指通过 CLI 或 Python 脚本执行，而是指项目现有 MCP 工具普遍采用的分层：

```text
MCP Tool
  -> helpers 处理凭证、JSON 参数、统一响应
  -> domain request/result 模型
  -> services manager 编排业务
  -> transport/api/client 执行远端或浏览器交互
```

## 外部 MCP/FastMCP 约束

FastMCP 官方文档说明，Server 会把 Python 函数包装为 MCP tool，并根据函数签名和类型注解生成 schema。这说明 MCP Tool 最适合做稳定、薄的函数入口，而不是承载复杂业务编排。

参考：

- FastMCP Welcome: https://gofastmcp.com/getting-started/welcome
- FastMCP Tools: https://gofastmcp.com/servers/tools
- FastMCP Server: https://gofastmcp.com/servers/server
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk

## 项目内标准样式

### Keepa

文件：

- `opscli/mcp/tools/keepa.py`
- `opscli/keepa/domain/models.py`
- `opscli/keepa/services/api_manager.py`

调用链：

```text
keepa_run(...)
  -> _get_auth_pair("ops", session_id, jwt)
  -> _parse_json_arg(params, dict)
  -> KeepaScenarioRequest(...)
  -> await KeepaApiManager(jwt=jw, session_id=sid).run(request)
  -> _public_result(result.to_dict())
  -> _ok(...)
```

特点：

1. MCP Tool 不直接调用 CLI。
2. MCP Tool 不承载场景业务细节。
3. 复杂逻辑在 `KeepaApiManager.run()`。
4. 入参模型是 `KeepaScenarioRequest`。
5. 结果对象是 `KeepaScenarioResult`。
6. Tool 层只做参数解析、认证获取、调用 manager、结果脱敏。

### SellerSprite

文件：

- `opscli/mcp/tools/seller_sprite.py`
- `opscli/seller_sprite/domain/models.py`
- `opscli/seller_sprite/services/api_manager.py`

调用链：

```text
seller_sprite_run(...)
  -> _get_auth_pair("ops", session_id, jwt)
  -> _parse_json_arg(params, dict)
  -> SellerSpriteScenarioRequest(...)
  -> await SellerSpriteApiManager(jwt=jw, session_id=sid).run(request)
  -> _ok(result.to_dict())
```

特点与 Keepa 一致：MCP Tool 是薄入口，业务编排在 API manager。

### Query

文件：

- `opscli/mcp/tools/query.py`
- `opscli/mcp/tools/helpers.py`
- `opscli/query/services/manager.py`

调用链：

```text
query_simple(...)
  -> _get_auth_pair("ops", session_id, jwt)
  -> 参数归一化
  -> _query_manager(jwt=jw, session_id=sid).build_simple_and_run(...)
  -> _ok(result)
```

特点：

1. MCP Tool 做 AI 参数容错。
2. 服务层 `QueryManager` 做真实构造、校验、执行。
3. helper 里有专用 `_query_manager()` 工厂。

## Rufus 当前状态

文件：

- `opscli/mcp/tools/amazon_rufus.py`
- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/services/remote_consent.py`
- `opscli/amazon_rufus/transport/client.py`

当前已经做到：

1. Skill 运行期只走 MCP Tool，不再 fallback CLI。
2. MCP Tool 直接调用 `RufusManager`、`RemoteConsentStore`、`RufusTransportClient`，不调用 `opscli amazon-rufus ...`。
3. MCP HTTP/SSE 模式下通过 `_get_credential_dir()` 使用 API Key + Agent 名称隔离凭证。
4. `amazon_rufus_get` 已默认走 `RufusManager.get_backend()`。
5. `amazon_rufus_watch_login`、`login_status`、`logout`、`remote_consent` 已经暴露成 MCP Tool。
6. MCP 返回使用 allowlist 过滤敏感字段。

当前仍不完全像 Keepa/SellerSprite 的地方：

1. `opscli/mcp/tools/amazon_rufus.py` 中仍有较多业务适配代码：
   - manager 工厂
   - remote consent store 工厂
   - `_run_manager`
   - 多个 payload builder
   - 报告写入
   - allowlist 维护
2. Rufus 没有统一的 MCP-facing request/result 模型。
3. Rufus 没有类似 `KeepaApiManager` / `SellerSpriteApiManager` 的 MCP 专用 façade。
4. CLI 和 MCP 都直接面对 `RufusManager`，但两者的输出策略不同：
   - CLI 写报告或输出 JSON。
   - MCP 必须返回稳定、脱敏、Agent 友好的 JSON。
5. `RufusManager` 同时包含传统 CLI 能力和 MCP-only 后端能力：
   - `get`
   - `get_headless`
   - `get_backend`
   - `watch_login`
   - `save_cookie`
   - `save_curl`
   - `platform_cookie` 管理

## 目标架构判断

Rufus MCP 不需要改成“直接调用 py 脚本”，也不应该改成“调用 CLI”。正确方向是新增一个 MCP/API façade，使架构变成：

```text
opscli/mcp/tools/amazon_rufus.py
  -> RufusMcpManager / RufusApiManager
  -> RufusManager
  -> BrowserAttachService / RufusBrowserStateStore / RufusTransportClient / HeadlessRufusClient
```

其中：

- `RufusManager` 保留底层业务能力。
- `RufusMcpManager` 负责 MCP-facing 编排、脱敏、报告写入、凭证注入。
- `amazon_rufus.py` 只保留 FastMCP Tool 函数、参数解析、`_ok/_err`。

## 推荐改造范围

### 必做

1. 新增 `opscli/amazon_rufus/domain/mcp_models.py` 或扩展 `domain/models.py`：
   - `RufusGetRequest`
   - `RufusWatchLoginRequest`
   - `RufusLogoutRequest`
   - `RufusRemoteConsentRequest`
   - `RufusMcpResult`
2. 新增 `opscli/amazon_rufus/services/mcp_manager.py`：
   - 封装当前 MCP Tool 里的 `_build_*_payload`
   - 封装 `AnswerReportWriter().write(data)`
   - 封装 `asyncio.to_thread` 或提供同步方法由 Tool 层统一 `to_thread`
   - 接收 `auth_client`、`credential_dir`、`transport_client`
3. 精简 `opscli/mcp/tools/amazon_rufus.py`：
   - 只做 Tool 签名、构造 request、调用 manager、返回 `_ok/_err`
4. 保留现有 `RufusManager` 作为底层业务编排，不把 MCP 响应格式散落在其中。
5. 测试迁移到新边界：
   - MCP Tool 测试只断言工具注册、schema、调用 manager。
   - `RufusMcpManager` 测试断言脱敏、报告、错误边界、凭证隔离。

### 不建议做

1. 不删除 CLI。
2. 不让 MCP 调 CLI。
3. 不让 MCP 调单独 `.py` 脚本。
4. 不公开 `platform_cookie_get` MCP Tool。
5. 不把 cookie、localStorage、storage_state、headers、payload、seed request 放进 MCP 参数或响应。

## 结论

Rufus MCP 当前已经达到“不是 CLI wrapper”的基本目标。若要与项目中其他 MCP 工具完全对齐，下一步不是补更多工具，而是做结构收敛：

```text
当前：
MCP Tool -> RufusManager / RemoteConsentStore / AnswerReportWriter / payload builders

目标：
MCP Tool -> RufusMcpManager -> RufusManager / RemoteConsentStore / AnswerReportWriter
```

这样可以让 Rufus MCP 具备与 Keepa、SellerSprite、Query 一致的工程边界：Tool 层薄、业务层可测、模型稳定、敏感字段集中治理。
