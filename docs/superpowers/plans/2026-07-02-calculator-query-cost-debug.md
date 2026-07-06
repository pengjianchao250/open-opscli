# 新品计算器 queryCost 调试可见性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强 `opscli calculator draft`，让本地 CLI 能在不新增命令的前提下展示 Web 端“点击确定”对应的 `/calculator/newProduct/queryCost` 请求，并支持显式透传 `_t`。

**Architecture:** 保持 `draft` 作为主流程：`cli.py` 负责 Typer 参数、调试输出和调用编排，`models.py` 继续负责第一阶段 payload 构造，`client.py` 继续封装 Polaris HTTP 接口。新增 `--debug-request` 只影响终端可见性，新增 `--request-t` 只在显式传入时加入 payload；默认行为、草稿包结构和提交流程不变。

**Tech Stack:** Python >=3.10、Typer、httpx、pytest、respx、pathlib、json。

## Global Constraints

- 不新增 `query-cost` 独立命令。
- 不默认添加 `_t`，只在 `--request-t` 显式传入或 `--payload` 文件存在 `_t` 时转发。
- 不改变 `draft` 默认输出结构和草稿包文件结构。
- 不在终端默认打印完整后端响应；完整默认表单数据继续写入 `draft.json`。
- 测试不能访问真实网络，HTTP 使用 fake client 或 respx mock。
- 面向用户的输出使用中文，避免 emoji 和 GBK 不安全字符。
- 代码风格匹配现有 `opscli/calculator`：中文模块 docstring、简洁 helper、Typer 命令层只做编排。
- 文档和代码变更后必须更新 `docs/change-log-pending.md`。
- 不提交 git commit，除非用户明确要求提交。

---

## File Structure

修改文件：

- `opscli/calculator/models.py`：扩展 `build_query_payload()`，支持 `request_t` 参数，并保留 payload 文件中的 `_t`。
- `opscli/calculator/cli.py`：为 `draft` 命令增加 `--debug-request` 和 `--request-t`，在请求前打印 queryCost 路径和 JSON payload。
- `tests/calculator/test_draft.py`：增加 payload 构造层 `_t` 行为测试。
- `tests/calculator/test_cli.py`：增加 CLI 调试输出和 `_t` 透传测试，并让 `FakeClient` 记录收到的 queryCost payload。
- `docs/change-log-pending.md`：追加本次 queryCost 调试可见性变更记录。

---

### Task 1: 扩展 queryCost payload 构造

**Files:**
- Modify: `opscli/calculator/models.py`
- Test: `tests/calculator/test_draft.py`

**Interfaces:**
- Consumes: Existing `read_json_file(path: str | Path) -> dict[str, Any]` and `write_json_file(path: str | Path, payload: dict[str, Any]) -> None`.
- Produces: `build_query_payload(*, country: str | None, platforms: list[int] | None, hs_code_id: int | None, department: str | None, reference: str, reference_value: str | None, payload: dict[str, Any] | None, request_t: int | None = None) -> dict[str, Any]`.
- Contract: `request_t` overrides payload-file `_t` only when `request_t is not None`; otherwise payload-file `_t` is preserved when present.

- [ ] **Step 1: Write failing tests for `_t` payload behavior**

Append these tests after `test_build_query_payload_from_cli_options()` in `tests/calculator/test_draft.py`:

```python
def test_build_query_payload_includes_request_t_from_cli_options():
    payload = build_query_payload(
        country="US",
        platforms=[1, 7],
        hs_code_id=337,
        department=None,
        reference="NONE",
        reference_value=None,
        payload=None,
        request_t=1782983898,
    )

    assert payload == {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 337,
        "department": None,
        "reference": "NONE",
        "reference_value": None,
        "_t": 1782983898,
    }


def test_build_query_payload_preserves_request_t_from_payload_file():
    payload = build_query_payload(
        country="DE",
        platforms=[9],
        hs_code_id=999,
        department="D2",
        reference="NONE",
        reference_value=None,
        payload={"country_code": "US", "platforms": [1, 7], "hs_code_id": 337, "_t": 1782983898},
    )

    assert payload == {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 337,
        "department": None,
        "reference": "NONE",
        "reference_value": None,
        "_t": 1782983898,
    }
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator/test_draft.py::test_build_query_payload_includes_request_t_from_cli_options tests/calculator/test_draft.py::test_build_query_payload_preserves_request_t_from_payload_file -v
```

