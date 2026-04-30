# ops-amazon-rufus Architecture

## 2026-04-30 架构增量：前端渲染对齐答案输出

### 设计原则

本轮变更只处理 CLI 成功输出展示，不改变 Rufus 原始解析结构。formatter 必须参考前端 `asinRufusView` 的渲染规则，使用完整 `data` 生成确定性文本报告，不能总结、删减或改写业务内容。

### 模块边界

新增文件：

```text
opscli/amazon_rufus/services/answer_report_formatter.py
```

职责：

1. 接收 `RufusManager.get()` 返回的完整 `data`。
2. 读取 `answers[]`、`upload_payload.records[0].questions[]`、`asin`、`country`、`page_url`。
3. 按前端 section/card 结构输出问题、相关产品、正文、推荐 ASIN、总结。
4. 优先消费 `answer.blocks`，缺失时回退解析 `answer.text`。
5. 返回完整格式化字符串。

推荐类：

```python
class AnswerReportFormatter:
    def format_data(self, data: dict) -> str:
        ...
```

CLI 层改造：

1. `commands/cli.py` 的 `_emit_answers_text()` 改为 `_emit_answer_report()`，并调用 `AnswerReportFormatter.format_data(data)`。
2. `_emit_answer_report()` 不再直接输出完整报告，而是写入运行目录下的 `output/amazon-rufus`。
3. 文件名使用 `<ASIN>-YYYYMMDD-HHMMSS.md`，时间精确到秒。
4. 成功时 stdout 只输出报告保存路径。
5. `get` 命令不新增可配置文件输出参数。

不改动：

1. `RufusParserService` 不做展示格式化。
2. `RufusManager.get()` 返回结构不变。
3. `AnswerData.to_dict()` 不变。
4. `upload_payload` 构造不变。

### 前端对齐数据模型

参考前端：

- `AsinRufusSectionCard.vue`
- `AsinRufusAnswerBlocks.vue`
- `utils/asinRufus/answerBlocks.ts`
- `utils/asinRufus/toSections.ts`
- `api/types/intercept.ts`

CLI formatter 的 section 组装规则：

1. `answers = data.get("answers", [])`。
2. `questions` 优先从 `data["questions"]` 读取；若不存在，从 `data["upload_payload"]["records"][0]["questions"]` 读取；仍不存在时使用 `第 N 题`。
3. `answer.isSuccess is False` 或 `answer.text` 以 `【失败】` 开头时标记为失败。
4. 输出顺序沿用答案数组顺序，不在 CLI 展示层重新排序；题库顺序由 `QuestionBankService` 和 `RufusManager` 保证。

### 正文 block 渲染算法

推荐实现步骤：

1. `_build_answer_blocks(text, structured_blocks)` 对齐前端 `buildAsinRufusAnswerBlocks()`。
2. 若 `structured_blocks` 非空：
   - `heading` 输出 Markdown 标题，level 限制在 1-6。
   - `paragraph` 输出普通段落。
   - 连续 `list_item` 合并为 `- item` 列表。
   - 连续 `table_row` 合并为 Markdown 表格，优先使用 `cells`，缺失时解析 `text` 中的 `|`。
3. 若 `structured_blocks` 为空：
   - 标准化换行。
   - 支持 Markdown heading。
   - 支持 `-/*/•` 与 `1.` / `1)` 列表。
   - 缩进行并入上一条列表项。
   - 只有存在 delimiter 行时才识别 Markdown 表格。
4. 输出前压缩多余空行，但不主动删减正文。

该算法不尝试把退化表格自动重建为 Markdown 表格。原因是 Rufus 文本来源复杂，自动推断列数容易误伤正文。若后续需要表格重建，应基于 parser 的结构化 blocks 做增量设计，而不是在纯文本层猜测。

### 文件输出边界

终端截断不是 CLI 进程完全可控的问题。本轮通过默认文件落地规避 stdout 长文本承载风险，但不新增分页器、剪贴板中转或交互式分段输出。

实现约束：

1. 输出目录固定为 `Path.cwd() / "output" / "amazon-rufus"`。
2. 文件写入使用 UTF-8。
3. stdout 不输出完整答案报告，只输出保存路径提示。
4. 错误路径继续使用稳定 JSON 结构，不写报告文件。
5. formatter 仍负责报告文本生成，CLI 层只负责文件命名、目录创建、写入和提示。

### 测试策略

1. formatter 单元测试：
   - 对齐前端 `answerBlocks.test.ts`：结构化 blocks 优先、text fallback、无 delimiter 不识别表格、空文本无 blocks。
   - 渲染 `productLinks`、`recommendedAsins`、`summaryText`。
   - 保留原文内容不主动删减。
   - 失败空答案输出稳定提示。
