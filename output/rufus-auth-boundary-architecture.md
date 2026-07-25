# Rufus 认证边界修复架构

日期：2026-06-09

## 设计原则

1. OPS 认证只负责访问 OPS 平台接口。
2. Rufus/Amazon 登录态只来自平台 Cookie content 中保存的 Amazon 会话材料。
3. HTTP 401 必须归类为 OPS 平台接口鉴权失败，不能触发 Amazon 登录恢复。
4. MCP 必须使用当前请求上下文的隔离凭证，不隐式复用默认 CLI 凭证。
5. 保持最小改动，不新增用户未要求的账号池、删除接口或 MCP 参数。

## 错误类型设计理由

`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 是平台 Cookie API 专用边界错误，不是普通远端 HTTP 错误的别名。

新增该错误类型的原因：

1. `RUFUS_REMOTE_HTTP_ERROR` 只能表达“远端 HTTP 失败”，不能表达失败发生在 `/v1/platform-cookies` 这个 Rufus 登录态底座上。
2. `/v1/platform-cookies` 的 HTTP 401 表示 OPS Bearer Token 或 Session Cookie 不可用；这与 Amazon Cookie、`storage_state`、`curl_data` 或 Rufus seed request 是否存在无关。
3. Skill 需要稳定机器码来决定恢复路径。该错误必须停止 `watch-login`，否则会让用户重复登录 Amazon，但无法修复 OPS API 401。
4. Manager 需要通过该错误保护副作用顺序。`logout()` 远端清理失败时不得继续删除本机 browser profile。

因此该错误只在平台 Cookie GET/POST 的 HTTP 401 上产生；平台 content 缺失、国家不匹配或 Rufus 请求材料缺失仍归入 Rufus 登录态恢复路径。

## 拟调整模块

### `opscli/amazon_rufus/domain/exceptions.py`

新增 Rufus 业务异常：

```python
class RufusPlatformCookieAuthError(RufusError):
    """OPS 平台 Cookie API 鉴权失败。"""

    code = "RUFUS_PLATFORM_COOKIE_AUTH_ERROR"
```

异常应保留 HTTP status code，便于 CLI/MCP JSON 输出和测试断言；message 不包含 JWT、session、Cookie、headers、content 或 URL query 中的敏感信息。

### `opscli/amazon_rufus/transport/client.py`

保持 GET/POST path 和三字段保存契约不变。

新增最小映射：

- 当 `parse_remote_response()` 抛出 `RufusRemoteHttpError` 且 `status_code == 401` 时，转换为 `RufusPlatformCookieAuthError`。
- 仅平台 Cookie GET/POST 做该映射，`/v1/rufus/upload` 仍保持现有 Rufus 上传错误语义。
- 其它平台 Cookie HTTP 状态继续保留 `RUFUS_REMOTE_HTTP_ERROR`，避免把网络故障、服务端错误或权限外问题误归为认证边界错误。

原因：

- `/v1/platform-cookies` 是 Rufus 登录态读写的底座，401 直接影响状态判断。
- 用户可见错误需要明确说明“先修复 OPS/MCP 平台接口认证”，而不是“重新登录 Amazon”。

### `opscli/amazon_rufus/services/browser_state_store.py`

远端模式行为保持：

- `load(country)` 读取 `platform=amazon` content。
- 业务码 404 返回 `None`，表示未保存 Rufus/Amazon 状态。
- HTTP 401 由 transport 映射后向上抛出 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
- `delete(country)` 仍使用空 record 覆盖远端 content；401 时向上抛出，不吞掉。

可选限制：

- 保存前校验 `len(content) <= 65535`，与 OAS 的 TEXT 限制一致；如超限，返回 `INVALID_RUFUS_PLATFORM`。该项只在实现确认后纳入，避免扩大范围。

### `opscli/amazon_rufus/services/manager.py`

#### `login_status()`

处理规则：

```text
platform API 401
  -> 抛出 RUFUS_PLATFORM_COOKIE_AUTH_ERROR

platform API 404 / missing content
  -> status=missing, can_get_backend=false

content JSON invalid
  -> status=invalid, can_get_backend=false

content 有可用 storage_state/curl_data
  -> status=ready, can_get_backend=true
