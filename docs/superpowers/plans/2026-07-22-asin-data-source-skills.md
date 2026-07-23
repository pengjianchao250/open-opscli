# ASIN Data Source Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy monolithic ASIN collection guidance with one compatibility router and three CLI-only source skills for basic, BI and category Top data.

**Architecture:** `ops-asin-data-collector` remains the discovery entry and delegates requests by intent. Each child skill owns one current `opscli asin-data` command and its response-validation rules; no child skill contains service code or calls another child command automatically.

**Tech Stack:** Markdown Agent Skills, JSON version metadata, Python 3.10+, pytest, opscli skill packaging manifest.

## Global Constraints

- Use CLI only; no MCP tools, MCP setup or MCP examples.
- Use `opscli asin-data basic`, `opscli asin-data bi` and `opscli asin-data category-top` as the only query commands.
- Default output is JSON; Excel, OSS, `live-data`, `fetch-file`, SellerSprite and Rufus are out of scope.
- `ops-asin-data-collector` version becomes `0.2.0`; each new child skill starts at `0.1.0`.
- All four skills must be included in source, wheel, binary and binary-full artifacts.
- Every failed `opscli` invocation must immediately follow `ops-feedback`.

---

### Task 1: Router Skill Contract

**Files:**
- Create: `tests/skills/test_ops_asin_data_source_skills.py`
- Modify: `opscli/skills/templates/ops-asin-data-collector/SKILL.md`
- Modify: `opscli/skills/templates/ops-asin-data-collector/data/VERSION.json`

**Interfaces:**
- Consumes: Existing template discovery by directory name.
- Produces: Router targets `ops-asin-data-basic`, `ops-asin-data-bi`, and `ops-asin-data-category-top`.

- [ ] **Step 1: Write the failing router tests**

Create a helper that reads UTF-8 skill files and add assertions:

```python
from pathlib import Path
import json


ROOT = Path("opscli/skills/templates")
ROUTER = ROOT / "ops-asin-data-collector"


def read_skill(name: str) -> str:
    return (ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def read_version(name: str) -> dict:
    return json.loads((ROOT / name / "data" / "VERSION.json").read_text(encoding="utf-8"))


def test_router_delegates_to_three_source_skills():
    text = read_skill("ops-asin-data-collector")
    assert "ops-asin-data-basic" in text
    assert "ops-asin-data-bi" in text
    assert "ops-asin-data-category-top" in text
    assert "live-data" not in text
    assert "fetch-file" not in text
    assert "asin_data_" not in text


def test_router_version_is_0_2_0():
    assert read_version("ops-asin-data-collector")["version"] == "0.2.0"
```

- [ ] **Step 2: Run the router tests and verify RED**

Run:

```powershell
$env:PYTHONPATH=(Get-Location).Path
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/skills/test_ops_asin_data_source_skills.py -q
```

Expected: FAIL because the router still contains legacy commands and version `0.1.6`.

- [ ] **Step 3: Replace the router with minimal routing guidance**

Write frontmatter with name `ops-asin-data-collector`, a `Use when...` description covering ASIN data source selection, and version `0.2.0`. The body must contain this routing table:

```markdown
| Intent | Delegate to |
| --- | --- |
| Listing, crawler, title, bullets, A+, QA, reviews | `ops-asin-data-basic` |
| Sales, traffic, conversion, ads, SQP, deals, inventory | `ops-asin-data-bi` |
| Category Top ASIN or category ranking | `ops-asin-data-category-top` |
```

Add shared rules for auth status, JSON validation, credential redaction and immediate `ops-feedback` on command failure. Replace `data/VERSION.json` with:

```json
{
  "name": "ops-asin-data-collector",
  "version": "0.2.0",
  "data_state": "ready"
}
```

- [ ] **Step 4: Run router tests and verify GREEN**

Run the Task 1 pytest command. Expected: router tests PASS while child-folder tests are not yet present.

- [ ] **Step 5: Commit the router**

```powershell
git add tests/skills/test_ops_asin_data_source_skills.py opscli/skills/templates/ops-asin-data-collector
git commit -m "refactor(skill): route asin data requests by source"
```

### Task 2: Basic Data Source Skill

