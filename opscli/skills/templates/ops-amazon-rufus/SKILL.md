---
name: ops-amazon-rufus
description: Amazon Rufus 默认题库数据、单题问题获取、拒答改写重试与报告格式化规范。用于执行 opscli amazon-rufus get、通过 --question 回答指定 ASIN/Rufus 商品问题、按默认题库生成报告、读取或格式化 output/amazon-rufus/*.md 报告。
---

# ops-amazon-rufus

提供 `opscli amazon-rufus get <asin> <country>` 所需的默认题库数据，并定义通过 `--question` 直接提问时的执行规则。

## 前置条件

使用本 Skill 前，必须先在对应国家站点登录 Amazon 账户。不同国家站点的登录态相互独立，例如 `US` 对应 `amazon.com`，`DE` 对应 `amazon.de`。

PowerShell 下通过 `uv run` 执行任何 `opscli amazon-rufus` 或 `opscli skills upgrade ops-amazon-rufus` 命令前，推荐在同一命令行设置 UTF-8 环境与本地开发构建开关，避免状态提示乱码，并跳过源码仓库内的 Cython 编译。完整 Rufus 答案报告不依赖终端历史，命令成功后会写入运行目录下的 `output/amazon-rufus`。推荐统一使用以下前缀：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1";
```

推荐使用初始化命令打开固定 Chrome profile 的登录窗口：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus init US
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

## 问题来源选择

当用户已经给出明确 Rufus 问题时，优先使用 `--question` 单题模式，不要默认跑完整题库：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome --question "这个商品适合送礼吗？"
```

当用户只提供 ASIN 和国家，或要求“默认报告”“完整分析”“跑题库”时，使用默认题库模式：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome
```

单题模式一次只传入一个问题。用户要求多个临时问题时，逐条执行 `--question`，或在用户接受时改用默认题库模式。

## 拒答处理

执行 Rufus 获取后，需要判断答案是否属于拒绝回答。若检测到拒答，系统应在保持原问题语义的前提下改写问题，并满足以下规则：

1. 改写问题不得超过 180 字。
2. 改写后的问题必须使用中文；原问题为英文或中英混合时，也要转写为自然中文问题。
3. 保留商品对象、比较对象、分析维度和用户意图。
4. 使用中性、基于商品页面和公开评价的表达。
5. 最多改写并重试 3 次；加上原问题首次执行，单题最多 4 次尝试。
6. 3 次改写重试后仍拒答时，保留最后一次结果并在报告中说明已达到重试上限。

发生拒答改写时，最终回复用户只说明已自动改写并重试，并给出报告路径；除非用户明确要求排障，不输出首次拒答全文、`seed_request`、`upload_payload`、headers 或原始 JSON。

## 最新数据优先

当用户询问 ASIN 的 Rufus 分析、商品判断、报告内容或要求输出报告时，默认必须重新执行 `opscli amazon-rufus get <asin> <country>` 获取最新数据，不得直接使用 `output/amazon-rufus` 下的历史报告作答。

只有在用户明确要求“历史数据”“已有报告”“指定文件路径”“不要重新获取”时，才读取历史报告或指定文件。若用户未提供 ASIN 或国家站点，先补齐必要参数；不要用历史报告替代最新获取。

PowerShell 下通过 `uv run` 执行 `opscli` 命令前必须在当前命令会话设置 UTF-8 环境与本地开发构建开关：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome
```

如果用户提供明确问题，改用：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome --question "请分析该商品的主要差评风险"
```

如需切换国家，请先执行对应国家的初始化命令并完成该站点登录，例如：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus init DE
```

命令执行成功后只输出报告保存路径，例如 `Rufus 答案报告已保存：output/amazon-rufus/B0TEST1234-20260430-101530.md`。完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`，文件名时间精确到秒。除非用户明确要求排障，不输出 `seed_request`、`upload_payload`、headers 或原始 JSON。

说明：`--new-chrome` 命令完成后默认关闭本次新开的 Chrome 调试窗口；如需保留窗口，使用 `--new-chrome --keep-chrome-open`。

手动启动 Chrome 的命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'
```

## 数据文件

- `data/question_templates.json`：合并模板与题目的默认题库
- `references/question-templates.md`：问题模板获取、保存和本地题库文件结构说明；该文件只包含问题模板相关内容。

## 报告格式化

每次生成或输出 `output/amazon-rufus/*.md` 报告后，都必须读取 `references/rufus-report-formatting.md`，并在同目录额外写出格式化后的 Markdown 文档。格式化必须完整保留 Rufus 原始输出内容，只做 Markdown 标题、列表、表格、代码块、引用块、空行与缩进等格式化处理。

回复用户时同时给出原始报告路径和格式化报告路径；除非用户只要求排障，不输出 `seed_request`、`upload_payload`、headers 或原始 JSON。
