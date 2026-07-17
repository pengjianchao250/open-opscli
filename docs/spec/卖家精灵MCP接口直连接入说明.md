# 卖家精灵 MCP 接口直连接入说明

## 模块边界

旧 Playwright 采集方案已移动到 `opscli/seller_sprite_legacy`，仅保留为迁移参考。

新接口直连方案位于 `opscli/seller_sprite`，MCP 工具位于 `opscli/mcp/tools/seller_sprite.py`。后续对外入口优先使用 MCP，不暴露卖家精灵账号密码。

## CLI 命令契约

- `opscli seller-sprite` 是正式的 remote-first 用户入口，对外命令面只保留远端 MCP 相关能力。
- 当前 `opscli seller-sprite` 实现仍通过现有本地服务链路做迁移桥接，但命令面已经冻结为正式公共契约；后续切到 remote MCP 时不再新增本地专用参数。
- `opscli seller-sprite-debug` 仅用于开发调试，保留本地浏览器/账号执行链路和本地专用参数。
- 本地浏览器/账号直跑能力不属于公开 `opscli seller-sprite` 命令契约。

## 账号配置

服务端本地配置账号，MCP 调用方不传账号密码。

远端 MCP 调用方也不得向 SellerSprite 业务工具传递 `session_id/jwt`。服务端以当前已验证的 MCP API Key 为身份，按 API Key + Agent 隔离复用 OPS 凭证；凭证缺失或过期时自动执行一步登录。旧客户端携带的显式凭证参数仅保留为过渡兼容，服务端忽略其值且不会持久化或用于任务执行。

支持 `.env` 或环境变量：

```env
OPSCLI_SELLER_SPRITE_USERNAME=your_account
OPSCLI_SELLER_SPRITE_PASSWORD=your_password
OPSCLI_SELLER_SPRITE_ACCOUNT_NAME=default
OPSCLI_SELLER_SPRITE_OUTPUT_DIR=D:/seller_sprite_runs
OPSCLI_SELLER_SPRITE_PAGE_SIZE=100
```

未配置 `OPSCLI_SELLER_SPRITE_OUTPUT_DIR` 时，默认输出到 `~/.config/opscli/seller_sprite/api_runs`。

## MCP 启动

stdio：

```bash
opscli-mcp
```

HTTP：

```bash
opscli-mcp --transport http --port 8765
```

SSE：

```bash
opscli-mcp --transport sse --port 8765
```

## MCP Tools

### `seller_sprite_scenarios` / `seller_sprite_quota_status`

`seller_sprite_scenarios` 列出当前支持的场景；`seller_sprite_quota_status` 返回当前 MCP 用户的每日额度快照。这两类只读请求不消费查询额度。

### `seller_sprite_run`

普通任务调用一次 `seller_sprite_run` 后立即持久化入队，不在入口内等待业务完成。调用方只传业务参数，采集模式由后端决定，不传 `mode`、`browser-route`、`api-direct` 或 `async_mode`。

参数：

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `scenario` | `str`，必填 | 场景 ID |
| `params` | `dict \| str \| null` | 场景参数对象或 JSON 字符串 |
| `site` | `str = "US"` | 站点，如 `US`、`JP`、`DE` |
| `period` | `str = "30d"` | 日期，如 `30d`、`nearly`、`2026-03` |
| `page_size` | `int = 100` | 每页数量 |
| `export_format` | `str = "xls"` | 可选 `xlsx` / `xls` / `json` |
| `page_prepare` | `bool \| null` | 可选页面预热设置 |
| `task_interval_seconds` | `float \| null` | 可选任务间隔 |
| `cooldown_seconds` | `float \| null` | 可选失败冷却 |
| `output_dir` | `str \| null` | 可选任务输出目录 |
| `job_id` | `str \| null` | 可选指定任务 ID |
| `session_id` / `jwt` | `str \| null` | 可选显式认证；省略时读取当前 MCP 隔离凭证 |

输入示例：

```text
seller_sprite_run(
  scenario="keyword-reverse",
  params={"asin": "B07YRMT36L"},
  site="JP",
  period="nearly",
  page_size=100,
  export_format="xls"
)
```

立即入队返回示例：

```json
{
  "success": true,
  "data": {
    "job_id": "SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-20260710-153000-a1b2c3",
    "scenario": "keyword-reverse",
    "site": "JP",
    "period": "nearly",
    "state": "queued",
    "stage": "queued",
    "position": 2,
    "created_at": "2026-07-10T15:30:00+08:00"
  },
  "error": null
}
```

顶层 `success=true` 只表示工具请求成功，不表示业务已完成；上例的 `state=queued` 仍是 pending。

### `seller_sprite_job_status`

单任务签名为 `seller_sprite_job_status(job_id: str, wait_seconds: int = 0)`。`wait_seconds` 会被限制在 0–30 秒；Agent 跟踪普通任务时使用 `seller_sprite_job_status(job_id, wait_seconds=30)`。

精确输入示例：`seller_sprite_job_status(job_id="job-1", wait_seconds=30)`。

