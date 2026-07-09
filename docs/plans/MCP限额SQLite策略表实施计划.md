# MCP 限额 SQLite 策略表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MCP quota 策略从 `mcp-quota.json` 迁移为 SQLite 表驱动，并让线上直接 SQL 修改在下一次 MCP 调用立即生效。

**Architecture:** `SQLiteQuotaStore` 统一管理策略表、每日用量表和长期加额表；`QuotaLimiter` 不再持有启动时策略快照，而是在每次调用前通过 store 读取当前 tool 策略。JSON 配置加载链路彻底删除，只保留 SQLite 路径环境变量和 quota 总开关环境变量。

**Tech Stack:** Python 3.10、标准库 `sqlite3`、pytest、Typer/FastMCP 既有 MCP tool 注册切面。

## Global Constraints

- 运行时 quota 策略唯一来源是 SQLite 表 `mcp_quota_policy`。
- 删除 `mcp-quota.json` 运行时读取链路，不保留 JSON 兜底、不提供 JSON 自动迁移。
- 保留 `OPSCLI_MCP_QUOTA_ENABLED` 作为 quota 总开关。
- 保留 `OPSCLI_MCP_QUOTA_SQLITE_PATH` 作为 quota SQLite 文件路径覆盖入口。
- 空策略表只初始化 `default_quota_policies()` 的代码默认值：`keepa_run=5`、`seller_sprite_run=5`、`seller_sprite_listing_analysis_submit=5`。
- 非空策略表不能被默认策略覆盖。
- 普通业务 tool 遇到无策略或 `enabled=0` 时直接放行。
- 已启用策略遇到 SQLite 不可用、策略字段非法或身份缺失时继续阻断调用。
- 不改变现有响应顶层 `quota` 字段结构。
- Python 代码新增或修改的注释、docstring 必须使用中文。
- 终端输出新增内容必须 GBK 兼容，不使用 emoji、Dingbats 成功/失败符号。
- 除非用户明确要求，不执行 `git commit` 或 `git push`；每个任务以 review checkpoint 结束。
- 任何代码文件通过 Edit/Write 修改后，立即追加 `docs/change-log-pending.md` 变更记录。

---

## File Structure

- Modify: `opscli/mcp/quota.py`
  - 删除 JSON 配置结构、环境变量和查找函数。
  - 新增 `mcp_quota_policy` schema 初始化。
  - 新增策略表默认初始化、策略读取和策略行校验。
  - 将 `QuotaLimiter` 改为每次调用动态读取策略。
- Modify: `tests/mcp/test_quota.py`
  - 删除 JSON 配置读取测试。
  - 新增 SQLite 策略表、动态策略读取、禁用策略、删除策略、非法策略测试。
  - 调整 `QuotaLimiter` 构造方式和内存测试 store。
- Modify: `pyproject.toml`
  - 从 package-data 移除 `mcp/configs/mcp-quota.json`。
- Delete: `opscli/mcp/configs/mcp-quota.json`
  - JSON 配置文件不再作为运行时配置或包资源。
- Modify: `docs/change-log-pending.md`
  - 追加本次代码变更记录和验证命令结果。

---

### Task 1: SQLite 策略表 schema 与策略读取

**Files:**
- Modify: `opscli/mcp/quota.py`
- Test: `tests/mcp/test_quota.py`

**Interfaces:**
- Consumes: `QuotaPolicy(tool_name: str, service: str, daily_limit: int, timezone: str = "Asia/Shanghai")`
- Produces: `QuotaStore.get_policy(tool_name: str) -> Coroutine[Any, Any, QuotaPolicy | None]`
- Produces: `SQLiteQuotaStore.get_policy(tool_name: str) -> Coroutine[Any, Any, QuotaPolicy | None]`
- Produces: `mcp_quota_policy(tool_name, service, daily_limit, enabled, timezone, created_at, updated_at)`

- [ ] **Step 1: Write failing tests for default policy initialization and non-overwrite behavior**

