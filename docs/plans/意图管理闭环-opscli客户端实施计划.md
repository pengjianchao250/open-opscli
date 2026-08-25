# 意图管理闭环 · opscli 客户端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 catalog/intent 接口并补齐匹配器缺口，让每次意图匹配上报服务端、每次查询执行携带意图归因。

**Architecture:** 内核 `intent_matcher.py` 补业务约束透传与 embedded_intent 解析两个缺口后，取消 CLI/MCP 四处注册注释恢复接口；`QueryManager.intent_match()` 匹配后 fire-and-forget 上报拿回 `match_record_id`；`query run/simple` 新增三个归因参数经 HTTP Header 透传；Skill 降级路径经 plan 文件把 `intent_code` 带到执行段。

**Tech Stack:** Python 3.10+、typer、httpx、pytest + respx。

**Spec:** `docs/plans/意图管理闭环-总体规划.md`（契约 1/2 的权威定义；本计划实现客户端侧）

## Global Constraints

- 工作目录：`/Users/mask/python3/opscli`，测试用 `.venv` 环境 `python3 -m pytest`
- 遵循项目 CLAUDE.md 全部铁律，重点：铁律17（中文注释，重要逻辑说明"为什么"）、铁律18（每个 Task 提交前向 `docs/change-log-pending.md` 追加变更记录）、铁律23（终端输出 GBK 安全）、铁律8（测试不碰真实网络与 Keychain，HTTP 一律 respx mock）
- 上报失败必须静默（不阻塞、不打印错误堆栈），上报请求超时固定 5 秒
- `tests/skills/` 存在既有基线失败（test_cli 1 / test_dashboard_skills 2 / test_manager 3 / test_ops_feedback_template 1 / test_ops_methods_card_xlsx_preview 1），回归时对照基线判断，勿误判为本计划引入
- Skill 模板版本号随文档改动 1.3.20 → 1.3.21（`SKILL.md` 与 `data/VERSION.json` 同步）

---

### Task B1: 匹配器补缺口 A——业务约束透传

**Files:**
- Modify: `opscli/query/services/intent_matcher.py:112-137`（`_intent_constraints`）
- Test: `tests/query/test_intent_matcher_guardrails.py`（新建）

**Interfaces:**
- Produces: `match_catalog_intents()` 的 `candidates[].intent_constraints` 新增键 `hard_constraints: list[str]`、`avoid_when: list[str]`、`clarify_when: list[str]`（Task B3 恢复的 CLI/MCP 输出、Skill 文档消费）

- [ ] **Step 1: 编写失败测试**

```python
"""意图匹配器护栏透传回归：catalog 的业务约束不许在匹配层被静默丢弃。

为什么需要：catalog 里 36/41 条意图带 hard_constraints（如"库存快照字段只能用于
明细表"），此前 _intent_constraints 未透传这三个键，Agent 经 query intent 拿到的
候选会丢失全部防错数护栏——同一份数据走 local_fallback.py 却是带的，两条路径不一致。
"""
from opscli.query.services.intent_matcher import match_catalog_intents


def _catalog_with_guardrails() -> dict:
    return {
        "version": "v1.0.0",
        "intent_count": 1,
        "intents": [{
            "intent_code": "ops_comprehensive_monitoring",
            "intent_name": "综合运营监控",
            "table_id": 1,
            "dataset_alias": "ds_d35ac6f3910c",
            "dataset_name": "即时综合数据集",
            "keywords": ["经营大盘"],
            "use_cases": [],
            "scenario_description": "",
            "priority": 100,
            "hard_constraints": ["总库存属于库存快照字段，只能用于明细表或无聚合过滤条件"],
            "avoid_when": ["亚马逊广告活动明细深挖"],
            "clarify_when": ["用户只问单一业务域时需判断是否转专项数据集"],
        }],
    }


def test_intent_constraints_carry_guardrails():
    """hard_constraints / avoid_when / clarify_when 必须原样出现在候选约束里。"""
    result = match_catalog_intents(_catalog_with_guardrails(), "经营大盘")
    constraints = result["candidates"][0]["intent_constraints"]
    assert constraints["hard_constraints"] == ["总库存属于库存快照字段，只能用于明细表或无聚合过滤条件"]
    assert constraints["avoid_when"] == ["亚马逊广告活动明细深挖"]
    assert constraints["clarify_when"] == ["用户只问单一业务域时需判断是否转专项数据集"]


def test_intent_constraints_default_guardrails_to_empty_lists():
    """catalog 缺这三个键时给空列表，不得抛 KeyError。"""
    catalog = _catalog_with_guardrails()
    for key in ("hard_constraints", "avoid_when", "clarify_when"):
        del catalog["intents"][0][key]
    result = match_catalog_intents(catalog, "经营大盘")
    constraints = result["candidates"][0]["intent_constraints"]
    assert constraints["hard_constraints"] == []
    assert constraints["avoid_when"] == []
    assert constraints["clarify_when"] == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/query/test_intent_matcher_guardrails.py -v`
