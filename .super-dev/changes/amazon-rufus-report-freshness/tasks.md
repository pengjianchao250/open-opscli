# Tasks: Amazon Rufus Report Freshness Guard

## 1. Tests

- [x] Add a failing test that asserts template and installed `SKILL.md` contain current `report_path` freshness wording.
- [x] Add a failing test that asserts template and installed `rufus-mcp-workflow.md` forbid returning historical ASIN Markdown reports.
- [x] Add a failing test that asserts README includes the report freshness constraint.

## 2. Docs

- [x] Update template `SKILL.md` final output step.
- [x] Update installed `.agents` `SKILL.md` final output step.
- [x] Add report freshness section to template `references/rufus-mcp-workflow.md`.
- [x] Add the same section to installed `.agents` workflow reference.
- [x] Update template and installed README common path rules.

## 3. Verification

- [x] Run targeted Skill tests.
- [x] Run relevant Rufus MCP/Skill regression tests if target tests pass.
- [x] Review diff for accidental sensitive-field exposure.