**Files:**
- Modify: `tests/skills/test_ops_asin_data_source_skills.py`
- Create: `opscli/skills/templates/ops-asin-data-basic/SKILL.md`
- Create: `opscli/skills/templates/ops-asin-data-basic/data/VERSION.json`

**Interfaces:**
- Consumes: Router delegation name `ops-asin-data-basic`.
- Produces: Guidance for `opscli asin-data basic` and listing/crawler source precedence.

- [ ] **Step 1: Add the failing basic skill test**

```python
def test_basic_skill_uses_only_basic_command_and_defines_source_precedence():
    text = read_skill("ops-asin-data-basic")
    assert "opscli asin-data basic" in text
    assert "--source listing" in text
    assert "--source crawler" in text
    assert "listing" in text and "crawler" in text
    assert "A+" in text and "QA" in text and "reviews" in text
    assert "live-data" not in text
    assert "fetch-file" not in text
    assert "asin_data_" not in text
    assert read_version("ops-asin-data-basic")["version"] == "0.1.0"
```

- [ ] **Step 2: Run the basic test and verify RED**

Run the focused test. Expected: FAIL with `FileNotFoundError` for `ops-asin-data-basic/SKILL.md`.

- [ ] **Step 3: Create the basic source skill**

Create a concise `SKILL.md` with:

- `Use when...` frontmatter for title, bullets, listing, crawler, A+, QA and review requests.
- Complete-data command using repeated `--asin`, `--site`, and optional `--pretty`.
- Listing-only and crawler-only examples using repeated `--source` flags.
- Mapping: listing owns internal listing facts; crawler owns Amazon supplemental A+/QA/review data.
- Conflict rule: listing wins for overlapping listing facts.
- Validation order: top-level `success`, `data.status`, each source `status`, `row_count`, then `rows`.
- Empty-result and `ops-feedback` handling.

Create version metadata:

```json
{"name":"ops-asin-data-basic","version":"0.1.0","data_state":"ready"}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: router and basic tests PASS.

- [ ] **Step 5: Commit the basic skill**

```powershell
git add tests/skills/test_ops_asin_data_source_skills.py opscli/skills/templates/ops-asin-data-basic
git commit -m "feat(skill): add asin basic data source skill"
```

### Task 3: BI Data Source Skill

**Files:**
- Modify: `tests/skills/test_ops_asin_data_source_skills.py`
- Create: `opscli/skills/templates/ops-asin-data-bi/SKILL.md`
- Create: `opscli/skills/templates/ops-asin-data-bi/data/VERSION.json`

**Interfaces:**
- Consumes: Router delegation name `ops-asin-data-bi`.
- Produces: Domain selection and date handling for `opscli asin-data bi`.

- [ ] **Step 1: Add the failing BI skill test**

```python
def test_bi_skill_covers_domains_dates_and_empty_results():
    text = read_skill("ops-asin-data-bi")
    assert "opscli asin-data bi" in text
    assert "--date-from" in text and "--date-to" in text
    for domain in ("sales_traffic", "sp_search_term", "sqp", "deals", "turnover_inventory"):
        assert f"`{domain}`" in text
    assert "row_count" in text
    assert "0" in text and "success" in text
    assert "live-data" not in text
    assert "asin_data_" not in text
    assert read_version("ops-asin-data-bi")["version"] == "0.1.0"
```

- [ ] **Step 2: Run the BI test and verify RED**

Expected: FAIL with `FileNotFoundError` for `ops-asin-data-bi/SKILL.md`.

- [ ] **Step 3: Create the BI source skill**

Create a concise `SKILL.md` containing the exact command form, repeated-ASIN and repeated-domain examples, all five domain mappings, explicit date forwarding, source status validation, zero-row semantics and immediate feedback handling. State that agents select only requested domains and never substitute one domain for another.

Create version metadata:

```json
{"name":"ops-asin-data-bi","version":"0.1.0","data_state":"ready"}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: router, basic and BI tests PASS.

- [ ] **Step 5: Commit the BI skill**

```powershell
git add tests/skills/test_ops_asin_data_source_skills.py opscli/skills/templates/ops-asin-data-bi
git commit -m "feat(skill): add asin bi data source skill"
```

### Task 4: Category Top Data Source Skill

