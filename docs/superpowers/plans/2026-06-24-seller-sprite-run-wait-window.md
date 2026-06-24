# Seller Sprite Run Wait Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让公开 `seller_sprite_run` 在任务进入 `running` 后最多同步等待 8 分钟，只有超时后才返回 `job_id` 供后续查询。

**Architecture:** 保留现有 SQLite 队列、调度器和 `job_status/export` 续查链路不变，只在 MCP 公共入口 `seller_sprite_run` 增加“入队后代等”逻辑。等待逻辑按 `queued` 无限等待、`running` 计时 8 分钟、`succeeded/failed` 立即返回的统一规则执行，并在超时回包里补充排队与运行时长。

**Tech Stack:** Python 3.10、Typer、FastMCP、pytest、SQLite

---

### Task 1: 用测试锁定新的 seller_sprite_run 等待语义

**Files:**
- Modify: `tests/mcp/test_seller_sprite_tools.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] **Step 1: 写 seller_sprite_run 成功直返的失败测试**

```python
def test_seller_sprite_run_waits_until_success(monkeypatch, tmp_path):
    ...
    result = _run(seller_sprite_tools.seller_sprite_run(...))
    assert result["success"] is True
    assert result["data"]["state"] == "succeeded"
```

- [ ] **Step 2: 运行单测确认当前实现失败**

Run: `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -k "waits_until_success" -v`
Expected: FAIL，当前实现仍直接返回 `queued`

- [ ] **Step 3: 写 running 超时后返回 job_id 与时长的失败测试**

```python
def test_seller_sprite_run_returns_job_id_after_running_timeout(monkeypatch, tmp_path):
    ...
    assert result["data"]["state"] == "running"
    assert result["data"]["job_id"] == "job-timeout-1"
    assert result["data"]["queue_duration"] is not None
    assert result["data"]["running_duration"] is not None
```

- [ ] **Step 4: 运行超时用例确认当前实现失败**

Run: `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -k "running_timeout" -v`
Expected: FAIL，当前实现没有代等与超时摘要

### Task 2: 在 seller_sprite_run 入口实现代等与超时摘要

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] **Step 1: 增加等待常量、时长计算与轮询辅助函数**

```python
SELLER_SPRITE_RUN_POLL_INTERVAL_SECONDS = 5.0
SELLER_SPRITE_RUN_RUNNING_TIMEOUT_SECONDS = 8 * 60

async def _wait_for_seller_sprite_run_result(...):
    ...
```

- [ ] **Step 2: 在 seller_sprite_run 入队成功后改为代等结果**

```python
queued_status = await scheduler.enqueue(request)
final_status = await _wait_for_seller_sprite_run_result(
    scheduler=scheduler,
    job_id=str(request.job_id),
    initial_status=queued_status,
)
return _ok(final_status)
```

- [ ] **Step 3: 运行 seller_sprite MCP 定向回归**

Run: `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -v`
Expected: PASS

### Task 3: 同步 Skill 文档与变更记录

**Files:**
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- Modify: `docs/change-log-pending.md`

- [ ] **Step 1: 更新卖家精灵 Skill 的运行与续查说明**

```md
- `seller_sprite_run` 会先等待任务完成；只有进入 `running` 后超过 8 分钟仍未完成时，才返回 `job_id` 供续查。
```

- [ ] **Step 2: 追加变更记录**

```md
## 2026-06-24 seller_sprite - run 入口增加 8 分钟运行态代等
...
```

- [ ] **Step 3: 运行本次改动的最终验证**

Run: `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli_split.py -v`
Expected: PASS
