# ops-amazon-rufus PRD

## 2026-04-30 变更需求：参考前端渲染的答案格式化

### 背景

`amazon-rufus get` 目前成功时只输出 `answers[].text`，但输出文本来自 Rufus 流式内容还原，存在大量空行、项目符号拆行和结构化信息缺失问题。用户要求参考 operation-frontend 中 `asinRufusView` 的渲染方式，用 CLI 输出前拿到的全量数据对结果进行格式化。

### 目标

1. CLI 成功时默认将 Rufus 答案报告写入运行目录下的 `output/amazon-rufus`。
2. 输出格式参考前端 `AsinRufusSectionCard` 与 `AsinRufusAnswerBlocks` 的展示顺序。
3. 优先使用 `answer.blocks`、`productLinks`、`recommendedAsins`、`summaryText` 等结构化字段，而不是只输出 `answer.text`。
4. 格式化过程不得截断、总结、改写 Rufus 原文。
5. stdout 只输出报告保存路径，不再承载完整报告正文。

### 非目标

1. 不修改 Rufus 请求、题库、SSE 解析或上传 payload 结构。
2. 不引入 GUI、Web 页面或默认分页器。
3. 不把原始 `seed_request`、headers、cookie 或 `upload_payload` 输出给最终用户。
4. 不使用 LLM 对答案二次润色，避免改变业务含义。
5. 不新增可配置文件输出参数；本轮固定使用运行目录下的 `output/amazon-rufus`。
6. 不实现分页器、剪贴板中转或交互式查看器。
7. 不尝试把已退化的一列文本强行猜测成表格。

### 功能需求

#### FR-FMT-1 默认报告式输出

`opscli amazon-rufus get <asin> <country>` 成功时，必须生成格式化后的答案报告文件。

文件路径规则：

1. 输出目录：`Path.cwd() / "output" / "amazon-rufus"`。
2. 文件名：`<ASIN>-YYYYMMDD-HHMMSS.md`。
3. `ASIN` 使用 manager 返回的标准化大写 ASIN。
4. 时间使用命令运行时本地时间，精确到秒。
5. stdout 输出保存路径提示，不输出完整报告正文。

每个问题按 section 输出：

1. 标题：`## 第 N 题：<question>`。
2. 相关产品：来自 `answer.productLinks`。
3. 答案正文：来自 `answer.blocks` 或 `answer.text`。
4. 推荐 ASIN：来自 `answer.recommendedAsins`。
5. 总结：来自 `answer.summaryText`。
6. 单题失败且文本为空时，继续输出 `第 N 题未获取到答案`。

#### FR-FMT-2 前端 block 模型对齐

正文渲染必须参考前端 `buildAsinRufusAnswerBlocks()`：

1. 优先消费 `answer.blocks`。
2. 支持 `heading`、`paragraph`、`list_item`、`table_row`。
3. 连续 `list_item` 合并为列表输出。
4. 连续 `table_row` 合并为 Markdown 表格输出，第一行作为表头，后续行作为表体。
5. 缺少 `blocks` 时回退解析 `answer.text`，支持 Markdown 标题、列表和带 delimiter 的 Markdown 表格。
6. 不满足表格条件的管道文本保持普通段落。

#### FR-FMT-3 原文保留

格式化器不得使用会主动丢弃内容的行数限制、字符数限制或摘要逻辑。只要 Rufus 返回了文本，CLI 展示层不得主动删减。

#### FR-FMT-4 输出安全边界

格式化输出不得包含：

1. `seed_request`
2. `upload_payload`
3. 请求头
4. cookie
5. 原始完整 JSON

#### FR-FMT-5 文件落地边界

文件写入必须满足：

1. 自动创建 `output/amazon-rufus` 目录。
2. 使用 UTF-8 编码写入报告，保证中文答案可读。
3. 成功路径不再把完整报告写入 stdout。
4. 如果 formatter 返回空字符串，仍写入空报告文件并输出路径，保持成功链路可追踪。
5. 错误路径维持现有 JSON 错误输出，不生成报告文件。

### 验收标准

1. 用前端 `answerBlocks.test.ts` 的样例构造 Python formatter 测试，验证 heading、paragraph、list、table 输出一致。
2. `answer.blocks` 存在时优先使用结构化 blocks，不直接输出 fallback text。
3. `productLinks`、`recommendedAsins`、`summaryText` 按前端顺序展示。
4. 成功执行后在运行目录的 `output/amazon-rufus` 生成 `<ASIN>-YYYYMMDD-HHMMSS.md`。
5. 现有隐藏 `seed_request` 与 `upload_payload` 的测试继续通过。
6. stdout 只包含保存路径提示，不包含报告正文、`seed_request` 或 `upload_payload`。
7. `tests/amazon_rufus/test_core.py` 新增 CLI 与 formatter 回归测试。

