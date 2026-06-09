# amazon-rufus-plaintext-state Proposal

## 背景

Rufus 当前把 Amazon `storage_state`、cookies、localStorage、`curl_data` 和 streaming seed 保存为本地 AES 加密 `.bin` 文件，并依赖 `.browser-state-key` 解密。用户明确要求去掉这层加密，改为直接明文保存，方便复制状态文件到其他环境复用。

## 目标

1. 将 Rufus 本地状态文件改为 `browser-state-<COUNTRY>.json`。
2. 状态内容使用 UTF-8 明文 JSON 保存。
3. 移除 Rufus browser state store 对 `Crypto` 和 `.browser-state-key` 的依赖。
4. 不做旧 `.bin` 密文迁移兼容；`.json` 不存在时视为无状态。
5. 保持 CLI/MCP/report 输出脱敏，不展示 cookies、headers、payload、`storage_state` 或完整请求。

## 非目标

1. 不修改 auth 通用 credential store。
2. 不新增 MCP 参数或 Skill 手动 cookie/curl 导入路径。
3. 不读取、解密、迁移或删除旧 `browser-state-<COUNTRY>.bin`。
4. 不输出状态文件路径或文件内容。

## 影响范围

1. `opscli/amazon_rufus/services/browser_state_store.py`
2. `opscli/amazon_rufus/services/backend_secret.py`
3. `opscli/amazon_rufus/services/manager.py`
4. `opscli/amazon_rufus/commands/cli.py`
5. `opscli/skills/templates/ops-amazon-rufus/*`
6. `.agents/skills/ops-amazon-rufus/*`
7. `tests/amazon_rufus/test_core.py`
8. `tests/skills/test_ops_amazon_rufus_updater.py`
9. `docs/change-log-pending.md`

## 风险

明文 JSON 包含 Amazon 登录态和 Rufus 请求上下文，复制该文件可能复制登录态。代码只保留文件权限 `0600` 和对外输出脱敏，不再提供加密保护。

