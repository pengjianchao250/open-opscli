# ASIN 取数鉴权回退与用户手册实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ASIN 刊登实时取数补齐个人 Polaris 鉴权失败后的托管 BJX Token 回退，并交付与实际 CLI/MCP 契约一致的两份用户手册。

**Architecture:** 保持 `BiReportDataClient` 为刊登鉴权唯一入口，在默认 `user` 模式内按个人 Polaris JWT、直接 `/api/auth/cli-token` exchange、OPS 托管 BJX Token 的顺序依次尝试。显式 `managed` 与 `bi_login` 模式不变；CLI、MCP 和类目 Top10 因复用该客户端自动获得相同行为。文档契约测试从源代码枚举和固定协议要求验证两份手册，避免命令说明漂移。

**Tech Stack:** Python 3.10+、httpx、Typer、pytest、Markdown。

## 全局约束

- 不新增公开 CLI/MCP 参数，不改变现有成功 envelope。
- 默认 `user` 模式必须优先保留当前用户 Polaris 权限，只有前两条路径失败后才能请求 BJX Token。
- 错误摘要不得包含 Token、Cookie、Session ID、用户名、密码或远端敏感响应正文。
- `managed` 与 `bi_login` 显式模式保持原行为。
- 两份手册只包含 `live-data`、`fetch-file`、`yicopy-keyword-engine`、`category-top` 及对应 MCP 工具，不提供 `collect` 调用。
- Python 新增注释和 docstring 使用中文；终端输出保持 GBK 安全。
- 不提交 `output/asin-data/live-basic-refresh-20260714/`。

---

### Task 1: 默认 user 模式增加 BJX Token 回退

**Files:**
- Modify: `opscli/asin_data/services/bi_report_data.py`
- Test: `tests/asin_data/test_bi_report_data.py`

**Interfaces:**
- Consumes: `_build_user_polaris_request_auth(refresh: bool)`、`_build_direct_polaris_request_auth()`、`_build_remote_polaris_bjx_request_auth()`。
- Produces: `_build_listing_request_auth(...) -> tuple[dict[str, str], dict[str, str]]` 的三级回退行为，公开签名不变。

- [ ] **Step 1: 编写个人 JWT 优先和直接 exchange 失败后 BJX 回退测试**

  在 `tests/asin_data/test_bi_report_data.py` 增加测试，使用现有 fake auth/response 辅助对象记录调用顺序；断言个人 JWT 成功时未访问 `DEFAULT_POLARIS_BJX_TOKEN_ENDPOINT`，Polaris 未注册或 `/api/auth/cli-token` 返回 500 时最终得到 `Authorization: Bearer managed-token`。

- [ ] **Step 2: 运行新增测试并确认 RED**

  Run: `uv run pytest tests/asin_data/test_bi_report_data.py -k "user_auth or bjx_fallback" -v`

  Expected: 新增的 fallback 测试失败，错误仍为 `POLARIS_USER_AUTH_MISSING`，证明缺失的是第三条回退路径。

- [ ] **Step 3: 实现最小三级回退**

  在 `_build_listing_request_auth()` 的直接 exchange 异常分支中调用 `_build_remote_polaris_bjx_request_auth()`；成功时通过 `_listing_browser_headers()` 和 `_cache_listing_auth()` 返回。第三条路径也失败或返回空时抛出 `AsinBiReportDataBusinessError("POLARIS_USER_AUTH_MISSING", ...)`，消息仅包含三条路径的脱敏异常摘要。

- [ ] **Step 4: 增加三路失败脱敏测试及显式模式回归断言**

  三路均失败时断言消息包含 `Polaris user auth is missing or invalid`、`direct token exchange failed`、`managed BJX token fallback failed`，且不包含测试中注入的 token/session/password 值。复用现有 managed、bi_login 测试确认两种模式没有进入 user 链路。

- [ ] **Step 5: 运行鉴权测试并确认 GREEN**

  Run: `uv run pytest tests/asin_data/test_bi_report_data.py -v`

  Expected: 文件内全部测试通过。