## 2026-04-29 变更需求：新增 init 登录初始化命令

### 背景

`amazon-rufus get` 使用独立 Chrome profile 打开 Amazon 商品页并复用浏览器登录态。首次使用时，用户需要先在该 profile 中登录 Amazon，否则 `get` 可能无法捕获 Rufus 请求或无法获得完整站点能力。

### 用户故事

作为运营或采集执行者，我希望先运行一条初始化命令打开对应国家的 Amazon 站点，并在新窗口中完成登录，从而让后续 `amazon-rufus get` 复用相同浏览器 profile 执行 Rufus 问答。

### 命令定义

```bash
opscli amazon-rufus init <country>
```

参数：

- `country`：国家名，沿用现有 `US/UK/DE/JP` 站点映射。

示例：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus init US
```

### 功能需求

#### FR-INIT-1 国家站点解析

系统必须复用现有国家站点映射，将 `country` 解析为对应 Amazon 首页：

- `US -> https://www.amazon.com`
- `UK -> https://www.amazon.co.uk`
- `DE -> https://www.amazon.de`
- `JP -> https://www.amazon.co.jp`

不支持的国家必须返回现有稳定错误结构，并提示支持范围。

#### FR-INIT-2 浏览器打开方式

系统必须使用与现有 Rufus 获取流程相同的 Chrome 打开方式：

- 使用固定 remote debugging 端口 `9222`。
- 使用固定独立 profile `E:\chrome-profiles\opscli-rufus`。
- 通过 Playwright CDP 连接该 Chrome。
- 打开解析出的 Amazon 首页。

#### FR-INIT-3 用户提示

页面打开后，命令必须输出：

```text
请在新窗口中登录亚马逊
```

随后命令结束。

#### FR-INIT-4 窗口保留

`init` 命令结束时不得关闭新打开的 Chrome 窗口，以便用户继续完成登录，并让登录态写入固定 profile。

#### FR-INIT-5 职责边界

`init` 命令不得执行以下动作：

- 不读取 Rufus 题库。
- 不访问商品详情页。
- 不捕获 `/rufus/cl/streaming`。
- 不重放 Rufus 请求。
- 不构造上传 payload。

### 验收标准

1. `opscli amazon-rufus init --help` 可见。
2. `opscli amazon-rufus init US` 会打开 `https://www.amazon.com`。
3. `opscli amazon-rufus init DE` 会打开 `https://www.amazon.de`。
4. 成功打开后 CLI 输出 `请在新窗口中登录亚马逊`。
5. 命令结束后 Chrome 窗口保持打开。
6. 不支持的国家返回明确错误，不打开错误站点。

## 2026-04-29 变更需求：Skill 运行 UTF-8 与答案报告输出

### 背景

`ops-amazon-rufus` 面向 AI Agent 和运营同学使用，Rufus 回答包含中文、特殊符号和 Amazon 商品文本。若命令未在 UTF-8 环境下运行，Windows PowerShell 可能出现乱码；同时 Agent 使用场景只需要最终格式化报告，不需要把完整 JSON 暴露给用户。

### 目标

1. Skill 文档中的所有运行示例必须显式使用 UTF-8 环境变量。
2. 命令执行完成后，Skill 面向用户的最终输出返回报告保存路径，完整报告文件按前端渲染规则生成。
3. 原始 JSON 仅作为本地解析中间结果，不作为最终回复直接输出。
4. 不改变 `opscli amazon-rufus get <asin> <country>` 的核心运行链路。

### 非目标

1. 不移除 CLI 内部结构化 JSON 能力，避免破坏脚本与测试兼容性。
2. 不新增上传、批量调度或远端 API 调用能力。
3. 不在 Skill 层直接调用后端接口。

### 功能需求

1. PowerShell 示例必须在同一命令会话中设置 `$env:PYTHONUTF8 = "1"` 与 `$env:PYTHONIOENCODING = "utf-8"`。
2. `amazon-rufus get` 成功时只输出报告保存路径。
3. 当存在多条答案时，报告文件按题库顺序输出每个问题 section。
4. 当某题 `text` 为空但 `isSuccess` 为 `false` 时，报告文件应输出该题失败信息摘要，避免静默丢失。
5. 最终用户回复不得包含 `seed_request`、`upload_payload`、请求头或完整 JSON。

