# ops-amazon-rufus PRD

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
4. 命令输出中包含：
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
  [--output <file>] \
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
  - 可选，格式化 JSON 输出
- `--output`
  - 可选，将最终结果写入文件
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

### FR-8 命令输出

命令成功时返回 JSON，至少包含：

- `asin`
- `country`
- `page_url`
- `seed_record`
- `questions`
- `answers`
- `upload_payload`
- `captured_at`

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
