---
name: ops-asin-data-collector
description: Use when an AI agent must choose the correct opscli ASIN data source for listing, crawler, BI, advertising, inventory, SQP, or category Top ASIN requests.
---

# ASIN Data Source Router

Route each request to the smallest source skill that can answer it. This skill selects a workflow; it does not query data itself.

## Routing

| Intent | Delegate to |
| --- | --- |
| Listing, crawler, title, bullets, description, price, images, A+, QA, reviews | `ops-asin-data-basic` |
| Sales, traffic, conversion, advertising search terms, SQP, deals, inventory | `ops-asin-data-bi` |
| Category Top ASIN, category ranking, Top N products | `ops-asin-data-category-top` |

If a request explicitly needs multiple source groups, invoke each relevant source skill and keep their results separated by source.

## Shared Rules

1. Use the CLI workflow documented by the selected source skill.
2. Before the first real request, run `opscli auth token status` unless authentication was already verified in the current task.
3. Keep JSON as the default output. Add `--pretty` only when a human needs formatted output.
4. Validate top-level success, source status, and row counts before using returned data.
5. Treat a successful zero-row response as no matching data, not as a service failure.
6. If any `opscli` command fails, immediately follow `ops-feedback`, return its `feedback_uuid`, and continue only when a safe fallback exists.
7. Never expose tokens, cookies, passwords, authorization headers, or session identifiers.

## Boundaries

- Do not substitute one source for another when the requested source returns no data.
- Do not automatically chain category ranking into basic or BI requests.
- Do not edit listings, ads, inventory, pricing, or other remote business data.
