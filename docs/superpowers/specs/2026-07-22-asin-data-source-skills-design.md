# ASIN Data Source Skills Design

Date: 2026-07-22
Status: Confirmed for specification review
Base branch: `master`
Feature branch: `codex/asin-data-production`

## Goal

Split the current ASIN data collection guidance by data source while preserving one stable discovery entry point. The skills must guide AI agents to the current simplified CLI commands and must not duplicate service implementation.

## Skill Topology

### Router: `ops-asin-data-collector`

The existing skill remains the compatibility and discovery entry point. It classifies the request and delegates to exactly one source skill unless the user explicitly requests multiple source groups.

Routing rules:

| User intent | Target skill |
| --- | --- |
| Title, bullets, description, brand, price, images, A+, QA, reviews, listing or crawler details | `ops-asin-data-basic` |
| Sales, traffic, conversion, SP search terms, SQP, deals, inventory or turnover | `ops-asin-data-bi` |
| Category ranking, category Top ASIN, Top N products | `ops-asin-data-category-top` |

The router does not document deprecated `live-data` or historical `fetch-file` workflows. It does not expose MCP tools.

### Source Skill: `ops-asin-data-basic`

Command:

```text
opscli asin-data basic --asin <ASIN> --site <SITE> [--source listing] [--source crawler] [--pretty]
```

Responsibilities:

- Use `listing` for internal listing facts such as title, bullets, description, brand, price, variation attributes and product highlights.
- Use `crawler` for Amazon-page supplemental data such as A+ images, A+ descriptions, QA and reviews.
- Default to both sources when the user requests complete basic data.
- Prefer listing values when listing and crawler fields conflict.
- Support repeated `--asin` and `--asins` JSON input.
- Treat a successful source with zero rows as no data or no permission, not as fabricated content.

### Source Skill: `ops-asin-data-bi`

Command:

```text
opscli asin-data bi --asin <ASIN> --site <SITE> --date-from <YYYY-MM-DD> --date-to <YYYY-MM-DD> --domain <DOMAIN> [--domain <DOMAIN>] [--pretty]
```

Domain mapping:

| Domain | Data |
| --- | --- |
| `sales_traffic` | Sales, orders, sessions, traffic and conversion |
| `sp_search_term` | Sponsored Products search terms |
| `sqp` | Brand Analytics Search Query Performance |
| `deals` | Deal and promotion performance |
| `turnover_inventory` | Inventory and turnover snapshots |

Responsibilities:

- Require an explicit date range when the user specifies one; otherwise disclose the CLI default.
- Select only domains needed for the request instead of querying all domains by default.
- Support repeated `--asin`, `--asins` JSON and repeated `--domain`.
- Treat `status=success` with `row_count=0` as a valid empty result.
- Never replace an empty requested domain with data from another domain.

### Source Skill: `ops-asin-data-category-top`

Command:

```text
opscli asin-data category-top --category <CATEGORY> --site <SITE> [--date-from <YYYY-MM-DD>] [--date-to <YYYY-MM-DD>] [--limit <1-100>] [--pretty]
```

Responsibilities:

- Require the exact platform category name; do not guess a category path or node.
- Default site to `US` and limit to `10` only when the user does not provide them.
- Pass optional date filters directly to the command.
- Read records from `data.category_top` and validate `row_count`.
- Return only category Top data; do not automatically fetch basic or crawler details.

## Shared Execution Contract

All four skills follow these rules:

1. Use CLI only. Do not present MCP tools or MCP setup.
2. Run `opscli auth token status` before the first real request when authentication has not already been verified in the task.
3. Use JSON as the default output. Add `--pretty` only for human inspection.
4. Validate top-level `success`, source status and row counts before using data.
5. On any failed `opscli` invocation, immediately follow `ops-feedback` and return the feedback UUID.
6. Never expose tokens, cookies, session IDs or passwords.
7. Do not claim that a zero-row successful response is an interface failure.

## Packaging

Each skill contains:

```text
<skill-name>/
  SKILL.md
  data/VERSION.json
```

Initial versions:

- `ops-asin-data-collector`: bump from `0.1.6` to `0.2.0` because its command model changes to routing.
- New source skills: `0.1.0`.

All four entries are marked as internal skills included in source, wheel, binary and binary-full artifacts in `opscli/skills/templates/manifest.json`. This makes `opscli skills install/upgrade` deploy them consistently in production builds.

## Testing

Development follows test-first skill authoring:

1. Add contract tests that fail because the three source skill folders do not yet exist and the router still references legacy commands.
2. Verify each skill has valid frontmatter, a matching `VERSION.json`, CLI-only commands and source-specific trigger terms.
3. Verify router intents map to the expected source skill and do not contain `live-data`, `fetch-file` or MCP tool names.
4. Verify BI tests cover every supported domain and both date flags.
5. Verify category Top tests cover category, site, date and limit arguments plus `data.category_top`.
6. Verify manifest inclusion for all four release artifact profiles.
7. Run focused skill tests, packaging tests and the existing ASIN data test suite.

## Non-Goals

- No changes to ASIN service HTTP clients or response schemas.
- No new CLI commands or parameters.
- No MCP documentation or MCP tool changes.
- No Excel or OSS export workflow.
- No historical SellerSprite or Rufus file workflow.
- No automatic chaining from category Top into basic or BI queries.

