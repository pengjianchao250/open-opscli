---
name: ops-asin-data-bi
description: Use when users need ASIN sales, traffic, conversion, advertising search terms, SQP, deals, inventory, or turnover data from BI through opscli.
---

# ASIN BI Data

Use `opscli asin-data bi` for time-bounded ASIN metrics. Query only the domains required by the request.

## Domains

| Domain | Data |
| --- | --- |
| `sales_traffic` | Sales, revenue, orders, sessions, traffic, and conversion |
| `sp_search_term` | Sponsored Products customer search terms |
| `sqp` | Brand Analytics Search Query Performance |
| `deals` | Deals, promotions, and activity performance |
| `turnover_inventory` | Inventory snapshots and turnover metrics |

Never substitute another domain when the requested domain returns no rows.

## Commands

One ASIN and one domain:

```bash
opscli asin-data bi \
  --asin B0FWR7KT5R \
  --site US \
  --date-from 2026-06-01 \
  --date-to 2026-06-16 \
  --domain sales_traffic
```

One ASIN and multiple domains:

```bash
opscli asin-data bi \
  --asin B0FWR7KT5R \
  --site US \
  --date-from 2026-06-01 \
  --date-to 2026-06-16 \
  --domain sales_traffic \
  --domain sp_search_term \
  --domain turnover_inventory
```

Multiple ASINs can use repeated `--asin` flags or `--asins '["B0FWR7KT5R","B0DPZWQ66D"]'`. Add `--pretty` only for human-readable formatting.

## Date Rules

- Pass an explicitly requested range through `--date-from` and `--date-to` in `YYYY-MM-DD` format.
- When the user gives no range, the CLI defaults to the latest 30 calendar days including today. Disclose that resolved range with the result.
- `date_from` must not be later than `date_to`.
- The CLI maps these values to each upstream endpoint's expected date parameter names.

## Workflow

1. Normalize ASINs and site; default site to `US` only when omitted.
2. Map the requested metrics to the smallest domain set from the table above.
3. Run `opscli auth token status` before the first real request if authentication has not already been verified in this task.
4. Execute one command with repeated ASIN and domain flags rather than polling individual combinations.
5. Validate every requested domain independently.

## Response Validation

Read the JSON in this order:

1. Top-level `success` must be `true`.
2. Inspect `data.status`, `data.date_from`, `data.date_to`, and `data.domains`.
3. For each requested key in `data.sources`, check `status`, `row_count`, and `rows`.
4. `status: success` with `row_count: 0` is a valid empty result, not an interface failure.
5. A failed or partial source must remain visibly associated with its domain; do not merge it into successful domains.

For `sp_search_term`, avoid single-ASIN conclusions when diagnostics indicate the upstream ASIN filter could not be verified.

## Failure Handling

If the command exits non-zero or returns `success: false`, immediately follow `ops-feedback`. Include ASINs, site, date range, domains, original error code, reason, and repair suggestion. Return the resulting `feedback_uuid` without credentials.

## Boundaries

- Do not use listing or crawler fields to replace missing BI metrics.
- Do not modify ads, deals, inventory, pricing, or other remote business data.
- Do not expose tokens, cookies, passwords, authorization headers, or session identifiers.