2. CLI 测试：
   - 默认生成 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。
   - stdout 只输出保存路径提示。
   - 不存在可配置文件输出参数。
   - 不泄露 `seed_request` 与 `upload_payload`。
3. 回归测试：
   - 现有 `amazon_rufus` 测试继续通过。

## 2026-04-29 架构增量：init 登录初始化命令

### 设计原则

本轮新增 `amazon-rufus init <country>`，目标是为后续 `get` 准备同一个独立 Chrome profile 的 Amazon 登录态。实现必须复用现有浏览器打开机制，避免复制启动参数或新增独立 profile。

### 模块边界

1. `commands/cli.py` 增加 `init` Typer 子命令，只负责参数解析、调用 Manager、输出提示与错误结构。
2. `RufusManager` 增加 `init(country, cdp_url=...)` 方法，只编排国家解析与浏览器初始化。
3. `BrowserAttachService` 增加登录初始化专用方法，例如 `open_marketplace_for_login()`。
4. `country_map.py` 继续作为国家到 Amazon 站点的唯一映射来源。

### 浏览器复用契约

`init` 必须复用 `BrowserAttachService.DEFAULT_NEW_CHROME_ARGUMENTS`：

```text
--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --auto-open-devtools-for-tabs --no-first-run --no-default-browser-check
```

实现要求：

1. 启动 Chrome 的底层方法与 `get --new-chrome` 保持一致。
2. 等待 CDP 可用后连接浏览器。
3. 创建或复用 context，打开对应国家 Amazon 首页。
4. 调用 `page.bring_to_front()` 让登录窗口可见。
5. 方法返回后不关闭浏览器。

### CLI 输出契约

成功输出固定文案：

```text
请在新窗口中登录亚马逊
```

错误输出继续使用现有 `_error_payload("amazon-rufus init", exc)` 稳定结构。

### 职责隔离

`init` 不依赖题库服务和 replay 服务，避免初始化命令引入采集副作用。该设计符合 KISS/YAGNI：只打开登录窗口，不做任何 Rufus 私有接口操作。

### 测试策略

1. CLI help 测试：`amazon-rufus init --help` 可见国家参数。
2. Manager 测试：`init("US")` 解析到 `https://www.amazon.com` 并调用浏览器服务。
3. Browser 测试：模拟 Playwright/CDP，验证打开 URL、前置窗口、且不调用关闭逻辑。
4. 错误测试：不支持国家时返回稳定错误结构。

## 2026-04-29 架构增量：UTF-8 运行环境与答案报告投影

### 设计原则

本轮变更调整 CLI 成功输出契约：`amazon-rufus get` 执行完成后不输出完整 JSON，只输出格式化答案报告的保存路径。

### UTF-8 运行契约

Windows PowerShell 运行示例必须在同一进程环境中设置：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

说明：

1. `PYTHONUTF8=1` 强制 Python 使用 UTF-8 模式，降低 Windows 默认代码页导致的乱码风险。
2. `PYTHONIOENCODING=utf-8` 约束标准输入输出编码，保证中文保存路径和错误信息可被 Agent 正确读取。
3. 该环境变量只作用于当前命令会话，不修改系统级环境变量。

### 输出分层契约

1. CLI 层：成功时只输出格式化答案报告保存路径。
2. Service 层：仍可保留完整数据结构用于内部编排。
3. 用户展示层：只展示报告保存路径，不展示完整 JSON、`seed_request`、`upload_payload` 或 headers。

### 报告投影规则

伪代码：

```python
report = AnswerReportFormatter().format_data(data)
print(report)
```

失败处理：

1. 出现异常时输出稳定 JSON 错误结构。
2. 单题无 `text` 且 `isSuccess=false` 时，展示该题失败摘要。
3. 不把解析失败时的原始 JSON 直接贴给最终用户，除非用户明确要求排障。

### 代码实现边界

本变更移除 `--answers-text` 参数需求，成功路径默认执行报告投影、文件写入并输出保存路径。错误路径保留稳定 JSON 错误结构，便于排障。

## 2026-04-29 架构增量：Rufus 请求参数对齐

### 设计原则

本轮变更只触及 Rufus replay 请求构造，不改变 CLI 命令树、题库加载、浏览器 attach、SSE 解析与输出协议。实现应遵循 KISS/YAGNI：复刻扩展端已验证字段，不新增未观察到的私有参数。

### 推荐模块边界

1. `RufusReplayService.build_payload()` 负责 body 对齐：
   - 解析 seed body。
   - 替换问题。
   - 补齐 query/page/bottomSheet/impressions/history 字段。
   - 接收 `asin` 参数以修正 metadata。
