# ops-amazon-rufus 使用说明

`ops-amazon-rufus` 提供 `opscli amazon-rufus get <asin> <country>` 所需的默认问题模板库，并说明通过 `--question` 获取单题 Rufus 答案的执行规则。

## 常用命令

### PowerShell 本地运行前缀

PowerShell 下通过 `uv run` 执行任何 `opscli amazon-rufus` 或 `opscli skills upgrade ops-amazon-rufus` 命令前，推荐在同一命令行设置 UTF-8 环境与本地开发构建开关，避免状态提示乱码，并跳过源码仓库内的 Cython 编译。完整 Rufus 答案报告不依赖终端历史，命令成功后会写入运行目录下的 `output/amazon-rufus`：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1";
```

### 前置条件：登录对应国家站点

使用 Rufus 获取前，必须先在对应国家站点登录 Amazon 账户。不同国家站点的登录态相互独立，例如 `US` 对应 `amazon.com`，`DE` 对应 `amazon.de`。

推荐先执行初始化命令，让 opscli 使用与 Rufus 获取相同的固定 Chrome profile 打开对应站点：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus init US
```

请在新窗口中完成登录，再执行 `amazon-rufus get`。切换国家时，应先执行对应国家的初始化命令并确认该站点已登录。

### 启动 Chrome 调试窗口

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'
```

### 升级问题模板库

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli skills upgrade ops-amazon-rufus --skills-dir ".agents/skills" --pretty
```

升级成功后，问题模板库会保存到：

```text
.agents/skills/ops-amazon-rufus/data/question_templates.json
```

问题模板获取、保存和本地题库文件结构说明见 `references/question-templates.md`。本文后续只描述 Rufus 回答获取流程。

### 执行 Rufus 获取
确认新窗口已登录 Amazon 后，再执行获取命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

`--new-chrome` 默认会在命令输出结果后通过 CDP `Browser.close` 关闭本次新开的 Chrome 调试窗口。若需要保留窗口用于继续调试或复用登录态，追加：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome --keep-chrome-open
```

### 问题来源选择

当用户已经给出明确 Rufus 问题时，优先使用 `--question` 单题模式，不要默认跑完整题库：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome --question "这个商品适合送礼吗？"
```

当用户只提供 ASIN 和国家，或要求“默认报告”“完整分析”“跑题库”时，使用默认题库模式：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

单题模式一次只传入一个问题。用户要求多个临时问题时，逐条执行 `--question`，或在用户接受时改用默认题库模式。

### 拒答处理

执行 Rufus 获取后，需要判断答案是否属于拒绝回答。若检测到拒答，系统应在保持原问题语义的前提下改写问题，并满足以下规则：

1. 改写问题不得超过 180 字。
2. 改写后的问题必须使用中文；原问题为英文或中英混合时，也要转写为自然中文问题。
3. 保留商品对象、比较对象、分析维度和用户意图。
4. 使用中性、基于商品页面和公开评价的表达。
5. 最多改写并重试 3 次；加上原问题首次执行，单题最多 4 次尝试。
6. 3 次改写重试后仍拒答时，保留最后一次结果并在报告中说明已达到重试上限。

发生拒答改写时，最终回复用户只说明已自动改写并重试，并给出报告路径；除非用户明确要求排障，不输出首次拒答全文、`seed_request`、`upload_payload`、headers 或原始 JSON。

## 输出要求

命令执行成功后，stdout 只输出报告保存路径：

```text
Rufus 答案报告已保存：output/amazon-rufus/B0B1MLVMY5-20260430-101530.md
```

完整答案报告写入运行目录下的 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。文件名中的时间精确到秒，文件内容按题库顺序输出格式化答案报告。不得输出 `seed_request`、`upload_payload`、headers 或完整原始 JSON。


## `amazon-rufus get` 执行流程

