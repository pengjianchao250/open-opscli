# ops-amazon-rufus 明文浏览器状态架构

## 当前架构

```text
watch-login / save-state / save-cookie / save-curl
  -> RufusManager
  -> RufusBrowserStateStore.save()
  -> Crypto.encrypt(JSON)
  -> browser-state-<COUNTRY>.bin
  -> .browser-state-key

amazon_rufus_get
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load()
  -> RufusBrowserStateStore.load()
  -> Crypto.decrypt(bytes)
  -> JSON record
```

## 目标架构

```text
watch-login / save-state / save-cookie / save-curl
  -> RufusManager
  -> RufusBrowserStateStore.save()
  -> JSON text
  -> browser-state-<COUNTRY>.json

amazon_rufus_get
  -> RufusManager.get_backend()
  -> RufusBackendSecretProvider.load()
  -> RufusBrowserStateStore.load()
  -> json.loads(text)
  -> JSON record
```

## 文件布局

新格式：

```text
~/.config/opscli/amazon-rufus/browser-state-US.json
```

历史旧格式，新代码不处理：

```text
~/.config/opscli/amazon-rufus/browser-state-US.bin
~/.config/opscli/amazon-rufus/.browser-state-key
```

新实现不创建、读取或删除 `.browser-state-key`；也不读取、解密、迁移或删除旧 `.bin`。

## 存储格式

明文文件直接保存现有 record 结构：

```json
{
  "country": "US",
  "marketplace_origin": "https://www.amazon.com",
  "captured_at": 1710000000000,
  "storage_state": {
    "cookies": [],
    "origins": []
  },
  "curl_data": {
    "url": "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
    "headers": {},
    "cookies": "session-id=abc",
    "payload_template": {}
  },
  "seed_request": {
    "request_url": "https://www.amazon.com/rufus/cl/streaming?tabId=tab-1",
    "page_url": "https://www.amazon.com/dp/B0TEST1234",
    "tab_id": "tab-1",
    "asin": "B0TEST1234",
    "country": "US",
    "captured_at": 1710000000000
  }
}
```

## 模块变更

### `RufusBrowserStateStore`

职责保持不变：只负责 Rufus browser state 的本地持久化、读取、删除和 Cookie header 派生。

变更点：

1. 移除 `Crypto` import。
2. 移除 `self._crypto`，避免实例化 store 时自动创建 `.browser-state-key`。
3. `_state_path()` 返回 `.json` 文件。
4. `save()` 使用 `path.write_text(..., encoding="utf-8")` 写入 JSON。
5. `load()` 使用 `path.read_text(encoding="utf-8")` 读取 JSON。
6. `load()` 在 `.json` 不存在时直接返回 `None`，不 fallback 到 `.bin`。
7. `delete()` 只删除新 `.json`。
8. 注释和异常文案从“无法解密”调整为“格式无效”。

#### `load()` 读取顺序

```text
load(country)
  -> if browser-state-COUNTRY.json exists:
       read JSON -> validate record -> return
  -> else:
       return None
```

#### record 校验

`load()` 不应只做 `json.loads()`。读取 `.json` 后要校验：

1. 顶层是 dict。
2. `storage_state` 是 dict。
3. `storage_state.cookies` 是 list。
4. `storage_state.origins` 是 list。
5. 如果存在 `curl_data`，其 `url`、`headers`、`cookies`、`payload_template` 能被 `RufusBackendSecretProvider` 继续规范化。

其中第 5 点仍由 provider 做最终语义校验；store 只做基础结构校验，避免职责扩散。

### `RufusBackendSecretProvider`

主流程不需要结构性改动。

文案变更：

- “从加密状态中还原”改为“从本地状态中还原”。
- “加密保存的 curl 数据”改为“本地保存的 curl 数据”。

### `RufusManager`

主流程不需要结构性改动。

文案变更：

- `save_state()` 注释改为“捕获并明文保存”或“捕获并保存”。
- `save_cookie()` 注释改为“保存为 Rufus 本地状态”。
- `save_curl()` 注释改为“保存为 Rufus 后端请求状态”。

### CLI

CLI 输出不新增状态路径，也不输出文件内容。

