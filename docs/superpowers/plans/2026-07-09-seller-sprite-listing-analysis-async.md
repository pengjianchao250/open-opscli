# SellerSprite Listing Analysis Async Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 SellerSprite `listing-analysis` 场景，并新增专用 submit/status/result 三段式入口，避免 3 分钟以上 AI 结果等待阻塞公开 CLI/MCP 调用。

**Architecture:** 先恢复被 `4d6a168` 隐藏的场景注册与测试，再在 browser-route 中补齐 `POST_QUERY`、页面输入 ASIN 和点击查询按钮。公开入口不暴露通用 `seller_sprite_start`，而是新增 listing-analysis 专用 MCP/CLI 方法；submit 只负责真人化触发并返回本地 `job_id` 与 SellerSprite `task_id`，status/result 再按 `job_id` 续查远端 AI task。

**Tech Stack:** Python 3.10、Typer、FastMCP、httpx、Playwright/Patchright、SQLite、pytest。

## Global Constraints

- 代码注释必须使用中文，公开类/方法和重要业务逻辑必须有中文说明。
- 终端输出字符必须 GBK 兼容，不能新增 emoji 或 Dingbats 符号。
- Skill 脚本不能直连后端 API，正式 CLI 仍通过远端 MCP 工具转发。
- 不开放通用 `seller_sprite_start`，只开放 listing-analysis 专用三段式业务入口。
- 不引入新常驻 worker 或新服务进程。
- 不自动提交 git commit；用户明确要求后再提交。
- 修改代码文件后必须追加 `docs/change-log-pending.md` 变更记录。

---

### Task 1: 恢复 listing-analysis 场景注册和历史测试

**Files:**
- Modify: `opscli/seller_sprite/api/scenarios.py`
- Modify: `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`
- Modify: `tests/seller_sprite/test_payloads.py`
- Modify: `tests/seller_sprite/test_api_manager.py`

**Interfaces:**
- Consumes: `make_listing_analysis_payload(input_data: dict[str, Any]) -> dict[str, Any]` from `opscli/seller_sprite/api/payloads.py`.
- Produces: `get_scenario("listing-analysis")` returns a `SellerSpriteScenario` with `method="POST_QUERY"` and `task_result_endpoint="/v3/api/ai-analysis/task/{task_id}"`.

- [ ] **Step 1: Restore the hidden commit without committing**

Run:

```bash
git revert --no-commit 4d6a168
```

Expected: working tree changes exactly the four files changed by `4d6a168`, with no commit created.

If revert conflicts, manually apply these semantic changes:

```python
from opscli.seller_sprite.api.payloads import (
    build_referer,
    make_competitor_payload,
    make_keyword_miner_payload,
    make_keyword_reverse_payload,
    make_listing_analysis_payload,
    make_market_research_payload,
    make_product_research_payload,
    make_traffic_source_payload,
)
```

```python
"listing-analysis": SellerSpriteScenario(
    scenario_id="listing-analysis",
    title="Listing Analysis",
    endpoint="/v3/api/ai-workflow/listing-analysis",
    method="POST_QUERY",
    task_result_endpoint="/v3/api/ai-analysis/task/{task_id}",
    required_params=("asin",),
    payload_builder=make_listing_analysis_payload,
),
```

- [ ] **Step 2: Verify payload/scenario test is restored**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_payloads.py -q
```

Expected: PASS, including a restored test that asserts:

```python
scenario = get_scenario("listing-analysis")
payload = scenario.build_payload(
    params={"asin": "b0test"},
    site="US",
    period="30d",
    page_size=100,
)
assert payload == {"asin": "B0TEST", "station": "GLOBAL"}
assert scenario.method == "POST_QUERY"
assert scenario.task_result_endpoint == "/v3/api/ai-analysis/task/{task_id}"
```

- [ ] **Step 3: Verify API manager historical listing-analysis coverage**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_api_manager.py -k "listing_analysis" -q
```

Expected: restored historical test passes or fails only because later tasks intentionally change browser-route submit behavior. If it fails for changed semantics, update it in Task 3 after adding submit-row extraction.

---

### Task 2: Add browser-route POST_QUERY and listing-analysis page interaction

**Files:**
- Modify: `opscli/seller_sprite/browser_route/worker.py`
- Modify: `tests/seller_sprite/test_browser_route_worker.py`

