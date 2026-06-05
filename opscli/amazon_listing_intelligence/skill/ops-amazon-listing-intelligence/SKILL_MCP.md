---
name: ops-amazon-listing-intelligence
mcp-version: v1.0.0
description: Amazon Listing Intelligence usage guide for planning Listing optimization data sources through amazon_listing_intelligence_* MCP tools.
---

# ops-amazon-listing-intelligence MCP

Use these MCP tools:

- `amazon_listing_intelligence_spec_must_read`: read this spec.
- `amazon_listing_intelligence_data_sources`: list data source TODO and onboarding items.
- `amazon_listing_intelligence_objectives`: list supported analysis objectives.
- `amazon_listing_intelligence_intake_plan`: generate a data-source intake plan for one Listing optimization request.
- `amazon_listing_intelligence_schema`: read request fields and source IDs.

## Workflow

1. Call `amazon_listing_intelligence_spec_must_read` before using the service.
2. Call `amazon_listing_intelligence_data_sources` when the user asks for data source TODO, account applications, or roadmap.
3. Call `amazon_listing_intelligence_intake_plan` when the user provides ASIN, keyword, marketplace, or an optimization objective.
4. If the plan includes SellerSprite, call `seller_sprite_scenarios` or `seller_sprite_run` next. Do not guess SellerSprite scenario params when missing.
5. If required inputs are missing, ask only for those missing inputs.

## Objectives

| objective | Use when |
| --- | --- |
| `listing_audit` | Analyze Listing wording, keyword coverage, Review/Q&A gaps |
| `keyword_opportunity` | Find keyword opportunities and trend signals |
| `buyer_insight` | Extract user pain points, buying motives, objections |
| `competitor_positioning` | Compare competitors, price bands, differentiation |
| `category_intelligence` | Evaluate category trends and new product opportunities |

## Data Source IDs

MVP:

- `seller_sprite`
- `amazon_listing`
- `amazon_search`
- `amazon_review`
- `amazon_qa`
- `google_trends`
- `reddit`

Enhanced:

- `amazon_pa_api`
- `tiktok_creative_center`
- `aliexpress`
- `ebay`
- `walmart`

Commercial:

- `keepa`
- `rainforest`
- `dataforseo`
- `oxylabs`
- `tiktok_shop`
- `temu`

## Call Examples

```json
{
  "phase": "mvp"
}
```

```json
{
  "asin": "B00MA2T9BC",
  "keyword": "bed frame",
  "marketplace": "US",
  "objective": "listing_audit",
  "available_sources": ["seller_sprite"]
}
```

```json
{
  "keyword": "solar outdoor lights",
  "marketplace": "US",
  "objective": "keyword_opportunity"
}
```

## Result Handling

For `amazon_listing_intelligence_intake_plan`, read:

- `data.required_sources`
- `data.missing_inputs`
- `data.next_actions`
- `data.boundaries`

If `missing_inputs` is not empty, ask the user to provide those fields before running downstream data tools.

If `next_actions` includes SellerSprite:

- Use `keyword-miner` for keyword opportunity.
- Use `keyword-reverse` when ASIN is available.
- Use `traffic-source` for traffic source checks.
- Use `competitor-lookup` or `product-research` for competitor pool or market checks.

Do not expose SellerSprite credentials. Do not output full raw JSON unless the user asks for debugging details.

## Boundaries

- This service plans and orchestrates data access; it does not directly scrape pages.
- Prefer existing MCP tools over adding new crawlers.
- Do not generate full ready-to-publish Listing copy.
- Do not claim Review, Q&A, Reddit, trend, BSR, or sales conclusions without source data.
