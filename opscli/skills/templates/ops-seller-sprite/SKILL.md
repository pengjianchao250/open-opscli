---
name: ops-seller-sprite
description: Use when the user asks to query or export SellerSprite/卖家精灵 data through MCP tools, including 竞品查询, 选竞品, 选产品, 选市场, 查流量来源, 关键词挖掘, 关键词反查, ASIN reverse lookup, keyword mining, product research, market research, traffic source, competitor lookup, XLS/XLSX export, or JSON export.
---

# ops-seller-sprite

Use this skill to turn natural-language SellerSprite requests into MCP tool calls. CLI commands are local debug only and must not be presented as the user-facing path.

## Default Path

Use MCP tools:

1. Call `seller_sprite_scenarios` if the available scenarios or required params are unclear.
2. Map the user intent to a `scenario`.
3. Collect missing required params only.
4. Call `seller_sprite_run`.
5. If the user asks for the generated file or link, call `seller_sprite_export` with the returned `job_id`.
6. If MCP tools are unavailable, report that SellerSprite MCP is unavailable instead of falling back to CLI for the user.

MCP default export is `xls`, which the backend writes as an XLSX file. If the user explicitly asks for JSON, pass `export_format: "json"`.

## Missing Params Policy

- Ask only for missing required params, including one-of required groups.
- Do not ask for optional params. Omit them and let backend defaults apply unless the user explicitly provides values.
- If a scenario has no required params, run it with defaults after mapping the intent.
- Always include known user-provided conditions in `params`; do not invent category node IDs or hidden enum values.
- If category text maps to multiple possible nodes or no local node ID is available, ask the user to choose or run without the category filter.

## Intent Map

| User intent | scenario |
| --- | --- |
| 查竞品, 查产品, 选竞品, 竞品查询, competitor lookup | `competitor-lookup` |
| 选产品, 产品筛选, product research | `product-research` |
| 关键词挖掘, 挖词, keyword mining | `keyword-miner` |
| 关键词反查, ASIN 反查, reverse ASIN | `keyword-reverse` |
| 查流量来源, 流量来源, traffic source | `traffic-source` |
| 选市场, market research | `market-research` |

## Required Params

| scenario | Required | Common optional params |
| --- | --- | --- |
| `competitor-lookup` | one of `keyword`, `brand`, `sellerName`, `asins`, product link | `node` |
| `product-research` | none | `recommendationMode`, `node`/`category`, `minPrice`, `maxPrice`, `minSales`, `maxSales`, `minReviews`, `maxReviews`, `minReviewRating`, `maxReviewRating` |
| `keyword-miner` | `keyword` | `filterRootWord`, `amazonChoice`, `includeHighFrequency` |
| `keyword-reverse` | `asin` | `amazonChoice`/`ac`, `includeHighFrequency`, `badges` |
| `traffic-source` | `keywordOrAsin` | `keyword`, `asin`, `asins`, `order`, `desc` |
| `market-research` | none | `node`/`category`, `departmentKeyword`, `newReleaseNum`/`newReleaseMonths`, `topn` |

Always pass:

- `site`: marketplace code such as `US`, `JP`, `DE`, `UK`, `FR`, `IT`, `ES`, `CA`, `IN`, `MX`.
- `period`: `30d`, `nearly`, or a month such as `2026-03`.
- `page_size`: default `100` unless the user requests otherwise.

For `competitor-lookup`, product links are accepted as user input, but tool params should pass ASINs: extract the ASIN from Amazon product URLs and set `params.asins`.

For `product-research`, 推荐模式传 `params.recommendationMode`，可用值：

`低价长尾选品`, `研发新品榜`, `潜力单变体`, `销量飙升`, `潜力市场`, `未被满足的市场`, `不压库存的市场`, `投机市场`, `高需求低要求市场`, `全品类铺货`, `精品铺货`, `低价商品`, `新手推荐`.

推荐模式会展开为一组筛选条件；用户同时提供同名筛选条件时，以用户显式条件为准。

`product-research` accepts official SellerSprite API aliases in `params`; they are converted internally:

| Official alias | Internal field |
| --- | --- |
| `minUnits` / `maxUnits` | `minSales` / `maxSales` |
| `minRatings` / `maxRatings` | `minReviews` / `maxReviews` |
| `minStar` / `maxStar` | `minReviewRating` / `maxReviewRating` |
| `availableMonth` | `putawayMonth` |
| `fulfillment` | `sellerTypes` |
| `badgeNR=true` | `productTags=["NewRelease"]` |
| `variation` | `maxVariations` |
| `minBsr` / `maxBsr` | `minRanking` / `maxRanking` |

If both alias and internal field are provided, the internal field wins.

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
  },
  "export_format": "json"
}
```

Default XLSX export:

```json
{
  "scenario": "product-research",
  "site": "US",
  "period": "30d",
  "params": {}
}
```

Product research with recommendation mode:

```json
{
  "scenario": "product-research",
  "site": "US",
  "period": "30d",
  "params": {
    "recommendationMode": "精品铺货"
  }
}
```

Product research with official aliases:

```json
{
  "scenario": "product-research",
  "site": "US",
  "period": "30d",
  "params": {
    "minUnits": 300,
    "maxRatings": 50,
    "availableMonth": 6,
    "fulfillment": ["FBA"],
    "badgeNR": true
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
  },
  "export_format": "json"
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

## Local Debug Only

CLI commands are only for local development and debugging. Do not expose CLI as an available user workflow.

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
