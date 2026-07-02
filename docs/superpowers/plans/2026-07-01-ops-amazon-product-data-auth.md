# ops-amazon-product-data Auth Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `ops-amazon-product-data` Skill so it prefers the official CLI path, documents CLI authorization and CLI-to-remote-MCP API Key exchange, and limits `scrape_do_spec_must_read` / `scrape_do_scenarios` to MCP direct usage.

**Architecture:** This is a Skill documentation behavior change guarded by pytest tests that parse the shipped `SKILL.md`. No runtime command code changes are required. The implementation updates one Skill template and adds focused tests to prevent future regressions in the CLI/MCP authorization instructions.

**Tech Stack:** Python 3.10+, pytest, Markdown Skill template files under `opscli/skills/templates/`.

## Global Constraints

- Follow TDD: write failing tests before editing `SKILL.md`.
- Do not modify `opscli scrape-do` CLI implementation or MCP tools.
- Do not expose underlying third-party provider names, internal endpoints, token values, API Key values, or local credential paths in user-facing Skill guidance.
- CLI path must not require `scrape_do_spec_must_read` or `scrape_do_scenarios` as universal pre-steps.
- MCP direct path must include `auth_is_authenticated()` and `auth_mcp_login()` before Amazon product data MCP calls.
- CLI path must include `opscli auth token status`, `opscli auth login`, `opscli scrape-do scenarios`, `opscli scrape-do run`, `opscli scrape-do job-status`, and `opscli scrape-do export`.
- CLI path must state that the CLI uses local `opscli auth` login state to fetch remote MCP config/API Key and that agents must not ask users to provide API Keys.
- If any `opscli` CLI command or MCP tool call fails during execution, follow `AGENTS.md`: read `opscli/skills/templates/ops-feedback/SKILL.md`, submit structured feedback, and report the feedback UUID unless the failure is an auth expected state, user cancellation, or duplicate within 5 minutes.

---

## File Structure

- Modify: `opscli/skills/templates/ops-amazon-product-data/SKILL.md`
  - Responsibility: public Skill instructions for Amazon product data collection, including route selection, authorization steps, scenario mapping, user-facing wording, and safety rules.
- Create: `tests/skills/test_ops_amazon_product_data_skill.py`
  - Responsibility: documentation behavior tests that lock the route-selection and authorization contract in the Skill template.

---

### Task 1: Add failing tests for Skill route and authorization guidance

**Files:**
- Create: `tests/skills/test_ops_amazon_product_data_skill.py`

**Interfaces:**
- Consumes: existing Skill template at `opscli/skills/templates/ops-amazon-product-data/SKILL.md`.
- Produces: pytest tests that fail against the current Skill and pass once Task 2 updates the Markdown.

- [ ] **Step 1: Create the tests directory if needed**

Run:

```bash
mkdir -p tests/skills
```

Expected: command exits with status 0.

- [ ] **Step 2: Write the failing tests**

Create `tests/skills/test_ops_amazon_product_data_skill.py` with exactly this content:

```python
from pathlib import Path


SKILL_PATH = Path("opscli/skills/templates/ops-amazon-product-data/SKILL.md")


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    assert start != -1, f"missing section: {heading}"
    next_start = text.find("\n## ", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def test_cli_path_documents_auth_and_remote_mcp_config_exchange():
    text = _skill_text()
    cli_section = _section(text, "CLI 授权与执行流程")

    assert "opscli auth token status" in cli_section
    assert "opscli auth login" in cli_section
    assert "opscli scrape-do scenarios" in cli_section
    assert "opscli scrape-do run" in cli_section
    assert "opscli scrape-do job-status" in cli_section
    assert "opscli scrape-do export" in cli_section
    assert "本地登录态" in cli_section
    assert "远端 MCP 配置/API Key" in cli_section
    assert "不要要求用户提供 API Key" in cli_section
    assert "不要手动拼接远端 MCP URL" in cli_section


def test_mcp_tools_are_limited_to_mcp_direct_path():
    text = _skill_text()
    route_section = _section(text, "运行路径选择")
    cli_section = _section(text, "CLI 授权与执行流程")
    mcp_section = _section(text, "MCP 授权与执行流程")

    assert "CLI 优先" in route_section
    assert "MCP 直连" in route_section
    assert "scrape_do_spec_must_read" not in cli_section
    assert "scrape_do_scenarios" not in cli_section
    assert "scrape_do_spec_must_read" in mcp_section
    assert "scrape_do_scenarios" in mcp_section


def test_mcp_direct_path_documents_auth_status_before_product_data_tools():
    text = _skill_text()
    mcp_section = _section(text, "MCP 授权与执行流程")

    assert "auth_is_authenticated()" in mcp_section
    assert "auth_mcp_login()" in mcp_section
    assert mcp_section.index("auth_is_authenticated()") < mcp_section.index("scrape_do_spec_must_read")
    assert mcp_section.index("auth_mcp_login()") < mcp_section.index("scrape_do_spec_must_read")


def test_skill_does_not_make_mcp_spec_tools_universal_prerequisites():
    text = _skill_text()

    forbidden_phrases = [
        "首次使用本能力时，先调用",
        "这两个工具是当前 Amazon 商品数据接口的 MCP 入口",
        "调用 `scrape_do_spec_must_read` 和 `scrape_do_scenarios`。",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in text
```

