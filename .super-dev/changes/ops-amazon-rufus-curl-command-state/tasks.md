# ops-amazon-rufus cURL 命令态任务清单

## 任务 1：测试新状态结构

- [x] 在 `tests/amazon_rufus/test_core.py` 中更新本地和远端状态保存断言，要求本地 fallback 保存 `version=2` 和 `curl` 字符串，远端平台 Cookie content 直接保存 cURL 字符串。
- [x] 增加 `RufusBackendSecretProvider` 只解析新 `curl` 的测试。
- [x] 增加旧 `curl_data` 缺少 `curl` 时抛出 `RufusSecretNotReadyError` 的测试。
- [x] 增加 `login_status` 只按 `curl` 判定可用性的测试。
- [x] 运行目标测试并确认新增/更新测试先失败。

## 任务 2：实现保存端 cURL 命令态

- [x] 在 `RufusBrowserStateStore` 中构造单行 browser-like cURL 命令。
- [x] 远端 content 直接保存 cURL 命令态；本地 fallback 保存 `version=2`、`curl` 和脱敏 `seed_request` 元数据。
- [x] 删除保存端 `curl_data`、顶层 `headers`、顶层 `payload_template`、顶层 `streaming_url` 写入。
- [x] 保持 Cookie/header/payload 不进入 CLI/MCP 输出。

## 任务 3：实现读取端新结构解析

- [x] 在 `RufusBackendSecretProvider` 中注入或实例化 `RufusCurlParser`。
- [x] 只从 cURL 命令解析 URL、headers、cookies、payload_template；远端裸 cURL 先包装为内部 `record["curl"]`。
- [x] 删除 `_normalize_curl_data()`、旧字段 fallback 和 `storage_state` fallback。
- [x] 用解析后的 payload 还原可复用 `SeedRequestRecord`。

## 任务 4：同步登录态检查和文档

- [x] 修改 `RufusManager.login_status()`，基于新 `curl` 判断 `can_get_backend`。
- [x] 更新 `opscli/skills/templates/ops-amazon-rufus/README.md` 和 reference 文档中的敏感字段/状态说明。
- [x] 追加 `docs/change-log-pending.md` 变更记录。

## 任务 5：验证

- [x] 运行 `uv run pytest tests/amazon_rufus/test_core.py -v`。
- [x] 运行 `uv run pytest tests/amazon_rufus/test_mcp_manager.py tests/mcp/test_amazon_rufus_tools.py -v`。
- [x] 运行 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py -v`。
- [x] 执行最小 diff review，确认没有旧兼容代码残留和敏感输出扩散。
