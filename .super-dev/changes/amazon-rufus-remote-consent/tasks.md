# amazon-rufus-remote-consent Tasks

## 任务

- [x] 增加远程授权与 storage_state 保存的失败测试。
- [x] 新增浏览器状态捕获/保存服务。
- [x] 新增 RufusManager 远程状态获取入口，调用已有 headless Rufus 获取链路。
- [x] CLI 登录失败时接入远程获取授权分支。
- [x] 更新 Skill/README 与待归档变更记录。
- [x] 运行定向测试和 Amazon Rufus 模块回归。

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run pytest "tests/amazon_rufus/test_core.py" -q
```
