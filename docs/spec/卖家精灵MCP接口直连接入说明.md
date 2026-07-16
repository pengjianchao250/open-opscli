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

### `seller_sprite_scenarios`

列出当前支持的接口场景。

### `seller_sprite_run`

执行场景并导出 XLSX。

兼容说明：调用方只需要传业务参数，不需要选择同步/异步或采集模式。后端会在长任务场景或同账号浏览器 worker 已有运行中/排队任务时，自动切换为异步任务并立即返回 `job_id`。这样后续请求不会把 MCP 同步等待时间耗在浏览器队列排队上。采集模式由服务端配置和风控策略决定，不通过 MCP 参数暴露。

参数：

| 参数 | 说明 |
| --- | --- |
| `scenario` | 场景 ID |
| `params` | 场景参数对象 |
| `site` | 站点，如 `US`、`JP`、`DE` |
| `period` | 日期，如 `30d`、`nearly`、`2026-03` |
| `page_size` | 默认 `100` |
| `export_format` | MCP 默认 `xls`；可选 `xlsx` / `xls` / `json` |
| `output_dir` | 可选任务输出目录 |
| `job_id` | 可选指定任务 ID |

返回：

```json
{
  "success": true,
  "data": {
    "job_id": "SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-20260522-153000-a1b2c3",
    "scenario": "keyword-reverse",
    "row_count": 100,
    "raw_path": ".../raw.json",
    "result_path": ".../result.json",
    "export": {
      "path": ".../SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-20260522-153000-a1b2c3.xlsx",
      "filename": "SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-20260522-153000-a1b2c3.xlsx",
      "url": "file:///.../SellerSprite-ReverseASIN-JP-B07YRMT36L-Nearly-20260522-153000-a1b2c3.xlsx",
      "format": "xlsx"
    }
  },
  "error": null
}
```

### `seller_sprite_job_status`

通过 `job_id` 读取 `result.json`。

异步返回示例：

返回示例：

```json
{
  "success": true,
  "data": {
    "job_id": "SellerSprite-ProductResearch-US-Bookcases-20260616-120000-a1b2c3",
    "scenario": "product-research",
    "site": "US",
    "period": "30d",
    "state": "queued",
    "stage": "created"
  },
  "error": null
}
```

Agent 应在同一轮对话内用 `seller_sprite_job_status(job_id)` 自动轮询 60 到 90 秒；如果仍未完成，应把 `job_id` 留在对话上下文中，用户后续说“继续”或“查结果”时直接复用该任务编号。

### `seller_sprite_export`

通过 `job_id` 读取导出文件信息。当前返回服务器本地路径和 `file://` 文件链接，不返回二进制。远程公网下载后续可扩展 HTTP 临时链接、base64 或 MCP resource。

CLI 调用默认导出 XLSX：

```bash
opscli seller-sprite run keyword-reverse --site JP --period nearly --params "{\"asin\":\"B07YRMT36L\"}"
```

CLI 也可导出 JSON：

```bash
opscli seller-sprite run keyword-reverse --site JP --period nearly --params "{\"asin\":\"B07YRMT36L\"}" --export-format json
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

- 配置服务端账号后，调用 `seller_sprite_scenarios` 能返回 4 个场景。
- 调用 `seller_sprite_run` 跑通登录。
- 4 个场景分别获取 100 条以内数据。
- 每个任务目录包含 `params.json`、`raw.json`、`result.json`、`*.xlsx`。
- `seller_sprite_job_status(job_id)` 能读取行数、路径和导出信息。
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