### 验收标准

1. `ops-amazon-rufus` 的 `SKILL.md` 和 `README.md` 均包含 UTF-8 运行示例。
2. 文档明确要求最终只向用户输出报告保存路径。
3. 原有 CLI 全量数据契约在架构文档中被标记为内部解析契约，而不是 Skill 最终展示契约。

## 2026-04-29 变更需求：复刻扩展端 Rufus 请求行为

### 背景

当前 `amazon-rufus` CLI 已能捕获 Rufus seed request 并逐题重放，但请求参数比扩展端 `AsinRufusDialog` 少。为提升回答成功率、上下文准确性和跨站点一致性，需要让 CLI 尽量复刻扩展端的请求构造行为。

### 目标

1. CLI 使用题库问题获取 Rufus 回答时，请求 body 字段与扩展端保持一致。
2. CLI 重放 URL 显式携带扩展端使用的 `tabId/programId/ref` 参数。
3. 保持现有命令入口、输出结构和题库加载方式不变，降低升级风险。
4. 不引入上传、远端 API、GUI 或新命令。

### 非目标

1. 不复制扩展端表单驱动的 `keyword/persona/optimizeAsin` 动态问题生成逻辑。
2. 不把浏览器所有 request headers 无差别注入页面内 fetch。
3. 不改变 `opscli amazon-rufus get <asin> <country>` 的用户交互路径。
4. 不在文档确认前创建 `.super-dev/changes/*` 或开始编码。

### 功能需求

1. Payload 构造必须基于 seed body 深拷贝，避免污染原始记录。
2. 每题必须替换 `queryContext.query`。
3. 每题必须设置 `queryContext.actionType = "SEARCH"`。
4. 每题必须设置 `queryContext.qis = "NileCLTextInput"`。
5. 每题必须设置 `pageContext.originPageType = "DETAIL_PAGE"`。
6. 每题必须确保 `pageContext.targetPageMetadata` 中存在 `{ type: "ASIN", value: <目标 ASIN> }`。
7. 每题必须确保 `pageContext.originPageMetadata` 中存在 `{ type: "ASIN", value: <目标 ASIN> }`。
8. 每题必须设置 `bottomSheetContext.previousTurnsBottomSheetSize = "expanded"`。
9. 每题必须设置 `impressionsContext.FIRST_TIME_USER_MESSAGE_SEEN_STATUS = "SEEN"`。
10. 当沿用上一题 `threadId` 时，`historyThreadContext` 必须包含 `threadId` 与 `threadState`，其中 `threadState` 默认 `THREAD_STATE_UNKNOWN`。
11. 重放 URL 必须保留 seed origin/path，并确保 query 参数包含 `tabId`、`programId=NILE_CLASSIC:desktop-cl`、`ref=nl_cl_dsk_csq`。

### 验收标准

1. 单元测试覆盖 body 补字段、ASIN metadata 覆盖/追加、URL query 参数补齐。
2. 原有 `amazon-rufus` 测试继续通过。
3. CLI 输出结构不破坏既有字段：`asin`、`country`、`page_url`、`question_count`、`answers`、`seed_request`、`upload_payload`。
4. 新实现保持 KISS：请求复刻逻辑集中在 replay/service 层，不分散到 CLI 层。

## 需求概述

新增一套 Amazon Rufus CLI 与 Skill 能力，支持用户基于已登录的本地 Chrome 会话，对指定 ASIN 自动发起题库问题并返回结构化答案。

本期交付目标：

- 新增命令：`opscli amazon-rufus get <asin> <country>`
- 新增 Skill：`ops-amazon-rufus`
- 支持 Skill 远端升级，用于同步题库与运行参数
- 复用 Amazon 商品页真实 Rufus 请求上下文
- 返回结构化答案
- 构造与现有前端一致的上传 payload，但暂不发送上传接口

---

## 用户故事

### 用户故事 1

作为使用 `opscli` 的运营同学或 AI Agent，
我希望输入一个 ASIN 和国家站点，
命令就能自动打开商品页、抓取 seed request、跑题库并返回回答，
这样我就不需要手工逐题在 Amazon 页面里点 Rufus。

### 用户故事 2

作为技能维护者，
我希望默认题库可以通过 `opscli skills upgrade ops-amazon-rufus` 更新，
这样不需要每次改题都发 CLI 代码版本。

