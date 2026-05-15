# amazon-rufus-login-resume Proposal

## 背景

`ops-amazon-rufus` 依赖对应国家站点的 Amazon 登录态。当前 `amazon-rufus get` 在已捕获 Rufus seed request 但 replay 没有返回可用答案时，可能继续生成空答案报告；如果命令使用 `--new-chrome`，本次新开的 Chrome 默认会在命令结束时关闭，用户无法在同一窗口完成登录后继续。

## 目标

1. 调用 Skill 时仍先按正常流程执行 `opscli amazon-rufus get`。
2. 当 replay 后没有可用答案时，返回稳定错误码 `RUFUS_LOGIN_REQUIRED`。
3. 触发 `RUFUS_LOGIN_REQUIRED` 时保留浏览器窗口，不关闭本次新开的 Chrome。
4. Skill 文档要求 Agent 停止执行，并提示用户：如果登录完成，请继续告诉我，我会继续执行。
5. 用户说“继续”后，Agent 复用上一轮 ASIN、国家、问题和 Chrome 参数重新执行 Rufus 获取。

## 非目标

1. 不在 CLI 内部等待用户输入。
2. 不自动登录 Amazon，不处理账号、密码或 MFA。
3. 不新增后台任务、持久化队列或跨会话恢复存储。
4. 不改变正常成功报告的文件输出格式。
5. 不把未捕获 `/rufus/cl/streaming` 的场景并入本错误码，该场景继续使用 `SEED_REQUEST_NOT_CAPTURED`。

## 技术方案

### 业务异常

在 `opscli/amazon_rufus/domain/exceptions.py` 新增 `RufusLoginRequiredError`，继承 `RufusError`，错误码为 `RUFUS_LOGIN_REQUIRED`。

### 浏览器生命周期

将 `BrowserAttachService.capture_seed_request()` 的 `on_captured` 回调扩展为可返回布尔值。返回 `True` 表示本次 capture 后需要保留新开的 Chrome。关闭判断改为：

```python
if new_chrome and not keep_chrome_open and not keep_open_after_capture:
    self._close_new_chrome(browser)
```

### 空答案判定

在 `RufusManager.get()` 中判断答案是否可用：

1. `answers` 为空，视为未获取到答案。
2. `answers` 非空但所有答案均无 `text`、`html`、`summary_text`，视为未获取到答案。
3. 只要存在一个非空答案，就继续按现有流程生成报告。

当页面内 replay 已返回空答案时，回调返回 `True`，让浏览器保留；随后 Manager 抛出 `RufusLoginRequiredError`。

### Skill 对话规则

更新模板 Skill 和当前安装副本：

1. 遇到 `RUFUS_LOGIN_REQUIRED` 时停止执行。
2. 不继续重试，不关闭浏览器。
3. 提示用户登录完成后说“继续”。
4. 用户说“继续”后复用上一轮参数重新执行同一条 `amazon-rufus get`。

## 验收标准

1. `RufusManager.get()` 在 replay 返回空答案时抛出 `RUFUS_LOGIN_REQUIRED`。
2. `BrowserAttachService.capture_seed_request()` 在 `on_captured` 返回 `True` 时不关闭新 Chrome。
3. CLI 失败输出包含 `RUFUS_LOGIN_REQUIRED` 和“如果登录完成，请继续告诉我，我会继续执行”。
4. 两份 `ops-amazon-rufus/SKILL.md` 包含登录中断续跑规则。
5. `tests/amazon_rufus/test_core.py` 定向测试通过。

