# Change: Amazon Rufus Report Freshness Guard

## Problem

`ops-amazon-rufus` can generate multiple Markdown reports for the same ASIN under `output/amazon-rufus/`. The current flow says to return `report_path`, but it does not explicitly forbid Agent-side fallback that scans `output/amazon-rufus/<ASIN>-*.md` and reads an older report.

This can cause a user to receive stale Rufus answers even after a fresh `amazon_rufus_get` call or after a login recovery retry.

## Goals

1. Treat the current tool response `data.report_path` as the only valid report path for the current Skill invocation.
2. Forbid reading arbitrary historical ASIN Markdown reports when the user asks for report contents.
3. Require login-recovery retry success to overwrite any previous report path state.
4. Document the CLI fallback rule: parse the path from the current command output first; only if absent, choose the latest file by timestamp and mtime.
5. Add tests that prevent the Skill template and installed Skill docs from losing this rule.

## Non-Goals

1. Do not delete historical reports.
2. Do not change `AnswerReportWriter` filename format.
3. Do not add a UI.
4. Do not add cookie, headers, storage_state, or CDP parameters to MCP.
5. Do not implement a report cleanup or archive policy.

## Proposed Scope

Update:

- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `.agents/skills/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`
- `.agents/skills/ops-amazon-rufus/README.md`
- `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
- `.agents/skills/ops-amazon-rufus/references/rufus-mcp-workflow.md`
- Relevant Skill documentation tests

## Acceptance Criteria

1. `SKILL.md` says the final response uses only the current tool-returned `report_path`.
2. `rufus-mcp-workflow.md` contains a dedicated report freshness rule.
3. README says historical ASIN Markdown reports must not be returned.
4. Tests fail before the docs are updated and pass after the update.
5. No sensitive Rufus request material is added to docs or tests.
