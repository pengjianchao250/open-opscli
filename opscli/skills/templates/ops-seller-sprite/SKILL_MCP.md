---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 MCP usage guide for querying scenarios and exporting JSON or XLSX files through seller_sprite_* tools.
---

# ops-seller-sprite MCP

Use these MCP tools:

- `seller_sprite_scenarios`: list available scenarios.
- `seller_sprite_run`: run a scenario and create an export file.
- `seller_sprite_job_status`: read a saved task result by `job_id`.
- `seller_sprite_export`: read export path, `file://` URL, filename, format, and MIME type.

## Workflow

1. Call `seller_sprite_scenarios` when scenario names or required params are uncertain.
2. Call `seller_sprite_run` with `scenario`, `site`, `period`, `params`, and optionally `export_format`.
3. Use the returned `data.job_id` for follow-up status/export calls.
4. Call `seller_sprite_export` when the user needs the file link.
5. If MCP tools are unavailable, report that SellerSprite MCP is unavailable. Do not fall back to CLI in user-facing flows.

## Export Format

- MCP default: `xls`, which the backend writes as an XLSX file.
- Use `export_format: "json"` only when the user explicitly asks for JSON.
- `xlsx` is accepted by the backend; `xls` and `xlsx` both produce XLSX files.

## Missing Params Policy

- Ask only for missing required params.
- Do not ask for optional params. Omit them and let backend defaults apply unless the user explicitly provides values.
- If a scenario has no required params, run it with defaults after mapping the intent.
- Always include known user-provided conditions in `params`; do not invent category node IDs or hidden enum values.
- If category text maps to multiple possible nodes or no local node ID is available, ask the user to choose or run without the category filter.

## Scenario Mapping

| Natural language | scenario |
| --- | --- |
| 选竞品 / competitor lookup | `competitor-lookup` |
| 选产品 / product research | `product-research` |
| 关键词挖掘 / keyword mining | `keyword-miner` |
| 关键词反查 / reverse ASIN | `keyword-reverse` |
| 查流量来源 / traffic source | `traffic-source` |
| 选市场 / market research | `market-research` |

## Required Params

| scenario | Required | Common optional params |
| --- | --- | --- |
| `competitor-lookup` | none | `keyword`, `brand`, `sellerName`, `asins`, `node` |
| `product-research` | none | `node`/`category`, `minPrice`, `maxPrice`, `minSales`, `maxSales`, `minReviews`, `maxReviews`, `minReviewRating`, `maxReviewRating` |
| `keyword-miner` | `keyword` | `filterRootWord`, `amazonChoice`, `includeHighFrequency` |
| `keyword-reverse` | `asin` | `amazonChoice`/`ac`, `includeHighFrequency`, `badges` |
| `traffic-source` | `keywordOrAsin` | `keyword`, `asin`, `asins`, `order`, `desc` |
| `market-research` | none | `node`/`category`, `departmentKeyword`, `newReleaseNum`/`newReleaseMonths`, `topn` |

Always pass:

- `site`: marketplace code such as `US`, `JP`, `DE`, `UK`, `FR`, `IT`, `ES`, `CA`, `IN`, `MX`.
- `period`: `30d`, `nearly`, or a month such as `2026-03`.
- `page_size`: default `100` unless the user requests otherwise.

## Defaults

Top-level defaults:

| Field | Default |
| --- | --- |
| `site` | `US` |
| `period` | `30d` |
| `page_size` | `100` |
| `export_format` | `xls` (XLSX file) |

Scenario defaults:

| scenario | Defaults |
| --- | --- |
| `competitor-lookup` | `page=1`, `order.field=amz_unit`, `order.desc=true`, `lowPrice=N` |
| `product-research` | `page=1`, `selectType=2`, `order.field=amz_unit`, `order.desc=true`, `smallAndLight=N`, `lowPrice=N` |
| `keyword-miner` | `pageNum=1`, `orderBy=5`, `desc=true`, `filterRootWord=0`, `amazonChoice=false`, `includeHighFrequency=true` |
| `keyword-reverse` | `page=1`, `order=12`, `desc=true`, `ac=false`, `includeHighFrequency=true` |
| `traffic-source` | `pageNo=1`, `order=10`, `desc=true` |
| `market-research` | `marketId=US(1)`, `monthName=bsr_sales_nearly`, `sampleNumber=1`, `topn=10`, `newReleaseNum=6`, `order.field=total_sales`, `order.desc=true` |

## Call Examples

```json
{
  "scenario": "keyword-reverse",
  "site": "JP",
  "period": "nearly",
  "params": {
    "asin": "B07YRMT36L"
  },
  "export_format": "xlsx"
}
```

```json
{
  "scenario": "keyword-miner",
  "site": "JP",
  "period": "nearly",
  "params": {
    "keyword": "flashlight",
    "filterRootWord": 1,
    "amazonChoice": true
  },
  "export_format": "json"
}
```

```json
{
  "scenario": "traffic-source",
  "site": "US",
  "period": "nearly",
  "params": {
    "keyword": "solar outdoor lights"
  },
  "export_format": "json"
}
```

```json
{
  "scenario": "market-research",
  "site": "CA",
  "period": "nearly",
  "params": {
    "departmentKeyword": "Baby Diapers",
    "newReleaseNum": 3
  },
  "export_format": "xlsx"
}
```

## Result Handling

For `seller_sprite_run`, read:

- `data.job_id`
- `data.row_count`
- `data.export.filename`
- `data.export.path`
- `data.export.url`
- `data.export.format`

If `success=false`, report `error.message` and do not reuse stale files.