- [ ] **Step 3: Run the new tests and verify they fail for the expected reason**

Run:

```bash
pytest tests/skills/test_ops_amazon_product_data_skill.py -q
```

Expected: FAIL. The expected failures mention missing sections such as `CLI 授权与执行流程`, because the current `SKILL.md` still has the old universal MCP-tool flow.

- [ ] **Step 4: Do not edit production documentation in this task**

Confirm no changes were made to `opscli/skills/templates/ops-amazon-product-data/SKILL.md` during Task 1.

Run:

```bash
git diff -- opscli/skills/templates/ops-amazon-product-data/SKILL.md
```

Expected: no output.

---

### Task 2: Update the Skill Markdown to distinguish CLI and MCP direct paths

**Files:**
- Modify: `opscli/skills/templates/ops-amazon-product-data/SKILL.md`
- Test: `tests/skills/test_ops_amazon_product_data_skill.py`

**Interfaces:**
- Consumes: tests from Task 1.
- Produces: updated Skill guidance with these exact top-level sections: `运行路径选择`, `CLI 授权与执行流程`, `MCP 授权与执行流程`.

- [ ] **Step 1: Replace the obsolete universal MCP prerequisite section**

In `opscli/skills/templates/ops-amazon-product-data/SKILL.md`, remove the section that starts with:

```markdown
## 必须先读规范
```

and ends before:

```markdown
## 场景选择
```

Replace it with this content:

```markdown
## 运行路径选择

默认优先使用正式 CLI 路径。只有在用户明确要求 MCP、当前宿主只能调用 MCP Tool、或 CLI 首次正式调用不可用时，才切换到 MCP 直连路径。

| 环境 / 约束 | 路径 | 说明 |
|---|---|---|
| 当前在 `opscli` 项目或本地可执行正式命令，且用户未指定 MCP | CLI 优先 | 使用 `opscli auth` 和 `opscli scrape-do`；这是最贴近真实交付的路径 |
| 用户明确要求 MCP，或当前宿主只能调用 MCP Tool | MCP 直连 | 使用 `auth_*` 与 `scrape_do_*` MCP tools |
| CLI 首次正式调用失败 | 切换 MCP 直连 | 若失败属于 `opscli` 命令失败，按项目规则提交 `ops-feedback` 后继续 |

不要在两条路径之间来回切换。选定路径后保持一致，除非当前路径不可用。

## CLI 授权与执行流程

CLI 路径先使用 `ops-auth` 的 CLI 模式确认本地登录态，再调用正式商品数据命令。

1. 检查登录态：`opscli auth token status`。
2. 如果未登录或 Token 无效，执行：`opscli auth login`。
3. 查看支持场景：`opscli scrape-do scenarios`。
4. 执行采集：`opscli scrape-do run <scenario> --site <site> --params '<json>'`。
5. 如需复核任务状态：`opscli scrape-do job-status <job_id>`。
6. 如需读取导出信息：`opscli scrape-do export <job_id>`。

CLI 内部会使用本地登录态向 OPS 获取远端 MCP 配置/API Key，然后调用远端 MCP 服务。不要要求用户提供 API Key，不要手动拼接远端 MCP URL，也不要在回复中展示 API Key、远端 URL、token 或内部 endpoint。

示例：

```bash
opscli auth token status
opscli scrape-do scenarios
opscli scrape-do run amazon-pdp --site US --params '{"asin":"B0C7BKZ883"}'
opscli scrape-do job-status <job_id>
opscli scrape-do export <job_id>
```

## MCP 授权与执行流程

MCP 直连路径先使用 `ops-auth` 的 MCP 模式确认登录态，再调用商品数据 MCP tools。

1. 检查登录态：`auth_is_authenticated()`。
2. 如果未登录，执行：`auth_mcp_login()`。
3. 首次使用当前 MCP 能力时，调用 `scrape_do_spec_must_read()`。
4. 调用 `scrape_do_scenarios()` 查看支持场景。
5. 选择场景并调用 `scrape_do_run()`。
6. 如需复核，调用 `scrape_do_job_status(job_id)`。
7. 如需下载表格，调用 `scrape_do_export(job_id)`。

MCP 直连路径也不要要求用户提供认证令牌或 API Key；凭证由登录态、远端配置或服务端托管。
```

- [ ] **Step 2: Replace the old recommended execution flow**

Find the current section:

```markdown
## 推荐执行流程
```

Replace the entire section body, from `## 推荐执行流程` through the line before `## 输出文件说明`, with this content:

```markdown
## 推荐执行流程

1. 明确目标：ASIN、关键词、站点、是否需要报价/搜索/商品页。
2. 按“运行路径选择”确定 CLI 或 MCP 直连路径。
3. 按所选路径完成授权检查；不要要求用户提供 token 或 API Key。
4. 选择场景并执行采集。
5. 查看返回的 `job_id`、`row_count`、`billing`、`export.url`。
6. 如需复核，按所选路径查询任务状态。
7. 如需下载表格，按所选路径读取导出信息。
8. 向用户总结时只说业务结果、导出文件、字段情况，不暴露供应商、API Key、远端 URL 或内部 endpoint。
```

- [ ] **Step 3: Keep scenario and output sections unchanged unless wording conflicts**

Review the remaining sections in `SKILL.md`. Keep the scenario table, optional parameters, output file description, review field description, example JSON payloads, user reply template, common errors, and safety rules. Only adjust lines that still imply MCP-only tools are universal.

Specifically verify these lines remain present somewhere in the file:

```markdown
| 商品页 / PDP / ASIN 基础信息 / 评论字段 | `amazon-pdp` | `asin` | 返回商品页结构化字段；可能包含 `reviews` 基础信息 |
| 卖家报价 / Offer Listing / Buy Box | `amazon-offer-listing` | `asin` | 返回报价列表、卖家、配送、价格等 |
| 关键词搜索 / 搜索页商品列表 | `amazon-search` | `keyword` | 返回搜索商品、排名、广告位、筛选项等 |
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
pytest tests/skills/test_ops_amazon_product_data_skill.py -q
```

Expected: PASS, with all 4 tests passing.

- [ ] **Step 5: Inspect the diff for accidental provider or secret leakage**

Run:

```bash
git diff -- opscli/skills/templates/ops-amazon-product-data/SKILL.md tests/skills/test_ops_amazon_product_data_skill.py
```

Expected: diff shows only the test file and Skill guidance updates. It should not include real API Keys, token values, internal endpoint URLs, or local credential paths.

---

### Task 3: Run regression checks and final review

**Files:**
- Verify: `opscli/skills/templates/ops-amazon-product-data/SKILL.md`
- Verify: `tests/skills/test_ops_amazon_product_data_skill.py`

**Interfaces:**
- Consumes: completed Task 1 and Task 2.
- Produces: verified working tree ready for user review.

- [ ] **Step 1: Run focused Skill documentation tests**

Run:

```bash
pytest tests/skills/test_ops_amazon_product_data_skill.py -q
```

Expected: PASS.

- [ ] **Step 2: Run related scrape-do tests**

Run:

```bash
pytest tests/scrape_do/test_cli_remote.py tests/mcp/test_scrape_do_tools.py -q
```

Expected: PASS. These tests verify the CLI remote adapter and MCP scrape-do tools still behave as expected. This task did not change runtime code, so failures here indicate environment or unrelated regressions that must be reported accurately.

- [ ] **Step 3: Run all Skill-related tests if present**

Run:

```bash
pytest tests/skills -q
```

Expected: PASS.

- [ ] **Step 4: Check working tree status**

Run:

```bash
git status --short
```

Expected: modified `opscli/skills/templates/ops-amazon-product-data/SKILL.md`, new `tests/skills/test_ops_amazon_product_data_skill.py`, and the planning/spec docs if they have not been committed separately.

- [ ] **Step 5: Review final Skill sections manually**

Open `opscli/skills/templates/ops-amazon-product-data/SKILL.md` and verify:

```text
- CLI is described as the default route.
- MCP direct route is described as the fallback or explicit route.
- CLI authorization includes opscli auth token status and opscli auth login.
- CLI execution includes opscli scrape-do scenarios/run/job-status/export.
- CLI explains local login state -> remote MCP config/API Key exchange.
- CLI does not require scrape_do_spec_must_read or scrape_do_scenarios.
- MCP direct route includes auth_is_authenticated(), auth_mcp_login(), scrape_do_spec_must_read(), scrape_do_scenarios(), scrape_do_run(), scrape_do_job_status(), scrape_do_export().
- User-facing wording still hides provider names, API Keys, remote URLs, tokens, and internal endpoints.
```

- [ ] **Step 6: Report verification results**

In the final response, state exactly which commands passed or failed. If any command failed, include the relevant failure output and do not claim the work is complete.

---

## Self-Review Notes

- Spec coverage: the plan covers CLI default routing, MCP direct fallback, CLI authorization, MCP authorization, removal of universal MCP pre-steps, and user-facing secrecy rules.
- Placeholder scan: no TBD/TODO/fill-in placeholders remain.
- Type consistency: tests use only `Path`, strings, and local helper functions defined in the test file.