**Files:**
- Modify: `tests/skills/test_ops_asin_data_source_skills.py`
- Create: `opscli/skills/templates/ops-asin-data-category-top/SKILL.md`
- Create: `opscli/skills/templates/ops-asin-data-category-top/data/VERSION.json`

**Interfaces:**
- Consumes: Router delegation name `ops-asin-data-category-top`.
- Produces: Exact category Top query guidance and `data.category_top` response contract.

- [ ] **Step 1: Add the failing category Top test**

```python
def test_category_top_skill_covers_all_query_parameters_and_response_path():
    text = read_skill("ops-asin-data-category-top")
    assert "opscli asin-data category-top" in text
    for flag in ("--category", "--site", "--date-from", "--date-to", "--limit"):
        assert flag in text
    assert "data.category_top" in text
    assert "row_count" in text
    assert "1-100" in text
    assert "live-data" not in text
    assert "asin_data_" not in text
    assert read_version("ops-asin-data-category-top")["version"] == "0.1.0"
```

- [ ] **Step 2: Run the category Top test and verify RED**

Expected: FAIL with `FileNotFoundError` for `ops-asin-data-category-top/SKILL.md`.

- [ ] **Step 3: Create the category Top source skill**

Create a concise `SKILL.md` with exact category-name guidance, defaults `site=US` and `limit=10`, optional date flags, allowed limit `1-100`, response path `data.category_top`, zero-row semantics and a prohibition on automatically chaining basic or BI calls.

Create version metadata:

```json
{"name":"ops-asin-data-category-top","version":"0.1.0","data_state":"ready"}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: all source-skill contract tests PASS.

- [ ] **Step 5: Commit the category Top skill**

```powershell
git add tests/skills/test_ops_asin_data_source_skills.py opscli/skills/templates/ops-asin-data-category-top
git commit -m "feat(skill): add asin category top source skill"
```

### Task 5: Production Packaging and Regression Gate

**Files:**
- Modify: `tests/skills/test_ops_asin_data_source_skills.py`
- Modify: `opscli/skills/templates/manifest.json`

**Interfaces:**
- Consumes: Four complete skill template directories.
- Produces: Installation through all supported release artifact profiles.

- [ ] **Step 1: Add the failing manifest test**

```python
def test_all_asin_data_skills_are_in_every_release_artifact():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name in (
        "ops-asin-data-collector",
        "ops-asin-data-basic",
        "ops-asin-data-bi",
        "ops-asin-data-category-top",
    ):
        config = manifest["skills"][name]
        assert config["source"] is True
        assert config["wheel"] is True
        assert config["binary"] is True
        assert config["binary_full"] is True
        assert config["tier"] == "internal"
```

- [ ] **Step 2: Run the manifest test and verify RED**

Expected: FAIL because the router is excluded and child entries are absent.

- [ ] **Step 3: Update the release manifest**

Set all four skills to `source`, `wheel`, `binary`, and `binary_full` true with tier `internal`. Use reasons that identify the router or source-specific query role.

- [ ] **Step 4: Run focused and packaging tests**

```powershell
$env:PYTHONPATH=(Get-Location).Path
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/skills/test_ops_asin_data_source_skills.py tests/skills/test_packaging.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Run ASIN and skill regressions**

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests/asin_data tests/mcp/test_asin_data_tools.py tests/mcp/test_asin_data_limit.py tests/skills/test_ops_asin_data_source_skills.py tests/skills/test_packaging.py -q
```

Expected: all tests PASS with no warnings or collection errors.

- [ ] **Step 6: Validate template manifest and diff**

```powershell
D:\workspace\open-opscli\.venv\Scripts\python.exe -c "from opscli.skills.packaging import validate_release_manifest; problems=validate_release_manifest(); print(problems); raise SystemExit(bool(problems))"
git diff --check
git status --short
```

Expected: `[]`, no whitespace errors, and only planned files modified.

- [ ] **Step 7: Commit packaging and verification changes**

```powershell
git add tests/skills/test_ops_asin_data_source_skills.py opscli/skills/templates/manifest.json
git commit -m "feat(skills): package asin data source skills"
```

- [ ] **Step 8: Push the feature branch**

```powershell
git push origin codex/asin-data-production
```
