# 卖家精灵 MCP 调用记录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `seller_sprite_run` 增加基于现有 SQLite 库的 MCP 调用记录能力，持续更新同一条 `job_id` 记录直到任务完成或失败。

**Architecture:** 复用 `opscli/seller_sprite/services/task_queue_store.py` 作为同库仓储，在现有 `task_queue.sqlite3` 中新增独立表 `seller_sprite_mcp_runs`。`opscli/mcp/tools/seller_sprite.py` 负责在 MCP 入队前创建初始记录，`opscli/seller_sprite/services/task_scheduler.py` 负责在任务开始、成功、失败三个阶段更新同一条记录。

**Tech Stack:** Python 3.10、Typer/FastMCP、SQLite3、pytest

---

## 文件结构

- 修改: `opscli/seller_sprite/services/task_queue_store.py`
  - 新增 MCP 调用记录表初始化与 CRUD 方法
- 修改: `opscli/mcp/tools/seller_sprite.py`
  - 在 `seller_sprite_run` 中解析邮箱并创建初始调用记录
- 修改: `opscli/seller_sprite/services/task_scheduler.py`
  - 在调度执行阶段持续更新调用记录状态
- 修改: `tests/seller_sprite/test_task_queue_store.py`
  - 增加仓储层 RED/GREEN 测试
- 修改: `tests/mcp/test_seller_sprite_tools.py`
  - 增加 MCP 入口创建/失败回写测试
- 修改: `tests/seller_sprite/test_task_scheduler.py`
  - 增加调度阶段运行中/成功/失败更新测试
- 修改: `docs/change-log-pending.md`
  - 记录本次代码改动、验证结果与回滚方式

### Task 1: 仓储层新增 MCP 调用记录表

**Files:**
- Modify: `opscli/seller_sprite/services/task_queue_store.py`
- Test: `tests/seller_sprite/test_task_queue_store.py`

- [ ] **Step 1: 写仓储层失败测试，要求初始化后存在审计表且可创建初始记录**

```python
def test_store_creates_mcp_run_record(tmp_path: Path):
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": "B07YRMT36L"},
        job_id="job-mcp-1",
        export_format="json",
        mode="browser-route",
    )

    store.create_mcp_run(
        request=request,
        user_email="user@example.com",
    )

    row = store.get_mcp_run("job-mcp-1")
    assert row["job_id"] == "job-mcp-1"
    assert row["user_email"] == "user@example.com"
    assert row["scenario"] == "keyword-reverse"
    assert row["mode"] == "browser-route"
    assert row["result_state"] == "queued"
    assert row["result_row_count"] == 0
    assert row["result_export_format"] is None
```

- [ ] **Step 2: 运行单测，确认因为缺少方法/表结构而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py -k mcp_run -v`

Expected: FAIL，错误指向 `create_mcp_run` / `get_mcp_run` 不存在，或 SQLite 中缺少 `seller_sprite_mcp_runs`

- [ ] **Step 3: 写最小实现，补表结构和初始读写方法**

```python
def create_mcp_run(
    self,
    *,
    request: SellerSpriteScenarioRequest,
    user_email: str,
) -> None:
    with self._connect() as conn:
        conn.execute(
            """
            INSERT INTO seller_sprite_mcp_runs (
                job_id, user_email, scenario, mode, params_json,
                result_state, result_row_count, result_export_format,
                result_export_filename, result_export_job_id, error_json,
                created_at, started_at, finished_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'queued', 0, NULL, NULL, NULL, NULL, ?, NULL, NULL, ?)
            """,
            (
                request.job_id,
                user_email,
                request.scenario,
                request.mode or "browser-route",
                json.dumps(request.params, ensure_ascii=False),
                _now_iso(),
                _now_iso(),
            ),
        )

