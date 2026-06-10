# amazon-rufus-plaintext-state Tasks

## 1. 测试先行

- [x] 更新 browser state store 单测：断言保存为 `.json`，文件可读且包含明文 cookie/localStorage。
- [x] 更新 seed/curl/cookie 保存单测：断言 `.json` 明文包含 `curl_data.cookies`，CLI/Manager 返回仍脱敏。
- [x] 新增 no legacy fallback 单测：仅存在 `browser-state-<COUNTRY>.bin` 时 `load()` 返回 `None`。
- [x] 更新 delete 单测：只删除 `.json`，不处理旧 `.bin` 或 `.browser-state-key`。

## 2. 实现

- [x] `RufusBrowserStateStore` 移除 `Crypto` 依赖和 `_crypto` 字段。
- [x] `_state_path()` 改为 `browser-state-<COUNTRY>.json`。
- [x] `save()` 改为 UTF-8 明文 JSON 写入，并保持 `0600` 权限。
- [x] `load()` 改为读取 UTF-8 JSON；`.json` 不存在时返回 `None`。
- [x] `delete()` 只删除 `.json`。
- [x] 更新 backend secret、manager、CLI 注释中“加密”相关文案。

## 3. Skill 和文档

- [x] 更新模板 Skill 与 `.agents` 副本：本地加密状态 -> 本地明文状态（敏感）。
- [x] 更新 workflow reference：说明旧 `.bin` 不再读取，需重新捕获生成 `.json`。
- [x] 更新 Skill 文档契约测试。
- [x] 更新 `docs/change-log-pending.md`。

## 4. 验证

- [x] 运行 Rufus 状态相关定向测试并确认 RED/GREEN。
- [x] 运行 `tests/amazon_rufus/test_core.py`。
- [x] 运行 `tests/mcp/test_amazon_rufus_tools.py`。
- [x] 运行 `tests/skills/test_ops_amazon_rufus_updater.py`。
- [x] 运行必要的文案残留扫描。
