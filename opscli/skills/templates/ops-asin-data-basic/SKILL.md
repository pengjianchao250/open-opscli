---
name: ops-asin-data-basic
description: Use when users need Amazon ASIN listing or crawler basic data, including title, bullets, description, brand, price, images, A+ content, QA, reviews, or product highlights through opscli.
version: 0.1.0
---

# ASIN Basic Data

Use `opscli asin-data basic` for listing facts and Amazon-page crawler supplements. This skill is read-only.

## Source Selection

| Need | Source |
| --- | --- |
| Title, bullets, description, brand, price, variation attributes, product highlights | `listing` |
| A+ images, A+ description, QA, reviews, and Amazon-page supplements | `crawler` |
| Complete basic data | Both sources, which is the command default |

When both sources contain the same listing fact, use the `listing` value. Keep crawler-only fields as supplements and do not overwrite them with empty listing values.

## Commands

Complete basic data:

```bash
opscli asin-data basic --asin B0DPZWQ66D --site US
```

Listing only:

```bash
opscli asin-data basic --asin B0DPZWQ66D --site US --source listing
```

Crawler only:

```bash
opscli asin-data basic --asin B0DPZWQ66D --site US --source crawler
```

Multiple ASINs:

```bash
opscli asin-data basic \
  --asin B0DPZWQ66D \
  --asin B086M58PQ3 \
  --site US
```

Use `--asins '["B0DPZWQ66D","B086M58PQ3"]'` when the caller already has a JSON array. Add `--pretty` only for human-readable formatting.

## Workflow

1. Normalize ASINs to uppercase and choose the requested site; default to `US` only when the user omitted it.
2. Select `listing`, `crawler`, or both from the requested fields.
3. Run `opscli auth token status` before the first real request if authentication has not already been checked in this task.
4. Execute one batch command instead of polling individual ASINs when the request contains multiple ASINs.
5. Validate the response before using any fields.

## Response Validation

Read the JSON in this order:

1. Top-level `success` must be `true`.
2. `data.status` must be `success` or an explicitly accepted partial status.
3. Inspect `data.sources.listing_basic` and `data.sources.crawler_details` only when requested.
4. For each source, check `status`, then `row_count`, then `rows`.
5. A successful source with `row_count: 0` means the ASIN has no matching data or the current user cannot view it. Do not fabricate fallback values.

The normalized listing row must use one lowercase `asin` field. Do not reintroduce a duplicate uppercase ASIN field.

## Failure Handling

If the command exits non-zero or returns `success: false`, immediately follow `ops-feedback` with the command, ASINs, site, selected sources, original error code, reason, and repair suggestion. Return the resulting `feedback_uuid` without exposing credentials.

## Boundaries

- Do not use BI data as a substitute for missing listing or crawler data.
- Do not edit listing content or remote business data.
- Do not expose tokens, cookies, passwords, authorization headers, or session identifiers.
