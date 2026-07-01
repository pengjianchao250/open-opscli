# Rufus 打开 Amazon 页面不打开控制台 - Architecture

## 当前架构

```text
CLI watch-login
  -> RufusManager.watch_login
  -> BrowserAttachService.watch_login_and_capture_seed_request
  -> BrowserAttachService._ensure_cdp_ready
  -> BrowserAttachService._start_new_chrome
  -> Chrome/Edge with remote debugging
  -> Playwright connect_over_cdp
  -> context.new_page
  -> page.goto(Amazon)
```

控制台是否自动打开主要由 Chrome 启动参数和 profile 偏好共同决定。

## 设计原则

1. KISS：只修复 opscli 自建 profile 的 DevTools 自动打开行为。
2. YAGNI：不新增 CLI 配置项，不做通用浏览器偏好管理器。
3. DRY：复用 `_start_new_chrome()` 中已计算的 profile 目录。
4. SOLID：把偏好清理作为 `BrowserAttachService` 的内部私有方法，不泄漏到 Manager、CLI 或 MCP schema。

## 推荐实现

### 新增私有方法

在 `opscli/amazon_rufus/services/browser.py` 中新增：

```python
def _disable_auto_open_devtools(self, profile_dir: Path) -> None:
    """关闭 opscli 自建 Rufus profile 中的 DevTools 自动打开偏好。"""
```

职责：

1. 只处理传入的 opscli Rufus profile 目录。
2. 尝试读取 profile 下可能存在的 Preferences / Local State JSON。
3. 删除或关闭 DevTools 自动打开相关偏好。
4. 文件不存在、格式异常、写入失败时静默跳过，不阻断浏览器启动。

### 接入点

在 `_start_new_chrome()` 中：

```text
profile_dir = ~/.opscli/chrome-profiles/amazon-rufus-<port>
profile_dir.mkdir(...)
_disable_auto_open_devtools(profile_dir)
subprocess.Popen([...])
```

这样只影响 opscli 自己要启动的浏览器。

### 启动参数保持

继续保留：

```text
--remote-debugging-port=<port>
--user-data-dir=<profile_dir>
--no-first-run
--no-default-browser-check
```

继续禁止：

```text
--auto-open-devtools-for-tabs
```

可作为后续独立加固项评估：

```text
--remote-debugging-address=127.0.0.1
```

本轮不强制纳入，避免扩大范围。

## 测试策略

### 已有测试延续

`test_browser_start_new_chrome_does_not_auto_open_devtools` 继续断言启动参数不包含自动打开 DevTools flag。

### 新增测试一：清理 profile 偏好

构造临时 profile：

```text
tmp/.opscli/chrome-profiles/amazon-rufus-9333/Default/Preferences
```

写入 DevTools 自动打开相关字段，调用 `_start_new_chrome()` 后断言字段被删除或置为关闭。

### 新增测试二：不删除无关数据

同一 Preferences 中写入无关字段，调用后断言仍存在。

### 新增测试三：异常宽容

Preferences 文件为非法 JSON 时，调用 `_start_new_chrome()` 不抛错，仍调用 `subprocess.Popen()`。

## 影响范围

1. 仅影响 `BrowserAttachService._start_new_chrome()` 自动启动 Chrome/Edge 的路径。
2. 不影响已运行 CDP 浏览器。
3. 不影响 MCP `amazon_rufus_get` 默认后端/headless 获取。
4. 不影响 Rufus 登录态保存、报告生成、题库加载和回答质量判断。

## 回滚方式

如出现兼容问题，删除新增私有方法和 `_start_new_chrome()` 中的调用即可。已有“不包含 `--auto-open-devtools-for-tabs`”测试仍应保留。

