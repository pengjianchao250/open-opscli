# amazon-rufus-login-guidance Tasks

## 1. 测试先行

- [x] 1.1 新增 `skills install ops-amazon-rufus` 成功输出登录提示测试。
- [x] 1.2 新增普通 Skill 安装不包含 Rufus 登录提示测试。
- [x] 1.3 新增交互安装结果包含 Rufus 登录提示测试。
- [x] 1.4 新增未捕获 `/rufus/cl/streaming` 时提示 `opscli amazon-rufus init <country>` 的测试。
- [x] 1.5 运行新增测试并确认按预期失败。

## 2. 实现

- [x] 2.1 在 `opscli/skills/commands/cli.py` 增加安装后提示 helper。
- [x] 2.2 非交互安装路径调用 helper。
- [x] 2.3 交互安装路径调用 helper。
- [x] 2.4 在 `BrowserAttachService.capture_seed_request()` 中增强 `SeedRequestNotCapturedError` 文案。

## 3. 验证

- [x] 3.1 运行目标测试：`pytest tests/skills/test_cli.py tests/amazon_rufus/test_core.py -q`。
- [ ] 3.2 若目标测试通过，运行更宽的相关测试：`pytest tests/skills tests/amazon_rufus -q`。
- [x] 3.3 检查 diff，确认本次实现只涉及 skills CLI、Rufus browser 错误文案、对应测试与 Super Dev 文档。

备注：`uv run pytest tests/skills tests/amazon_rufus -q` 已执行，当前失败集中在既有 Windows 路径分隔断言和 `E:\Users\mask\python3\opscli\...` 绝对路径缺失，不属于本次 Rufus 登录提示改动。