**Interfaces:**
- Consumes: `BrowserRouteRequest.scenario`, `BrowserRouteRequest.method`, `BrowserRouteRequest.payload`.
- Produces: browser-route can submit `POST_QUERY` as `POST <endpoint>?asin=...&station=...` with body `{}`.
- Produces: `_trigger_request(...)` uses listing-analysis-specific page input/click when `request.scenario == "listing-analysis"`.

- [ ] **Step 1: Write failing test for POST_QUERY context request**

Add to `tests/seller_sprite/test_browser_route_worker.py`:

```python
class FakeContextRequest:
    def __init__(self):
        self.post_calls = []

    async def post(self, url, **kwargs):
        self.post_calls.append({"url": url, "kwargs": kwargs})
        return SimpleNamespace(status=200)


class FakeContextPage:
    def __init__(self):
        self.url = "https://www.sellersprite.com/v3/listing-analysis?asin=B0TEST&station=GLOBAL"
        self.context = SimpleNamespace(request=FakeContextRequest())


def test_post_query_context_request_uses_query_and_empty_json_body():
    page = FakeContextPage()

    response = _run(
        worker_module._request_with_browser_context(
            page,
            endpoint="/v3/api/ai-workflow/listing-analysis",
            method="POST_QUERY",
            payload={"asin": "B0TEST", "station": "GLOBAL"},
        )
    )

    assert response.status == 200
    call = page.context.request.post_calls[0]
    assert call["url"] == "https://www.sellersprite.com/v3/api/ai-workflow/listing-analysis?asin=B0TEST&station=GLOBAL"
    assert call["kwargs"]["data"] == "{}"
    assert call["kwargs"]["headers"]["Content-Type"] == "application/json;charset=UTF-8"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py::test_post_query_context_request_uses_query_and_empty_json_body -q
```

Expected: FAIL because `POST_QUERY` currently posts payload JSON to the absolute endpoint without query params.

- [ ] **Step 3: Implement POST_QUERY in route handler and context fallback**

In `opscli/seller_sprite/browser_route/worker.py`, update `_execute_route_fetch._handle()` before the generic JSON branch:

```python
            if normalized_method == "POST_QUERY":
                headers["content-type"] = "application/json;charset=UTF-8"
                await route.continue_(
                    url=_url_with_query(endpoint, payload),
                    method="POST",
                    headers=headers,
                    post_data="{}",
                )
                return
```

Update `_context_request_headers()` to keep JSON headers for `POST_QUERY` through the existing `elif method != "GET"` branch.

Update `_request_with_browser_context()` before the generic JSON POST:

```python
        if method == "POST_QUERY":
            return await page.context.request.post(
                _url_with_query(endpoint, payload),
                headers=headers,
                data="{}",
                timeout=DEFAULT_TIMEOUT_MS,
                fail_on_status_code=False,
            )
```

- [ ] **Step 4: Run the POST_QUERY test**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py::test_post_query_context_request_uses_query_and_empty_json_body -q
```

Expected: PASS.

- [ ] **Step 5: Write failing test for listing-analysis input/click trigger**

Add fake locator helpers and test:

```python
class FakeListingLocator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind
        self.first = self

    async def count(self):
        return 1

    async def is_visible(self, **kwargs):
        return True

    async def fill(self, value):
        self.page.fills.append({"kind": self.kind, "value": value})

    async def click(self, **kwargs):
        self.page.clicks.append(self.kind)


class FakeListingPage:
    def __init__(self):
        self.fills = []
        self.clicks = []

    def locator(self, selector):
        if "input" in selector:
            return FakeListingLocator(self, "asin")
        return FakeListingLocator(self, "submit")


def test_listing_analysis_trigger_fills_asin_and_clicks_submit():
    page = FakeListingPage()

    clicked = _run(
        worker_module._trigger_listing_analysis_query(
            page,
            {"asin": "B0TEST123", "station": "GLOBAL"},
        )
    )

    assert clicked is True
    assert page.fills == [{"kind": "asin", "value": "B0TEST123"}]
    assert page.clicks == ["submit"]
```

- [ ] **Step 6: Run the failing listing-analysis trigger test**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py::test_listing_analysis_trigger_fills_asin_and_clicks_submit -q
```

Expected: FAIL because `_trigger_listing_analysis_query` does not exist.

- [ ] **Step 7: Implement listing-analysis input/click helper**