Add these tests to `tests/mcp/test_quota.py` after `test_default_quota_policies_only_limit_public_service_run_entries`:

```python
def test_sqlite_quota_store_initializes_default_policy_table(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)

    policy = _run(store.get_policy("seller_sprite_run"))

    assert policy == QuotaPolicy(
        tool_name="seller_sprite_run",
        service="seller_sprite",
        daily_limit=5,
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tool_name, service, daily_limit, enabled, timezone
            FROM mcp_quota_policy
            ORDER BY tool_name
            """
        ).fetchall()

    assert rows == [
        ("keepa_run", "keepa", 5, 1, "Asia/Shanghai"),
        ("seller_sprite_listing_analysis_submit", "seller_sprite", 5, 1, "Asia/Shanghai"),
        ("seller_sprite_run", "seller_sprite", 5, 1, "Asia/Shanghai"),
    ]


def test_sqlite_quota_store_does_not_overwrite_existing_policy_table(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE mcp_quota_policy (
                tool_name TEXT NOT NULL PRIMARY KEY,
                service TEXT NOT NULL,
                daily_limit INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO mcp_quota_policy (
                tool_name, service, daily_limit, enabled, timezone, created_at, updated_at
            )
            VALUES ('seller_sprite_run', 'seller_sprite', 100, 1, 'Asia/Shanghai', '2026-07-09T10:00:00+08:00', '2026-07-09T10:00:00+08:00')
            """
        )

    store = SQLiteQuotaStore(db_path)
    policy = _run(store.get_policy("seller_sprite_run"))

    assert policy == QuotaPolicy(
        tool_name="seller_sprite_run",
        service="seller_sprite",
        daily_limit=100,
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_name, daily_limit FROM mcp_quota_policy ORDER BY tool_name"
        ).fetchall()

    assert rows == [("seller_sprite_run", 100)]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
pytest tests/mcp/test_quota.py::test_sqlite_quota_store_initializes_default_policy_table tests/mcp/test_quota.py::test_sqlite_quota_store_does_not_overwrite_existing_policy_table -v
```

Expected: FAIL because `SQLiteQuotaStore` does not yet expose `get_policy()` and `mcp_quota_policy` is not created.

- [ ] **Step 3: Add policy read interface to `QuotaStore`**

In `opscli/mcp/quota.py`, update `class QuotaStore(Protocol)` to include this method before `reserve()`:

```python
    async def get_policy(self, tool_name: str) -> QuotaPolicy | None:
        """读取当前 tool 的限额策略；无策略或禁用时返回 None。"""
```

- [ ] **Step 4: Add `SQLiteQuotaStore.get_policy()`**

In `opscli/mcp/quota.py`, add this method inside `class SQLiteQuotaStore`, before `reserve()`:

```python
    async def get_policy(self, tool_name: str) -> QuotaPolicy | None:
        """从 SQLite 策略表读取当前 tool 的最新限额策略。"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT tool_name, service, daily_limit, enabled, timezone
                    FROM mcp_quota_policy
                    WHERE tool_name = ?
                    """,
                    (tool_name,),
                ).fetchone()
        except QuotaUnavailableError:
            raise
        except Exception as exc:
            raise QuotaUnavailableError(str(exc)) from exc

        if row is None:
            return None
        if int(row["enabled"] or 0) == 0:
            return None
        return _policy_from_row(row)
```

- [ ] **Step 5: Create and initialize `mcp_quota_policy` in `_ensure_schema()`**

In `opscli/mcp/quota.py`, add this block at the start of `SQLiteQuotaStore._ensure_schema()` before creating `mcp_quota_daily`:

```python
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_quota_policy (
                tool_name TEXT NOT NULL PRIMARY KEY,
                service TEXT NOT NULL,
                daily_limit INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        policy_count = conn.execute("SELECT COUNT(*) AS cnt FROM mcp_quota_policy").fetchone()
        if int(policy_count["cnt"] or 0) == 0:
            self._insert_default_policies(conn)
```

