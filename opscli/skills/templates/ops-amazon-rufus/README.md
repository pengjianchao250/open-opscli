# ops-amazon-rufus 使用说明

`ops-amazon-rufus` 提供 `opscli amazon-rufus get <asin> <country>` 所需的默认问题模板库。

## 常用命令

### 启动 Chrome 调试窗口

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check'
```

### 升级问题模板库

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli skills upgrade ops-amazon-rufus --skills-dir ".agents/skills" --pretty
```

升级成功后，问题模板库会保存到：

```text
.agents/skills/ops-amazon-rufus/data/question_templates.json
```

### 执行 Rufus 获取

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

`--new-chrome` 默认会在命令输出结果后通过 CDP `Browser.close` 关闭本次新开的 Chrome 调试窗口。若需要保留窗口用于继续调试或复用登录态，追加：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome --keep-chrome-open
```

## 输出要求

命令执行完成后只输出：

```text
data.answers[].text
```

多条回答按题库顺序输出，并用空行分隔。不得输出 `seed_request`、`upload_payload`、headers 或完整原始 JSON。


## `amazon-rufus get` 执行流程

```mermaid
flowchart TD
    A[执行 get 命令] --> B[Typer 解析参数]
    B --> C[标准化 ASIN 与国家]
    C --> D[校验国家站点映射]
    D --> E[读取本地问题模板库]
    E --> F{问题模板是否可用}
    F -- 否 --> F1[返回 QUESTION_BANK_NOT_READY]
    F -- 是 --> G[生成 Amazon 商品页 URL]
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
    Q --> R[提取 text html threadId 等结果]
    R --> S[构造 answers 与 upload_payload]
    S --> T[CLI 输出 JSON]
    T --> T1[Agent 提取 answers.text]
    T1 --> T2[最终只输出答案文本]
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

    User->>CLI: amazon-rufus get ASIN US --skills-dir .agents/skills
    CLI->>Bank: load_templates()
    Bank-->>CLI: questions[]
    CLI->>Browser: capture_seed_request()
    Browser->>Rufus: 打开商品页触发 ASIN_CLICK
    Rufus-->>Browser: /rufus/cl/streaming seed request
    Browser-->>CLI: SeedRequestRecord
    CLI->>Replay: replay_with_page(page, seed, questions)
    Replay->>Rufus: fetch streaming request
    Rufus-->>Replay: text/event-stream
    Replay->>Parser: parse(raw_text)
    Parser-->>Replay: AnswerData
    Replay-->>CLI: answers[]
    CLI-->>User: 仅展示 answers.text
```

## 关键文件

- `opscli/amazon_rufus/commands/cli.py`：CLI 参数解析与 JSON 输出。
- `opscli/amazon_rufus/services/manager.py`：编排题库、浏览器捕获、Rufus 重放与输出结构。
- `opscli/amazon_rufus/services/question_bank.py`：读取 `.agents/skills/ops-amazon-rufus/data/question_templates.json`。
- `opscli/amazon_rufus/services/browser.py`：启动或连接 Chrome，并捕获 Rufus seed request。
- `opscli/amazon_rufus/services/replay.py`：基于 seed request 重放问题请求。
- `opscli/amazon_rufus/services/parser.py`：解析 Rufus SSE 响应。

## 注意事项

- `amazon-rufus get` 只读取本地题库，不会自动升级题库。
- PowerShell 下运行命令必须设置 `$env:PYTHONUTF8 = "1"` 与 `$env:PYTHONIOENCODING = "utf-8"`，避免中文答案乱码。
- Agent 执行完成后只向用户输出 `answers.text`，不输出完整 JSON。
- 题库升级需要单独执行 `opscli skills upgrade ops-amazon-rufus --skills-dir ".agents/skills"`。
- `--new-chrome` 会启动固定用户目录的 Chrome 调试窗口，命令完成后默认关闭该窗口。
- `--keep-chrome-open` 仅配合 `--new-chrome` 使用，表示命令完成后保留本次新开的 Chrome 窗口。
- Node 的 `[DEP0169] url.parse()` 是 Playwright 依赖链警告，通常不影响命令执行。