### 用户故事 3

作为后续接口开发者，
我希望当前 CLI 输出的 upload payload 与前端既有格式兼容，
这样后面只要接入真实上传接口即可，无需重做数据模型。

---

## 成功标准

满足以下条件视为一期成功：

1. 用户执行 `opscli amazon-rufus get <asin> <country>` 时，能够在本地已登录 Chrome 上跑通完整流程。
2. 命令能捕获一个有效 seed request，并用它重放题库问题。
3. 至少能正确解析出每题的最终回答文本和结构化 answer 数据。
4. CLI 内部全量数据中包含以下解析字段，Skill 最终回复只展示格式化答案报告：
   - 请求上下文摘要
   - 逐题答案
   - 标准上传 payload
5. `opscli skills install ops-amazon-rufus` 与 `opscli skills upgrade ops-amazon-rufus` 能正常工作。

---

## 范围

### In Scope

- 新增 `amazon-rufus` 顶级 CLI 模块
- 新增 `get` 子命令
- Playwright attach 到本地 Chrome CDP 端口
- 基于国家码拼装商品页 URL
- 监听页面 `/rufus/cl/streaming` seed request
- 从本地 Skill 数据读取默认题目模板
- 逐题重放 Rufus
- 解析 SSE 为结构化 answer
- 构造标准上传 payload
- Skill 安装 / 状态 / 升级链路接入

### Out of Scope

- 真正调用上传接口
- 批量多 ASIN 调度
- 自动登录 Amazon
- 自建桌面 UI 或 Web UI
- 宿主 Chrome MCP 作为正式运行依赖

---

## 命令设计

### 主命令

```bash
opscli amazon-rufus get <asin> <country>
```

### 推荐选项

```bash
opscli amazon-rufus get <asin> <country> \
  [--cdp-url http://127.0.0.1:9222] \
  [--new-chrome] \
  [--chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"] \
  [--launch-if-needed] \
  [--skills-dir <dir>] \
  [--timeout 90] \
  [--pretty] \
  [--no-upload-payload]
```

### 参数说明

- `asin`
  - 必填，10 位 Amazon ASIN
- `country`
  - 必填，2 位国家码，如 `US`、`UK`、`DE`、`JP`
- `--cdp-url`
  - 可选，Chrome DevTools 地址，默认 `http://127.0.0.1:9222`
- `--new-chrome`
  - 可选，先新开一个 Chrome 调试窗口，再连接默认 CDP 地址
- `--chrome-path`
  - 可选，Chrome 可执行文件路径
- `--launch-if-needed`
  - 可选，当 CDP 不可用时自动尝试启动 Chrome
- `--skills-dir`
  - 可选，指定 `ops-amazon-rufus` Skill 所在目录
- `--timeout`
  - 可选，单题最大等待秒数
- `--pretty`
  - 保留参数但不改变成功输出口径；成功时仍只输出报告保存路径
- `--no-upload-payload`
  - 可选，仅返回答案，不输出上传 payload

---

## 功能需求

### FR-1 题库读取

命令执行时必须先读取本地 `ops-amazon-rufus` Skill 数据，包括：

- 默认模板列表
- 模板内嵌问题列表

国家站点映射直接固定在代码中，不再作为 Skill 数据下发。

若本地数据缺失，应提示用户先执行：

```bash
opscli skills install ops-amazon-rufus
opscli skills upgrade ops-amazon-rufus
```

### FR-2 国家站点映射

系统必须根据 `country` 解析目标商品页 origin，例如：

- `US -> https://www.amazon.com`
- `UK -> https://www.amazon.co.uk`
- `DE -> https://www.amazon.de`
- `JP -> https://www.amazon.co.jp`

映射数据不写死在业务代码，走 Skill 数据文件。

### FR-3 Chrome attach

系统必须优先 attach 到用户本地已启动 Chrome。

新增 `--new-chrome` 参数后，系统必须先启动一个独立 Chrome 调试窗口，再连接 CDP。默认 Windows 启动命令固定为：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

该模式使用独立 `user-data-dir`，避免污染用户默认 Chrome profile，并确保 remote debugging 端口可被当前命令连接。

若 attach 失败：

- `--launch-if-needed` 未开启：直接报错，并提示用户手动以 remote debugging 模式启动 Chrome
- `--launch-if-needed` 开启且 `--chrome-path` 可用：尝试自动启动 Chrome
- `--new-chrome` 已开启：先执行固定启动命令，短暂等待 CDP 可用后再 attach；若仍失败，返回启动命令与 `--cdp-url` 排障提示