Add this private method inside `class SQLiteQuotaStore`, after `_ensure_schema()`:

```python
    def _insert_default_policies(self, conn: sqlite3.Connection) -> None:
        """空策略表初始化代码默认策略，避免首次部署后所有受限 tool 失控放行。"""
        now = _updated_at_iso(datetime.now(UTC))
        rows = [
            (
                policy.tool_name,
                policy.service,
                policy.daily_limit,
                1,
                policy.timezone,
                now,
                now,
            )
            for policy in default_quota_policies().values()
        ]
        conn.executemany(
            """
            INSERT INTO mcp_quota_policy (
                tool_name, service, daily_limit, enabled, timezone, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
```

- [ ] **Step 6: Add policy row validation helper**

In `opscli/mcp/quota.py`, add this function before `_load_local_quota_email()`:

```python
def _policy_from_row(row: sqlite3.Row) -> QuotaPolicy:
    """将 SQLite 策略行转换为运行时策略对象，并阻断非法配置。"""
    tool_name = str(row["tool_name"] or "").strip()
    service = str(row["service"] or "").strip()
    timezone = str(row["timezone"] or "").strip() or "Asia/Shanghai"
    try:
        daily_limit = int(row["daily_limit"])
    except (TypeError, ValueError) as exc:
        raise QuotaUnavailableError(f"MCP 限额策略 daily_limit 非法：{tool_name}") from exc

    if not tool_name:
        raise QuotaUnavailableError("MCP 限额策略 tool_name 不能为空")
    if not service:
        raise QuotaUnavailableError(f"MCP 限额策略 service 不能为空：{tool_name}")
    if daily_limit <= 0:
        raise QuotaUnavailableError(f"MCP 限额策略 daily_limit 必须大于 0：{tool_name}")

    return QuotaPolicy(
        tool_name=tool_name,
        service=service,
        daily_limit=daily_limit,
        timezone=timezone,
    )
```

- [ ] **Step 7: Run Task 1 tests to verify they pass**

Run:

```bash
pytest tests/mcp/test_quota.py::test_sqlite_quota_store_initializes_default_policy_table tests/mcp/test_quota.py::test_sqlite_quota_store_does_not_overwrite_existing_policy_table -v
```

Expected: PASS for both tests.

- [ ] **Step 8: Review checkpoint**

Inspect `opscli/mcp/quota.py` and `tests/mcp/test_quota.py` diff. Confirm:

```text
mcp_quota_policy is created before daily usage is read.
Empty policy table receives code defaults once.
Existing non-empty policy table is not overwritten.
All new comments and docstrings are Chinese.
```

---

### Task 2: Dynamic policy lookup in `QuotaLimiter`

**Files:**
- Modify: `opscli/mcp/quota.py`
- Test: `tests/mcp/test_quota.py`

**Interfaces:**
- Consumes: `QuotaStore.get_policy(tool_name: str) -> Coroutine[Any, Any, QuotaPolicy | None]`
- Produces: `QuotaLimiter(store: QuotaStore, identity_resolver: QuotaIdentityResolver | Callable[[], str | None] | None = None, quota_enabled: Callable[[], bool] | None = None)`
- Produces: `QuotaLimiter.before_call(tool_name: str) -> Coroutine[Any, Any, QuotaDecision]`
- Produces: `QuotaLimiter.quota_snapshot(tool_name: str, identity: str | None = None) -> Coroutine[Any, Any, dict[str, Any]]`

- [ ] **Step 1: Write failing tests for dynamic reads, disabled policy, deleted policy, and invalid policy**

Add these tests to `tests/mcp/test_quota.py` after `test_limiter_refunds_failed_call_and_records_failure`:

```python
def test_limiter_reads_policy_from_sqlite_on_each_call(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )

    first = _run(limiter.before_call("seller_sprite_run"))
    assert first.allowed is True

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET daily_limit = 1, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    second = _run(limiter.before_call("seller_sprite_run"))

    assert second.allowed is False
    assert second.error_response["error"]["code"] == "MCP_QUOTA_EXCEEDED"
    assert second.error_response["quota"]["limit"] == 1
    assert second.error_response["quota"]["used"] == 1


def test_limiter_allows_disabled_policy_without_creating_daily_record(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET enabled = 0, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is True
    assert decision.ticket is None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM mcp_quota_daily").fetchone()
    assert row[0] == 0


def test_limiter_allows_deleted_policy_without_creating_daily_record(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM mcp_quota_policy WHERE tool_name = 'seller_sprite_run'")

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is True
    assert decision.ticket is None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM mcp_quota_daily").fetchone()
    assert row[0] == 0


def test_limiter_blocks_invalid_sqlite_policy_without_calling_service(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    store = SQLiteQuotaStore(db_path)
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "email:user@example.com",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_quota_policy
            SET daily_limit = 0, updated_at = '2026-07-09T10:00:00+08:00'
            WHERE tool_name = 'seller_sprite_run'
            """
        )

    decision = _run(limiter.before_call("seller_sprite_run"))

    assert decision.allowed is False
    assert decision.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"
    assert decision.error_response["quota"]["service"] == "seller_sprite_run"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
pytest tests/mcp/test_quota.py::test_limiter_reads_policy_from_sqlite_on_each_call tests/mcp/test_quota.py::test_limiter_allows_disabled_policy_without_creating_daily_record tests/mcp/test_quota.py::test_limiter_allows_deleted_policy_without_creating_daily_record tests/mcp/test_quota.py::test_limiter_blocks_invalid_sqlite_policy_without_calling_service -v
```

Expected: FAIL because `QuotaLimiter` still expects `policies=` and does not dynamically query the store.

- [ ] **Step 3: Refactor `QuotaLimiter.__init__()`**

In `opscli/mcp/quota.py`, replace the `QuotaLimiter.__init__()` signature and body with:

```python
    def __init__(
        self,
        *,
        store: QuotaStore,
        identity_resolver: QuotaIdentityResolver | Callable[[], str | None] | None = None,
        quota_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store
        self.identity_resolver = identity_resolver or QuotaIdentityResolver()
        self.quota_enabled = quota_enabled or _quota_enabled
```

Update the class docstring to:

```python
    """MCP Tool 限额编排器。

    该类每次调用都从存储层读取最新策略，避免线上修改 SQLite 策略表后
    仍然使用进程启动时的旧快照。
    """
```

- [ ] **Step 4: Refactor `QuotaLimiter.before_call()`**

In `opscli/mcp/quota.py`, replace `before_call()` with:

```python
    async def before_call(self, tool_name: str) -> QuotaDecision:
        """在真实工具执行前动态读取策略并检查限额。"""
        if not self.quota_enabled():
            return QuotaDecision(allowed=True)

        try:
            policy = await self.store.get_policy(tool_name)
        except QuotaUnavailableError as exc:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_UNAVAILABLE",
                    f"限额服务不可用：{exc}",
                    _empty_snapshot_for_tool(tool_name),
                ),
            )

        if not policy:
            return QuotaDecision(allowed=True)

        identity = self._resolve_identity()
        if not identity:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_IDENTITY_MISSING",
                    "无法识别当前 MCP 调用用户，已阻断受限服务调用",
                    _empty_snapshot(policy),
                ),
            )

        try:
            allowed, snapshot = await self.store.reserve(policy, identity)
        except QuotaUnavailableError as exc:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_UNAVAILABLE",
                    f"限额服务不可用：{exc}",
                    _empty_snapshot(policy),
                ),
            )

        if not allowed:
            return QuotaDecision(
                allowed=False,
                error_response=_error_response(
                    "MCP_QUOTA_EXCEEDED",
                    "已超出当前服务的每日调用限额",
                    snapshot,
                ),
            )

        return QuotaDecision(
            allowed=True,
            ticket=QuotaTicket(policy=policy, identity=identity, snapshot=snapshot),
        )
```

