# SellerSprite 普通任务两段式异步与批量跟踪实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将普通 `seller_sprite_run` 改成持久化入队后立即返回 `job_id/state/position`，并支持 Agent 对一个或多个普通任务进行有界状态跟踪。

**Architecture:** 继续复用现有 SQLite 队列和独立后台 scheduler。`run` 只负责认证、审计、入队和启动 worker；单任务与批量状态工具共享最多 30 秒的长轮询语义；Listing Analysis 保持现有 submit/status/result 三段式。

**Tech Stack:** Python 3.10+、FastMCP、Typer、asyncio、SQLite、pytest。

## Global Constraints

- `seller_sprite_run` 入队成功后立即返回，不再等待 queued/running 任务完成。
- 单次状态等待范围为 `0..30` 秒，每 5 秒读取一次，终态提前返回，到期返回最新 pending 状态。
- 批量状态支持 1–50 个普通任务 ID，去重并保持首次出现顺序。
- 批量查询先校验所有任务归属；任一越权、缺失或 Listing Analysis 任务均整批拒绝。
- Agent 同轮累计跟踪 90–120 秒；queued、running、ready=false 和等待窗口到期都不是失败。
- 状态查询和 export 不消耗 SellerSprite 提交额度，不得重复调用 `seller_sprite_run` 刷新状态。
- 请求取消不取消、失败或关闭后台 scheduler/持久化任务。
- Listing Analysis 保持现有三段式，不纳入普通批量状态工具。
- 使用仓库虚拟环境执行：`.\.venv\Scripts\python.exe ...`。
- 不提交、不推送。

---

### Task 1: `run` 入队后立即返回

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

**Interfaces:**
- Produces: `seller_sprite_run(...) -> {success: true, data: queued_status}`，其中 queued status 保留 `job_id/state/stage/position/created_at`。

- [ ] 先把旧“等待成功”和“running 8 分钟后返回”测试替换为立即返回测试。
- [ ] 使用 `job_status()` 被调用即抛断言的 scheduler，证明 `run` 不再隐藏轮询。
- [ ] 运行测试并确认旧实现按预期失败。
- [ ] 入队后直接 `_ok(queued_status)`。
- [ ] 删除旧 8 分钟等待常量、helper、测试 fixture 和无用 import。
- [ ] 运行认证、额度、审计顺序、入队失败补偿与立即返回测试。

### Task 2: 单任务有界等待与任务归属保护

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

**Interfaces:**
- Produces: `seller_sprite_job_status(job_id: str, wait_seconds: int = 0) -> dict`。
- Produces: 通用任务所有者校验，供普通 status、批量 status、export 和 Listing Analysis wrapper 复用。

- [ ] 先增加本人/跨用户/缺用户/缺记录授权测试，以及 export 不能绕过授权的测试。
- [ ] 先增加立即读取、提前终态、30 秒到期、上限封顶、负数归零、取消传播、scheduler 不关闭测试。
- [ ] 运行测试并确认按预期失败。
- [ ] 泛化 Listing Analysis owner helper，同时保留场景约束 wrapper。
- [ ] 使用 monotonic deadline 与 `min(5, remaining)` 实现有界等待。
- [ ] 正数且非终态时幂等启动/复用 scheduler；不关闭 scheduler，不捕获 `CancelledError`。
- [ ] 普通 export 接入相同所有者校验。
- [ ] 运行单任务、授权、export 与 Listing Analysis 回归测试。

### Task 3: 多任务批量状态查询

**Files:**
- Modify: `opscli/mcp/tools/seller_sprite.py`
- Test: `tests/mcp/test_seller_sprite_tools.py`

**Interfaces:**
- Produces: `seller_sprite_jobs_status(job_ids: list[str], wait_seconds: int = 0) -> dict`。
- Response data: `ready`、`summary.total/queued/running/succeeded/failed`、有序 `jobs`。

- [ ] 先测试空列表、超过 50、去重保序、越权整批拒绝、Listing Analysis 拒绝。
- [ ] 先测试混合状态汇总、全部终态提前返回、窗口到期返回最新状态、取消不影响后台任务。
- [ ] 运行测试并确认按预期失败。
- [ ] 实现 ID 规范化、批量预授权、共享轮询和 summary 构建。
- [ ] 将工具加入公开注册列表，继续隐藏 `seller_sprite_start`。
- [ ] 运行批量状态与现有 Listing Analysis 测试。

### Task 4: MCP Schema、适配器与 CLI

**Files:**
- Modify: `opscli/seller_sprite/remote_adapter.py`
- Modify: `opscli/seller_sprite/cli.py`
- Test: `tests/mcp/test_tools.py`
- Test: `tests/seller_sprite/test_remote_adapter.py`
- Test: `tests/seller_sprite/test_cli_split.py`

**Interfaces:**
- Produces: `SellerSpriteRemoteAdapter.job_status(job_id, wait_seconds=0)`。
- Produces: `SellerSpriteRemoteAdapter.jobs_status(job_ids, wait_seconds=0)`。
- Produces CLI: `job-status JOB_ID --wait-seconds 0..30`。
- Produces CLI: `jobs-status JOB_ID... --wait-seconds 0..30`。

- [ ] 先增加 MCP Schema、adapter 精确转发、CLI 默认值/范围/帮助文本和多 ID 顺序测试。
- [ ] 运行测试并确认按预期失败。
- [ ] 扩展远端适配器和正式 CLI。
- [ ] 确认 `run` 不暴露等待参数、`seller_sprite_start` 仍不公开。
- [ ] 运行 Schema、adapter 和 CLI 聚焦测试。

### Task 5: Skill 与正式文档

**Files:**
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- Modify: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- Modify if needed: `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`
- Modify: `docs/spec/卖家精灵MCP接口直连接入说明.md`
- Modify: `docs/change-log-pending.md`
- Test: `tests/mcp/test_seller_sprite_tools.py`

- [ ] 先扩展规范加载测试，锁定立即返回、单/批量跟踪、30 秒、90–120 秒、pending 非失败、跨轮复用和 Listing Analysis 例外。
- [ ] 运行测试并确认旧文档按预期失败。
- [ ] 更新两份 SellerSprite Skill，删除 queued 无限代等、running 8 分钟代等和 timeout duration 旧说明。
- [ ] 更新正式 MCP 接入说明，加入单任务和多任务示例。
- [ ] 在 pending changelog 顶部追加本次变更和回滚说明，不改写历史记录。
- [ ] 运行规范加载测试。

### Task 6: 验证与审查

- [ ] 运行 `./.venv/Scripts/python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -q`。
- [ ] 运行 `./.venv/Scripts/python.exe -m pytest tests/mcp/test_tools.py -q`。
- [ ] 运行 `./.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py -q`。
- [ ] 运行队列和 scheduler 回归测试。
- [ ] 运行 `./.venv/Scripts/python.exe -m pytest -q`。
- [ ] 先读取 MCP server CLI help，再按用户指定的 `./.venv/Scripts/python.exe -m opscli.mcp.server xxxx` 形式做无副作用本地验证。
- [ ] 检查 `git diff --check`、`git diff`、`git status`。
- [ ] 完成最终代码审查；如实区分既有 `seller-sprite-debug` 基线失败与本次回归。
