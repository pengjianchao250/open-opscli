# ops-amazon-rufus Architecture

## 2026-04-29 架构增量：UTF-8 运行环境与答案文本投影

### 设计原则

本轮变更调整 CLI 成功输出契约：`amazon-rufus get` 执行完成后不输出完整 JSON，只输出 `answers[].text`。

### UTF-8 运行契约

Windows PowerShell 运行示例必须在同一进程环境中设置：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

说明：

1. `PYTHONUTF8=1` 强制 Python 使用 UTF-8 模式，降低 Windows 默认代码页导致的乱码风险。
2. `PYTHONIOENCODING=utf-8` 约束标准输入输出编码，保证 JSON 中中文答案可被 Agent 正确解析。
3. 该环境变量只作用于当前命令会话，不修改系统级环境变量。

### 输出分层契约

1. CLI 层：成功时只输出 `answers[].text`。
2. Service 层：仍可保留完整数据结构用于内部编排。
3. 用户展示层：只展示答案文本，不展示完整 JSON、`seed_request`、`upload_payload` 或 headers。

### 文本投影规则

伪代码：

```python
answers = data.get("answers", [])
texts = [answer.get("text", "").strip() for answer in answers if answer.get("text", "").strip()]
print("\n\n".join(texts))
```

失败处理：

1. 出现异常时输出稳定 JSON 错误结构。
2. 单题无 `text` 且 `isSuccess=false` 时，展示该题失败摘要。
3. 不把解析失败时的原始 JSON 直接贴给最终用户，除非用户明确要求排障。

### 代码实现边界

本变更移除 `--answers-text` 参数需求，成功路径默认执行文本投影输出。错误路径保留稳定 JSON 错误结构，便于排障。

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

- CLI 层只做参数解析与 JSON 输出
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
- 统一 JSON 输出
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
- 验证 `opscli amazon-rufus get` 的 JSON 输出结构

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