- [ ] **Step 5: Refactor `QuotaLimiter.quota_snapshot()`**

In `opscli/mcp/quota.py`, replace `quota_snapshot()` with:

```python
    async def quota_snapshot(self, tool_name: str, identity: str | None = None) -> dict[str, Any]:
        """读取某个受限工具当前身份的额度快照。"""
        if not self.quota_enabled():
            raise ValueError("MCP quota 当前已关闭，无法读取额度")

        policy = await self.store.get_policy(tool_name)
        if not policy:
            raise ValueError(f"未启用限额策略：{tool_name}")

        resolved_identity = identity or self._resolve_identity()
        if not resolved_identity:
            raise ValueError("无法识别当前 MCP 调用用户，无法读取额度")

        return await self.store.snapshot(policy, resolved_identity)
```

- [ ] **Step 6: Add fallback snapshot for policy-read failures**

In `opscli/mcp/quota.py`, add this function after `_empty_snapshot()`:

```python
def _empty_snapshot_for_tool(tool_name: str) -> dict[str, Any]:
    """策略读取失败时生成保守 quota 元信息，避免错误响应缺少 quota 字段。"""
    return _snapshot(tool_name, 0, 0, 0, datetime.now(UTC))
```

- [ ] **Step 7: Update existing limiter tests to the new constructor**

In `tests/mcp/test_quota.py`, replace existing `QuotaLimiter(policies=..., store=..., identity_resolver=...)` calls with the new constructor.

For `test_limiter_allows_first_five_calls_and_blocks_sixth`, replace the body with:

```python
def test_limiter_allows_first_five_calls_and_blocks_sixth(tmp_path):
    store = SQLiteQuotaStore(tmp_path / "quota.sqlite3")
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "user:user-1",
    )

    results = [_run(limiter.before_call("seller_sprite_run")) for _ in range(5)]
    blocked = _run(limiter.before_call("seller_sprite_run"))

    assert [item.allowed for item in results] == [True, True, True, True, True]
    assert blocked.allowed is False
    assert blocked.error_response["error"]["code"] == "MCP_QUOTA_EXCEEDED"
    assert blocked.error_response["quota"]["used"] == 5
    assert blocked.error_response["quota"]["remaining"] == 0
```

For `test_limiter_refunds_failed_call_and_records_failure`, replace the body with:

```python
def test_limiter_refunds_failed_call_and_records_failure(tmp_path):
    store = SQLiteQuotaStore(tmp_path / "quota.sqlite3")
    limiter = QuotaLimiter(
        store=store,
        identity_resolver=lambda: "user:user-1",
    )

    decision = _run(limiter.before_call("seller_sprite_run"))
    response = _run(limiter.after_call(decision.ticket, {"success": False, "data": None, "error": {"code": "ValueError"}}))

    assert response["quota"]["used"] == 0
    assert response["quota"]["failures"] == 1
```

For `test_limiter_returns_unavailable_error_without_calling_service`, replace the body with:

```python
def test_limiter_returns_unavailable_error_without_calling_service():
    class UnavailablePolicyStore:
        async def get_policy(self, tool_name):
            raise QuotaUnavailableError("sqlite down")

        async def reserve(self, policy, identity):
            raise AssertionError("reserve must not be called when policy loading fails")

        async def refund_failure(self, policy, identity):
            raise AssertionError("refund must not be called when policy loading fails")

        async def snapshot(self, policy, identity):
            raise AssertionError("snapshot must not be called when policy loading fails")

    limiter = QuotaLimiter(
        store=UnavailablePolicyStore(),
        identity_resolver=lambda: "user:user-1",
    )

    result = _run(limiter.before_call("seller_sprite_run"))

    assert result.allowed is False
    assert result.error_response["error"]["code"] == "MCP_QUOTA_UNAVAILABLE"
```

- [ ] **Step 8: Run Task 2 tests to verify they pass**

