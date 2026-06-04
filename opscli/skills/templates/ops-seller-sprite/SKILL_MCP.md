---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 usage guide for querying scenarios and exporting JSON or XLSX files through seller_sprite_* MCP tools.
---

# ops-seller-sprite MCP

Use these MCP tools:

- `seller_sprite_scenarios`: list available scenarios.
- `seller_sprite_run`: run a scenario and create an export file.
- `seller_sprite_job_status`: read a saved task result by `job_id`.
- `seller_sprite_export`: read export path, `file://` URL, filename, format, and MIME type.

## Workflow

1. Call `seller_sprite_scenarios` when scenario names or required params are uncertain.
2. If the user intent cannot be mapped to exactly one scenario, ask the user to confirm the scenario before calling `seller_sprite_run`.
3. If required params are missing or ambiguous, ask the user to provide only those params before calling `seller_sprite_run`.
4. Call `seller_sprite_run` with `scenario`, `site`, `period`, `params`, and optionally `export_format`.
5. Use the returned `data.job_id` for follow-up status/export calls.
6. Call `seller_sprite_export` when the user needs the file link.
7. If MCP tools are unavailable, report that SellerSprite MCP is unavailable.

## Authentication

SellerSprite login is cached by the backend. Do not trigger repeated login manually; normal runs reuse cached cookies and only re-login when the session expires.

SellerSprite integration accounts are cached in the backend process for 10 minutes by default. Session expiration should only trigger SellerSprite re-login with the cached account; refresh integration accounts only when SellerSprite login itself fails.

## Export Format

- MCP default: `xls`, which the backend writes as an XLSX file.
- Use `export_format: "json"` only when the user explicitly asks for JSON.
- `xlsx` is accepted by the backend; `xls` and `xlsx` both produce XLSX files.

## Missing Params Policy

- Do not call `seller_sprite_run` when the scenario is unclear or required params are missing.
- Ask a concise clarification question when the user request is too broad, such as `跑卖家精灵`, `查一下`, `导出数据`, or `看这个产品`, and no scenario can be determined confidently.
- If multiple scenarios may match the same wording, ask the user to choose. Common ambiguous cases:
  - `查关键词`: choose `keyword-miner`, `keyword-reverse`, or `traffic-source`.
  - `查产品`: choose `competitor-lookup` or `product-research`.
  - `看市场/类目`: choose `market-research` or `product-research`.
- Ask only for missing required params, including one-of required groups.
- Do not ask for optional params. Omit them and let backend defaults apply unless the user explicitly provides values.
- If a scenario has no required params, run it with defaults after mapping the intent.
- Always include known user-provided conditions in `params`; do not invent hidden enum values.
- Category text can be passed directly in `params.category` or `params.node`. The backend resolves it through SellerSprite's category API before querying.
- If SellerSprite returns multiple category matches, stop and ask the user to choose one of the returned full category paths or provide `nodeIdPath`.

Clarification examples:

- `你想做关键词挖掘、关键词反查，还是查流量来源？`
- `查竞品需要 keyword、brand、sellerName、asins 或 Amazon 产品链接中的一种，请补充。`
- `关键词反查需要 ASIN，请提供 ASIN 或 Amazon 产品链接。`
- `查流量来源需要关键词或 ASIN，请补充。`

## Scenario Mapping

| Natural language | scenario |
| --- | --- |
| 查竞品 / 查产品 / 选竞品 / competitor lookup | `competitor-lookup` |
| 选产品 / product research | `product-research` |
| 关键词挖掘 / keyword mining | `keyword-miner` |
| 关键词反查 / reverse ASIN | `keyword-reverse` |
| 查流量来源 / traffic source | `traffic-source` |
| 选市场 / market research | `market-research` |

## Required Params

| scenario | Required | Common optional params |
| --- | --- | --- |
| `competitor-lookup` | one of `keyword`, `brand`, `sellerName`, `asins`, product link | `node` / `category` |
| `product-research` | none | `recommendationMode`, `node`/`category`, `minPrice`, `maxPrice`, `minSales`, `maxSales`, `minReviews`, `maxReviews`, `minReviewRating`, `maxReviewRating` |
| `keyword-miner` | `keyword` | `filterRootWord`, `amazonChoice`, `includeHighFrequency` |
| `keyword-reverse` | `asin` | `badges` |
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

### Category Params

For `product-research`, `competitor-lookup`, and `market-research`, pass category filters through `params.node`, `params.category`, `params.nodeIdPath`, or `params.nodeIdPaths`.

- The backend calls SellerSprite's category API `/v2/competitor-lookup/nodes` with `marketId`, `table`, and `nodeLabelPath` to resolve category text.
- You may pass natural language category text, such as `bath`, `bed frames`, or a more complete path.
- You may also pass a SellerSprite node path directly, such as `1055398:1063236`; numeric paths are used as-is.
- If the category API returns exactly one match, the backend converts it to `nodeIdPath` before querying.
- If the category API returns multiple matches, the run fails with candidate `nodeIdPath` and full category paths. Ask the user to choose; do not retry by guessing.
- If no category is found, ask the user for a more complete category path or a known `nodeIdPath`.

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
| `keyword-reverse` | `page=1`, `order=12`, `desc=true` |
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

```json
{
  "scenario": "product-research",
  "site": "US",
  "period": "30d",
  "params": {
    "category": "bed frames",
    "minSales": 300,
    "maxReviews": 50
  }
}
```

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

## Result Handling

For `seller_sprite_run`, read:

- `data.summary`
- `data.job_id`
- `data.row_count`
- `data.export.filename`
- `data.export.path`
- `data.export.url`
- `data.export.format`

If `success=false`, report `error.message` and do not reuse stale files.

Keep the final answer short and user-facing. Do not print the full tool call JSON, raw params, or long local paths unless the user explicitly asks for debugging details.

If the tool returns `data.summary`, use that summary as the primary final answer. Do not rewrite it into raw JSON. Only add extra details when the user explicitly asks.

For successful runs, use this shape:

```md
已按 `site` 做好了 `scenario title`，并导出为 `format`。

结果：
- `job_id`: xxx
- `row_count`: 20
- 导出文件: [filename](url-or-path)
```

Rules:

- Put only important conditions in the first sentence, such as site, keyword, ASIN, period, or recommendation mode.
- Prefer filename or link for the export file; avoid showing full local paths as standalone code blocks.
- If row count is 0, say `row_count: 0` and include the parameters used only in a compact inline form.
- If row count is 0, ask the user to confirm whether key inputs are correct before retrying. Mention likely mismatches such as marketplace/site vs ASIN region, wrong ASIN, typo in keyword, overly narrow category/filter, or an unsupported month/period. Example: `没有查到数据。请确认站点和 ASIN 是否匹配，比如 US 站不能查询只在 FR 站有效的 ASIN；也可以补充正确站点或 ASIN 后我再查。`
- Do not expose SellerSprite account credentials.
