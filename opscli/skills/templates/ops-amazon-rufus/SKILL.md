---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据与使用说明
version: v0.0.1
---
# ops-amazon-rufus

提供 `opscli amazon-rufus get <asin> <country>` 所需的默认题库数据。

## 使用

1. 安装 Skill：`opscli skills install ops-amazon-rufus`
2. 同步题库：`opscli skills upgrade ops-amazon-rufus`
3. 启动 Chrome 调试端口并登录 Amazon，或使用 `--new-chrome` 让命令先新开调试窗口
4. 执行：`opscli amazon-rufus get B0TEST1234 US --new-chrome`

PowerShell 下执行 `opscli` 命令前必须在当前命令会话设置 UTF-8 环境，避免中文答案乱码：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome
```

命令执行完成后只输出 `data.answers[].text`，不要输出完整 JSON。多条答案按题库顺序输出，并用空行分隔；除非用户明确要求排障，不输出 `seed_request`、`upload_payload`、headers 或原始 JSON。

说明：`--new-chrome` 命令完成后默认关闭本次新开的 Chrome 调试窗口；如需保留窗口，使用 `--new-chrome --keep-chrome-open`。

手动启动 Chrome 的命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'
```

## 数据文件

- `data/question_templates.json`：合并模板与题目的默认题库