Run:

```bash
pytest tests/mcp/test_quota.py::test_limiter_reads_policy_from_sqlite_on_each_call tests/mcp/test_quota.py::test_limiter_allows_disabled_policy_without_creating_daily_record tests/mcp/test_quota.py::test_limiter_allows_deleted_policy_without_creating_daily_record tests/mcp/test_quota.py::test_limiter_blocks_invalid_sqlite_policy_without_calling_service tests/mcp/test_quota.py::test_limiter_allows_first_five_calls_and_blocks_sixth tests/mcp/test_quota.py::test_limiter_refunds_failed_call_and_records_failure tests/mcp/test_quota.py::test_limiter_returns_unavailable_error_without_calling_service -v
```

Expected: PASS for all listed tests.

- [ ] **Step 9: Review checkpoint**

Inspect the diff. Confirm:

```text
QuotaLimiter no longer stores a policies dict.
QuotaLimiter checks quota_enabled on each before_call and quota_snapshot.
Disabled and deleted policies do not create rows in mcp_quota_daily.
Invalid enabled policies return MCP_QUOTA_UNAVAILABLE instead of allowing calls.
```

---

### Task 3: Remove JSON quota configuration surface

**Files:**
- Modify: `opscli/mcp/quota.py`
- Modify: `tests/mcp/test_quota.py`
- Modify: `pyproject.toml`
- Delete: `opscli/mcp/configs/mcp-quota.json`

**Interfaces:**
- Removes: `ENV_QUOTA_CONFIG_PATH`
- Removes: `QuotaConfig`
- Removes: `load_quota_config(path: str | Path | None = None) -> QuotaConfig`
- Removes: `_find_quota_config_path()` and JSON path helper functions
- Produces: `get_quota_limiter() -> QuotaLimiter` backed only by `SQLiteQuotaStore`

- [ ] **Step 1: Write failing test for removed JSON config API**

Add this test to `tests/mcp/test_quota.py` near the bottom of the file:

```python
def test_quota_module_no_longer_exposes_json_config_loader():
    import opscli.mcp.quota as quota_module

    assert not hasattr(quota_module, "ENV_QUOTA_CONFIG_PATH")
    assert not hasattr(quota_module, "QuotaConfig")
    assert not hasattr(quota_module, "load_quota_config")
    assert not hasattr(quota_module, "_find_quota_config_path")
```

- [ ] **Step 2: Run the API removal test to verify it fails**

Run:

```bash
pytest tests/mcp/test_quota.py::test_quota_module_no_longer_exposes_json_config_loader -v
```

Expected: FAIL because the JSON config symbols still exist.

- [ ] **Step 3: Remove JSON imports and symbols from `quota.py`**

In `opscli/mcp/quota.py`, remove:

```python
import json
```

Remove this constant:

```python
ENV_QUOTA_CONFIG_PATH = "OPSCLI_MCP_QUOTA_CONFIG_PATH"
```

Remove the whole `QuotaConfig` dataclass:

```python
@dataclass(frozen=True)
class QuotaConfig:
    ...
```

Remove these functions completely:

```python
def load_quota_config(path: str | Path | None = None) -> QuotaConfig:
    ...


def _default_quota_config_path() -> Path:
    ...


def _find_quota_config_path() -> Path | None:
    ...


def _working_directory_quota_config_path() -> Path:
    ...


def _project_quota_config_path() -> Path:
    ...


def _packaged_quota_config_path() -> Path:
    ...


def _parse_sqlite_path(value: Any) -> Path | None:
    ...


def _merge_policy_config(raw_policies: Any) -> dict[str, QuotaPolicy]:
    ...
```

- [ ] **Step 4: Simplify `get_quota_limiter()`**

In `opscli/mcp/quota.py`, replace `get_quota_limiter()` with:

```python
def get_quota_limiter() -> QuotaLimiter:
    """获取默认限额编排器，供 MCP Tool 注册切面使用。"""
    global _default_limiter
    if _default_limiter is None:
        sqlite_path = os.environ.get(ENV_SQLITE_PATH)
        _default_limiter = QuotaLimiter(
            store=SQLiteQuotaStore(sqlite_path),
        )
    return _default_limiter
```

- [ ] **Step 5: Update `tests/mcp/test_quota.py` imports and delete JSON config tests**

In `tests/mcp/test_quota.py`, remove these imports:

```python
import json
```

```python
    ENV_QUOTA_CONFIG_PATH,
```

```python
    load_quota_config,
```

Delete these test functions entirely:

```python
def test_load_quota_config_overrides_default_policy_limit(tmp_path):
    ...


def test_load_quota_config_can_disable_policy(tmp_path):
    ...


def test_load_quota_config_uses_env_path_before_default_user_config(tmp_path, monkeypatch):
    ...


def test_load_quota_config_uses_project_config_before_user_config(tmp_path, monkeypatch):
    ...


def test_load_quota_config_uses_working_directory_config_for_packaged_deploy(tmp_path, monkeypatch):
    ...
```

- [ ] **Step 6: Remove package-data entry from `pyproject.toml`**

In `pyproject.toml`, change this block:

```toml
[tool.setuptools.package-data]
# Hook 脚本作为资源文件保留（非编译对象，由 settings_injector.py 部署到用户目录）
"opscli" = [
    "skills/hooks/report_skill_usage.py",
    "mcp/configs/mcp-quota.json",
]
```

To this block:

```toml
[tool.setuptools.package-data]
# Hook 脚本作为资源文件保留（非编译对象，由 settings_injector.py 部署到用户目录）
"opscli" = [
    "skills/hooks/report_skill_usage.py",
]
```

- [ ] **Step 7: Delete obsolete JSON file**

Run:

```bash
rm opscli/mcp/configs/mcp-quota.json
```

Expected: file is removed from the working tree.

- [ ] **Step 8: Run Task 3 tests to verify removal is complete**

Run:

```bash
pytest tests/mcp/test_quota.py::test_quota_module_no_longer_exposes_json_config_loader -v
```

Expected: PASS.

Run:

```bash
rg -n "mcp-quota|load_quota_config|ENV_QUOTA_CONFIG_PATH|QuotaConfig|_find_quota_config_path" opscli tests pyproject.toml
```

Expected: no matches in runtime code, tests, or package metadata. Matches in historical docs are acceptable only when the search scope includes `docs/`.

- [ ] **Step 9: Review checkpoint**

Inspect the diff. Confirm:

```text
quota.py no longer imports json.
Runtime code has no JSON quota config path lookup.
pyproject.toml no longer packages mcp-quota.json.
opscli/mcp/configs/mcp-quota.json is deleted.
```

---

### Task 4: Full regression verification and change log

**Files:**
- Modify: `docs/change-log-pending.md`
- Test: `tests/mcp/test_quota.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`
- Test: `tests/mcp/test_keepa_tools.py`

**Interfaces:**
- Consumes: completed Tasks 1-3
- Produces: verified regression result and pending change log entry

- [ ] **Step 1: Run full quota test file**

Run:

```bash
pytest tests/mcp/test_quota.py -v
```

Expected: PASS for all tests in `tests/mcp/test_quota.py`.

- [ ] **Step 2: Run seller sprite MCP tool regression tests**

Run:

```bash
pytest tests/mcp/test_seller_sprite_tools.py -v
```

Expected: PASS for all tests in `tests/mcp/test_seller_sprite_tools.py`.

- [ ] **Step 3: Run Keepa MCP tool regression tests**

Run:

```bash
pytest tests/mcp/test_keepa_tools.py -v
```

Expected: PASS for all tests in `tests/mcp/test_keepa_tools.py`.

- [ ] **Step 4: Run targeted search for removed JSON runtime symbols**

Run:

```bash
rg -n "mcp-quota|load_quota_config|ENV_QUOTA_CONFIG_PATH|QuotaConfig|_find_quota_config_path" opscli tests pyproject.toml
```

