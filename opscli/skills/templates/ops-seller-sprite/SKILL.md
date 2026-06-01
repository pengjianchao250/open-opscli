---
name: ops-seller-sprite
description: Use when the user asks to query or export SellerSprite/卖家精灵 data through opscli MCP or CLI, including 竞品查询, 选竞品, 选产品, 选市场, 查流量来源, 关键词挖掘, 关键词反查, ASIN reverse lookup, keyword mining, product research, market research, traffic source, competitor lookup, XLS/XLSX export, or JSON export. Prefer MCP tools seller_sprite_scenarios, seller_sprite_run, seller_sprite_job_status, and seller_sprite_export when available; fall back to opscli seller-sprite commands only when MCP tools are unavailable.
---

# ops-seller-sprite

Use this skill to turn natural-language SellerSprite requests into MCP tool calls or `opscli seller-sprite` commands.

## Default Path

Prefer MCP tools:

1. Call `seller_sprite_scenarios` if the available scenarios or required params are unclear.
2. Map the user intent to a `scenario`.
3. Collect missing required params only.
4. Call `seller_sprite_run`.
5. If the user asks for the generated file or link, call `seller_sprite_export` with the returned `job_id`.

MCP default export is `json`. If the user asks for Excel, XLS, XLSX, 表格, or 导出文件, pass `export_format: "xlsx"`.

## Intent Map

| User intent | scenario |
| --- | --- |
| 选竞品, 竞品查询, competitor lookup | `competitor-lookup` |
| 选产品, 产品筛选, product research | `product-research` |
| 关键词挖掘, 挖词, keyword mining | `keyword-miner` |
| 关键词反查, ASIN 反查, reverse ASIN | `keyword-reverse` |
| 查流量来源, 流量来源, traffic source | `traffic-source` |
| 选市场, market research | `market-research` |

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

## MCP Examples

Keyword reverse XLSX:

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

Keyword mining JSON:

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

Competitor lookup XLSX:

```json
{
  "scenario": "competitor-lookup",
  "site": "DE",
  "period": "2026-04",
  "params": {
    "keyword": "flashlight"
  },
  "export_format": "xlsx"
}
```

Traffic source JSON:

```json
{
  "scenario": "traffic-source",
  "site": "US",
  "period": "nearly",
  "params": {
    "keyword": "solar outdoor lights"
  }
}
```

Market research XLSX:

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

After `seller_sprite_run`, return the `job_id`, row count, export filename, and export URL/path. Do not expose SellerSprite account credentials.

## CLI Fallback

Use CLI only when MCP tools are unavailable.

List scenarios:

```bash
opscli seller-sprite scenarios
```

Run XLSX export:

```bash
opscli seller-sprite run keyword-reverse --site JP --period nearly --params "{\"asin\":\"B07YRMT36L\"}" --export-format xlsx
```

Run JSON export:

```bash
opscli seller-sprite run keyword-miner --site JP --period nearly --params "{\"keyword\":\"flashlight\"}" --export-format json
```

## Guardrails

- Do not ask the user for SellerSprite account credentials; they are configured on the server.
- Do not call SellerSprite APIs directly from the agent. Use MCP tools or CLI.
- Do not invent category node IDs or hidden filter values. Ask for them or omit optional filters.
- If a scenario returns 0 rows, report the parameters used and suggest checking the same filters in the SellerSprite web UI.
