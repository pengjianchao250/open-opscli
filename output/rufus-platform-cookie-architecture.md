# Rufus 平台 Cookie CLI 架构

日期：2026-06-08

## 总体设计

本次变更在现有 Rufus 模块内补齐 OPS 后端平台 Cookie 接口转发能力，并让 Rufus 状态 record 可作为 `content` 在远端往返：

1. Transport 层负责 HTTP 请求与 OPS 鉴权。
2. Browser state store 负责把完整 Rufus record 序列化为 `content`，并从远端 content 反序列化回现有 record。
3. Manager 层负责平台、国家和 content 参数校验。
4. CLI 层负责 Typer 命令暴露和统一 JSON 输出。
5. Skill 文档只描述命令编排，不承载脚本实现。

## API 契约

固定后端 path：

```http
POST /v1/platform-cookies
GET /v1/platform-cookies?platform=<PLATFORM>
```

base URL 继续复用 opscli 的 OPS 系统地址：

```text
{get_ops_url().rstrip("/")}/v1/platform-cookies
```

认证：

- `AuthClient().build_request_auth("ops")`
- `get_mcp_request_headers()`

## 代码边界

### `opscli/amazon_rufus/transport/client.py`

新增常量：

```python
PLATFORM_COOKIE_ENDPOINT = "/v1/platform-cookies"
```

新增方法：

```python
def save_platform_cookie(self, *, platform: str, country: str, content: str) -> dict:
    """保存或覆盖当前用户指定平台 Cookie 记录。"""

def get_platform_cookie(self, *, platform: str) -> dict:
    """读取当前用户指定平台 Cookie 记录。"""
```

行为：

- `save_platform_cookie()` 发送 POST，JSON 只包含 `platform`、`country`、`content`。
- `get_platform_cookie()` 发送 GET，query 只包含 `platform`。
- 统一使用 `parse_remote_response()`。
- 不在 Transport 层脱敏，保持 HTTP 客户端职责单一。

### `opscli/amazon_rufus/services/browser_state_store.py`

新增可选注入：

```python
def __init__(self, base_dir=None, platform_cookie_client=None, platform="amazon") -> None:
    ...
```

行为：

- 未注入 `platform_cookie_client` 时保留本地 JSON 文件读写能力，支撑测试和兼容场景。
- 注入 `platform_cookie_client` 时，`save()` 将完整 record `json.dumps(..., ensure_ascii=False)` 后写入远端 `content`。
- 注入 `platform_cookie_client` 时，`load(country)` 调用 `GET /v1/platform-cookies?platform=<PLATFORM>`，校验返回国家与 content 内 `country` 后还原 record。
- `RufusManager` 默认创建注入 `RufusTransportClient` 的 store，`save_state`、`watch_login`、`save_cookie`、`save_curl`、`login_status`、`get_backend`、`logout` 默认均通过线上平台 Cookie content 读写，不再读写 `browser-state-<COUNTRY>.json`。
- `RufusBackendSecretProvider` 独立实例化时也默认创建线上 store；只有显式注入 `RufusBrowserStateStore(base_dir=...)` 时才使用本地 JSON fallback。

### `opscli/amazon_rufus/services/manager.py`

新增方法：

```python
def save_platform_cookie(self, *, platform: str, country: str, content: str) -> dict:
    """保存平台 Cookie content 并返回摘要。"""

def get_platform_cookie(self, *, platform: str, country: str) -> dict:
    """读取平台 Cookie content。"""
```

职责：

- 规范化并校验 `platform`：trim 后不能为空，长度不超过 50。
- 规范化并校验 `country`：2 位字母，转大写。
- 校验 `content`：保存时不能为空。
- 调用 Transport 层。
- 将业务码 404 映射为 `status=missing`。
- `get_platform_cookie()` 返回远端 `content`，但 Skill/报告不得展示。
- 默认状态存储使用 `platform=amazon`，除平台、国家外的 `storage_state`、`curl_data`、headers、payload 和 seed request 统一位于远端 `content` 大 JSON。

### `opscli/amazon_rufus/commands/cli.py`

新增子命令组：

```python
platform_cookie_app = typer.Typer(help="管理 OPS 平台 Cookie 记录")
app.add_typer(platform_cookie_app, name="platform-cookie")
```

新增命令：

```powershell
opscli amazon-rufus platform-cookie save <PLATFORM> <COUNTRY> --from-stdin --pretty
opscli amazon-rufus platform-cookie get <PLATFORM> <COUNTRY> --pretty
```

命令输出沿用现有结构：

```json
{
  "success": true,
  "command": "amazon-rufus platform-cookie get",
  "data": {},
  "error": null
}
```

## 异常策略

- 平台参数非法：抛出 Rufus 模块业务异常，CLI 返回 `success=false`。
- HTTP 401：沿用 `RUFUS_REMOTE_HTTP_ERROR`。
- 业务码 422：沿用 `RUFUS_REMOTE_BUSINESS_ERROR`。
- 业务码 404：在 `get_platform_cookie()` 中转为 `status=missing`，不是 CLI 失败。

## 测试策略

遵循 TDD：

1. RED：Transport POST 测试，确认 URL、请求体、鉴权和超时。
2. RED：Transport GET 测试，确认 query 参数只包含平台。
3. RED：Manager 脱敏测试，确认响应不含 `cookie_content` 原文。
4. RED：Manager 404 映射测试，确认返回 `status=missing`。
5. RED：Browser state store 测试，确认完整 Rufus record 能通过远端 `content` 往返并被 provider 读取。
6. RED：CLI help/命令测试，确认新增 `platform-cookie save/get`。
7. GREEN：最小实现。
8. 回归：`tests/amazon_rufus/test_transport.py`、`tests/amazon_rufus/test_core.py`、`tests/skills/test_ops_amazon_rufus_updater.py`。

## 变更记录

正式修改 Python 或 Skill 文件后，按项目规范追加 `docs/change-log-pending.md`。当前阶段仅写 Super Dev 文档，不写变更记录。
