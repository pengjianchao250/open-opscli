# amazon-rufus-login-resume Tasks

## 1. 测试先行

- [x] 1.1 新增 `RufusManager.get()` 空答案时抛出 `RUFUS_LOGIN_REQUIRED` 的测试。
- [x] 1.2 新增 `BrowserAttachService.capture_seed_request()` 在回调要求保留窗口时不关闭 Chrome 的测试。
- [x] 1.3 新增 CLI 错误 payload 包含 `RUFUS_LOGIN_REQUIRED` 的测试。
- [x] 1.4 运行新增测试并确认按预期失败。

## 2. 实现

- [x] 2.1 在 `opscli/amazon_rufus/domain/exceptions.py` 新增 `RufusLoginRequiredError`。
- [x] 2.2 在 `BrowserAttachService.capture_seed_request()` 支持 `on_captured` 返回保留窗口信号。
- [x] 2.3 在 `RufusManager.get()` 增加空答案判定和登录中断异常。
- [x] 2.4 确认 CLI 复用现有 `_error_payload()` 输出稳定错误码。

## 3. Skill 文档

- [x] 3.1 更新 `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 的登录中断续跑规则。
- [x] 3.2 同步更新 `.agents/skills/ops-amazon-rufus/SKILL.md`。

## 4. 验证与记录

- [x] 4.1 运行定向测试：`uv run pytest "tests/amazon_rufus/test_core.py" -k "login_required or callback_requests or outputs_login_required" -q`。
- [x] 4.2 运行模块回归：`uv run pytest "tests/amazon_rufus/test_core.py" -q`。
- [x] 4.3 使用 `rg` 检查两份 Skill 文档命中 `RUFUS_LOGIN_REQUIRED` 和 `继续告诉我`。
- [x] 4.4 更新 `docs/change-log-pending.md`。
- [x] 4.5 回读 diff，确认本轮新增文件与代码改动聚焦 Rufus 登录续跑；两份 Skill 文档中存在既有 listing 触发未提交改动，未回退。