Expected: FAIL，KeyError `'hard_constraints'`

- [ ] **Step 3: 实现**

`intent_matcher.py` 的 `_intent_constraints()` 中，`"select_columns"` 行之后追加：

```python
        # 业务约束护栏：catalog 里未经人工复核的约束也必须原样透传给 Agent，
        # 丢在匹配层等于把防错数护栏静默吞掉（local_fallback 路径一直是带的，两侧必须一致）
        "hard_constraints": _value_or_default(intent.get("hard_constraints"), []),
        "avoid_when": _value_or_default(intent.get("avoid_when"), []),
        "clarify_when": _value_or_default(intent.get("clarify_when"), []),
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `python3 -m pytest tests/query/test_intent_matcher_guardrails.py tests/query/test_manager.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 追加变更记录 + 提交**

`docs/change-log-pending.md` 顶部追加（格式按文件既有条目）后：

```bash
git add opscli/query/services/intent_matcher.py tests/query/test_intent_matcher_guardrails.py docs/change-log-pending.md
git commit -m "🐛 fix(query): 意图匹配候选透传业务约束护栏"
```

---

### Task B2: 匹配器补缺口 B——embedded_intent 落到执行表

**Files:**
- Modify: `opscli/query/services/intent_matcher.py`（`match_catalog_intents` / `_candidate`）
- Test: `tests/query/test_intent_matcher_guardrails.py`（追加用例）

**Interfaces:**
- Produces: `candidates[]` 新增键 `routing_status: str`、`embedded_from_table_id: int|None`；`routing_status == "embedded_intent"` 时 `table_id`/`dataset_alias`/`dataset_name` 已替换为执行父表的值

- [ ] **Step 1: 编写失败测试（追加到同一测试文件）**

```python
def test_embedded_intent_resolves_to_execution_dataset():
    """embedded_intent 必须把 table_id/alias 落到 execution_dataset_id 指向的父表。

    为什么：catalog 的「即时销售」意图 routing_status=embedded_intent、
    execution_dataset_id 指向即时综合（父表）；不解析的话 Agent 会被指去
    意图自身的表，与路由契约（local_fallback._resolve_execution_row）不一致。
    """
    catalog = {
        "version": "v1.0.0",
        "intent_count": 2,
        "intents": [
            {
                "intent_code": "parent_intent", "intent_name": "即时综合分析",
                "table_id": 1, "dataset_alias": "ds_parent", "dataset_name": "即时综合数据集",
                "keywords": ["即时综合"], "priority": 100,
            },
            {
                "intent_code": "realtime_sales_monitoring", "intent_name": "实时销售监控",
                "table_id": 3, "dataset_alias": "ds_child", "dataset_name": "即时销售数据集",
                "keywords": ["大促"], "priority": 100,
                "routing_status": "embedded_intent", "execution_dataset_id": 1,
            },
        ],
    }
    result = match_catalog_intents(catalog, "大促表现")
    top = result["candidates"][0]
    assert top["intent_code"] == "realtime_sales_monitoring"
    assert top["routing_status"] == "embedded_intent"
    assert top["table_id"] == 1                      # 已落到父表
    assert top["dataset_alias"] == "ds_parent"
    assert top["embedded_from_table_id"] == 3        # 保留原表供披露


def test_embedded_intent_missing_parent_keeps_own_table():
    """execution_dataset_id 在 catalog 里找不到父表时退回自身表，不得产出空 table_id。"""
    catalog = {
        "version": "v1.0.0", "intent_count": 1,
        "intents": [{
            "intent_code": "orphan", "intent_name": "断链意图",
            "table_id": 3, "dataset_alias": "ds_child", "dataset_name": "子表",
            "keywords": ["断链"], "priority": 100,
            "routing_status": "embedded_intent", "execution_dataset_id": 999,
        }],
    }
    top = match_catalog_intents(catalog, "断链查询")["candidates"][0]
    assert top["table_id"] == 3
    assert top["dataset_alias"] == "ds_child"
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/query/test_intent_matcher_guardrails.py -v -k embedded`
Expected: FAIL，KeyError `'routing_status'`

