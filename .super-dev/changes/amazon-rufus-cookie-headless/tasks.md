# amazon-rufus-cookie-headless Tasks

## 任务

- [x] 增加 cookie headless 获取的单元测试
- [x] 新增 headless 捕获服务，封装 Playwright cookie 注入与 `rufus/cl/streaming` 捕获
- [x] 新增 headless Rufus client，封装 streaming 请求与 SSE 解析
- [x] 在 `RufusManager` 增加 `get_headless(..., cookie=...)`
- [x] 运行定向测试并更新 `docs/change-log-pending.md`

## 验证命令

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run pytest "tests/amazon_rufus/test_core.py" -q
```
