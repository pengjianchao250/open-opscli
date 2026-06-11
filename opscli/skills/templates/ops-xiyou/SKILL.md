---
name: ops-xiyou
description: Use when the user asks to query or export 西柚洞察/Xiyou data through opscli MCP or CLI, especially 排行榜, 反查关键词, 多ASIN对比, 关键词分析, 以词找词, ASIN ranking, keyword ranking, reverse keyword, ASIN compare, keyword analysis, or keyword explorer. Prefer MCP tools xiyou_scenarios, xiyou_run, xiyou_job_status, and xiyou_export when available; fall back to opscli xiyou commands only when MCP tools are unavailable.
---

# ops-xiyou

Use this skill to turn natural-language Xiyou requests into MCP tool calls or `opscli xiyou` commands.

## Default Path

Prefer MCP tools:

1. Call `xiyou_scenarios` if the available targets or rank patterns are unclear.
2. Map the user intent to one supported `function`.
3. Collect missing required params only.
4. Call `xiyou_run`.
5. If the user asks for the generated file or link, call `xiyou_export` with the returned `job_id`.

MCP default export is `json`. If the user asks for Excel, XLS, XLSX, 表格, or 导出文件, pass `export_format: "xlsx"`.

## Intent Map

| User intent | function | target | rank_pattern | Required |
| --- | --- | --- | --- |
| ASIN 流量排行榜, ASIN ranking | `ranking` | `asin` | `flow` | none |
| ASIN 流量暴增榜, ASIN surge ranking | `ranking` | `asin` | `surge` | none |
| 关键词 ABA 排行榜, keyword ABA ranking | `ranking` | `keyword` | `aba` | none |
| 搜索暴增榜, keyword surge ranking | `ranking` | `keyword` | `surge` | none |
| 反查关键词, ASIN 关键词反查 | `reverse-keyword` | omit | omit | `asin` |
| 广告分析 | `ad-analysis` | omit | omit | `asin` |
| 父体分析 | `parent-analysis` | omit | omit | `parent_asin`, `asins` |
| 订单量分析 | `sales-analysis` | omit | omit | `asin`, `parent_asin` |
| 流量诊断仪 | `flow-diagnosis` | omit | omit | `asin` |
| 流量洞察 | `flow-insight` | omit | omit | `asin`, `start_date`, `end_date` |
| 广告洞察 | `ad-insight` | omit | omit | `asin`, `start_date`, `end_date` |
| 流量周报 | `flow-weekly` | omit | omit | `asin`, `start_date`, `end_date` |
| 多ASIN对比 | `asin-compare` | omit | omit | `asins` |
| 关键词分析 | `keyword-analysis` | omit | omit | `keyword` |
| 以词找词, 关键词拓展 | `keyword-explorer` | omit | omit | `keyword` |

## Required Params

Always pass:

- `function`: one of `ranking`, `reverse-keyword`, `ad-analysis`, `parent-analysis`, `sales-analysis`, `flow-diagnosis`, `flow-insight`, `ad-insight`, `flow-weekly`, `asin-compare`, `keyword-analysis`, `keyword-explorer`.
- `provider`: `xiyou` unless the user explicitly asks for another supported provider.
- `site`: 西柚站点 code。支持：
  - 北美及拉美：`US`（美国）、`CA`（加拿大）、`MX`（墨西哥）、`BR`（巴西）
  - 欧洲：`DE`（德国）、`UK`（英国）、`FR`（法国）、`IT`（意大利）、`ES`（西班牙）
  - 日本：`JP`
  - 中东：`AE`（阿联酋）、`SA`（沙特）
  - 澳洲：`AU`（澳大利亚）

  用户用中文国家名（如"日本"、"美国站"）时优先映射为对应 code 再传入；opscli 内部对中文别名也有兜底映射，传入不在以上列表的站点会直接报错。
- `page_size`: default `50` unless the user requests otherwise.

For `ranking`, also pass:

- `target`: `asin` or `keyword`.
- `period`: `week` or `month`.
- `rank_pattern`: see intent map.
- `query`: optional ASIN / keyword filter. If the user says `asin=...` in an ASIN ranking request or `keyword=...` in a keyword ranking request, you may pass that value through `asin` / `keyword`; opscli will treat it as a `query` alias for `ranking`.

For resource export scenarios:

- `reverse-keyword`: pass `asin`. When the latest web doc requires the monthly data view, also pass `view_mode` plus `keyword_type`; `keyword_type=organic/advertising` maps to the dedicated `dataList` request and table variant.
- `ad-analysis`: pass `asin`; when `parent_asin` / `asins` are omitted, opscli will auto-call the documented variation preflight APIs to resolve them. Use `search_terms` or `keyword/query` for the searched term list.
- `parent-analysis`: pass `parent_asin`, `asins`; `query` is the filtered keyword text, and `keyword_type` supports `all/organic/advertising`.
- `sales-analysis`: pass `asin`, `parent_asin`; use monthly `cycle_period` or `start_month/end_month`.
- `flow-diagnosis`: pass `asin` only when the user is asking about the scenario itself. If the user explicitly asks to download/export this scenario, stop immediately and tell them Xiyou officially has no download API for it. Do not try alternate endpoints, page scraping, or inferred export paths.
  Natural-language alias guidance: map `流量诊断仪` and `流量诊断` to `flow-diagnosis`. Do not map the standalone word `诊断仪` by itself, because it is too broad and may refer to other diagnosis capabilities in future.