- [ ] **Step 3: 实现**

`match_catalog_intents()` 在遍历打分前构建父表索引，并把它传给 `_candidate`：

```python
    # embedded_intent 解析用：table_id -> 意图行。父表信息只能从 catalog 自身反查，
    # 匹配器没有 datasets.csv 可用；查不到父表时退回自身表，宁可少一层跳转
    # 也不能产出解析不出 table_id 的候选（旧画像腐烂的教训）
    intents_by_table_id = {
        _safe_int(item.get("table_id")): item
        for item in intents if isinstance(item, dict) and item.get("table_id")
    }
```

`_candidate()` 签名加 `intents_by_table_id: dict`，函数体开头解析执行表：

```python
    routing_status = str(intent.get("routing_status") or "direct_intent")
    execution = intent
    embedded_from = None
    if routing_status == "embedded_intent":
        parent = intents_by_table_id.get(_safe_int(intent.get("execution_dataset_id")))
        if parent is not None:
            execution = parent
            embedded_from = _safe_int(intent.get("table_id"))
```

输出字典中 `dataset_alias`/`table_id`/`dataset_name` 改取 `execution`，并追加：

```python
        "routing_status": routing_status,
        "embedded_from_table_id": embedded_from,
```

（`intent_code`/`intent_name`/`priority`/约束仍取原 `intent`——披露口径要保留用户认知里的意图名。）

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `python3 -m pytest tests/query/ -v`
Expected: 全部 PASS（含 B1 用例与既有 manager 用例）

- [ ] **Step 5: 追加变更记录 + 提交**

```bash
git add opscli/query/services/intent_matcher.py tests/query/test_intent_matcher_guardrails.py docs/change-log-pending.md
git commit -m "🐛 fix(query): 意图匹配解析 embedded_intent 到执行父表"
```

---

### Task B3: 恢复 CLI 与 MCP 的 catalog/intent 接口

**Files:**
- Modify: `opscli/query/commands/cli.py:350-351,378-379`（删除"临时屏蔽"注释行，取消 `@app.command` 注释）
- Modify: `opscli/mcp/tools/query.py:24,831-833`（docstring 屏蔽说明改为已注册；`_ALL_TOOLS` 取消两行注释）
- Test: `tests/query/test_cli_intent_commands.py`（新建）

**Interfaces:**
- Consumes: Task B1/B2 后的匹配器输出
- Produces: `opscli query catalog` / `opscli query intent` 命令与 MCP 工具 `query_catalog` / `query_intent_match` 可用（Skill 文档 Task B7 消费）

- [ ] **Step 1: 编写失败测试**

```python
"""catalog/intent 接口恢复回归：命令注册即视为对外承诺，防止再次静默消失。"""
from typer.testing import CliRunner

from opscli.query.commands.cli import app


def _registered_commands() -> set:
    return {command.name for command in app.registered_commands}


def test_catalog_and_intent_commands_registered():
    assert {"catalog", "intent"} <= _registered_commands()


def test_intent_command_outputs_match_result(monkeypatch):
    """intent 命令输出 JSON 信封，data 为匹配结果。"""
    from opscli.query.services.manager import QueryManager

    def fake_intent_match(self, **kwargs):
        return {"matched": False, "fallback_required": True, "candidates": []}

    monkeypatch.setattr(QueryManager, "intent_match", fake_intent_match)
    result = CliRunner().invoke(app, ["intent", "--query", "看下广告费"])
    assert result.exit_code == 0
    assert '"command": "query intent"' in result.stdout or '"command":"query intent"' in result.stdout


def test_mcp_tools_registered():
    from opscli.mcp.tools import query as query_tools

    tool_names = {tool.__name__ for tool in query_tools._ALL_TOOLS}
    assert {"query_catalog", "query_intent_match"} <= tool_names
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/query/test_cli_intent_commands.py -v`
Expected: FAIL，registered_commands 不含 catalog/intent