```text
seller_sprite_job_status(job_id="job-1", wait_seconds=30)
```

等待窗口到期、任务仍在执行时返回最新快照：

```json
{
  "success": true,
  "data": {
    "job_id": "job-1",
    "state": "running",
    "stage": "running",
    "position": null
  },
  "error": null
}
```

`queued`、`running`、`ready=false` 和等待窗口到期都表示 pending，不是工具失败或业务失败。到期不会取消、标记失败或重新入队持久任务。

### `seller_sprite_jobs_status`

批量签名为 `seller_sprite_jobs_status(job_ids: list[str], wait_seconds: int = 0)`，一次接收 1–50 个普通任务 ID。工具先校验完整集合归属，按首次出现顺序去重，并返回 `ready`、`summary` 和 `jobs`。

精确输入示例：`seller_sprite_jobs_status(job_ids=["job-a", "job-b"], wait_seconds=30)`。

```text
seller_sprite_jobs_status(job_ids=["job-a", "job-b"], wait_seconds=30)
```

批量 pending 返回示例：

```json
{
  "success": true,
  "data": {
    "ready": false,
    "summary": {
      "total": 2,
      "queued": 1,
      "running": 1,
      "succeeded": 0,
      "failed": 0
    },
    "jobs": [
      {
        "job_id": "job-a",
        "state": "queued",
        "stage": "queued",
        "position": 2
      },
      {
        "job_id": "job-b",
        "state": "running",
        "stage": "fetching",
        "position": null
      }
    ]
  },
  "error": null
}
```

`ready=false` 表示至少一个任务仍未终态；`ready=true` 表示全部任务均为 `succeeded` 或 `failed`。状态窗口到期只返回最新 `summary/jobs` 快照，不改变队列生命周期。

### Agent 单任务/批量跟踪契约

1. 一个普通 pending ID：调用 `seller_sprite_job_status(job_id, wait_seconds=30)`。
2. 多个普通 pending ID：优先每个窗口调用一次 `seller_sprite_jobs_status(job_ids, wait_seconds=30)`，不要逐个查询。
3. 同一轮执行 3–4 个 30 秒有界窗口，总预算 90–120 秒；全部终态时提前停止。
4. 每个窗口后保留全部未完成 `job_id`。预算到期时告诉用户可直接说“继续”或“查结果”；后续裸 `继续` / `查结果` 恢复完整 pending 集合，除非用户明确选择子集。
5. pending 普通任务不得重新提交，不得再次调用 `run` 查状态，也不得重新消耗额度。`run` 消耗额度；状态和导出不消耗额度。
6. 等待窗口到期不会取消、标记失败或重新入队；它只结束本次有界状态请求。

### `seller_sprite_export`

`seller_sprite_export(job_id: str)` 读取当前 MCP 用户所属普通任务的导出文件信息。任务成功后再调用；状态和导出不消耗额度。

### Listing Analysis 专用流程

Listing Analysis 必须使用 `seller_sprite_listing_analysis_submit`、`seller_sprite_listing_analysis_status`、`seller_sprite_listing_analysis_result` 的 submit/status/result 三段式。`seller_sprite_run` 生产入口会明确拒绝 `listing-analysis`，调用方必须改用 `seller_sprite_listing_analysis_submit`。它不属于普通批量任务，Listing Analysis `job_id` 不得传入 `seller_sprite_jobs_status`；本工作流继续使用专用 status/result，不推荐改用通用单任务状态工具。

```text
seller_sprite_listing_analysis_submit(asin="B0XXXX", station="GLOBAL", site="US", export_format="json")
seller_sprite_listing_analysis_status(job_id="listing-job-1")
seller_sprite_listing_analysis_result(job_id="listing-job-1", export_format="json")
```

`status/result` 返回 `ready=false` 时保留同一个 Listing Analysis `job_id`，不要重新 submit；用户裸“继续/查结果”时仍走专用 status/result，不并入普通 pending 集合。

### 正式 CLI 对应命令

```bash
opscli seller-sprite run keyword-reverse --site JP --period nearly --params "{\"asin\":\"B07YRMT36L\"}" --export-format xls
opscli seller-sprite job-status job-1 --wait-seconds 30
opscli seller-sprite jobs-status job-a job-b --wait-seconds 30
opscli seller-sprite export job-1
```

## 场景参数示例

竞品查询精简验证：

```json
{
  "scenario": "competitor-lookup",
  "site": "DE",
  "period": "2026-04",
  "params": {
    "keyword": "flashlight"
  }
}
```

竞品查询可选筛选：

```json
{
  "params": {
    "keyword": "flashlight",
    "brand": "anker",
    "sellerName": "AnkerDirect",
    "asins": "B00FLYWNYQ",
    "node": "78191031"
  }
}
```

选竞品：

```json
{
  "scenario": "product-research",
  "site": "JP",
  "period": "2026-03",
  "params": {}
}
```

关键词挖掘：