Expected: no output.

- [ ] **Step 5: Append change log entry immediately after code changes**

Append this entry to `docs/change-log-pending.md` after the tests above pass:

```markdown
## 2026-07-09 MCP - 限额策略迁移到 SQLite 表

**变更原因**：MCP quota 策略此前依赖 `mcp-quota.json`，线上修改后需要重启服务才能生效，运维成本高。
**改动点**：删除 quota JSON 配置读取链路和包内 `mcp-quota.json`；新增 `mcp_quota_policy` SQLite 策略表；`QuotaLimiter` 改为每次调用动态读取 SQLite 策略；保留现有每日用量、失败退回和长期日加额逻辑。
**验证结果**：已运行 `pytest tests/mcp/test_quota.py -v`、`pytest tests/mcp/test_seller_sprite_tools.py -v`、`pytest tests/mcp/test_keepa_tools.py -v`，全部通过；已运行 `rg -n "mcp-quota|load_quota_config|ENV_QUOTA_CONFIG_PATH|QuotaConfig|_find_quota_config_path" opscli tests pyproject.toml`，无输出。
**影响范围**：影响 MCP 外部服务工具的 quota 策略加载方式；`keepa_run`、`seller_sprite_run`、`seller_sprite_listing_analysis_submit` 的默认策略由 SQLite 表驱动；线上需直接修改 `mcp_quota_policy` 调整额度。
**回滚方式**：回滚本次代码变更即可恢复旧 JSON 配置链路；SQLite 中新增的 `mcp_quota_policy` 表不会被旧代码读取，如需清理可执行 `DROP TABLE IF EXISTS mcp_quota_policy;`。
---
```

If any verification command fails, replace the `验证结果` line with the failing command and the actual failure summary before stopping for review.

- [ ] **Step 6: Optional build verification when build tooling is installed**

Run:

```bash
python -m build
```

Expected when build tooling is installed: command completes and produces distributions under `dist/`.

Expected when build tooling is missing: command fails with a Python module error for `build`; report that build verification was skipped because the local build module is not installed.

- [ ] **Step 7: Final review checkpoint**

Inspect the final diff. Confirm:

```text
Only the planned files changed.
No runtime reference to mcp-quota.json remains under opscli, tests, or pyproject.toml.
New Python comments and docstrings are Chinese.
Change log entry exists in docs/change-log-pending.md.
Regression commands and outcomes are recorded accurately.
```

---

## Self-Review

**Spec coverage:**

- SQLite 策略唯一来源：Task 1 creates `mcp_quota_policy`; Task 2 reads it dynamically; Task 3 deletes JSON config surface.
- 每次调用读取：Task 2 adds `test_limiter_reads_policy_from_sqlite_on_each_call` and refactors `QuotaLimiter.before_call()`.
- 直接改 SQLite 生效：Task 2 modifies `daily_limit` with SQL and verifies the next call uses it.
- 空表代码默认值：Task 1 verifies default initialization.
- 非空表不覆盖：Task 1 verifies existing policy table remains unchanged.
- JSON 逻辑删除：Task 3 removes symbols, package-data, and JSON file.
- 错误处理：Task 2 verifies invalid policy returns `MCP_QUOTA_UNAVAILABLE`; existing tests keep identity, unavailable store, refund, and exceeded behavior covered.
- 测试和变更记录：Task 4 runs regression commands and appends `docs/change-log-pending.md`.

**Placeholder scan:**

This plan contains no TBD, no TODO, no unspecified implementation steps, and no unnamed files.

**Type consistency:**

`QuotaStore.get_policy()` returns `QuotaPolicy | None`; `QuotaLimiter.before_call()` and `quota_snapshot()` consume the same interface. `SQLiteQuotaStore.get_policy()` validates and returns the same `QuotaPolicy` dataclass used by `reserve()`, `snapshot()`, and `_empty_snapshot()`.
