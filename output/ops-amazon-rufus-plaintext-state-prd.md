# ops-amazon-rufus 明文浏览器状态 PRD

## 目标

将 Rufus 本地 Amazon 登录态从 AES 加密文件改为明文 JSON 保存，使用户可以直接复制状态文件到其他环境，并继续使用 CLI/MCP 获取 Rufus。

## 非目标

1. 不新增 MCP 参数来传递 cookie、headers、payload 或 `storage_state`。
2. 不新增 Skill 中的手动 cookie/curl 复制指引。
3. 不读取、解密、迁移或删除旧 `browser-state-<COUNTRY>.bin` 密文。
4. 不改变 Rufus 问答报告格式。
5. 不改变 `amazon_rufus_get` 默认服务层读取本地状态的边界。

## 用户故事

### 1. 复制登录态

作为 Rufus CLI 用户，我希望登录成功后生成一个可读 JSON 文件，这样我可以把该文件复制到另一台机器同一路径，然后直接运行 Rufus CLI/MCP。

验收标准：

- 登录态保存到 `CONFIG_DIR/amazon-rufus/browser-state-<COUNTRY>.json`。
- 文件内容是 UTF-8 JSON。
- 文件包含 `storage_state`、可选 `curl_data` 和 seed 摘要。
- 复制该 JSON 文件后，不需要额外复制 `.browser-state-key`。

### 2. 保留输出脱敏

作为 Agent 使用者，我希望状态文件可以明文复制，但 CLI/MCP 的返回仍不展示敏感内容。

验收标准：

- `save-cookie` 返回不包含 cookie value。
- `save-curl` 返回不包含 csrf、cookie、payload 明文。
- `watch-login` 返回不包含 cookies、headers、payload、`storage_state`。
- `amazon_rufus_get` 报告不包含 cookie、headers、payload 或完整 streaming 请求。

### 3. 清理新状态

作为 Rufus 恢复流程使用者，我希望 `logout` 能清理当前国家站点的新明文状态，避免失败恢复继续读到旧 JSON 文件。

验收标准：

- `logout <COUNTRY>` 删除 `browser-state-<COUNTRY>.json`。
- `logout` 不处理旧 `browser-state-<COUNTRY>.bin` 或 `.browser-state-key`。
- `logout` 后 `amazon_rufus_get` 不应读取旧 `.bin` 密文。
- MCP 失败恢复仍按 `logout -> watch-login -> amazon_rufus_get` 执行。

## 登录态影响面

本次实现必须处理干净以下入口：

1. 写入入口：`RufusManager.save_state()`、`watch_login()`、`save_cookie()`、`save_curl()`。
2. 读取入口：`RufusManager.cookie_status()`、`RufusBackendSecretProvider.load()`。
3. 消费入口：`RufusManager.get_backend()` 通过 secret provider 读取 cookie、`storage_state`、seed 和 `curl_data`。
4. 删除入口：`RufusManager.logout()`。
5. CLI 展示入口：`save-state`、`watch-login`、`cookie status`、`cookie save`、`curl save`、`logout`。
6. MCP 展示入口：`amazon_rufus_get` 报告和 tool response。

## 功能需求

### FR-1 明文保存

`RufusBrowserStateStore.save()` 应直接写入 JSON：

```json
{
  "country": "US",
  "marketplace_origin": "https://www.amazon.com",
  "captured_at": 1710000000000,
  "storage_state": {
    "cookies": [],
    "origins": []
  }
}
```

带 streaming seed 时，继续保存：

- `curl_data.url`
- `curl_data.headers`
- `curl_data.cookies`
- `curl_data.payload_template`
- `streaming_url`
- `headers`
- `payload_template`
- `seed_request`

### FR-2 明文读取

`RufusBrowserStateStore.load(country)` 应读取 `.json` 文件并解析为 dict。

如果 `.json` 不存在，返回 `None`。

如果文件不是合法 JSON 或基础结构无效，抛出 `InvalidRufusBrowserStateError`。

### FR-3 不再创建密钥

实例化 `RufusBrowserStateStore` 不应创建 `.browser-state-key`。新代码不读取、创建或删除该 key。

### FR-4 删除新状态文件

`RufusBrowserStateStore.delete(country)` 应删除：

- `browser-state-<COUNTRY>.json`

返回值语义保持：删除了 `.json` 返回 `True`，文件不存在返回 `False`。

### FR-5 不处理 legacy `.bin`

`RufusBrowserStateStore` 不应包含 legacy `.bin` 迁移逻辑：

1. 不 import `Crypto`。
2. 不定义 `_legacy_state_path()`。
3. 不定义 `_legacy_key_path()`。
4. 不读取 `.bin`。
5. 不删除 `.bin` 或 `.browser-state-key`。

### FR-6 Skill 文案同步

`ops-amazon-rufus` Skill 和 workflow reference 应把“本地加密状态”改为“本地明文状态（敏感）”，并明确：

- 该文件可复制复用。
- 该文件泄露等同登录态泄露。
- Agent 不读取、不展示、不上传该文件内容。
- 旧 `.bin` 密文不会被新版本读取；需要重新登录捕获或重新保存生成 `.json`。

## 质量要求

1. KISS：只改 Rufus browser state store，不改 auth `Crypto` 和通用 credential store。
2. DRY：保留现有 record 结构，避免新增重复状态格式。
3. YAGNI：不做旧 `.bin` 迁移兼容，不引入多版本状态格式兼容层。
4. SOLID：存储格式变化只由 `RufusBrowserStateStore` 负责，`RufusBackendSecretProvider` 继续依赖其 `load()` 抽象。

## 测试要求

1. 单测覆盖明文 JSON 可读。
2. 单测覆盖 `.browser-state-key` 不再生成。
3. 单测覆盖 `curl_data.cookies` 在文件中明文存在。
4. 单测覆盖 CLI/Manager 返回仍不包含敏感值。
5. 单测覆盖 `delete()` 只清理 `.json`。
6. 单测覆盖 `.json` 缺失且 legacy `.bin` 存在时 `load()` 仍返回 `None`。
7. 回归测试覆盖 `RufusBackendSecretProvider.load()` 继续可读取 cookie、seed、payload template。