- [ ] **Step 6: 提交鉴权实现**

  Run: `git add opscli/asin_data/services/bi_report_data.py tests/asin_data/test_bi_report_data.py && git commit -m "fix: fallback asin listing auth to managed token"`

---

### Task 2: 编写 CLI 与 MCP 用户手册

**Files:**
- Create: `docs/guide/ASIN取数CLI命令手册.md`
- Create: `docs/guide/ASIN取数MCP工具手册.md`
- Create: `tests/asin_data/test_asin_data_manuals.py`

**Interfaces:**
- Consumes: `FileKey`、`LiveDataScope`、`LiveDataReturnMode` 和四个 MCP tool 的公开签名。
- Produces: 可直接供用户和 AI Skill 使用的稳定命令/工具契约，不产生运行时代码接口。

- [ ] **Step 1: 编写文档契约测试并确认 RED**

  测试读取两份目标 Markdown，断言 CLI 手册包含四个命令、MCP 手册包含四个工具；两份文档均包含成功/失败 JSON、Polaris 开关与鉴权恢复说明，并断言不存在字符串 `asin-data collect`。文档尚不存在时应因 `FileNotFoundError` 失败。

  Run: `uv run pytest tests/asin_data/test_asin_data_manuals.py -v`

  Expected: FAIL，原因是两份手册尚未创建。

- [ ] **Step 2: 编写 CLI 手册**

  文档覆盖安装升级、`polaris_enabled=true`、登录和 Token 检查；逐项列出 `live-data` 的 scope/return mode/日期/站点/OSS 参数，`fetch-file` 的六种 file key，yicopy 和 category-top 参数；给出可执行命令及源自现有 envelope 的成功/失败示例、退出码、常见错误和恢复动作。

- [ ] **Step 3: 编写 MCP 手册**

  文档覆盖远程 HTTP/SSE 与本地 stdio 的接入边界；逐项列出四个工具的参数类型、必填项和默认值；给出 `_ok`/`_err` 成功失败 envelope；说明调用方不传敏感 Token，个人 JWT 与 BJX 回退由服务内部处理。

- [ ] **Step 4: 运行文档契约测试并确认 GREEN**

  Run: `uv run pytest tests/asin_data/test_asin_data_manuals.py -v`

  Expected: 全部通过。

- [ ] **Step 5: 提交用户手册**

  Run: `git add docs/guide/ASIN取数CLI命令手册.md docs/guide/ASIN取数MCP工具手册.md tests/asin_data/test_asin_data_manuals.py && git commit -m "docs: add asin data cli and mcp manuals"`

---

### Task 3: 变更记录和整体回归验证

**Files:**
- Modify: `docs/change-log-pending.md`

**Interfaces:**
- Consumes: Task 1 的三级鉴权行为和 Task 2 的正式手册。
- Produces: 可发布的变更说明和定向验证证据。

- [ ] **Step 1: 更新待发布变更记录**

  将现有“设计、本阶段尚未修改运行时代码”描述更新为实际实现：默认 user 三级回退、显式模式不变、两份手册和契约测试，并写明敏感信息不会出现在错误消息中。

- [ ] **Step 2: 运行 ASIN 与 MCP 定向测试**

  Run: `uv run pytest tests/asin_data/test_bi_report_data.py tests/asin_data/test_asin_data_manuals.py tests/mcp/test_asin_data_tools.py -v`

  Expected: 全部通过。

- [ ] **Step 3: 运行语法和差异检查**

  Run: `uv run python -m compileall -q opscli/asin_data opscli/mcp/tools/asin_data.py`

  Run: `git diff --check`

  Expected: 两条命令退出码均为 0，无语法错误、尾随空格或冲突标记。

- [ ] **Step 4: 检查敏感信息和命令边界**

  Run: `rg -n "password|Bearer ey|polarisUserToken|asin-data collect" docs/guide/ASIN取数CLI命令手册.md docs/guide/ASIN取数MCP工具手册.md`

  Expected: 不出现真实密码、JWT、Cookie 或 `asin-data collect` 调用；仅允许说明“password/Token 不得传递”一类脱敏文字。

- [ ] **Step 5: 提交变更记录**

  Run: `git add docs/change-log-pending.md && git commit -m "docs: record asin listing auth fallback"`