```json
{
  "scenario": "keyword-miner",
  "site": "JP",
  "period": "nearly",
  "params": {
    "keyword": "flashlight",
    "filterRootWord": 1,
    "amazonChoice": true
  }
}
```

关键词反查：

```json
{
  "scenario": "keyword-reverse",
  "site": "JP",
  "period": "nearly",
  "params": {
    "asin": "B07YRMT36L"
  }
}
```

## 手动验证清单

- 配置服务端账号后，调用 `seller_sprite_scenarios` 能返回当前注册场景。
- 对当前注册场景分别调用一次 `seller_sprite_run`，确认任务立即持久化入队并返回 `job_id`。
- 一个普通 pending 任务使用 `seller_sprite_job_status(job_id, wait_seconds=30)` 做有界状态查询。
- 多个普通 pending 任务使用 `seller_sprite_jobs_status(job_ids, wait_seconds=30)` 做有界批量状态查询。
- 任务完成后，每个任务目录包含 `params.json`、`raw.json`、`result.json`、`*.xlsx`。
- `seller_sprite_export(job_id)` 返回 XLSX 路径和 `file://` 文件链接。
- 失败时 MCP 返回 `_err` 结构，并包含状态码或响应摘要。

## 2026-05-22 本地验证记录

运行环境：

- 仓库：`D:/Gitlab/open-opscli`
- 账号来源：复用 `D:/Gitlab/sellersprite-api-lab/.env`，运行时映射到 `OPSCLI_SELLER_SPRITE_USERNAME` / `OPSCLI_SELLER_SPRITE_PASSWORD`
- 输出目录：`D:/Gitlab/open-opscli/tmp-validation/seller-sprite-runs`
- `uv sync` 在当前机器因缺少 MSVC Build Tools 无法构建本项目 editable wheel；本次验证改用 `uv pip install --python .venv/Scripts/python.exe ...` 安装运行依赖。

验证结果：

| 场景 | 条件 | 结果 |
| --- | --- | --- |
| `seller_sprite_scenarios` | 无 | 返回 4 个场景 |
| XLSX smoke | 本地模拟 1 行 | 成功生成 `tmp-validation/seller-sprite-export-smoke.xlsx` |
| `keyword-reverse` | `JP` / `nearly` / `B07YRMT36L` | 100 行，已生成 XLSX |
| `product-research` | `JP` / `2026-03` | 100 行，已生成 XLSX |
| `keyword-miner` | `JP` / `nearly` / `flashlight` / 词根匹配 + AC | 10 行，已生成 XLSX |
| `competitor-lookup` | `DE` / `2026-04` / 关键词 `flashlight` | 待用精简条件重新验证 |
| `seller_sprite_job_status` | 竞品查询最小条件任务 | 成功读取 `row_count=100` |
| `seller_sprite_export` | 竞品查询最小条件任务 | 成功返回 XLSX 路径 |

说明：竞品查询完整筛选条件返回 0 行，不是接口调用失败；同接口最小条件已验证可返回 100 行。

## XLSX 模板对齐说明

已参考以下官方导出模板对齐 sheet 和列顺序：

| 模板 | Sheet |
| --- | --- |
| `Competitor-US-Last-30-days-442354.xlsx` | `Competitor-US-Last-30-days`、`Notes` |
| `Product-JP-2026.03-458153.xlsx` | `Product-JP-202603`、`Notes` |
| `KeywordMining-JP-flashlight-Last-30-days-467502.xlsx` | 主表、`Unique Words`、`Notes` |
| `ReverseASIN-JP-B07YRMT36L-Last-30-days.xlsx` | 主表、`Unique Words`、`Notes` |

当前导出策略：

- 产品类场景（竞品查询、选竞品）使用 64 列官方模板顺序。
- 关键词挖掘使用 34 列官方模板顺序。
- 关键词反查使用 31 列官方模板顺序。
- 高频词接口成功时写入 `Unique Words`，列为 `词语`、`出现频次`、`百分比`。
- 高频词接口失败时不阻断主表导出，错误写入 `raw.json.warnings` 和 `result.json.warnings`。
- 当前导出不写入 `Notes`，只保留业务数据 sheet。

模板字段与当前接口数据差异：

| 场景 | 模板字段 | 当前处理 |
| --- | --- | --- |
| 竞品查询 / 选竞品 | `SP广告`、`品牌故事`、`品牌广告`、`7天促销`、`标签` | 当前接口主列表未稳定提供对应字段，导出为空 |
| 竞品查询 / 选竞品 | 币种列名 | 按站点处理；`JP` 使用 `円`，其他站点当前使用 `$` |
| 关键词挖掘 / 关键词反查 | `Unique Words` | 依赖高频词附加接口；触发风控时为空且主表继续导出 |
| 关键词反查 | 排名页码、更新时间、关键词类型中文文案 | 当前按接口原值导出；如接口返回 code/对象，后续可补中文映射 |

后续新增模块时，应优先补充对应官方导出模板：sheet 名、列顺序、字段来源、缺失字段说明。