已有注释中“只允许从 stdin 读取并加密保存”需要改为“只允许从 stdin 读取并保存到本地状态”。

## 兼容策略

不兼容旧密文。

规则：

1. `.json` 是唯一可读状态文件。
2. `.json` 不存在时，`load()` 返回 `None`。
3. `.bin` 即使存在也不读取、不解密、不迁移。
4. `.browser-state-key` 即使存在也不读取、不删除。
5. 用户需要通过 `watch-login`、`save-state` 或底层保存入口生成新的 `.json`。

清理规则：

1. `delete()` 只删除同国家的 `.json`。
2. `save()` 只写入新 `.json`。
3. `load()` 不产生写入或迁移动作。

## 登录态使用影响面

### 写入入口

1. `RufusManager.save_state()`：捕获当前 CDP context 的 `storage_state`，写入 `.json`。
2. `RufusManager.watch_login()`：登录检测成功后捕获 `storage_state` 和 streaming seed，写入 `.json`。
3. `RufusManager.save_cookie()`：将 Cookie header 转换为最小 `storage_state`，写入 `.json`。
4. `RufusManager.save_curl()`：将 Copy-as-cURL 转换为 `storage_state`、`curl_data`、`seed_request`，写入 `.json`。

### 读取入口

1. `RufusManager.cookie_status()`：读取 `.json` 状态并返回脱敏摘要。
2. `RufusBackendSecretProvider.load()`：读取 `.json` 状态并生成 `RufusSecret`。

### 消费入口

1. `RufusManager.get_backend()`：读取 `RufusSecret`，优先复用同 ASIN seed，否则将 `storage_state` / cookies 交给 headless capture。
2. `HeadlessRufusCaptureService.capture_seed_request()`：使用 `storage_state` 创建 browser context，或用 Cookie header 注入 cookie。
3. `HeadlessRufusClient.query()`：使用 secret 中的 cookies、headers、payload template 调 Rufus streaming。

### 删除入口

1. `RufusManager.logout()`：调用 store 删除新 `.json` 状态，再按参数清理 opscli-owned Chrome profile。
2. `BrowserAttachService.clear_owned_profile()`：只清理本地调试 Chrome profile，不处理状态文件。

### 文案与测试入口

1. `opscli/amazon_rufus/commands/cli.py`：所有状态相关命令输出仍为脱敏摘要。
2. `opscli/skills/templates/ops-amazon-rufus` 和 `.agents/skills/ops-amazon-rufus`：从“加密状态”改为“明文敏感状态”，并说明旧 `.bin` 不再读取。
3. `tests/amazon_rufus/test_core.py`：更新 encrypted 命名、文件路径、明文断言和 no legacy fallback 断言。
4. `tests/mcp/test_amazon_rufus_tools.py`：继续断言 MCP 不暴露 `storage_state`、headers、payload、cookie。
5. `tests/skills/test_ops_amazon_rufus_updater.py`：继续断言 Skill 不引导手动 cookie/curl 暴露，新增明文敏感状态文案断言。

## 安全边界

明文状态文件是敏感文件。

继续保留的保护：

1. 文件权限设置为 `0600`。
2. CLI/MCP 返回只展示摘要，不展示 secret。
3. MCP schema 不新增 cookie、curl、headers、payload、storage_state 参数。
4. Skill 不引导用户粘贴或上传敏感请求材料。
5. 报告不输出 `curl_data`、`storage_state`、headers、payload 或完整 streaming 请求。

用户侧新增事实：

1. 复制 `browser-state-<COUNTRY>.json` 即可能复制登录态。
2. 泄露该文件等同泄露 Amazon 会话凭证。
3. 旧 `.bin` 文件不会被新版本读取；需要重新登录捕获或重新保存生成 `.json`。

## 实现顺序

1. 更新测试为明文 JSON 预期，先跑 RED。
2. 新增 no legacy fallback 测试，先跑 RED。
3. 修改 `RufusBrowserStateStore`。
4. 修改 `RufusBackendSecretProvider`、`RufusManager`、CLI 注释和文案。
5. 修改 Skill 模板与 `.agents` 副本。
6. 更新 `docs/change-log-pending.md`。
7. 跑 Rufus 核心、MCP 和 Skill 文档契约回归。
