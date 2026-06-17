# Seller Sprite Async Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-stage async MCP task path for SellerSprite so long `seller_sprite_run` jobs can return `job_id` quickly and be tracked through `seller_sprite_job_status`.

**Architecture:** Keep the current single-account browser worker execution model. Add a lightweight task status layer under `opscli/seller_sprite/services/`, keep `SellerSpriteApiManager.start()` as an internal helper, and make `seller_sprite_run` the only public collection entry that automatically returns async task status when needed.

**Tech Stack:** Python 3.10+, FastMCP tool functions, asyncio background tasks, pytest.

---

### Task 1: Lock Async MCP Behavior

**Files:**
- Modify: `tests/mcp/test_seller_sprite_tools.py`

- [x] **Step 1: Write failing tests**

Add tests proving `seller_sprite_run` returns async task status for long-running scenarios without awaiting `run`, while internal controls remain hidden from the MCP schema.

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -q
```

Expected: failures because automatic async behavior and schema hiding do not exist yet.

### Task 2: Add Task Status Service

**Files:**
- Create: `opscli/seller_sprite/services/task_status.py`
- Modify: `tests/seller_sprite/test_api_manager.py`

- [x] **Step 1: Write failing tests**

Add tests for queued status creation, succeeded status after background run, and failed status after exception.

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_api_manager.py -q
```

Expected: failures because manager async start/status support does not exist yet.

### Task 3: Implement Manager Start

**Files:**
- Modify: `opscli/seller_sprite/services/api_manager.py`
- Create: `opscli/seller_sprite/services/task_status.py`

- [x] **Step 1: Implement minimal task status helpers**

Create status read/write helpers with Chinese docstrings and comments.

- [x] **Step 2: Implement `SellerSpriteApiManager.start()`**

Generate the same style of `job_id`, write `queued`, schedule a background coroutine, then return the status payload immediately.

- [x] **Step 3: Update `job_status()`**

Return completed `result.json` when present; otherwise return `status.json`.

### Task 4: Expose MCP Tools

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`

- [x] **Step 1: Add internal async start path**

Call `SellerSpriteApiManager.start()` from `seller_sprite_run` when the backend decides the task should be async, and return `_ok(status)`.

- [x] **Step 2: Keep internal controls out of the MCP schema**

Do not expose `seller_sprite_start`, `async_mode`, or collection `mode` to Agent-facing MCP callers.

- [x] **Step 3: Update Skill docs**

Document async workflow, automatic Agent polling, and `job_id` continuation behavior.

### Task 5: Verify and Record

**Files:**
- Modify: `docs/change-log-pending.md`

- [x] **Step 1: Append change log**

Record reason, files, verification, impact, and rollback.

- [x] **Step 2: Run targeted tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py tests\seller_sprite\test_api_manager.py -q
```

Expected: all targeted tests pass.