- [ ] **Step 3: 取消注释**

- `cli.py`：删除 `# 【临时屏蔽】catalog 命令暂停对外暴露，恢复时取消下一行注释即可` 注释行，`# @app.command("catalog")` → `@app.command("catalog")`；`intent` 同理
- `mcp/tools/query.py`：`_ALL_TOOLS` 中两行取消注释并删除屏蔽说明注释；模块 docstring 第 24 行「内部暂时屏蔽（不对外注册）：query_catalog、query_intent_match。」改为「catalog / intent 路线：query_catalog — 读取数据集业务语义索引；query_intent_match — 自然语言匹配 catalog intents。」

- [ ] **Step 4: 运行确认通过 + 冒烟**

Run: `python3 -m pytest tests/query/test_cli_intent_commands.py tests/mcp/test_query_tools.py -v`
Expected: 全部 PASS
Run: `opscli query intent --help`
Expected: 正常输出参数帮助（GBK 安全字符）

- [ ] **Step 5: 追加变更记录 + 提交**

```bash
git add opscli/query/commands/cli.py opscli/mcp/tools/query.py tests/query/test_cli_intent_commands.py docs/change-log-pending.md
git commit -m "✨ feat(query): 恢复 catalog/intent CLI 命令与 MCP 工具注册"
```

---

### Task B4: 意图匹配上报（fire-and-forget）

**Files:**
- Modify: `opscli/query/transport/client.py`（`fetch_dataset_catalog` 后追加 `report_intent_match`）
- Modify: `opscli/query/services/manager.py:1728`（`intent_match()` 增加上报）
- Test: `tests/query/test_intent_match_report.py`（新建，respx mock）

**Interfaces:**
- Consumes: 总纲契约 1 的端点结构
- Produces: `QueryClient.report_intent_match(payload: dict) -> dict`；`QueryManager.intent_match(..., report_source: str = "cli_intent")` 返回值新增键 `match_record_id: int|None`（Task B5/B6 透传消费）

- [ ] **Step 1: 编写失败测试**

```python
"""意图匹配上报回归：命中与未命中都上报，上报失败绝不影响匹配结果返回。"""
import httpx
import respx

from opscli.query.services.manager import QueryManager

_REPORT_URL = "https://ops.api.xenkee.com/api/v1/data-metrics/datasets/skill/intent-match-report"
_CATALOG = {
    "version": "v1.0.0", "intent_count": 1,
    "intents": [{
        "intent_code": "ads_overall", "intent_name": "广告总览",
        "table_id": 15, "dataset_alias": "ds_ads", "dataset_name": "广告费数据集",
        "keywords": ["广告费"], "priority": 100,
    }],
}


def _manager(monkeypatch) -> QueryManager:
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "fetch_dataset_catalog", lambda: _CATALOG)
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))
    return manager


@respx.mock
def test_intent_match_reports_and_returns_record_id(monkeypatch):
    route = respx.post(_REPORT_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"match_record_id": 77}, "msg": "ok"})
    )
    result = _manager(monkeypatch).intent_match(query="看下广告费")
    assert result["match_record_id"] == 77
    body = route.calls.last.request.content
    assert b'"matched": true' in body or b'"matched":true' in body
    assert b"ads_overall" in body


@respx.mock
def test_unmatched_query_still_reports(monkeypatch):
    route = respx.post(_REPORT_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"match_record_id": 78}, "msg": "ok"})
    )
    result = _manager(monkeypatch).intent_match(query="毫无关联的天气话题")
    assert result["fallback_required"] is True
    assert result["match_record_id"] == 78
    assert b"no_intent_match" in route.calls.last.request.content


@respx.mock
def test_report_failure_is_silent(monkeypatch):
    respx.post(_REPORT_URL).mock(side_effect=httpx.ConnectError("down"))
    result = _manager(monkeypatch).intent_match(query="看下广告费")
    assert result["matched"] is True           # 匹配结果不受上报失败影响
    assert result["match_record_id"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/query/test_intent_match_report.py -v`
