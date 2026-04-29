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

手动启动 Chrome 的命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

## 数据文件

- `data/question_templates.json`：合并模板与题目的默认题库