Add helpers in `opscli/seller_sprite/browser_route/worker.py` near `_click_query_button()`:

```python
async def _trigger_listing_analysis_query(page, payload: dict[str, Any]) -> bool:
    """在 Listing Analysis 页面填写 ASIN 并点击查询按钮。"""
    asin = str(payload.get("asin") or "").strip().upper()
    if not asin:
        return False
    input_box = await _first_visible_page_locator(
        page,
        [
            "input[placeholder*='ASIN']:visible:not([readonly]):not([disabled])",
            "input[placeholder*='asin']:visible:not([readonly]):not([disabled])",
            "input[type='text']:visible:not([readonly]):not([disabled])",
        ],
    )
    if input_box is None:
        return False
    await input_box.fill(asin)
    button = await _first_visible_page_locator(
        page,
        [
            "button:visible:has-text('立即分析')",
            "[role='button']:visible:has-text('立即分析')",
            "button:visible:has-text('立即查询')",
            "[role='button']:visible:has-text('立即查询')",
            ".el-button:visible:has-text('立即分析')",
            ".el-button:visible:has-text('立即查询')",
            ".ant-btn:visible:has-text('立即分析')",
            ".ant-btn:visible:has-text('立即查询')",
        ],
    )
    if button is None:
        return False
    await button.click(timeout=5000)
    return True


async def _first_visible_page_locator(page, selectors: list[str]):
    """返回页面中第一个可见 locator。"""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible(timeout=800):
                return locator
        except Exception:
            continue
    return None
```

- [ ] **Step 8: Wire listing-analysis helper into `_trigger_request()` and avoid duplicate fallback**

In `_trigger_request()`, replace the generic click section with a branch:

```python
            listing_analysis_clicked = False
            if request and request.scenario == "listing-analysis":
                listing_analysis_clicked = await _trigger_listing_analysis_query(page, payload)
                clicked = listing_analysis_clicked
            else:
                clicked = await _click_query_button(page)
            _record_timing(..., clicked=clicked)
            if not clicked:
                raise _NoQueryButtonError()
```

In the `except` block, before `_request_with_browser_context(...)`, add:

```python
        if request and request.scenario == "listing-analysis" and "listing_analysis_clicked" in locals() and listing_analysis_clicked:
            raise SellerSpriteApiError(
                "卖家精灵 Listing Analysis 已点击提交但未捕获接口响应，请稍后用页面或任务记录确认，避免重复提交",
                response_excerpt=f"endpoint={endpoint}",
                api_code="ERR_LISTING_ANALYSIS_RESPONSE_MISSED",
                api_message="已完成页面点击，不再自动 fallback 重复创建 AI 任务。",
            ) from exc
```

- [ ] **Step 9: Run browser-route focused tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q
```

Expected: PASS.

---

### Task 3: Extract taskId submit rows for listing-analysis

**Files:**
- Modify: `opscli/seller_sprite/services/api_manager.py`
- Modify: `tests/seller_sprite/test_api_manager.py`

**Interfaces:**
- Consumes: SellerSprite submit response shape `{"data": {"taskId": "...", "taskStatus": "..."}}`.
- Produces: `_extract_items(response)` returns one row for submit-only AI task responses.

- [ ] **Step 1: Write failing test for submit-only taskId extraction**

Add to `tests/seller_sprite/test_api_manager.py`:

```python
def test_extract_items_returns_listing_analysis_submit_task_row():
    from opscli.seller_sprite.services import api_manager

    rows = api_manager._extract_items(
        {
            "code": "OK",
            "data": {
                "taskId": "task-listing-1",
                "taskStatus": "PENDING",
                "asin": "B0TEST123",
                "station": "GLOBAL",
            },
        }
    )

    assert rows == [
        {
            "taskId": "task-listing-1",
            "taskStatus": "PENDING",
            "asin": "B0TEST123",
            "station": "GLOBAL",
            "contentReady": False,
        }
    ]
```

- [ ] **Step 2: Run failing extraction test**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_api_manager.py::test_extract_items_returns_listing_analysis_submit_task_row -q
```

Expected: FAIL because `_extract_items()` currently only recognizes AI content/htmlContent rows.

- [ ] **Step 3: Implement submit-row extraction**

In `_extract_items()`, before returning empty rows for dict data, add:

```python
    task_id = data.get("taskId") or data.get("task_id")
    if task_id:
        return [
            {
                "taskId": str(task_id),
                "taskStatus": data.get("taskStatus") or data.get("status"),
                "asin": data.get("asin"),
                "station": data.get("station"),
                "contentReady": bool(data.get("content") or data.get("htmlContent")),
            }
        ]
```

Keep the existing full-content extraction behavior for completed task responses.

- [ ] **Step 4: Run API manager listing-analysis tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_api_manager.py -k "listing_analysis or extract_items_returns_listing_analysis_submit_task_row" -q
```

Expected: PASS.

---

### Task 4: Add listing-analysis MCP submit/status/result tools

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Modify: `tests/mcp/test_seller_sprite_tools.py`
- Modify: `tests/mcp/test_tools.py`

**Interfaces:**
- Produces: `seller_sprite_listing_analysis_submit(asin: str, station: str = "GLOBAL", site: str = "US", export_format: str = "json", job_id: str | None = None, session_id: str | None = None, jwt: str | None = None) -> dict`.
- Produces: `seller_sprite_listing_analysis_status(job_id: str, session_id: str | None = None, jwt: str | None = None) -> dict`.
- Produces: `seller_sprite_listing_analysis_result(job_id: str, export_format: str = "json", session_id: str | None = None, jwt: str | None = None) -> dict`.

- [ ] **Step 1: Write failing registration test**

Update `tests/mcp/test_tools.py::test_seller_sprite_internal_controls_are_not_exposed` to assert:

```python
    assert "seller_sprite_listing_analysis_submit" in names
    assert "seller_sprite_listing_analysis_status" in names
    assert "seller_sprite_listing_analysis_result" in names
    assert "seller_sprite_start" not in names
```

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/mcp/test_tools.py::test_seller_sprite_internal_controls_are_not_exposed -q
```

Expected: FAIL because new tools are not registered.

- [ ] **Step 2: Write failing submit test**

Add to `tests/mcp/test_seller_sprite_tools.py`:

```python
def test_listing_analysis_submit_enqueues_without_run_wait(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: DummyScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_build_mcp_job_id", lambda request, site, period: "listing-job-1")
    monkeypatch.setattr(seller_sprite_tools, "_get_auth_pair", lambda system, session_id, jwt: ("sid", "jwt"))
    monkeypatch.setattr(seller_sprite_tools, "_get_current_mcp_user_email", lambda: "mcp-user@example.com")
    monkeypatch.setattr(seller_sprite_tools, "_get_task_queue_store", lambda: store)
    DummyScheduler.enqueue_calls = 0

    result = _run(
        seller_sprite_tools.seller_sprite_listing_analysis_submit(
            asin="b0test123",
            station="global",
            site="US",
            export_format="json",
        )
    )

    assert result["success"] is True
    assert result["data"]["job_id"] == "listing-job-1"
    assert result["data"]["state"] == "queued"
    assert DummyScheduler.last_request.scenario == "listing-analysis"
    assert DummyScheduler.last_request.params == {"asin": "B0TEST123", "station": "GLOBAL"}
    assert DummyScheduler.last_request.mode == "browser-route"
    assert DummyScheduler.enqueue_calls == 1
```

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/mcp/test_seller_sprite_tools.py::test_listing_analysis_submit_enqueues_without_run_wait -q
```

Expected: FAIL because `seller_sprite_listing_analysis_submit` does not exist.

- [ ] **Step 3: Implement submit tool**

Add helper and tool in `opscli/mcp/tools/seller_sprite.py`:

```python
def _extract_listing_analysis_task_id(status: dict[str, Any]) -> str | None:
    """从任务状态或结果行中提取 SellerSprite AI taskId。"""
    for row in status.get("data") or status.get("rows") or []:
        task_id = row.get("taskId") or row.get("task_id")
        if task_id:
            return str(task_id)
    response = ((status.get("raw") or {}).get("response") or {}) if isinstance(status.get("raw"), dict) else {}
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        task_id = data.get("taskId") or data.get("task_id")
        if task_id:
            return str(task_id)
    return None


async def seller_sprite_listing_analysis_submit(...):
    """提交 Listing Analysis AI 任务并立即返回本地 job_id。"""
```

Implementation details:

```python
parsed_asin = str(asin or "").strip().upper()
parsed_station = str(station or "GLOBAL").strip().upper()
if not parsed_asin:
    return _err(ValueError("listing-analysis 必须提供 asin"), tool="MCP → seller_sprite_listing_analysis_submit(...)")