Expected: FAIL，`match_record_id` KeyError

- [ ] **Step 3: 实现 client 方法**

`client.py` 中 `fetch_dataset_catalog` 后追加：

```python
    def report_intent_match(self, payload: dict) -> dict:
        """上报一次意图匹配事件（含未命中）。

        超时固定 5 秒：这是纯遥测请求，宁可丢一条记录也不能拖慢交互路径。
        """
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/data-metrics/datasets/skill/intent-match-report",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=5,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
```

- [ ] **Step 4: 实现 manager 上报**

`intent_match()` 改为：

```python
    def intent_match(
        self,
        *,
        query: str,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        source: str = "remote",
        fallback_local: bool = True,
        report_source: str = "cli_intent",
    ) -> dict:
        """按自然语言需求匹配 dataset catalog intents，并上报匹配事件。

        上报是 fire-and-forget：闭环遥测的价值在服务端聚合，客户端绝不因
        上报失败影响匹配结果（match_record_id 置 None 即可）。
        """
        catalog = self.catalog(
            skills_dir=skills_dir, cwd=cwd, source=source, fallback_local=fallback_local,
        )
        result = match_catalog_intents(catalog, query)
        result["match_record_id"] = self._report_intent_match(result, query, report_source)
        return result

    def _report_intent_match(self, result: dict, query: str, report_source: str) -> int | None:
        """构造并发送匹配事件；任何异常静默吞掉返回 None。"""
        selected = result.get("selected") or (result.get("candidates") or [{}])[0]
        payload = {
            "matched": bool(result.get("matched")),
            "intent_code": selected.get("intent_code") or None,
            "score": int(selected.get("score") or 0),
            "ask_required": bool(result.get("ask_user_question_required")),
            "fallback_reason": result.get("fallback_reason") or "",
            "match_source": report_source,
            "query_text": query[:500],
            "query_keywords": result.get("fallback_query_keywords")
                or [term for term in selected.get("matched_terms") or []],
            "catalog_version": str(result.get("catalog_version") or ""),
        }
        try:
            response = self.client.report_intent_match(payload)
            record_id = (response.get("data") or {}).get("match_record_id")
            return int(record_id) if record_id else None
        except Exception:
            return None
```

- [ ] **Step 5: 运行确认通过 + 回归**

Run: `python3 -m pytest tests/query/ -v`
Expected: 全部 PASS

- [ ] **Step 6: 追加变更记录 + 提交**

```bash
git add opscli/query/transport/client.py opscli/query/services/manager.py tests/query/test_intent_match_report.py docs/change-log-pending.md
git commit -m "✨ feat(query): 意图匹配事件上报（含未命中，失败静默）"
```

---

### Task B5: 查询执行归因参数（CLI + MCP）

**Files:**
- Modify: `opscli/query/commands/cli.py`（`run` 与 `simple` 命令各加三个 Option）
- Modify: `opscli/query/services/manager.py:220`（`run()` 与 simple 执行链传递 headers）
- Modify: `opscli/query/transport/client.py:377-410`（`cli_query` / `cli_simple_query` 加 `extra_headers` 参数）
- Modify: `opscli/mcp/tools/query.py`（`query_run` / `query_build_and_run` 加可选参数）
- Test: `tests/query/test_intent_attribution_headers.py`（新建）

**Interfaces:**
- Consumes: 总纲契约 2 的三个请求头
- Produces: CLI `--intent-code` / `--selection-source` / `--match-record-id` 参数；`QueryClient.cli_query(payload, extra_headers=None)`、`cli_simple_query(payload, extra_headers=None)`；`QueryManager.run(payload_path=..., intent_code=None, selection_source=None, match_record_id=None)`（Task B6 的 run_query.py 透传消费）

- [ ] **Step 1: 编写失败测试**