def get_mcp_run(self, job_id: str) -> dict[str, Any]:
    with self._connect() as conn:
        row = conn.execute(
            "SELECT * FROM seller_sprite_mcp_runs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"MCP 调用记录不存在：{job_id}")
    return dict(row)
```

- [ ] **Step 4: 运行单测，确认仓储初始写入通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py -k mcp_run -v`

Expected: PASS

- [ ] **Step 5: 提交该阶段改动**

```bash
git add tests/seller_sprite/test_task_queue_store.py opscli/seller_sprite/services/task_queue_store.py
git commit -m "feat: add seller sprite mcp run store"
```

### Task 2: 仓储层补运行中、成功、失败更新能力

**Files:**
- Modify: `opscli/seller_sprite/services/task_queue_store.py`
- Test: `tests/seller_sprite/test_task_queue_store.py`

- [ ] **Step 1: 写失败测试，覆盖 running / succeeded / failed 三种更新**

```python
def test_store_updates_mcp_run_states(tmp_path: Path):
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": "B07YRMT36L"},
        job_id="job-mcp-2",
        export_format="json",
        mode="browser-route",
    )
    store.create_mcp_run(request=request, user_email="user@example.com")

    store.mark_mcp_run_running("job-mcp-2")
    running = store.get_mcp_run("job-mcp-2")
    assert running["result_state"] == "running"
    assert running["started_at"] is not None

    store.finish_mcp_run_success(
        job_id="job-mcp-2",
        row_count=3,
        export_payload={"format": "json", "filename": "job-mcp-2.json"},
    )
    done = store.get_mcp_run("job-mcp-2")
    assert done["result_state"] == "succeeded"
    assert done["result_row_count"] == 3
    assert done["result_export_format"] == "json"
    assert done["result_export_filename"] == "job-mcp-2.json"
    assert done["result_export_job_id"] == "job-mcp-2"

def test_store_marks_mcp_run_failed(tmp_path: Path):
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
    request = SellerSpriteScenarioRequest(
        scenario="keyword-reverse",
        site="JP",
        period="nearly",
        params={"asin": "B07YRMT36L"},
        job_id="job-mcp-3",
        export_format="json",
        mode="browser-route",
    )
    store.create_mcp_run(request=request, user_email="user@example.com")

    store.finish_mcp_run_failed(
        job_id="job-mcp-3",
        error_payload={"code": "RuntimeError", "message": "boom"},
    )
    failed = store.get_mcp_run("job-mcp-3")
    assert failed["result_state"] == "failed"
    assert failed["finished_at"] is not None
    assert json.loads(failed["error_json"])["message"] == "boom"
```

- [ ] **Step 2: 运行单测，确认因为缺少更新方法而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py -k "updates_mcp_run_states or marks_mcp_run_failed" -v`

Expected: FAIL，错误指向 `mark_mcp_run_running`、`finish_mcp_run_success` 或 `finish_mcp_run_failed` 不存在

- [ ] **Step 3: 写最小实现，补三种状态更新方法**

```python
def mark_mcp_run_running(self, job_id: str) -> None:
    with self._connect() as conn:
        conn.execute(
            """
            UPDATE seller_sprite_mcp_runs
            SET result_state = 'running',
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE job_id = ?
            """,
            (_now_iso(), _now_iso(), job_id),
        )

def finish_mcp_run_success(
    self,
    *,
    job_id: str,
    row_count: int,
    export_payload: dict[str, Any] | None,
) -> None:
    export_format = export_payload.get("format") if export_payload else None
    export_filename = export_payload.get("filename") if export_payload else None
    with self._connect() as conn:
        conn.execute(
            """
            UPDATE seller_sprite_mcp_runs
            SET result_state = 'succeeded',
                result_row_count = ?,
                result_export_format = ?,
                result_export_filename = ?,
                result_export_job_id = ?,
                error_json = NULL,
                finished_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (row_count, export_format, export_filename, job_id, _now_iso(), _now_iso(), job_id),
        )

def finish_mcp_run_failed(
    self,
    *,
    job_id: str,
    error_payload: dict[str, Any],
) -> None:
    with self._connect() as conn:
        conn.execute(
            """
            UPDATE seller_sprite_mcp_runs
            SET result_state = 'failed',
                error_json = ?,
                finished_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (json.dumps(error_payload, ensure_ascii=False), _now_iso(), _now_iso(), job_id),
        )
```

- [ ] **Step 4: 运行单测，确认仓储状态更新通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py -k mcp_run -v`

Expected: PASS

- [ ] **Step 5: 提交该阶段改动**

```bash
git add tests/seller_sprite/test_task_queue_store.py opscli/seller_sprite/services/task_queue_store.py
git commit -m "feat: update seller sprite mcp run states"
```

### Task 3: MCP 入口创建初始调用记录

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] **Step 1: 写失败测试，要求 `seller_sprite_run` 入队前写入邮箱和参数**

```python
def test_seller_sprite_run_creates_mcp_run_record(monkeypatch, tmp_path):
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    class DummyScheduler:
        async def enqueue(self, request):
            return {"job_id": request.job_id, "state": "queued", "stage": "queued", "position": 1}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr("opscli.mcp.context.get_current_user_email", lambda: "user@example.com")
    monkeypatch.setattr("opscli.seller_sprite.services.task_queue_store.DEFAULT_QUEUE_DB_PATH", tmp_path / "queue.sqlite3")

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L"},
            export_format="json",
        )
    )

    assert result["success"] is True
    row = store.get_mcp_run(result["data"]["job_id"])
    assert row["user_email"] == "user@example.com"
    assert row["scenario"] == "keyword-reverse"
    assert json.loads(row["params_json"]) == {"asin": "B07YRMT36L"}
```