raw_request = _build_request(
    scenario="listing-analysis",
    params={"asin": parsed_asin, "station": parsed_station},
    site=site,
    period="30d",
    page_size=1,
    export_format=export_format,
    page_prepare=page_prepare,
    task_interval_seconds=task_interval_seconds,
    cooldown_seconds=cooldown_seconds,
    output_dir=output_dir,
    job_id=job_id,
)
request = _prepare_request_for_enqueue(raw_request)
store.create_mcp_run(request, user_email)
queued_status = await scheduler.enqueue(request)
return _ok(queued_status)
```

Do not call `_wait_for_seller_sprite_run_result()`.

- [ ] **Step 4: Register new tools without exposing `seller_sprite_start`**

Append new functions to `_ALL_TOOLS`:

```python
_ALL_TOOLS = [
    seller_sprite_spec_must_read,
    seller_sprite_scenarios,
    seller_sprite_quota_status,
    seller_sprite_run,
    seller_sprite_listing_analysis_submit,
    seller_sprite_listing_analysis_status,
    seller_sprite_listing_analysis_result,
    seller_sprite_job_status,
    seller_sprite_export,
]
```

- [ ] **Step 5: Add status/result tool skeleton tests**

Add tests that use monkeypatching to avoid network:

```python
def test_listing_analysis_status_returns_local_queue_state(monkeypatch):
    class LocalOnlyScheduler:
        def job_status(self, job_id):
            return {"job_id": job_id, "scenario": "listing-analysis", "state": "running", "stage": "running"}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: LocalOnlyScheduler())

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_status("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["state"] == "running"
    assert result["data"]["ready"] is False
```

```python
def test_listing_analysis_result_reports_not_ready(monkeypatch):
    class PendingScheduler:
        def job_status(self, job_id):
            return {
                "job_id": job_id,
                "scenario": "listing-analysis",
                "state": "succeeded",
                "data": [{"taskId": "task-1", "contentReady": False}],
            }

    async def fake_remote_status(*args, **kwargs):
        return {"task_id": "task-1", "ready": False, "remote": {"data": {"taskStatus": "RUNNING"}}}

    monkeypatch.setattr(seller_sprite_tools, "_get_task_scheduler", lambda **kwargs: PendingScheduler())
    monkeypatch.setattr(seller_sprite_tools, "_fetch_listing_analysis_remote_status", fake_remote_status)

    result = _run(seller_sprite_tools.seller_sprite_listing_analysis_result("listing-job-1"))

    assert result["success"] is True
    assert result["data"]["ready"] is False
    assert result["data"]["task_id"] == "task-1"
```

- [ ] **Step 6: Implement status/result minimum behavior**

Add `_fetch_listing_analysis_remote_status(...)` using existing `SellerSpriteApiClient`:

```python
async def _fetch_listing_analysis_remote_status(*, task_id: str, session_id: str | None, jwt: str | None) -> dict[str, Any]:
    """单次读取 Listing Analysis 远端 AI 任务状态。"""
    from opscli.seller_sprite.services import SellerSpriteApiManager
    from opscli.seller_sprite.api.client import SellerSpriteApiClient

    manager = SellerSpriteApiManager(jwt=jwt, session_id=session_id)
    account = manager.account_provider.get_default()
    async with SellerSpriteApiClient(account=account) as client:
        endpoint = f"/v3/api/ai-analysis/task/{task_id}"
        response = await client.get_json(endpoint, {}, referer="https://www.sellersprite.com/v3/listing-analysis")
    data = response.get("data") if isinstance(response, dict) else {}
    ready = bool(isinstance(data, dict) and (data.get("content") or data.get("htmlContent")))
    failed = bool(isinstance(data, dict) and str(data.get("taskStatus") or data.get("status") or "").lower() in {"failed", "fail", "error", "canceled", "cancelled"})
    return {"task_id": task_id, "ready": ready, "failed": failed, "remote": response}
```

Implement `seller_sprite_listing_analysis_status`:

```python
status = _get_task_scheduler().job_status(job_id)
task_id = _extract_listing_analysis_task_id(status)
if not task_id:
    status["ready"] = False
    return _ok(status)
remote = await _fetch_listing_analysis_remote_status(task_id=task_id, session_id=sid, jwt=jw)
return _ok({**status, **remote})
```

Implement `seller_sprite_listing_analysis_result` similarly. If `ready` is false, return `_ok({**status, **remote, "ready": False})`. If ready, return `_ok({**status, **remote, "ready": True})`. Keep export finalization minimal in this task; export persistence can be enhanced later if needed.

- [ ] **Step 7: Run MCP tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/mcp/test_seller_sprite_tools.py tests/mcp/test_tools.py -q
```

Expected: PASS.

---

### Task 5: Add public CLI and remote adapter methods

**Files:**
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Modify: `opscli/seller_sprite/cli.py`
- Modify: `tests/seller_sprite/test_remote_adapter.py`
- Modify: `tests/seller_sprite/test_cli_split.py`

**Interfaces:**
- Produces: `SellerSpriteRemoteAdapter.listing_analysis_submit(...)` maps to `seller_sprite_listing_analysis_submit`.
- Produces: `SellerSpriteRemoteAdapter.listing_analysis_status(job_id: str)` maps to `seller_sprite_listing_analysis_status`.
- Produces: `SellerSpriteRemoteAdapter.listing_analysis_result(job_id: str, export_format: str)` maps to `seller_sprite_listing_analysis_result`.
- Produces CLI commands: `listing-analysis-submit`, `listing-analysis-status`, `listing-analysis-result`.

- [ ] **Step 1: Write failing remote adapter test**

Add to `tests/seller_sprite/test_remote_adapter.py`:

```python
def test_remote_adapter_maps_listing_analysis_tools():
    config_client = FakeConfigClient()
    created_clients = []

    def make_remote_client(url: str):
        client = FakeRemoteClient(url)
        created_clients.append(client)
        return client

    adapter = SellerSpriteRemoteAdapter(config_client=config_client, remote_client_factory=make_remote_client)

    submit = adapter.listing_analysis_submit(asin="B0TEST123", station="GLOBAL", site="US", export_format="json", job_id=None, output_dir=None)
    status = adapter.listing_analysis_status("listing-job-1")
    result = adapter.listing_analysis_result("listing-job-1", export_format="json")

    assert submit["data"]["tool"] == "seller_sprite_listing_analysis_submit"
    assert submit["data"]["arguments"]["asin"] == "B0TEST123"
    assert submit["data"]["arguments"]["session_id"] == "sid-cli-123"
    assert status["data"]["tool"] == "seller_sprite_listing_analysis_status"
    assert result["data"]["tool"] == "seller_sprite_listing_analysis_result"
```

- [ ] **Step 2: Implement remote adapter methods**

Add methods to `SellerSpriteRemoteAdapter`:

```python
    def listing_analysis_submit(...):
        """提交 Listing Analysis 远端异步任务。"""
        session_id = self.auth_client.get_session("ops")
        return self.call_tool("seller_sprite_listing_analysis_submit", {...})
```

```python
    def listing_analysis_status(self, job_id: str) -> dict[str, Any]:
        """查询 Listing Analysis 远端任务状态。"""
        return self.call_tool("seller_sprite_listing_analysis_status", {"job_id": job_id})
```

```python
    def listing_analysis_result(self, job_id: str, *, export_format: str) -> dict[str, Any]:
        """读取 Listing Analysis 远端任务结果。"""
        return self.call_tool("seller_sprite_listing_analysis_result", {"job_id": job_id, "export_format": export_format})
```

- [ ] **Step 3: Write failing CLI test**

Add to `tests/seller_sprite/test_cli_split.py`:

```python
def test_public_seller_sprite_listing_analysis_commands_use_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def listing_analysis_submit(self, **kwargs):
            captured["submit"] = kwargs
            return {"success": True, "data": {"job_id": "listing-job-1"}}

        def listing_analysis_status(self, job_id):
            captured["status"] = job_id
            return {"success": True, "data": {"job_id": job_id, "ready": False}}

        def listing_analysis_result(self, job_id, *, export_format):
            captured["result"] = {"job_id": job_id, "export_format": export_format}
            return {"success": True, "data": {"job_id": job_id, "ready": True}}

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    submit = runner.invoke(app, ["seller-sprite", "listing-analysis-submit", "--asin", "B0TEST123", "--station", "GLOBAL", "--site", "US"])
    status = runner.invoke(app, ["seller-sprite", "listing-analysis-status", "listing-job-1"])
    result = runner.invoke(app, ["seller-sprite", "listing-analysis-result", "listing-job-1", "--export-format", "json"])

    assert submit.exit_code == 0
    assert status.exit_code == 0
    assert result.exit_code == 0
    assert captured["submit"]["asin"] == "B0TEST123"
    assert captured["status"] == "listing-job-1"
    assert captured["result"] == {"job_id": "listing-job-1", "export_format": "json"}
```

- [ ] **Step 4: Implement CLI commands**

Add three Typer commands to `opscli/seller_sprite/cli.py`:

```python
@app.command("listing-analysis-submit")
def listing_analysis_submit(...):
    """提交 Listing Analysis 任务并返回 job_id。"""
```

```python
@app.command("listing-analysis-status")
def listing_analysis_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Listing Analysis 任务状态。"""
```

```python
@app.command("listing-analysis-result")
def listing_analysis_result(...):
    """读取 Listing Analysis 任务结果。"""
```

Each command should call the matching adapter method and print JSON with `ensure_ascii=False, indent=2`.

- [ ] **Step 5: Run CLI/adapter tests**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py -q
```

Expected: PASS.

---

### Task 6: Update docs, change log, and run focused regression

**Files:**
- Modify: `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- Modify: `docs/change-log-pending.md`

**Interfaces:**
- Produces: user-facing docs that describe `listing-analysis-submit/status/result` as the recommended flow.
- Produces: change log entry for this code change.

- [ ] **Step 1: Update Skill docs**

Add a short workflow section to `SKILL.md` and `SKILL_MCP.md`:

```markdown
### Listing Analysis 三段式

`listing-analysis` 结果通常需要 3 分钟以上生成。不要用同步 `seller_sprite_run` 等完整结果；优先使用三段式：

1. `listing-analysis-submit` / `seller_sprite_listing_analysis_submit` 提交 ASIN 并获取 `job_id`。
2. 等待约 3 分钟后用 `listing-analysis-status` / `seller_sprite_listing_analysis_status` 查看是否 ready。
3. ready 后用 `listing-analysis-result` / `seller_sprite_listing_analysis_result` 获取最终内容。
```

- [ ] **Step 2: Append change log entry**

Append to `docs/change-log-pending.md`:

```markdown
## 2026-07-09 seller_sprite - 恢复 Listing Analysis 三段式异步入口

**变更原因**：SellerSprite Listing Analysis 服务通常 3 分钟以上才出 AI 结果，同步等待会拖慢 CLI/MCP 调用；同时 master 中曾隐藏该场景，需要恢复并改为更稳的 submit/status/result 链路。
**改动点**：恢复 `listing-analysis` 场景注册和参数手册；browser-route 增加 `POST_QUERY`、ASIN 输入和点击查询支持；新增 Listing Analysis 专用 MCP 与 CLI 三段式入口；补充相关测试。
**验证结果**：执行聚焦 SellerSprite/MCP/CLI 测试，结果以本次实际命令输出为准。
**影响范围**：影响 SellerSprite `listing-analysis` 场景、公开 MCP 工具列表和 `opscli seller-sprite` 正式命令；不开放通用 `seller_sprite_start`，其他卖家精灵场景保持原入口。
**回滚方式**：回退本次修改的 SellerSprite 场景、browser-route、MCP 工具、CLI/adapter、Skill 文档、测试和本条变更记录；必要时重新应用 `4d6a168` 的隐藏逻辑。
---
```

- [ ] **Step 3: Run focused regression**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_payloads.py tests/seller_sprite/test_api_manager.py -q
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q
.venv/Scripts/python.exe -m pytest tests/mcp/test_seller_sprite_tools.py tests/mcp/test_tools.py -q
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py -q
```

Expected: PASS. If unrelated failures appear, record exact failing tests and explain why they are unrelated before stopping.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only planned files changed; no generated output files or secrets.

---

## Self-Review

- Spec coverage: Task 1 restores hidden listing-analysis; Task 2 implements human-like input/click and `POST_QUERY`; Task 3 makes submit responses useful; Task 4 adds MCP three-step tools; Task 5 adds CLI/adapter; Task 6 covers docs/change-log/tests.
- Placeholder scan: no `TBD` or open-ended implementation placeholders remain; each task has file paths, snippets, and commands.
- Type consistency: new public MCP and adapter names use `listing_analysis_submit/status/result` in Python and `listing-analysis-submit/status/result` in CLI; existing `seller_sprite_start` remains unregistered.