- `flow-insight`: pass `asin`, `start_date`, `end_date`.
- `ad-insight`: pass `asin`, `start_date`, `end_date`.
- `flow-weekly`: pass `asin`, `start_date`, `end_date`.
- `asin-compare`: pass `asins` as a list or comma-separated string with at least 2 ASINs.
- `keyword-analysis`: pass `keyword`.
- `keyword-explorer`: pass `keyword`.

Optional:

- `query`: ASIN or keyword filter.
- `page`: default `1`.
- `job_id`: only when the user needs a stable custom job id.

## MCP Examples

ASIN ranking XLSX:

```json
{
  "function": "ranking",
  "provider": "xiyou",
  "target": "asin",
  "site": "US",
  "period": "week",
  "rank_pattern": "flow",
  "export_format": "xlsx"
}
```

Reverse keyword XLSX:

```json
{
  "function": "reverse-keyword",
  "provider": "xiyou",
  "asin": "B0G33FZ8XS",
  "site": "US",
  "export_format": "xlsx"
}
```

Reverse keyword monthly organic data view:

```json
{
  "function": "reverse-keyword",
  "provider": "xiyou",
  "asin": "B0DZFGTCLR",
  "site": "US",
  "view_mode": "data",
  "keyword_type": "organic",
  "cycle_period": "last1month",
  "query": "home decor",
  "export_format": "xlsx"
}
```

Ad analysis JSON:

```json
{
  "function": "ad-analysis",
  "provider": "xiyou",
  "asin": "B0DZFGTCLR",
  "parent_asin": "B0FDB5VR1V",
  "asins": ["B0DZFGTCLR", "B0DZFW1QS1"],
  "search_terms": ["candle warmer"],
  "site": "US",
  "export_format": "json"
}
```

Flow insight JSON:

```json
{
  "function": "flow-insight",
  "provider": "xiyou",
  "asin": "B0DZFGTCLR",
  "site": "US",
  "start_date": "2026-05-27",
  "end_date": "2026-06-09",
  "export_format": "json"
}
```

Multi-ASIN compare XLSX:

```json
{
  "function": "asin-compare",
  "provider": "xiyou",
  "asins": ["B0G33FZ8XS", "B0G337Q47M"],
  "site": "US",
  "export_format": "xlsx"
}
```

Keyword analysis XLSX:

```json
{
  "function": "keyword-analysis",
  "provider": "xiyou",
  "keyword": "tv stands for living room",
  "site": "US",
  "export_format": "xlsx"
}
```

Keyword explorer XLSX:

```json
{
  "function": "keyword-explorer",
  "provider": "xiyou",
  "keyword": "tv stand",
  "site": "US",
  "export_format": "xlsx"
}
```

Keyword ABA ranking JSON:

```json
{
  "function": "ranking",
  "provider": "xiyou",
  "target": "keyword",
  "site": "US",
  "period": "week",
  "rank_pattern": "aba"
}
```

After `xiyou_run`, return only the `job_id`, row count, export filename, and clickable `url` when available. If `resource_url` or `export.download_url` exists, show that real download link first; do not make the user click a local `.json` / `.url` wrapper file just to see the download URL. If `export.local_url` also exists, keep it only as a fallback. In the final user-facing answer, render the preferred link as a Markdown link and do not print the Windows `path` unless the user explicitly asks for it. Use `xiyou_job_status` only when the user asks for full task details. Do not expose Xiyou authorization token or cookies.

## CLI Fallback

Use CLI only when MCP tools are unavailable.

List scenarios:

```bash
opscli xiyou scenarios
```

Run ranking XLSX export:

```bash
opscli xiyou run ranking --provider xiyou --target asin --site US --period week --rank-pattern flow --export-format xlsx
```

Run reverse keyword XLSX export:

```bash
opscli xiyou run reverse-keyword --provider xiyou --asin B0G33FZ8XS --site US --export-format xlsx
```

Run multi-ASIN compare XLSX export:

```bash
opscli xiyou run asin-compare --provider xiyou --asins B0G33FZ8XS,B0G337Q47M --site US --export-format xlsx
```

Run keyword analysis XLSX export:

```bash
opscli xiyou run keyword-analysis --provider xiyou --keyword "tv stands for living room" --site US --export-format xlsx
```

Run keyword explorer XLSX export:

```bash
opscli xiyou run keyword-explorer --provider xiyou --keyword "tv stand" --site US --export-format xlsx
```

Run JSON export:

```bash
opscli xiyou run ranking --provider xiyou --target keyword --site US --period week --rank-pattern aba --export-format json
```

## Guardrails

- Do not ask the user for Xiyou account credentials; authorization is configured on the server.
- Do not call Xiyou APIs directly from the agent. Use MCP tools or CLI.
- Do not invent category IDs or hidden filters. Omit optional filters unless documented.
- If the scenario is `flow-diagnosis` and the user wants a download/export, explicitly tell them: `西柚官方暂未提供下载接口` and stop this task. Do not continue trying other technical paths.
- If a scenario returns 0 rows, report the parameters used and suggest checking the same filters in the Xiyou web UI.
- Resource export scenarios may return `row_count: 0` because the data is inside the downloaded Excel file. Do not treat that as no data when `data_mode` is `resource_export`.
