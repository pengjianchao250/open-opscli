# Seller Sprite Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为卖家精灵补上只读额度查询入口，并把执行后的剩余额度规则固化到正式 CLI 与 Skill 文档链路。

**Architecture:** 在 MCP 限额模块新增只读快照读取能力，再通过 `seller_sprite_quota_status` 暴露给卖家精灵工具和正式 CLI。`seller_sprite_run` 继续复用现有顶层 `quota` 契约，Skill 文档补齐“何时提示剩余额度”的规则，不改动任务调度主流程。

**Tech Stack:** Python 3.10、Typer、FastMCP、SQLite、pytest

---

### Task 1: 增加限额快照读取能力

**Files:**
- Modify: `opscli/mcp/quota.py`
- Test: `tests/mcp/test_quota.py`

- [ ] **Step 1: Write the failing test**

```python
def test_quota_snapshot_reads_current_usage_without_consuming(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    _run(store.reserve(policy, "email:user@example.com"))
    snapshot = _run(store.snapshot(policy, "email:user@example.com"))

    assert snapshot["limit"] == 5
    assert snapshot["used"] == 1
    assert snapshot["remaining"] == 4


def test_quota_snapshot_applies_bonus_daily_limit(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    policy = QuotaPolicy(tool_name="seller_sprite_run", service="seller_sprite", daily_limit=5)
    store = SQLiteQuotaStore(db_path)

    _run(store.upsert_bonus_daily_limit("seller_sprite", "user@example.com", 3))
    snapshot = _run(store.snapshot(policy, "email:user@example.com"))

    assert snapshot["limit"] == 8
    assert snapshot["used"] == 0
    assert snapshot["remaining"] == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/test_quota.py -k snapshot -v`
Expected: FAIL with `AttributeError` or missing snapshot method

- [ ] **Step 3: Write minimal implementation**

```python
class SQLiteQuotaStore:
    async def snapshot(self, policy: QuotaPolicy, identity: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        identity_type, identity_key, identity_hash = _identity_public_parts(identity)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            effective_limit = self._effective_daily_limit(conn, policy, identity_type, identity_key)
            calls, failures = self._read_or_create_record(
                conn,
                policy,
                identity_type,
                identity_key,
                identity_hash,
                now,
            )
            conn.commit()
            return _snapshot(policy.service, effective_limit, calls, failures, now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/mcp/test_quota.py -k snapshot -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/mcp/test_quota.py opscli/mcp/quota.py
git commit -m "feat: add seller sprite quota snapshot"
```

### Task 2: 暴露 seller_sprite_quota_status MCP 工具

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] **Step 1: Write the failing test**

```python
def test_seller_sprite_quota_status_returns_snapshot(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")

    class FakeLimiter:
        def quota_snapshot(self, tool_name, identity):
            assert tool_name == "seller_sprite_run"
            assert identity == "email:mcp-user@example.com"
            return {
                "service": "seller_sprite",
                "limit": 5,
                "used": 2,
                "remaining": 3,
                "failures": 0,
                "reset_at": "2026-06-24T00:00:00+08:00",
            }

    monkeypatch.setattr("opscli.mcp.tools.seller_sprite.get_quota_limiter", lambda: FakeLimiter())

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is True
    assert result["data"]["remaining"] == 3


def test_seller_sprite_quota_status_returns_error_when_user_email_missing(monkeypatch):
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: None)

    result = _run(seller_sprite_tools.seller_sprite_quota_status())

    assert result["success"] is False
    assert "邮箱" in result["error"]["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/test_seller_sprite_tools.py -k quota_status -v`
Expected: FAIL because `seller_sprite_quota_status` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
async def seller_sprite_quota_status() -> dict:
    user_email = _get_current_mcp_user_email()
    if not user_email:
        return _err(
            ValueError("当前 MCP 用户邮箱缺失，无法读取卖家精灵额度"),
            tool="MCP → seller_sprite_quota_status()",
        )

    from opscli.mcp.quota import get_quota_limiter

    identity = f"email:{user_email.strip().lower()}"
    snapshot = get_quota_limiter().quota_snapshot("seller_sprite_run", identity)
    return _ok(snapshot)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/mcp/test_seller_sprite_tools.py -k quota_status -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/mcp/test_seller_sprite_tools.py opscli/mcp/tools/seller_sprite.py
