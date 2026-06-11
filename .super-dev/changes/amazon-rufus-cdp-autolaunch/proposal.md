# amazon-rufus CDP 自动启动方案

## 背景

`opscli amazon-rufus get` 依赖 Chrome CDP。当前 CDP 未启动时，普通获取会直接返回 `CHROME_CDP_UNAVAILABLE`，用户需要手动查找 Chrome 并拼写 remote debugging 启动命令。现有 CLI 已预留 `--launch-if-needed` 和 `--chrome-path`，但参数尚未落地。

## 目标

1. `--launch-if-needed` 先检查 CDP，CDP 不可用时自动搜索并启动 Chrome。
2. `--chrome-path` 作为最高优先级 Chrome 可执行文件路径。
3. MCP `amazon_rufus_get` 同步支持 `launch_if_needed` 和 `chrome_path`。
4. Skill 文档增加 `CHROME_CDP_UNAVAILABLE` 的可恢复处理分支。
5. 启动 Chrome 使用 Python 参数列表，不要求用户手写 PowerShell。

## 非目标

1. 不在 Skill 目录新增 Python 启动脚本。
2. 不安装、更新或卸载 Chrome。
3. 不修改系统环境变量、注册表或默认浏览器设置。
4. 不复用用户默认 Chrome profile 开启 remote debugging。
5. 不改变 Rufus seed 捕获、replay、报告生成和题库解析逻辑。

## 设计

实现集中在 `BrowserAttachService`：

```text
capture_seed_request(...)
  -> ensure_cdp_available(...)
    -> check_cdp(cdp_url)
    -> resolve_chrome_executable(chrome_path)
    -> start_chrome_for_cdp(...)
    -> wait_for_cdp(cdp_url)
  -> connect_over_cdp(cdp_url)
```

Chrome 搜索优先级：

1. 显式 `chrome_path`
2. Windows 注册表 App Paths
3. Windows 常见安装路径
4. PATH 中的 `chrome` / `chrome.exe`
5. macOS/Linux 常见 Chrome/Chromium 路径

启动参数必须包含独立 profile：

```text
--remote-debugging-address=127.0.0.1
--remote-debugging-port=<port>
--user-data-dir=<opscli Rufus profile>
--no-first-run
--no-default-browser-check
```

## 验收

1. CDP 已可用时不启动 Chrome。
2. CDP 不可用且 `launch_if_needed=True` 时搜索并启动 Chrome。
3. 找不到 Chrome 时返回 `CHROME_CDP_UNAVAILABLE` 并提示 `chrome_path`。
4. CLI 参数实际透传到 Manager / Browser。
5. MCP 参数实际透传到 Manager。
6. Skill 文档覆盖 CDP 自动启动和失败后的下一步。