Expected: first test fails with `TypeError: build_query_payload() got an unexpected keyword argument 'request_t'`.

- [ ] **Step 3: Implement minimal payload support**

Replace the existing `build_query_payload()` function in `opscli/calculator/models.py` with:

```python
def build_query_payload(
    *,
    country: str | None,
    platforms: list[int] | None,
    hs_code_id: int | None,
    department: str | None,
    reference: str,
    reference_value: str | None,
    payload: dict[str, Any] | None,
    request_t: int | None = None,
) -> dict[str, Any]:
    """构造 queryCost 第一阶段请求参数。"""
    if payload is not None:
        source = dict(payload)
        result = {
            "country_code": source.get("country_code"),
            "platforms": source.get("platforms", []),
            "hs_code_id": source.get("hs_code_id"),
            "department": source.get("department"),
            "reference": source.get("reference", "NONE"),
            "reference_value": source.get("reference_value"),
        }
        if "_t" in source:
            result["_t"] = source["_t"]
    else:
        result = {
            "country_code": country,
            "platforms": platforms or [],
            "hs_code_id": hs_code_id,
            "department": department,
            "reference": reference,
            "reference_value": reference_value,
        }
    if request_t is not None:
        result["_t"] = request_t
    missing = [key for key in ("country_code", "platforms", "hs_code_id") if not result.get(key)]
    if missing:
        raise ValueError("缺少第一阶段必填参数：" + "、".join(missing))
    return result
```

- [ ] **Step 4: Run focused tests to verify pass**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator/test_draft.py::test_build_query_payload_includes_request_t_from_cli_options tests/calculator/test_draft.py::test_build_query_payload_preserves_request_t_from_payload_file tests/calculator/test_draft.py::test_build_query_payload_prefers_payload_file_values tests/calculator/test_draft.py::test_build_query_payload_from_cli_options -v
```

Expected: 4 tests pass.

---

### Task 2: 增强 `draft` 命令调试输出

**Files:**
- Modify: `opscli/calculator/cli.py`
- Test: `tests/calculator/test_cli.py`

**Interfaces:**
- Consumes: `build_query_payload(..., request_t: int | None = None) -> dict[str, Any]` from Task 1.
- Produces: `opscli calculator draft --debug-request` terminal output showing `/calculator/newProduct/queryCost` and formatted JSON payload.
- Produces: `opscli calculator draft --request-t <int>` payload field `"_t": <int>`.

- [ ] **Step 1: Update CLI tests to capture queryCost payload and assert default behavior**

In `tests/calculator/test_cli.py`, replace the current `FakeClient` class with this version:

```python
class FakeClient:
    last_query_payload = None

    def dropdown_list(self):
        return {
            "code": 200,
            "data": {
                "marketplaces": [{"key": "US", "value": "美国"}],
                "platforms": [{"key": 1, "value": "亚马逊"}, {"key": 7, "value": "沃尔玛"}],
                "customs_category": [
                    {"key": 4, "value": "8544421100-USB数据线"},
                    {"key": 20, "value": "8544421100-USB连接线"},
                    {"key": 1, "value": "8507600090-移动电源"},
                ],
            },
        }

    def query_cost(self, payload):
        type(self).last_query_payload = payload
        return {"code": 200, "data": {**payload, "tariff_rate": "", "calc_method": "GROSS_PROFIT"}}

    def do_calc(self, payload):
        return {"code": 200, "message": "success", "data": {"task_code": "NPC001"}}

    def zones_warehouse_list(self, country):
        return {"code": 200, "data": {"country_code": country, "by_warehouses": [{"key": "WH-1", "value": "深圳仓"}]}}

    def forecast_list(self, payload):
        assert payload["limit"] == 20
        assert "page_size" not in payload
        return {"code": 200, "data": {"list": [{"task_code": payload.get("task_code") or "NPC001", "country_code": "US"}], "total": 1}}

    def task_details(self, payload):
        assert payload["sudo"] == "admin"
        return {"code": 200, "data": {"task_code": payload["task_code"], "country_code": "US", "product_price": 39.99}}

    def copy_task(self, payload):
        assert payload["sudo"] == "admin"
        return {"code": 200, "data": {"task_code": payload["task_code"], "country_code": "US", "tariff_rate": ""}}
