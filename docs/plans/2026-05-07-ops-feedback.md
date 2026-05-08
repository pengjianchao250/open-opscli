# Ops Feedback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a first-phase feedback submission flow for CLI and MCP, backed by a `polaris_ops_metrics` table and an `ops-feedback` Skill.

**Architecture:** The server owns persistence and user identity. `opscli` exposes a shared `FeedbackManager` and `FeedbackClient`, then wires them into both Typer CLI commands and FastMCP tools. The Skill documents when to use CLI or MCP and requires structured execution summaries for failed tool calls.

**Tech Stack:** Laravel package migrations/controllers/services/models, Eloquent on `ops_metrics`, Typer, httpx, FastMCP, JSON Skill templates.

---

### Task 1: Server Persistence and API

**Files:**
- Create: `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/database/migrations/2026_05_07_000002_create_dm_user_feedbacks_table.php`
- Create: `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Models/UserFeedback.php`
- Create: `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Services/UserFeedbackService.php`
- Create: `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Http/Controllers/UserFeedbackApiController.php`
- Modify: `/Applications/MxSrvs/www/auto-scheduler/vendor/aukey/data-metrics/src/Http/routes.php`

**Steps:**
1. Create `dm_user_feedbacks` migration on `ops_metrics`.
2. Add Eloquent model with JSON casts.
3. Add service methods `submitForUser()` and `findByUuidForUser()`.
4. Add authenticated submit/detail controller actions.
5. Register `POST /v1/data-metrics/feedback` and `GET /v1/data-metrics/feedback/{feedback_uuid}`.

### Task 2: opscli CLI and Transport

**Files:**
- Create: `/Users/mask/python3/open-opscli/opscli/feedback/...`
- Modify: `/Users/mask/python3/open-opscli/opscli/cli.py`

**Steps:**
1. Add feedback domain exceptions and manager.
2. Add remote client methods for submit/detail.
3. Add `opscli feedback submit`, `opscli feedback detail`, and `opscli feedback schema`.
4. Support JSON file and inline JSON options, including `execution_summary`.

### Task 3: MCP Tooling

**Files:**
- Create: `/Users/mask/python3/open-opscli/opscli/mcp/tools/feedback.py`
- Modify: `/Users/mask/python3/open-opscli/opscli/mcp/server.py`

**Steps:**
1. Add `feedback_submit` and `feedback_detail`.
2. Reuse existing auth helper behavior.
3. Register the tool module.

### Task 4: Skill Template

**Files:**
- Create: `/Users/mask/python3/open-opscli/opscli/skills/templates/ops-feedback/...`

**Steps:**
1. Add Skill entry with CLI/MCP selection rules.
2. Add CLI and MCP references.
3. Document required failed-call summary fields: tool, call params, error, reason, fix suggestion.

### Task 5: Validation

**Steps:**
1. Run Python import/compile checks for new opscli modules.
2. Run focused pytest if feasible.
3. Run PHP syntax checks for new server files.