2. 新增或内聚一个 URL 构造方法，例如 `RufusReplayService.build_replay_url()`：
   - 基于 `seed.request_url`。
   - 保留原始 origin/path 与已有 query。
   - 补齐 `tabId`、`programId`、`ref`。
3. `replay_with_page()` 只负责组装 payload、URL、headers 并执行页面上下文 fetch。
4. `BrowserAttachService` 继续只负责捕获 seed request，不承担 payload 复刻逻辑。
5. `RufusManager` 继续负责业务编排，不下沉具体 Rufus 参数。

### 请求 body 契约

目标 payload 以 seed body 为基础，确保以下字段：

```json
{
  "queryContext": {
    "query": "当前题目",
    "actionType": "SEARCH",
    "qis": "NileCLTextInput"
  },
  "pageContext": {
    "originPageType": "DETAIL_PAGE",
    "targetPageMetadata": [{ "type": "ASIN", "value": "B0TEST1234" }],
    "originPageMetadata": [{ "type": "ASIN", "value": "B0TEST1234" }]
  },
  "bottomSheetContext": {
    "previousTurnsBottomSheetSize": "expanded"
  },
  "impressionsContext": {
    "FIRST_TIME_USER_MESSAGE_SEEN_STATUS": "SEEN"
  }
}
```

当存在上一题 `threadId` 时追加：

```json
{
  "historyThreadContext": {
    "threadId": "上一题返回的 threadId",
    "threadState": "THREAD_STATE_UNKNOWN"
  }
}
```

### 请求 URL 契约

URL 构造规则：

1. 优先解析 `seed.request_url`。
2. 保留 `https://<amazon-marketplace>/rufus/cl/streaming`。
3. `tabId` 优先使用 `seed.tab_id`，缺失时保留 URL 既有值。
4. `programId` 缺失时设置为 `NILE_CLASSIC:desktop-cl`。
5. `ref` 缺失时设置为 `nl_cl_dsk_csq`。

### Headers 策略

当前 CLI 在页面上下文内执行 fetch，仍应使用 allowlist：

- `anti-csrftoken-a2z`
- `content-type`
- `x-amz-is-papyrus`

不建议本轮直接复用扩展端完整 headers，因为浏览器脚本环境禁止设置部分安全 header，且 cookie/凭证由页面上下文自然携带。若后续实测 Amazon 站点需要更多 header，再通过最小 allowlist 扩展。

### 测试策略

1. `build_payload` 测试：seed body 为空、字段类型异常、已有 metadata、缺失 metadata、带 threadId。
2. `build_replay_url` 测试：URL 已有参数、URL 缺 `programId/ref`、`seed.tab_id` 覆盖 URL tabId。
3. `replay_with_page` 测试：传入页面 evaluate 的 `url/body/headers` 符合契约。

## 架构目标

以最小侵入方式为 `opscli` 增加一条新的 Rufus 运行链路，同时遵守现有项目分层：

- CLI 层只做参数解析、成功报告文件写入与错误 JSON 输出
- Service 层负责业务编排
- Transport 层负责远端接口
- Skill 远端升级数据与运行时解耦

---

## 总体设计

### 新增模块

```text
opscli/
└── amazon_rufus/
    ├── __init__.py
    ├── cli.py
    ├── commands/
    │   └── cli.py
    ├── services/
    │   ├── manager.py
    │   ├── browser.py
    │   ├── replay.py
    │   ├── parser.py
    │   └── question_bank.py
    ├── transport/
    │   └── client.py
    ├── domain/
    │   ├── models.py
    │   └── exceptions.py
    └── runtime/
        └── country_map.py
```

说明：

- `browser.py`
  - 负责 attach Chrome、打开商品页、监听 seed request
- `replay.py`
  - 负责基于 seed request 逐题重放 Rufus
- `parser.py`
  - 负责 SSE 解析与 answer 结构化
- `question_bank.py`
  - 负责从已安装 Skill 目录读取合并后的默认题目模板数据
- `transport/client.py`
  - 负责 `ops-amazon-rufus` Skill 升级所需的远端拉取接口
  - 同时预留上传接口代码，但一期默认不执行

---

## 命令层设计

### CLI 路由

顶级注册：

```python
from opscli.amazon_rufus.cli import app as amazon_rufus_app
app.add_typer(amazon_rufus_app, name="amazon-rufus")
```

命令树：

```text
opscli amazon-rufus
    get <asin> <country>
```

### CLI 职责