```python
"""执行归因请求头回归：三个可选参数必须以 Header 形式到达服务端，不污染 payload。"""
import json

import httpx
import respx

from opscli.query.services.manager import QueryManager

_QUERY_URL = "https://ops.api.xenkee.com/api/v1/data-metrics/cli-query"


@respx.mock
def test_run_sends_attribution_headers(tmp_path, monkeypatch):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"tableId": 1, "query": {"from": {"alias": "ds_x"}}}), encoding="utf-8")

    route = respx.post(_QUERY_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"result": {"success": True}}, "msg": "ok"})
    )
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))

    manager.run(
        payload_path=str(payload_file),
        intent_code="ads_overall",
        selection_source="intent_route",
        match_record_id=77,
    )

    request = route.calls.last.request
    assert request.headers["X-Intent-Code"] == "ads_overall"
    assert request.headers["X-Selection-Source"] == "intent_route"
    assert request.headers["X-Match-Record-Id"] == "77"
    assert b"intent" not in request.content.lower()   # payload 不被污染


@respx.mock
def test_run_without_attribution_sends_no_headers(tmp_path, monkeypatch):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps({"tableId": 1, "query": {"from": {"alias": "ds_x"}}}), encoding="utf-8")

    route = respx.post(_QUERY_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"result": {"success": True}}, "msg": "ok"})
    )
    manager = QueryManager()
    monkeypatch.setattr(manager.client, "_get_auth", lambda system: ({}, {}))
    manager.run(payload_path=str(payload_file))

    request = route.calls.last.request
    assert "X-Intent-Code" not in request.headers
    assert "X-Match-Record-Id" not in request.headers
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/query/test_intent_attribution_headers.py -v`
Expected: FAIL，`run() got an unexpected keyword argument 'intent_code'`

- [ ] **Step 3: 实现三层透传**

client 层（两个方法同样处理）：

```python
    def cli_query(self, payload: dict, extra_headers: dict | None = None) -> dict:
        """转发查询请求到 auto-scheduler 的 cli-query 接口。

        extra_headers 用于意图归因（X-Intent-Code 等）：走 Header 而不进 payload，
        因为 cli-query 的 body 会透传给 Python 取数服务，塞额外字段有被拒风险。
        """
        headers, cookies = self._get_auth("ops")
        if extra_headers:
            headers = {**headers, **extra_headers}
        ...  # 其余不变
```

manager 层，`run()` 签名加三个关键字参数，构造 headers 字典（None 值跳过）后传给 `cli_query`；simple 执行链同样处理（找到调用 `cli_simple_query` 的方法同步加参）。构造函数抽一个模块级帮助函数：

```python
def _attribution_headers(
    intent_code: str | None, selection_source: str | None, match_record_id: int | None,
) -> dict | None:
    """把归因三元组转成请求头字典；全空返回 None 表示不附加。"""
    headers = {}
    if intent_code:
        headers["X-Intent-Code"] = intent_code
    if selection_source:
        headers["X-Selection-Source"] = selection_source
    if match_record_id:
        headers["X-Match-Record-Id"] = str(match_record_id)
    return headers or None
```

CLI 层，`run` 与 `simple` 命令各追加：

```python
    intent_code: str | None = typer.Option(None, "--intent-code", help="意图归因编码（意图路由选表时透传）"),
    selection_source: str | None = typer.Option(None, "--selection-source", help="选表来源：planner/intent_route/local_fallback/user_specified"),
    match_record_id: int | None = typer.Option(None, "--match-record-id", help="意图匹配记录ID（query intent 返回的 match_record_id）"),
```