### FR-4 seed request 捕获

系统必须在进入商品页前注册监听器，尽早捕获 `/rufus/cl/streaming` request。

seed request 至少需要提取：

- `requestUrl`
- `requestBody`
- `requestHeaders`
- `tabId`
- `asin`
- `pageUrl`
- `country`

若未捕获到 seed request，应返回明确失败原因。

### FR-5 题库执行

系统必须按题库顺序逐题执行。

每题执行逻辑：

1. 基于 seed request 构造新的 payload
2. 替换问题文本
3. 必要时带回 `historyThreadContext`
4. 发送 Rufus 请求
5. 解析回答

### FR-6 回答解析

系统必须输出结构化 answer，字段与现有前端兼容：

- `text`
- `html`
- `summaryText`
- `productLinks`
- `recommendedAsins`
- `blocks`
- `isSuccess`

### FR-7 上传 payload 构造

系统必须构造两类 payload，本期默认不真正发 HTTP：

1. record collect payload
2. per-question answer update payload

要求：

- 外层结构与现有前端 `collectInterceptRecordsApi + updateRecordAnswerApi` 兼容
- `businessType` 使用新业务类型，例如 `asin_rufus_cli`
- `requestBody` 允许使用 CLI 自己的业务字段，只要求外层 record 结构一致
- 真实上传请求代码需要在实现中存在，但默认以注释状态保留，不参与一期运行

### FR-8 命令输出与 Skill 展示

CLI 命令成功时只输出格式化答案报告保存路径。内部数据结构仍至少包含：

- `asin`
- `country`
- `page_url`
- `seed_record`
- `questions`
- `answers`
- `upload_payload`
- `captured_at`

Skill/Agent 面向最终用户展示时，必须输出报告文件路径；完整报告基于上述全量数据生成，并且不得输出内部 JSON。

---

## 非功能需求

### NFR-1 运行稳定性

- 单题超时可配置
- 某一题失败时应保留失败信息，不影响前面已成功的题
- 最终返回中要区分成功题与失败题

### NFR-2 可审计性

- 输出要包含 seed request 摘要
- 输出要包含题库版本与模板 ID
- 输出要包含运行时间戳

### NFR-3 可扩展性

- 未来接真实上传接口时，不需要重写核心数据模型
- 未来可扩展到 batch 命令

### NFR-4 规范一致性

- Python 代码全中文注释
- Skill 不直接调用业务后端
- 远端数据同步统一收口到 `opscli skills upgrade ops-amazon-rufus`

---

## Skill 需求

### Skill 名称

- `ops-amazon-rufus`

### Skill 类型

- 远端升级型 Skill

### Skill 最小目录

```text
ops-amazon-rufus/
├── SKILL.md
└── data/
    ├── VERSION.json
    └── question_templates.json
```

`question_templates.json` 使用 `default-question-templates` 接口结构，模板与题目列表合并在同一个文件内：

```json
{
  "items": [
    {
      "id": 56,
      "description": "测试",
      "preferred_version_index": 0,
      "questions": [
        {
          "id": 3172,
          "text": "问题1",
          "position": 1
        }
      ],
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

`runner_config.json`、`marketplaces.json` 与 `questions/<template_id>.json` 不再作为一期 Skill 数据文件；国家站点映射固定在代码中，并按 `US` 等国家名选择。

### Skill 文档要求

`SKILL.md` 必须描述：

- 前置条件：Chrome、Amazon 登录、Skill 升级
- 登录前置条件必须明确到国家站点维度：不同国家站点 Amazon 账户登录态可能独立，执行 `get <asin> <country>` 前必须确认该 `country` 对应站点已登录
- 初始化登录命令：`opscli amazon-rufus init <country>`，并说明命令会打开对应国家站点且提示 `请在新窗口中登录亚马逊`
- `opscli amazon-rufus get` 的使用方式
- 常见错误排查
- 典型工作流

---

## 一期验收口径

满足以下验收项即可进入实现：

1. `opscli amazon-rufus --help` 与 `opscli amazon-rufus get --help` 可见。
2. `opscli skills install ops-amazon-rufus` 可安装模板。
3. `opscli skills upgrade ops-amazon-rufus` 能把题库同步到本地。
4. `opscli amazon-rufus get <asin> <country>` 能返回答案与 upload payload。
5. 上传请求代码存在于实现中，但默认注释掉，不会进行真实上传。
