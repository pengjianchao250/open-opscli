# amazon-rufus-auth-boundary Tasks

- [x] 1. 写失败测试：平台 Cookie 401 错误边界
  - [x] 1.1 在 `tests/amazon_rufus/test_transport.py` 覆盖 GET `/v1/platform-cookies` HTTP 401 映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
  - [x] 1.2 在 `tests/amazon_rufus/test_transport.py` 覆盖 POST `/v1/platform-cookies` HTTP 401 映射为 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
  - [x] 1.3 覆盖新错误 `to_dict()` 保留 `status_code=401` 且不包含敏感字段。
  - [x] 1.4 覆盖 `/v1/rufus/upload` HTTP 401 仍返回 `RUFUS_REMOTE_HTTP_ERROR`。

- [x] 2. 实现平台 Cookie 401 专用错误
  - [x] 2.1 在 `opscli/amazon_rufus/domain/exceptions.py` 新增 `RufusPlatformCookieAuthError`，使用中文 docstring。
  - [x] 2.2 在 `opscli/amazon_rufus/transport/client.py` 为平台 Cookie GET/POST 添加 401 映射辅助逻辑。
  - [x] 2.3 保持非 401 平台 Cookie HTTP 错误和 Rufus upload 错误语义不变。

- [x] 3. 写失败测试：Manager 状态和登出副作用顺序
  - [x] 3.1 在 `tests/amazon_rufus/test_core.py` 覆盖 `login_status()` 遇到平台 API 401 抛出 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR`。
  - [x] 3.2 覆盖 `login_status()` 遇到平台 API 404 或 missing content 返回 `status=missing`。
  - [x] 3.3 覆盖 `logout()` 遇到平台 API 401 不调用 `clear_owned_profile()`。
  - [x] 3.4 覆盖 `logout()` 远端清理成功后才按参数清理本机 profile。

- [x] 4. 实现 Manager 错误透传和登出保护
  - [x] 4.1 确认 `RufusBrowserStateStore.load()` 对平台 API 401 不吞错、不降级为 missing。
  - [x] 4.2 确认 `RufusBrowserStateStore.delete()` 对平台 API 401 不吞错。
  - [x] 4.3 调整 `RufusManager.login_status()`，让平台 API 401 直接失败退出。
  - [x] 4.4 调整 `RufusManager.logout()`，确保远端失败时不清理本机 profile。

- [x] 5. 写失败测试：MCP 当前请求凭证隔离
  - [x] 5.1 在 `tests/mcp/test_amazon_rufus_tools.py` monkeypatch `_get_credential_dir()`，断言 MCP Rufus manager 使用该 base_dir。
  - [x] 5.2 覆盖 `_get_credential_dir()` 返回 `None` 时保持 stdio/CLI 默认凭证行为。
  - [x] 5.3 覆盖隔离凭证缺失时返回 OPS/MCP 鉴权错误，不误报 `RUFUS_SECRET_NOT_READY`。
  - [x] 5.4 覆盖 content 命中时 MCP 输出仍过滤敏感字段。

- [x] 6. 实现 MCP Rufus manager 工厂
  - [x] 6.1 在 `opscli/mcp/tools/amazon_rufus.py` 新增 `_rufus_manager_for_current_request()`。
  - [x] 6.2 HTTP/SSE 模式使用 `_get_credential_dir()` 创建 `AuthClient(base_dir=cred_dir)`。
  - [x] 6.3 stdio 模式继续使用默认 `AuthClient()`，保持 CLI 兼容。
  - [x] 6.4 让 `amazon_rufus_get` 使用新工厂，保持 MCP schema 不变。

- [x] 7. 同步 Skill 恢复规则
  - [x] 7.1 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md`，新增 `RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 禁止 `watch-login` 规则。
  - [x] 7.2 更新 `opscli/skills/templates/ops-amazon-rufus/README.md`。
  - [x] 7.3 更新 `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`。
  - [x] 7.4 同步 `.agents/skills/ops-amazon-rufus/` 对应副本。
  - [x] 7.5 更新 `tests/skills/test_ops_amazon_rufus_updater.py`，验证模板与副本包含限制且不要求用户复制敏感 content。

- [x] 8. 变更记录与回归验证
  - [x] 8.1 追加 `docs/change-log-pending.md`，说明原因、改动点、验证结果、影响范围和回滚方式。
  - [x] 8.2 运行 `pytest tests/amazon_rufus/test_transport.py -v`。
  - [x] 8.3 运行 `pytest tests/amazon_rufus/test_core.py -v`。
  - [x] 8.4 运行 `pytest tests/mcp/test_amazon_rufus_tools.py -v`。
  - [x] 8.5 运行 `pytest tests/skills/test_ops_amazon_rufus_updater.py -v`。
  - [x] 8.6 扫描 Rufus/Skill 输出文档，确认不包含 JWT、session、Cookie、headers、payload、`storage_state`、`curl_data` 或平台 Cookie content 原文。
