---
name: ops-asin-data-category-top
description: Use when users need internal category Top ASIN rankings, Top N products, category sales leaders, or dated Amazon category performance through opscli.
---

# ASIN Category Top Data

Use `opscli asin-data category-top` to query ranked ASINs for one exact platform category. This skill returns category ranking data only.

## Required Input

- `--category`: exact platform category name, such as `Bed Frames`.
- Do not guess a category node, translate a category name silently, or broaden a category after a zero-row result.
- If the user provides a category path, use its final non-empty category name only when that leaf was explicitly supplied. For example, `Home & Kitchen,Furniture,Bed Frames` resolves to `Bed Frames`.

## Commands

Current-month Top 10 for the default US site:

```bash
opscli asin-data category-top --category "Bed Frames" --site US --limit 10
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
| `--category` | Required exact platform category name |
| `--site` | User value, otherwise `US` |
| `--date-from` | User value, otherwise first day of the current month |
| `--date-to` | User value, otherwise today |
| `--limit` | Integer from 1-100, otherwise 10 |

`date_from` must not be later than `date_to`.

## Workflow

1. Confirm the exact category name and site. Ask for the category only when no explicit leaf category is available.
2. Preserve the user's date range and limit; otherwise disclose resolved defaults.
3. Run `opscli auth token status` before the first real request if authentication has not already been verified in this task.
4. Execute the category query once.
5. Validate the response before presenting rankings.

## Response Validation

Read the JSON in this order:

1. Top-level `success` must be `true`.
2. Validate `data.category`, `data.site`, `data.date_from`, `data.date_to`, and `data.limit`.
3. Compare `data.row_count` with the number of records in `data.category_top`.
4. Preserve rank, ASIN, category, channel, sales, traffic, conversion, image, and product-link values from each returned record.
5. `row_count: 0` with a successful response means no matching category data for the filters. Do not invent rankings or retry with another category.

## Failure Handling

If the command exits non-zero or returns `success: false`, immediately follow `ops-feedback`. Include category, site, date range, limit, original error code, reason, and repair suggestion. Return the resulting `feedback_uuid` without credentials.

## Boundaries

- Do not automatically query basic listing, crawler, or BI data for returned ASINs.
- Do not generate Excel or upload files.
- Do not modify any remote business data.
- Do not expose tokens, cookies, passwords, authorization headers, or session identifiers.