- 参数解析
- 调用 `RufusManager.get()`
- 成功时输出格式化答案报告保存路径，错误时返回稳定 JSON 结构
- 错误映射为稳定结构

CLI 不直接：

- 打开浏览器
- 处理 Playwright 细节
- 读取 Skill 数据文件

---

## Service 层设计

### `RufusManager`

职责：

1. 校验入参
2. 解析国家站点
3. 读取本地默认题目模板
4. attach Chrome
5. 打开商品页并捕获 seed request
6. 调用 replay 逐题执行
7. 聚合结果
8. 构造 upload payload，并预留注释态上传调用代码

建议主入口：

```python
class RufusManager:
    def get(
        self,
        *,
        asin: str,
        country: str,
        skills_dir: str | None = None,
        cdp_url: str = "http://127.0.0.1:9222",
        new_chrome: bool = False,
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
        timeout_seconds: int = 90,
        include_upload_payload: bool = True,
    ) -> dict:
        ...
```

### `QuestionBankService`

职责：

- 从 `ops-amazon-rufus` 安装目录读取：
  - `question_templates.json`
- `question_templates.json` 同时承载模板列表与模板下题目列表，不再拆分 `questions/<template_id>.json`
- 国家站点映射不再通过 `marketplaces.json` 下发，直接固定在 `runtime/country_map.py` 代码中，并使用 `US` 等国家名作为输入枚举
- 负责本地数据校验
- 若文件缺失，抛出“请安装/升级 ops-amazon-rufus”的错误

本地 `question_templates.json` 应参考当前可访问接口 `http://127.0.0.1:8000/api/opencalw/default-question-templates` 的数据结构：

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

### `BrowserAttachService`

职责：

- 探测 CDP endpoint 是否可用
- 当 `new_chrome=True` 时，先新开独立 Chrome 调试窗口
- 必要时启动 Chrome
- `connect_over_cdp()` attach 到已有 Chrome
- 选择默认 context/page
- 在商品页跳转前注册 seed request 监听器

Windows 默认新开 Chrome 命令：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

实现约束：

- `new_chrome=True` 时优先执行固定启动命令，再轮询 `cdp_url` 可用性
- `new_chrome=False` 时保持原有行为，仅连接外部已启动 Chrome
- `chrome_path` 与 `launch_if_needed` 保持兼容，但不覆盖 `--new-chrome` 的固定默认启动命令
- 启动后必须继续使用 `connect_over_cdp()`，不切换为 Playwright 托管 `launch()`，以保持命令语义一致

关键输出模型：

```python
SeedRequestRecord(
    request_url: str,
    request_headers: dict[str, str],
    request_body: str,
    page_url: str,
    tab_id: str,
    asin: str,
    country: str,
    captured_at: int,
)
```

### `RufusReplayService`

职责：

- 按模板逐题执行 Rufus
- 基于 seed request 构造新的 payload
- 维护 `historyThreadContext`
- 调用页面上下文里的 fetch/replay 逻辑
- 将原始 SSE 交给 parser 处理

### `RufusParserService`

职责：

- 解析 SSE 事件
- 提取：
  - 主回答
  - summary
  - 推荐商品链接
  - 推荐 ASIN
  - blocks
- 产出与现有前端兼容的 `AnswerData`

实现策略：

- 优先复刻外部前端 `rufus.ts + rufusTextExtractor.ts` 的逻辑
- 先支持一期所需字段，不做额外抽象

---

## 运行时数据流

```text
opscli amazon-rufus get <asin> <country>
    -> RufusManager
        -> QuestionBankService 读取本地默认题目模板
        -> BrowserAttachService attach Chrome
        -> 打开商品页
        -> 捕获 seed request
        -> RufusReplayService 逐题重放
            -> build payload from seed request
            -> page context fetch /rufus/cl/streaming
            -> SSE raw text
            -> RufusParserService 解析 answer
        -> UploadPayloadBuilder 构造上传结构
        -> 生成注释态上传调用代码对应的数据入参
        -> 返回统一 JSON
```

---

## seed request 设计

### 为什么必须有 seed request

Rufus replay 依赖真实上下文，至少包括：

- 原始请求 URL
- `tabId`
- 原始 requestBody
- 会话线程上下文
- 当前 ASIN / page metadata

没有 seed request，就无法可靠重放。

### 捕获策略

在打开商品页前完成监听：

1. attach Chrome
2. 注册 request listener
3. 导航到商品页
4. 等待首个 `/rufus/cl/streaming`

### 失败策略

超时未捕获时返回：

- 当前页面 URL
- 站点国家
- 等待时长
- 建议操作：
  - 登录 Amazon
  - 刷新页面
  - 检查目标站点是否支持 Rufus