```

不建议把平台 API 401 包装为 `success=true` 的状态，因为调用方无法继续判断 Rufus 登录态。CLI 应失败退出，但错误码必须可区分，并由 Skill 据此停止 Amazon 登录恢复。

#### `logout()`

顺序不变但增加测试保障：

1. 调用 `browser_state_store.delete(country)` 清理远端 Rufus content。
2. 仅当第 1 步成功后，才按 `include_browser_profile` 清理本机 opscli Chrome profile。
3. 若第 1 步抛出 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`，直接向 CLI 返回失败，不清理 profile。

### `opscli/mcp/tools/amazon_rufus.py`

新增 MCP 专用 manager 工厂，避免 `RufusManager()` 默认读取错误凭证域：

```python
def _rufus_manager_for_current_request() -> RufusManager:
    """创建绑定当前 MCP 请求凭证目录的 RufusManager。"""
    cred_dir = _get_credential_dir()
    auth_client = AuthClient(base_dir=cred_dir) if cred_dir else AuthClient()
    transport = RufusTransportClient(auth_client=auth_client)
    return RufusManager(transport_client=transport)
```

实际实现需注意：

- `cred_dir is None` 时是 stdio 模式，继续与 CLI 共用默认凭证。
- HTTP/SSE 模式下，`AuthClient(base_dir=cred_dir)` 会读取 API Key + Agent 名称隔离目录。
- `RufusTransportClient` 仍会透传 `X-MCP-API-Key`，用于后端审计或多用户校验。
- 如果隔离凭证目录没有有效 OPS session/JWT，MCP 返回 OPS/MCP 鉴权错误，Skill 先走 `auth_mcp_login`。

### `opscli/skills/templates/ops-amazon-rufus/`

需要同步：

- `SKILL.md`
- `README.md`
- `references/rufus-mcp-workflow.md`
- `.agents/skills/ops-amazon-rufus/` 对应副本

新增执行限制：

```text
如果 login-status、logout 或 amazon_rufus_get 返回 RUFUS_PLATFORM_COOKIE_AUTH_ERROR，
说明 OPS 平台 Cookie API 鉴权失败，不是 Amazon 未登录。
本轮不得执行 watch-login 或重复 amazon_rufus_get。
CLI 路径先处理 opscli auth；MCP 路径先处理 auth_mcp_login。
```

## 数据流

### CLI 状态检查

```text
opscli amazon-rufus login-status US
  -> RufusManager.login_status()
  -> RufusBrowserStateStore.load("US")
  -> RufusTransportClient.get_platform_cookie(platform="amazon")
  -> OPS /v1/platform-cookies
  -> content -> record -> status summary
```

失败分流：

```text
HTTP 401
  -> RUFUS_PLATFORM_COOKIE_AUTH_ERROR
  -> 停止 Amazon 登录恢复

业务 code=404
  -> status=missing
  -> 可进入 watch-login
```

### MCP 获取

```text
amazon_rufus_get
  -> _rufus_manager_for_current_request()
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
  -> OPS /v1/platform-cookies?platform=amazon
  -> content -> curl_data/storage_state
  -> HeadlessRufusCaptureService / HeadlessRufusClient
  -> report_path
```

## 测试策略

1. Transport：
   - GET `/v1/platform-cookies` HTTP 401 映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
   - POST `/v1/platform-cookies` HTTP 401 映射为同一错误。
   - `/v1/rufus/upload` 不受该映射影响。

2. Manager：
   - `login_status()` 遇到平台 API 401 抛出新错误。
   - `login_status()` 遇到业务码 404 返回 missing。
   - `logout()` 遇到平台 API 401 不调用 `clear_owned_profile()`。
   - `logout()` 清理远端成功后才清理 profile。

3. MCP：
   - monkeypatch `_get_credential_dir()`，断言 `amazon_rufus_get` 创建的 `AuthClient` 使用该 base_dir。
   - 隔离凭证缺失时返回 OPS/MCP 鉴权错误，不误报 `RUFUS_SECRET_NOT_READY`。
   - content 命中时继续过滤敏感字段。

4. Skill：
   - 文档包含 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 限制。
   - 文档不包含要求用户复制 cookie、headers、payload 或完整 content 的流程。

5. 回归：
   - `tests/amazon_rufus/test_transport.py`
   - `tests/amazon_rufus/test_core.py`
   - `tests/mcp/test_amazon_rufus_tools.py`
   - `tests/skills/test_ops_amazon_rufus_updater.py`

## 变更记录要求

进入实现阶段修改 Python 或 Skill 文件后，必须追加 `docs/change-log-pending.md`，说明原因、改动点、验证结果、影响范围和回滚方式。