并透传给 manager 调用。MCP 层 `query_run` / `query_build_and_run` 各加三个同名可选参数（默认 None），docstring 说明用途，透传给 manager。

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `python3 -m pytest tests/query/ tests/mcp/test_query_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 追加变更记录 + 提交**

```bash
git add opscli/query/commands/cli.py opscli/query/services/manager.py opscli/query/transport/client.py opscli/mcp/tools/query.py tests/query/test_intent_attribution_headers.py docs/change-log-pending.md
git commit -m "✨ feat(query): 查询执行携带意图归因请求头"
```

---

### Task B6: Skill 降级路径归因透传

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/local_fallback.py`（`_emit_plan` 的 `execution_ref`）
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/run_query.py:303-317`（`_run_opscli` 及其调用链）
- Test: `tests/skills/test_local_fallback.py`（追加用例）、`tests/skills/test_run_query_intent_attribution.py`（新建）

**Interfaces:**
- Consumes: Task B5 的 `--intent-code` / `--selection-source` CLI 参数
- Produces: 降级 plan 的 `execution_ref.intent_code: str` 与 `execution_ref.selection_source: "local_fallback"`；`run_query.py` 执行时透传为 CLI 参数

- [ ] **Step 1: 编写失败测试**

`tests/skills/test_local_fallback.py` 追加：

```python
def test_emit_plan_carries_intent_attribution(tmp_path: Path):
    """降级 plan 必须带意图归因，执行段才能把 intent_code 透传给服务端落库。"""
    data_dir = tmp_path / "data"
    _write_ready_data_dir(data_dir)

    # 「大促」唯一命中 embedded 意图 realtime_sales_monitoring（参见 embedded 用例的选词说明）
    result = local_fallback.build_fallback("大促期间销售异常吗", data_dir=data_dir)
    assert result["status"] == "ready"
    plan_path = tmp_path / "plan.json"
    local_fallback._emit_plan(result, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert plan["execution_ref"]["intent_code"] == "realtime_sales_monitoring"
    assert plan["execution_ref"]["selection_source"] == "local_fallback"
```

`tests/skills/test_run_query_intent_attribution.py`（参照 `tests/skills/test_run_query_currency.py` 的 subprocess mock 模式）：

```python
"""run_query 执行段的意图归因透传回归。"""
import json
import sys
from pathlib import Path

SKILL_SCRIPTS = (
    Path(__file__).parents[2] / "opscli" / "skills" / "templates" / "ops-dataset-query" / "scripts"
)
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

import run_query  # noqa: E402


def test_run_opscli_passes_attribution_flags(monkeypatch):
    """plan 带 intent_code 时，subprocess 命令必须含 --intent-code / --selection-source。"""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = json.dumps({"success": True, "data": {"result": {"success": True, "data": []}}})
            stderr = ""

        return _Result()

    monkeypatch.setattr(run_query.subprocess, "run", fake_run)
    run_query._run_opscli(
        "1", {"dimensions": []},
        intent_code="realtime_sales_monitoring", selection_source="local_fallback",
    )
    cmd = captured["cmd"]
    assert "--intent-code" in cmd and "realtime_sales_monitoring" in cmd
    assert "--selection-source" in cmd and "local_fallback" in cmd


def test_run_opscli_without_attribution_keeps_command_clean(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = json.dumps({"success": True, "data": {"result": {"success": True, "data": []}}})
            stderr = ""

        return _Result()

    monkeypatch.setattr(run_query.subprocess, "run", fake_run)
    run_query._run_opscli("1", {"dimensions": []})
    assert "--intent-code" not in captured["cmd"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/skills/test_local_fallback.py -k attribution tests/skills/test_run_query_intent_attribution.py -v`
Expected: FAIL（plan 无 intent_code 键；`_run_opscli` 不接受关键字参数）

- [ ] **Step 3: 实现 local_fallback 侧**

`_emit_plan()` 的 `execution_ref` 字典中 `"dataset_alias"` 行之后追加：

```python
            # 意图归因：执行段（run_query.py）读取后经 --intent-code 透传给服务端落库，
            # 闭环统计"这条意图被降级路径命中并真实执行了多少次"
            "intent_code": (result.get("dataset_candidates") or [{}])[0].get("intent_id") or "",
            "selection_source": "local_fallback",
```

- [ ] **Step 4: 实现 run_query 侧**

`_run_opscli()` 签名加 `intent_code: str = "", selection_source: str = ""`，命令列表 `"--run"` 之后按需追加：

```python
    if intent_code:
        command.extend(["--intent-code", intent_code, "--selection-source", selection_source or "local_fallback"])
```

在 `_run_opscli` 的两处调用点（`run_query.py:444` 与 `:480` 附近），从当前 plan 上下文读取 `execution_ref.intent_code` / `execution_ref.selection_source` 并透传（沿现有 plan 传参路径，保持函数签名改动最小）。

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `python3 -m pytest tests/skills/ -v -p no:cacheprovider --tb=short 2>&1 | tail -20`
Expected: 除既有基线 8 个失败外全部 PASS（对照 Global Constraints 的基线清单）

- [ ] **Step 6: 追加变更记录 + 提交**

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/local_fallback.py opscli/skills/templates/ops-dataset-query/scripts/run_query.py tests/skills/test_local_fallback.py tests/skills/test_run_query_intent_attribution.py docs/change-log-pending.md
git commit -m "✨ feat(skills): 降级路径经 plan 透传意图归因"
```

---

### Task B7: Skill 文档与版本收口

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/SKILL.md`（降级层级 L2 + 版本号）
- Modify: `opscli/skills/templates/ops-dataset-query/references/cli.md`（新命令文档）
- Modify: `opscli/skills/templates/ops-dataset-query/references/mcp.md`（新 MCP 工具文档）
- Modify: `opscli/skills/templates/ops-dataset-query/data/VERSION.json`（1.3.20 → 1.3.21）
- Test: 复用 `tests/skills/test_dataset_query_flow.py`（文案锁定回归）

**Interfaces:**
- Consumes: Task B3 恢复的命令、Task B4 的 match_record_id、Task B5 的归因参数

- [ ] **Step 1: SKILL.md 降级层级改两段式 L2**

「降级层级」表格的 L2 行改为：

```markdown
| L2a | 目录为空或选表失败 | 跑 `opscli query intent -q "<用户原文>"`（远端实时意图目录，不依赖本地快照）；`matched=true` 按 `selected` 构造查询并在执行时带 `--intent-code <intent_code> --selection-source intent_route --match-record-id <match_record_id>`；`ask_user_question_required=true` 用 `AskUserQuestion` 让用户在 candidates 里选 |
| L2b | `query intent` 不可用、报错或 `fallback_required=true` | 跑 `python3 scripts/local_fallback.py "<用户原文>"` 拿本地候选，按其 `next_action_zh` 处置 |
```

并在候选处置清单（「拿到候选后」小节）追加一条：

```markdown
6. `query intent` 候选里的 `intent_constraints.hard_constraints` / `avoid_when` / `clarify_when` 处置口径与 `local_fallback` 的 `uncertified_hints_zh` 相同：先向用户复述确认再套用
```

- [ ] **Step 2: cli.md 追加命令文档**

按该文件既有命令条目格式追加 `opscli query catalog` 与 `opscli query intent` 两节，参数逐个列全（`--query/-q`、`--source remote|local`、`--fallback-local/--no-fallback-local`、`--skills-dir`、`--pretty`），并附输出关键键说明（`candidates[].intent_constraints`、`ask_user_question_required`、`fallback_required`、`match_record_id`）与一个典型工作流示例（intent → 构造查询 → run 带归因参数）。同时在 `query run` / `query simple` 条目追加三个归因参数说明。

- [ ] **Step 3: mcp.md 追加工具文档**

追加 `query_catalog` / `query_intent_match` 两个工具的说明与调用示例；写明定位：意图命中作为选表候选参考，最终字段仍以 `query_metadata(dataset=...)` 响应为唯一运行时来源（与该文件现行条款一致，不得冲突）。`query_run` / `query_build_and_run` 条目补三个归因参数。

- [ ] **Step 4: 版本号同步**

`SKILL.md` 版本标注与 `data/VERSION.json` 同步改为 `1.3.21`。

- [ ] **Step 5: 回归文档锁定测试**

Run: `python3 -m pytest tests/skills/test_dataset_query_flow.py tests/skills/test_local_fallback.py -v`
Expected: 全部 PASS（`test_skill_md_registers_uncertified_hints_key` 等文案锁定用例仍绿）

- [ ] **Step 6: 追加变更记录 + 提交**

```bash
git add opscli/skills/templates/ops-dataset-query/SKILL.md opscli/skills/templates/ops-dataset-query/references/cli.md opscli/skills/templates/ops-dataset-query/references/mcp.md opscli/skills/templates/ops-dataset-query/data/VERSION.json docs/change-log-pending.md
git commit -m "📝 docs(skills): 降级路径接入远端意图目录，版本 1.3.21"
```