---

## Rufus replay 设计

### 重放策略

推荐在页面上下文中发请求，而不是额外新建独立 httpx 客户端。

原因：

1. Amazon Rufus 更依赖真实浏览器会话上下文。
2. 页面上下文天然复用当前登录态。
3. 更接近外部前端现有实现，迁移风险更低。

### payload 构造

基于 seed request 的 `requestBody`：

1. 反序列化原始 JSON
2. 替换 `queryContext.query`
3. 保留或补齐：
   - `queryContext.actionType`
   - `pageContext.originPageType`
   - `pageContext.originUrl`
   - `pageContext.originPageMetadata`
   - `pageContext.targetPageMetadata`
   - `requestCancellationTokens`
4. 若拿到 threadId，则补 `historyThreadContext`

### 线程上下文

复用外部前端批量模式策略：

- 初始 threadId 优先从 seed payload 中取
- 若不存在，则在首题 SSE 的 `conversation_metadata` 中回填
- 一旦锁定 threadId，后续请求全部显式带回去

---

## 上传 payload 设计

### 设计原则

- 一期只构造，不发送
- 结构与现有前端兼容
- 业务类型与现有前端区分
- 上传 HTTP 实现代码需要存在于 `transport/client.py`
- 调用代码保留在 `manager.py`，但默认注释掉

### record collect payload

建议形状：

```json
{
  "records": [
    {
      "configId": "...",
      "requestUrl": ".../rufus/cl/streaming?...",
      "requestMethod": "POST",
      "requestBody": "{\"asin\":\"B0...\",\"country\":\"US\",\"template_ids\":[1,2,3],\"source\":\"opscli_rufus_cli\"}",
      "pageUrl": "https://www.amazon.com/dp/B0...",
      "country": "US",
      "tabId": 123,
      "capturedAt": 1710000000000,
      "asin": "B0...",
      "businessType": "asin_rufus_cli",
      "questions": [
        { "question": "[T1] ...", "capturedAt": 1710000000000 }
      ]
    }
  ]
}
```

### answer update payload

建议形状：

```json
[
  {
    "question": "[T1] ...",
    "answer": {
      "text": "...",
      "html": "...",
      "summaryText": "...",
      "productLinks": [],
      "recommendedAsins": [],
      "blocks": [],
      "isSuccess": true
    }
  }
]
```

---

## Skill 远端升级设计

### 新 Skill

```text
opscli/skills/templates/ops-amazon-rufus/
```

### 远端同步文件

建议同步以下数据：

- `question_templates.json`

不再同步以下数据：

- `runner_config.json`：一期不需要该文件接口
- `questions/<template_id>.json`：已合并进 `question_templates.json` 的 `questions` 字段
- `marketplaces.json`：国家站点映射固定在代码中

### SkillsUpdater 改造点

在 `opscli/skills/sync/updater.py` 中新增：

- `OPS_RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT`
- `upgrade_ops_amazon_rufus()`

`OPS_RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT` 对应当前接口：

```text
http://127.0.0.1:8000/api/opencalw/default-question-templates
```

### SkillsManager 改造点

在 `opscli/skills/services/manager.py` 中新增：

- `upgrade()` 对 `ops-amazon-rufus` 的分发

一期不新增 `ops-amazon-rufus` 远端版本判断，`status()` 不请求独立版本接口。

---

## 错误模型

建议新增 `opscli/amazon_rufus/domain/exceptions.py`：

- `RufusError`
- `ChromeCdpUnavailableError`
- `SeedRequestNotCapturedError`
- `QuestionBankNotReadyError`
- `RufusReplayError`
- `UnsupportedMarketplaceError`

错误都需要转换成稳定 JSON 输出。

---

## 测试策略

### 单元测试

- 国家码到 marketplace 的映射
- question bank 文件读取
- seed request 选择逻辑
- payload 构造逻辑
- SSE parser 逻辑
- upload payload 构造逻辑

### 集成测试

- mock Playwright browser / page / request
- mock `skills upgrade` 后的数据目录
- 验证 `opscli amazon-rufus get` 的内部数据结构与格式化报告文件输出

### 不做真实依赖

- 不连真实 Amazon
- 不依赖真实 Chrome
- 不调用真实上传接口

---

## 架构结论

推荐采用以下边界：

- `opscli amazon-rufus` 负责正式运行链路
- `ops-amazon-rufus` Skill 负责远端升级数据与使用指南
- Chrome MCP 不进入正式运行时依赖
- 上传接口代码一期写入，但调用位置默认注释掉

这个拆分与当前仓库的 `query + ops-dataset-query` 关系最接近，可维护性最好。
