# ops-amazon-rufus Architecture

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