```mermaid
flowchart TD
    A[执行 get 命令] --> B[Typer 解析参数]
    B --> C[标准化 ASIN 与国家]
    C --> D[校验国家站点映射]
    D --> E{是否传入 --question}
    E -- 是 --> E1[使用单题问题]
    E -- 否 --> F[读取本地问题模板库]
    F --> F2{问题模板是否可用}
    F2 -- 否 --> F1[返回 QUESTION_BANK_NOT_READY]
    F2 -- 是 --> G[生成 Amazon 商品页 URL]
    E1 --> G
    G --> H{是否传入 --new-chrome}
    H -- 是 --> H1[启动固定 Profile 的 Chrome 调试窗口]
    H -- 否 --> H2[连接已有 Chrome CDP]
    H1 --> I[等待 CDP 端点可用]
    I --> J[通过 Playwright 连接 Chrome]
    H2 --> J
    J --> K[打开商品详情页]
    K --> L[监听 /rufus/cl/streaming 请求]
    L --> M{是否捕获 seed request}
    M -- 否 --> M1[返回 SeedRequestNotCapturedError]
    M -- 是 --> N[基于 seed request 构造问题请求]
    N --> O[复用必要 Rufus 请求头]
    O --> P[在页面上下文中 fetch Rufus]
    P --> Q[解析 SSE 响应]
    Q --> Q1{是否拒答且重试未超过 3 次}
    Q1 -- 是 --> Q2[保持语义改写为 180 字以内中文问题]
    Q2 --> P
    Q1 -- 否 --> R[提取 text html threadId 等结果]
    R --> S[构造 answers 与 upload_payload]
    S --> T[格式化答案报告]
    T --> T1[写入 output/amazon-rufus/ASIN-时间.md]
    T1 --> T2[CLI 输出报告保存路径]
    T2 --> U{是否为 --new-chrome 且未传 --keep-chrome-open}
    U -- 是 --> U1[关闭本次新开的 Chrome 窗口]
    U -- 否 --> U2[保留 Chrome 状态]
```

## 关键数据流

```mermaid
sequenceDiagram
    participant User as 用户
    participant CLI as opscli CLI
    participant Bank as QuestionBankService
    participant Browser as BrowserAttachService
    participant Rufus as Amazon Rufus
    participant Replay as RufusReplayService
    participant Parser as RufusParserService

    User->>CLI: amazon-rufus get ASIN US [--question 问题] --skills-dir .agents/skills
    alt 传入 --question
        CLI->>CLI: 使用单题 question[]
    else 未传 --question
        CLI->>Bank: load_templates()
        Bank-->>CLI: 默认题库 questions[]
    end
    CLI->>Browser: capture_seed_request()
    Browser->>Rufus: 打开商品页触发 ASIN_CLICK
    Rufus-->>Browser: /rufus/cl/streaming seed request
    Browser-->>CLI: SeedRequestRecord
    CLI->>Replay: replay_with_page(page, seed, questions)
    Replay->>Rufus: fetch streaming request
    Rufus-->>Replay: text/event-stream
    Replay->>Parser: parse(raw_text)
    Parser-->>Replay: 判断是否拒答；拒答时最多改写重试 3 次
    Parser-->>Replay: AnswerData
    Replay-->>CLI: answers[]
    CLI-->>User: 输出报告文件路径
```

## 关键文件

- `opscli/amazon_rufus/commands/cli.py`：CLI 参数解析、报告文件写入与错误 JSON 输出。
- `opscli/amazon_rufus/services/manager.py`：编排题库、浏览器捕获、Rufus 重放与输出结构。
- `opscli/amazon_rufus/services/question_bank.py`：读取 `.agents/skills/ops-amazon-rufus/data/question_templates.json`。
- `opscli/amazon_rufus/services/browser.py`：启动或连接 Chrome，并捕获 Rufus seed request。
- `opscli/amazon_rufus/services/replay.py`：基于 seed request 重放问题请求。
- `opscli/amazon_rufus/services/parser.py`：解析 Rufus SSE 响应。
- `opscli/skills/templates/ops-amazon-rufus/references/question-templates.md`：问题模板获取与保存接口说明。

## 注意事项

- `amazon-rufus get` 只读取本地题库，不会自动升级题库。
- 使用本 Skill 前必须先登录对应国家站点的 Amazon 账户。
- `amazon-rufus init <country>` 会打开对应国家站点，并提示 `请在新窗口中登录亚马逊`。
- 不同国家站点登录态可能独立，切换国家时需要确认目标站点已登录。
- PowerShell 下通过 `uv run` 运行命令建议先设置 `$env:PYTHONUTF8 = "1"`、`$env:PYTHONIOENCODING = "utf-8"` 与 `$env:SKIP_CYTHON = "1"`，避免乱码并跳过本地 Cython 编译。
- Agent 执行完成后只向用户输出报告文件路径，完整报告读取 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`，不输出完整 JSON。
- 题库升级需要单独执行 `opscli skills upgrade ops-amazon-rufus --skills-dir ".agents/skills"`。
- 题库接口与保存模板接口不属于 `amazon-rufus get` 回答获取流程，相关说明见 `references/question-templates.md`。
- `--new-chrome` 会启动固定用户目录的 Chrome 调试窗口，命令完成后默认关闭该窗口。
- `--keep-chrome-open` 仅配合 `--new-chrome` 使用，表示命令完成后保留本次新开的 Chrome 窗口。
- Node 的 `[DEP0169] url.parse()` 是 Playwright 依赖链警告，通常不影响命令执行。