git commit -m "feat: add seller sprite quota status tool"
```

### Task 3: 打通正式 CLI quota-status 映射

**Files:**
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Modify: `opscli/seller_sprite/cli.py`
- Test: `tests/seller_sprite/test_remote_adapter.py`
- Test: `tests/seller_sprite/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_remote_adapter_maps_quota_status_tool():
    adapter = SellerSpriteRemoteAdapter(
        config_client=FakeConfigClient(),
        remote_client_factory=make_remote_client,
    )

    result = adapter.quota_status()

    assert result["data"]["tool"] == "seller_sprite_quota_status"
    assert result["data"]["arguments"] == {}


def test_public_seller_sprite_quota_status_uses_remote_adapter(monkeypatch):
    class FakeAdapter:
        def quota_status(self):
            return {
                "success": True,
                "data": {"service": "seller_sprite", "remaining": 4},
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(app, ["seller-sprite", "quota-status"])

    assert result.exit_code == 0
    assert '"remaining": 4' in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli.py -k quota_status -v`
Expected: FAIL because adapter and CLI command do not exist

- [ ] **Step 3: Write minimal implementation**

```python
class SellerSpriteRemoteAdapter:
    def quota_status(self) -> dict[str, Any]:
        return self._call_tool("seller_sprite_quota_status", {})


@app.command("quota-status")
def quota_status() -> None:
    payload = SellerSpriteRemoteAdapter().quota_status()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli.py -k quota_status -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli.py opscli/seller_sprite/remote_adapter.py opscli/seller_sprite/cli.py
git commit -m "feat: add seller sprite quota status cli"
```

### Task 4: 更新 Skill 文档与变更记录

**Files:**
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- Modify: `docs/change-log-pending.md`

- [ ] **Step 1: Write the documentation change**

```md
- `seller_sprite_quota_status`：读取当前用户今日额度快照。
- `seller_sprite_run` 会消耗次数；`seller_sprite_scenarios`、`seller_sprite_job_status`、`seller_sprite_export`、`seller_sprite_quota_status` 不消耗次数。
- `seller_sprite_run` 成功或失败后，回复中补充：`今日额度：已用 X / Y，剩余 Z，重置时间 reset_at`。
```

- [ ] **Step 2: Append change log entry**

```md
## 2026-06-23 seller_sprite - 卖家精灵额度查询与提示优化

**变更原因**：补齐卖家精灵每日限额的用户可见链路，支持执行前查询额度，并统一执行后的剩余额度提示规则。
**改动点**：新增 `seller_sprite_quota_status` 工具与正式 CLI 入口；扩展 MCP 限额模块只读快照能力；更新卖家精灵 Skill 文档额度规则。
**验证结果**：运行卖家精灵与 quota 相关 pytest 用例并通过。
**影响范围**：卖家精灵 MCP、正式 CLI、Skill 文档、额度快照读取逻辑。
**回滚方式**：回退 `opscli/mcp/quota.py`、`opscli/mcp/tools/seller_sprite.py`、`opscli/seller_sprite/*` 及对应测试和文档改动。
---
```

- [ ] **Step 3: Run focused verification**

Run: `pytest tests/mcp/test_quota.py tests/mcp/test_seller_sprite_tools.py tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add opscli/skills/templates/ops-seller-sprite/SKILL.md opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md docs/change-log-pending.md
git commit -m "docs: clarify seller sprite quota flow"
```

## Self Review

- 设计要求的两个目标都有任务覆盖：Task 2 和 Task 3 负责独立额度查询，Task 4 负责“执行后提示剩余额度”的文档固化。
- 无 `TODO`、`TBD`、`similar to` 之类占位内容。
- `seller_sprite_quota_status`、`snapshot`、`quota_status()` 等命名在任务间保持一致。
