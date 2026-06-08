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
| 多ASIN对比 | `asin-compare` | omit | omit | `asins` |
| 关键词分析 | `keyword-analysis` | omit | omit | `keyword` |
| 以词找词, 关键词拓展 | `keyword-explorer` | omit | omit | `keyword` |

## Required Params

Always pass:

- `function`: one of `ranking`, `reverse-keyword`, `asin-compare`, `keyword-analysis`, `keyword-explorer`.
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

For resource export scenarios:

- `reverse-keyword`: pass `asin`.
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

After `xiyou_run`, return only the `job_id`, row count, export filename, and clickable `url` when available. In the final user-facing answer, render the file as a Markdown link such as `[打开 Excel](file:///...)` and do not print the Windows `path` unless the user explicitly asks for it. Use `xiyou_job_status` only when the user asks for full task details. Do not expose Xiyou authorization token or cookies.

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
- If a scenario returns 0 rows, report the parameters used and suggest checking the same filters in the Xiyou web UI.
- Resource export scenarios may return `row_count: 0` because the data is inside the downloaded Excel file. Do not treat that as no data when `data_mode` is `resource_export`.
