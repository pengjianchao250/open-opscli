---
name: ops-xiyou
description: Use when the user asks to query or export 西柚洞察/Xiyou data through opscli MCP or CLI, especially 排行榜, ASIN 流量排行榜, ASIN 流量暴增榜, 关键词 ABA 排行榜, 搜索暴增榜, ranking list, ASIN ranking, or keyword ranking. Prefer MCP tools xiyou_scenarios, xiyou_run, xiyou_job_status, and xiyou_export when available; fall back to opscli xiyou commands only when MCP tools are unavailable.
---

# ops-xiyou

Use this skill to turn natural-language Xiyou ranking requests into MCP tool calls or `opscli xiyou` commands.

## Default Path

Prefer MCP tools:

1. Call `xiyou_scenarios` if the available targets or rank patterns are unclear.
2. Map the user intent to `function: "ranking"`.
3. Collect missing required params only.
4. Call `xiyou_run`.
5. If the user asks for the generated file or link, call `xiyou_export` with the returned `job_id`.

MCP default export is `json`. If the user asks for Excel, XLS, XLSX, 表格, or 导出文件, pass `export_format: "xlsx"`.

## Intent Map

| User intent | function | target | rank_pattern |
| --- | --- | --- | --- |
| ASIN 流量排行榜, ASIN ranking | `ranking` | `asin` | `flow` |
| ASIN 流量暴增榜, ASIN surge ranking | `ranking` | `asin` | `surge` |
| 关键词 ABA 排行榜, keyword ABA ranking | `ranking` | `keyword` | `aba` |
| 搜索暴增榜, keyword surge ranking | `ranking` | `keyword` | `surge` |

## Required Params

Always pass:

- `function`: `ranking`.
- `provider`: `xiyou` unless the user explicitly asks for another supported provider.
- `target`: `asin` or `keyword`.
- `site`: marketplace code such as `US`, `DE`, `UK`, `CA`, `FR`.
- `period`: `week` or `month`.
- `page_size`: default `50` unless the user requests otherwise.

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

Run XLSX export:

```bash
opscli xiyou run ranking --provider xiyou --target asin --site US --period week --rank-pattern flow --export-format xlsx
```

Run JSON export:

```bash
opscli xiyou run ranking --provider xiyou --target keyword --site US --period week --rank-pattern aba --export-format json
```

## Guardrails

- Do not ask the user for Xiyou account credentials; authorization is configured on the server.
- Do not call Xiyou APIs directly from the agent. Use MCP tools or CLI.
- Do not invent category IDs or hidden filters. Omit optional filters unless documented.
- This initial version only supports ranking. If the user asks for reverse keyword, multi-ASIN comparison, keyword analysis, or keyword mining, report that those Xiyou scenarios are not connected yet.
- If a scenario returns 0 rows, report the parameters used and suggest checking the same filters in the Xiyou web UI.
