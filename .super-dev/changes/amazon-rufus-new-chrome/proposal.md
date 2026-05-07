# Proposal: amazon-rufus new Chrome launch

## 背景

`opscli amazon-rufus get` 当前只能连接已存在的 Chrome DevTools 端口。实际使用中，用户希望命令可先新开一个独立 Chrome 调试窗口，再连接该窗口继续 Rufus 采集流程。

## 目标

- 为 `opscli amazon-rufus get` 增加 `--new-chrome` 参数。
- 传入 `--new-chrome` 时，先启动独立 Chrome 调试窗口。
- 启动命令使用固定 Windows 命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

- 启动后继续通过 `connect_over_cdp()` 连接 `--cdp-url`，默认 `http://127.0.0.1:9222`。
- 未传 `--new-chrome` 时保持现有行为。

## 非目标

- 不改 Rufus seed request 捕获与 replay 逻辑。
- 不改变默认 CDP 地址。
- 不引入跨平台 Chrome 启动策略。
- 不自动处理 Amazon 登录流程。