- [ ] **Step 2: 运行单测，确认因为入口未写审计记录而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -k creates_mcp_run_record -v`

Expected: FAIL，错误为 `MCP 调用记录不存在`

- [ ] **Step 3: 写最小实现，在 `seller_sprite_run` 中创建初始记录**

```python
from opscli.mcp.context import get_current_user_email
from opscli.seller_sprite.services.task_queue_store import SellerSpriteTaskQueueStore

user_email = (get_current_user_email() or "").strip().lower()
if not user_email:
    raise ValueError("当前 MCP 调用缺少用户邮箱，无法写入卖家精灵调用记录")

request = _build_request(...)
if not request.job_id:
    from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

    normalized = SellerSpriteTaskScheduler(auto_start=False)._normalize_request(request)
    request = normalized

SellerSpriteTaskQueueStore().create_mcp_run(
    request=request,
    user_email=user_email,
)
return _ok(await scheduler.enqueue(request))
```

- [ ] **Step 4: 运行单测，确认入口创建记录通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -k creates_mcp_run_record -v`

Expected: PASS

- [ ] **Step 5: 提交该阶段改动**

```bash
git add tests/mcp/test_seller_sprite_tools.py opscli/mcp/tools/seller_sprite.py
git commit -m "feat: record seller sprite mcp run on enqueue"
```

### Task 4: MCP 入口失败时回写失败态

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] **Step 1: 写失败测试，要求调度器入队异常时记录变为 failed**

```python
def test_seller_sprite_run_marks_mcp_run_failed_when_enqueue_errors(monkeypatch, tmp_path):
    store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")

    class BrokenScheduler:
        async def enqueue(self, request):
            raise RuntimeError("queue broken")

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: BrokenScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr("opscli.mcp.context.get_current_user_email", lambda: "user@example.com")
    monkeypatch.setattr("opscli.seller_sprite.services.task_queue_store.DEFAULT_QUEUE_DB_PATH", tmp_path / "queue.sqlite3")

    result = _run(
        seller_sprite_tools.seller_sprite_run(
            scenario="keyword-reverse",
            site="JP",
            period="nearly",
            params={"asin": "B07YRMT36L"},
            export_format="json",
        )
    )

    assert result["success"] is False
    job_id = next(iter(Path(tmp_path).glob("queue.sqlite3*")), None)
    row = store.get_mcp_run(store.get_latest_mcp_run_job_id())
    assert row["result_state"] == "failed"
    assert json.loads(row["error_json"])["message"] == "queue broken"
```

- [ ] **Step 2: 运行单测，确认入口异常未回写失败态**

Run: `.\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -k marks_mcp_run_failed -v`

Expected: FAIL，错误为记录状态仍是 `queued` 或无法读取错误对象

- [ ] **Step 3: 写最小实现，在 `seller_sprite_run` 异常分支补写失败态**

```python
created_job_id: str | None = None
try:
    request = _build_request(...)
    ...
    SellerSpriteTaskQueueStore().create_mcp_run(request=request, user_email=user_email)
    created_job_id = str(request.job_id)
    return _ok(await scheduler.enqueue(request))
except Exception as exc:
    if created_job_id:
        SellerSpriteTaskQueueStore().finish_mcp_run_failed(
            job_id=created_job_id,
            error_payload={"code": type(exc).__name__, "message": str(exc)},
        )
    return _err(...)
```

- [ ] **Step 4: 运行单测，确认失败回写通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -k marks_mcp_run_failed -v`

Expected: PASS

- [ ] **Step 5: 提交该阶段改动**

```bash
git add tests/mcp/test_seller_sprite_tools.py opscli/mcp/tools/seller_sprite.py
git commit -m "fix: mark seller sprite mcp run failed on enqueue error"
```

### Task 5: 调度阶段更新 running / succeeded / failed

**Files:**
- Modify: `opscli/seller_sprite/services/task_scheduler.py`
- Test: `tests/seller_sprite/test_task_scheduler.py`

- [ ] **Step 1: 写失败测试，要求调度阶段更新审计状态**

```python
def test_scheduler_updates_mcp_run_states(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        request = _request("job-state-1", "B07YRMT36L")
        store.create_mcp_run(request=request, user_email="user@example.com")

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: ResultFileRunManager(**kwargs),
            auto_start=False,
        )

        await scheduler.enqueue(request)
        await scheduler.start()
        await _wait_for_state(scheduler, "job-state-1", "succeeded")

        row = store.get_mcp_run("job-state-1")
        assert row["result_state"] == "succeeded"
        assert row["started_at"] is not None
        assert row["result_row_count"] == 2
        assert row["result_export_filename"] == "job.json"
    asyncio.run(scenario())

