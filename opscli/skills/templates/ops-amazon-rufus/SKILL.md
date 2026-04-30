---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据与使用说明
version: v0.0.1
---

# ops-amazon-rufus

提供 `opscli amazon-rufus get <asin> <country>` 所需的默认题库数据。

## 前置条件

使用本 Skill 前，必须先在对应国家站点登录 Amazon 账户。不同国家站点的登录态相互独立，例如 `US` 对应 `amazon.com`，`DE` 对应 `amazon.de`。

PowerShell 下执行任何 `opscli amazon-rufus` 或 `opscli skills upgrade ops-amazon-rufus` 命令前，只需在同一命令行设置 UTF-8 环境，避免状态提示或错误信息乱码。完整 Rufus 答案报告不依赖终端历史，命令成功后会写入运行目录下的 `output/amazon-rufus`。推荐统一使用以下前缀：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8";
```

推荐使用初始化命令打开固定 Chrome profile 的登录窗口：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus init US
```

命令打开页面后会提示：

```text
请在新窗口中登录亚马逊
```

请在新窗口中完成对应国家站点的 Amazon 登录，再执行 Rufus 获取命令。

## 使用

1. 安装 Skill：`opscli skills install ops-amazon-rufus`
2. 同步题库：`opscli skills upgrade ops-amazon-rufus`
3. 初始化登录窗口：`opscli amazon-rufus init US`
4. 在新窗口中登录对应国家站点的 Amazon 账户
5. 执行：`opscli amazon-rufus get B0TEST1234 US --new-chrome`

PowerShell 下执行 `opscli` 命令前必须在当前命令会话设置 UTF-8 环境：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome
```

如需切换国家，请先执行对应国家的初始化命令并完成该站点登录，例如：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus init DE
```

命令执行成功后只输出报告保存路径，例如 `Rufus 答案报告已保存：output/amazon-rufus/B0TEST1234-20260430-101530.md`。完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`，文件名时间精确到秒。除非用户明确要求排障，不输出 `seed_request`、`upload_payload`、headers 或原始 JSON。

说明：`--new-chrome` 命令完成后默认关闭本次新开的 Chrome 调试窗口；如需保留窗口，使用 `--new-chrome --keep-chrome-open`。

手动启动 Chrome 的命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'
```

## 数据文件

- `data/question_templates.json`：合并模板与题目的默认题库
