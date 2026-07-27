---
name: ops-asin-data-category-top
description: Use when users need internal category Top ASIN rankings, Top N products, category sales leaders, or dated Amazon category performance through opscli.
---

# ASIN Category Top Data

Use `opscli asin-data category-top` for either ranked ASINs in one exact platform category or category traffic funnel summaries. This skill returns category data only.

## Data Type Selection

| Need | Parameter | Response path |
| --- | --- | --- |
| Ranked ASIN products for one category | `--data-type asin` (default) | `data.category_top` |
| Traffic Top10 funnel averages by category | `--data-type traffic` | `data.category_traffic` |

Traffic mode uses `/dataMetrics/v1/asin-report-files/all-category-traffic-top10`. Omit `--category` to query all categories, or pass an exact category to filter the result.

## Input Rules

- `--category`: required exact platform category name for `asin`; optional exact filter for `traffic`.
- Do not guess a category node, translate a category name silently, or broaden a category after a zero-row result.
- If the user provides a category path, use its final non-empty category name only when that leaf was explicitly supplied. For example, `Home & Kitchen,Furniture,Bed Frames` resolves to `Bed Frames`.

## Commands

Current-month Top 10 for the default US site:

```bash
opscli asin-data category-top --category "Bed Frames" --site US --limit 10
```

Traffic funnel summary for one category:

```bash
opscli asin-data category-top \
  --data-type traffic \
  --category "3D Wall Panels" \
  --date-from 2026-07-01 \
  --date-to 2026-07-27
```

Traffic funnel summaries for all categories:

```bash
opscli asin-data category-top \
  --data-type traffic \
  --date-from 2026-07-01 \
  --date-to 2026-07-27
```

Explicit date range and Top N:

```bash
opscli asin-data category-top \
  --category "Bed Frames" \
  --site US \
  --date-from 2026-07-01 \
  --date-to 2026-07-22 \
  --limit 20
```

Add `--pretty` only for human-readable JSON formatting.

## Parameter Rules

| Parameter | Rule |
| --- | --- |
| `--data-type` | `asin` by default; use `traffic` for traffic funnel summaries |
| `--category` | Required for `asin`; optional exact filter for `traffic` |
| `--site` | User value, otherwise `US` |
| `--date-from` | User value, otherwise first day of the current month |
| `--date-to` | User value, otherwise today |
| `--limit` | Integer from 1-100, otherwise 10 |

`date_from` must not be later than `date_to`.

## Workflow

1. Select `asin` or `traffic`. For `asin`, confirm the exact category and site; for `traffic`, preserve an explicit category or omit it to query all categories.
2. Preserve the user's date range and limit; otherwise disclose resolved defaults.
3. Run `opscli auth token status` before the first real request if authentication has not already been verified in this task.
4. Execute the category query once.
5. Validate the response before presenting rankings.

## Response Validation

Read the JSON in this order:

1. Top-level `success` must be `true`.
2. Validate `data.category`, `data.date_from`, and `data.date_to`; for `asin`, also validate `data.site` and `data.limit`.
3. Compare `data.row_count` with `data.category_top` for `asin`, or with `data.category_traffic` for `traffic`.
4. For `asin`, preserve rank, ASIN, category, channel, sales, traffic, conversion, image, and product-link values. For `traffic`, preserve product counts and all `funnel_average` metrics.
5. `row_count: 0` with a successful response means no matching category data for the filters. Do not invent rankings or retry with another category.

## Failure Handling

If the command exits non-zero or returns `success: false`, immediately follow `ops-feedback`. Include category, site, date range, limit, original error code, reason, and repair suggestion. Return the resulting `feedback_uuid` without credentials.

## Boundaries

- Do not automatically query basic listing, crawler, or BI data for returned ASINs.
- Do not generate Excel or upload files.
- Do not modify any remote business data.
- Do not expose tokens, cookies, passwords, authorization headers, or session identifiers.