```

In `test_draft_command_creates_package()`, insert `FakeClient.last_query_payload = None` after `monkeypatch.setattr(...)`, and append these assertions after the existing output assertion:

```python
    assert FakeClient.last_query_payload is not None
    assert FakeClient.last_query_payload["country_code"] == "US"
    assert FakeClient.last_query_payload["platforms"] == [1, 7]
    assert FakeClient.last_query_payload["hs_code_id"] == 12345
    assert "_t" not in FakeClient.last_query_payload
```

- [ ] **Step 2: Add failing CLI debug test**

Append this test after `test_draft_command_creates_package()` in `tests/calculator/test_cli.py`:

```python
def test_draft_command_prints_query_cost_debug_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CalculatorClient", lambda: FakeClient())
    FakeClient.last_query_payload = None
    out_dir = tmp_path / "draft-pkg-debug"

    result = runner.invoke(
        cli.app,
        [
            "draft",
            "--country",
            "US",
            "--platform",
            "1",
            "--platform",
            "7",
            "--hs-code-id",
            "337",
            "--request-t",
            "1782983898",
            "--debug-request",
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0
    assert "第一步：调用 /calculator/newProduct/queryCost 获取表单默认参数" in result.output
    assert "请求参数：" in result.output
    assert '"country_code": "US"' in result.output
    assert '"hs_code_id": 337' in result.output
    assert '"_t": 1782983898' in result.output
    assert "queryCost 调用成功，已根据后端默认参数生成草稿。" in result.output
    assert FakeClient.last_query_payload == {
        "country_code": "US",
        "platforms": [1, 7],
        "hs_code_id": 337,
        "department": None,
        "reference": "NONE",
        "reference_value": None,
        "_t": 1782983898,
    }
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator/test_cli.py::test_draft_command_creates_package tests/calculator/test_cli.py::test_draft_command_prints_query_cost_debug_payload -v
```

Expected: `test_draft_command_prints_query_cost_debug_payload` fails because `--request-t` and `--debug-request` are not accepted by the current Typer command.

- [ ] **Step 4: Implement CLI options and debug output**

In `opscli/calculator/cli.py`, update the `draft_command()` signature to include the two new options:

```python
@app.command("draft")
def draft_command(
    country: str | None = typer.Option(None, "--country", help="试算站点，如 US"),
    platform: list[int] | None = typer.Option(None, "--platform", help="试算平台，可重复传入"),
    hs_code_id: int | None = typer.Option(None, "--hs-code-id", help="海关类目 ID"),
    department: str | None = typer.Option(None, "--department", help="部门 ID"),
    reference: str = typer.Option("NONE", "--reference", help="试算参考类型"),
    reference_value: str | None = typer.Option(None, "--reference-value", help="试算参考值"),
    request_t: int | None = typer.Option(None, "--request-t", help="Web 请求 _t 参数，调试对齐时使用"),
    debug_request: bool = typer.Option(False, "--debug-request", help="打印 queryCost 请求路径和 payload"),
    payload: Path | None = typer.Option(None, "--payload", help="第一阶段参数 JSON 文件"),
    out: Path = typer.Option(Path("calculator-draft"), "--out", help="草稿包输出目录"),
) -> None:
```

Then replace the body of `draft_command()` with:

```python
    """根据第一阶段参数生成试算草稿包。"""
    payload_data = read_json_file(payload) if payload else None
    query_payload = build_query_payload(
        country=country,
        platforms=platform,
        hs_code_id=hs_code_id,
        department=department,
        reference=reference,
        reference_value=reference_value,
        payload=payload_data,
        request_t=request_t,
    )
    if debug_request:
        typer.echo("第一步：调用 /calculator/newProduct/queryCost 获取表单默认参数")
        typer.echo("请求参数：")
        typer.echo(json.dumps(query_payload, ensure_ascii=False, indent=2))
    response = CalculatorClient().query_cost(query_payload)
    data = _extract_response_data(response, "生成草稿")
    draft_path = create_draft_package(data, out)
    if debug_request:
        typer.echo("queryCost 调用成功，已根据后端默认参数生成草稿。")
    typer.echo(f"已生成试算草稿：{draft_path}")
    typer.echo("")
    typer.echo(build_summary_text(read_json_file(draft_path)))
    typer.echo("")
    typer.echo(f"下一步：opscli calculator validate {draft_path}")
```

- [ ] **Step 5: Run focused CLI tests to verify pass**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator/test_cli.py::test_draft_command_creates_package tests/calculator/test_cli.py::test_draft_command_prints_query_cost_debug_payload -v
```

Expected: 2 tests pass.

---

### Task 3: Changelog and calculator regression

**Files:**
- Modify: `docs/change-log-pending.md`
- Test: `tests/calculator/test_draft.py`, `tests/calculator/test_cli.py`, `tests/calculator/test_client.py`, `tests/calculator/test_fields.py`

**Interfaces:**
- Consumes: Task 1 payload behavior and Task 2 CLI behavior.
- Produces: Pending changelog entry documenting the user-visible `draft` debug enhancement.

- [ ] **Step 1: Run full calculator regression**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator -v
```

Expected: all calculator tests pass. With the tests in this plan, the expected count is 31 passed.

- [ ] **Step 2: Update pending changelog**

Insert this section at the top of `docs/change-log-pending.md`, immediately after `# 待归档变更记录` and a blank line. If the final pytest count differs from 31, use the exact count from Step 1 in the `验证结果` line.

```markdown
## 2026-07-02 calculator - queryCost 调试可见性

**变更原因**：Web 端新品计算器第一步点击“确定”后会调用 `/calculator/newProduct/queryCost` 获取表单默认参数；本地 CLI 已在 `draft` 流程中调用该接口，但默认输出没有展示接口路径和请求参数，不便与浏览器 Network 并行调试。
**改动点**：`opscli calculator draft` 新增 `--debug-request` 打印第一阶段 `queryCost` 路径和 JSON 请求参数，新增 `--request-t` 用于显式透传 Web 请求 `_t` 字段；`build_query_payload()` 支持从 CLI 参数注入 `_t` 并保留 `--payload` 文件中的 `_t`；默认不传调试参数时现有草稿包生成流程保持不变。
**验证结果**：`.venv/Scripts/python.exe -m pytest tests/calculator -v` 通过，31 passed。
**影响范围**：仅影响 `opscli calculator draft` 的调试输出和可选 `_t` 透传；不新增独立命令，不改变默认请求参数、不改变草稿包结构。
**回滚方式**：回退 `opscli/calculator/models.py`、`opscli/calculator/cli.py`、`tests/calculator/test_draft.py`、`tests/calculator/test_cli.py` 和本条变更记录。
---
```

- [ ] **Step 3: Verify root CLI help exposes the enhanced command without breaking registration**

Run:

```bash
.venv/Scripts/python.exe -m opscli.cli calculator draft --help
```

Expected: command exits successfully and help output includes `--debug-request` and `--request-t`.

- [ ] **Step 4: Run final targeted regression after changelog edit**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/calculator -v
```

Expected: all calculator tests pass. Report the exact passed count and duration from pytest in the final response.

- [ ] **Step 5: Inspect git diff without committing**

Run:

```bash
git diff -- opscli/calculator/models.py opscli/calculator/cli.py tests/calculator/test_draft.py tests/calculator/test_cli.py docs/change-log-pending.md docs/superpowers/specs/2026-07-02-calculator-query-cost-debug-design.md docs/superpowers/plans/2026-07-02-calculator-query-cost-debug.md
```

Expected: diff contains only the approved queryCost debug enhancement, the approved design spec, this implementation plan, and the pending changelog entry.

---

## Self-Review

- Spec coverage: Task 1 covers optional `_t` and payload-file preservation; Task 2 covers `--debug-request`, `--request-t`, no new command, and no default full response printing; Task 3 covers changelog and verification.
- Scope check: This is a single focused enhancement to the existing calculator draft flow. It does not introduce MCP tools, a new `query-cost` command, or a web UI.
- Type consistency: The only signature change is `build_query_payload(..., request_t: int | None = None) -> dict[str, Any]`; existing callers remain valid because `request_t` has a default.
- Default behavior: Existing `draft` calls do not include `_t` unless the caller uses `--request-t` or provides `_t` in `--payload`.