def test_scheduler_marks_mcp_run_failed(tmp_path: Path):
    async def scenario():
        from opscli.seller_sprite.services.task_scheduler import SellerSpriteTaskScheduler

        class BrokenRunManager:
            def __init__(self, *, settings, account_provider, jwt=None, session_id=None):
                self.settings = settings

            async def run(self, request):
                raise RuntimeError("run failed")

        settings = SellerSpriteSettings(output_dir=tmp_path)
        store = SellerSpriteTaskQueueStore(db_path=tmp_path / "queue.sqlite3")
        request = _request("job-state-2", "B07YRMT36L")
        store.create_mcp_run(request=request, user_email="user@example.com")

        scheduler = SellerSpriteTaskScheduler(
            store=store,
            settings=settings,
            account_provider=DummyAccountProvider(),
            manager_factory=lambda **kwargs: BrokenRunManager(**kwargs),
            auto_start=False,
        )

        await scheduler.enqueue(request)
        await scheduler.start()
        await _wait_for_state(scheduler, "job-state-2", "failed")

        row = store.get_mcp_run("job-state-2")
        assert row["result_state"] == "failed"
        assert json.loads(row["error_json"])["message"] == "run failed"
    asyncio.run(scenario())
```

- [ ] **Step 2: 运行单测，确认调度阶段未更新审计状态**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_scheduler.py -k "updates_mcp_run_states or marks_mcp_run_failed" -v`

Expected: FAIL，错误为 `result_state` 仍是 `queued` 或缺少导出摘要

- [ ] **Step 3: 写最小实现，在 `_run_loop` / `_run_one` 中补状态更新**

```python
claimed = self.store.claim_next(...)
if claimed is not None:
    self.store.mark_mcp_run_running(str(claimed["job_id"]))
    await self._run_one(str(claimed["job_id"]))

try:
    result = await manager.run(request)
except Exception as exc:
    error_payload = error_to_dict(exc)
    self.store.fail_task(job_id=job_id, error_payload=error_payload)
    self.store.finish_mcp_run_failed(job_id=job_id, error_payload=error_payload)
    return

export_payload = result.export.to_dict() if result.export else None
self.store.finish_task(
    job_id=job_id,
    result_path=result.result_path,
    row_count=result.row_count,
    export_payload=export_payload,
)
self.store.finish_mcp_run_success(
    job_id=job_id,
    row_count=result.row_count,
    export_payload=export_payload,
)
```

- [ ] **Step 4: 运行单测，确认调度状态更新通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_scheduler.py -k "updates_mcp_run_states or marks_mcp_run_failed" -v`

Expected: PASS

- [ ] **Step 5: 提交该阶段改动**

```bash
git add tests/seller_sprite/test_task_scheduler.py opscli/seller_sprite/services/task_scheduler.py
git commit -m "feat: sync seller sprite mcp run states with scheduler"
```

### Task 6: 回归、文档和变更记录

**Files:**
- Modify: `docs/change-log-pending.md`
- Test: `tests/seller_sprite/test_task_queue_store.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`
- Test: `tests/seller_sprite/test_task_scheduler.py`

- [ ] **Step 1: 运行目标回归**

Run: `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py tests/mcp/test_seller_sprite_tools.py tests/seller_sprite/test_task_scheduler.py -q`

Expected: PASS，相关新增用例全部通过

- [ ] **Step 2: 更新变更记录**

```markdown
## 2026-06-22 seller_sprite - MCP 调用记录入 SQLite

**变更原因**：卖家精灵 MCP 需要记录调用用户、模式、参数和结果摘要，便于排查与审计。
**改动点**：在 `task_queue.sqlite3` 中新增 `seller_sprite_mcp_runs` 表；`seller_sprite_run` 在入队前创建记录；调度器在 running/succeeded/failed 阶段持续更新同一条记录；补充对应测试。
**验证结果**：列出本次定向 pytest 命令及通过结果。
**影响范围**：仅影响卖家精灵 MCP `seller_sprite_run` 调用链和同库 SQLite 审计表。
**回滚方式**：回退仓储、MCP 工具、调度器和测试改动，删除新增审计表逻辑。
---
```

- [ ] **Step 3: 提交最终收尾改动**

```bash
git add docs/change-log-pending.md
git commit -m "docs: record seller sprite mcp run audit change"
```

## 自检

- 规格覆盖：设计文档中的表结构、四个写入时机、仅 MCP `seller_sprite_run`、不保存原始结果内容，均已有对应任务覆盖。
- 占位符检查：计划中未使用 TBD / TODO / “类似上一步” 等占位写法。
- 类型一致性：计划内统一使用 `create_mcp_run`、`mark_mcp_run_running`、`finish_mcp_run_success`、`finish_mcp_run_failed` 四个方法名，状态名统一为 `queued` / `running` / `succeeded` / `failed`。
