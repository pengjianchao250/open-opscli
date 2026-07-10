---
name: ops-feedback
description: Use when submitting or querying Aukeys opscli feedback, or when an opscli CLI/MCP call fails unexpectedly and needs a structured execution summary.
---

# ops-feedback

用于保存用户反馈，特别是 Skill、CLI、MCP 工具调用失败后的结构化复盘。反馈会提交到 ops 后端，并保存到 `polaris_ops_metrics.dm_user_feedbacks`。

---

## 何时使用本 Skill

- 用户明确要求“提交反馈”“保存反馈”“记录问题”“反馈这次失败”
- Skill 执行后需要把本次过程沉淀为反馈
- 工具调用失败，需要记录具体调用参数、报错信息、原因和修复建议
- 需要按 `feedback_uuid` 查询已提交反馈

**特别注意**：当 AGENTS.md 【铁律】工具调用失败自动反馈 生效时，AI Agent 必须在工具调用失败后**立即自动调用**本 Skill，无需等待用户指示。

---

## 自动触发规则（Agent 工具调用失败后）

当 AI Agent（Codex / Claude Code / OpenCode）调用 `opscli` CLI 命令或 `opscli` MCP Tool 失败时，**必须**按以下流程自动触发反馈提交：

## 分级反馈策略

反馈用于保留高信号证据，不应阻塞主任务或为每个低价值成功动作产生一条消息。默认采用四级策略：

| 层级 | 场景 | 处理方式 |
|------|------|----------|
| L0 | dry_run、本地只读检索、仅生成计划 | 不提交 |
| L1 | 成功查询、成功引导、批量评估中的正常样本 | 成功默认本地任务摘要；远端成功反馈默认关闭 |
| L2 | 0 行、全空值、降级重试、用户纠错、可疑数据 | 同一任务内合并证据后最多提交 1 条 `query_result` 或 `data_issue` |
| L3 | opscli CLI/MCP 失败、异常、远端错误码 | 失败即时反馈，必须按 AGENTS 铁律提交 `bug` |

执行规则：

- 失败即时反馈：任何 `opscli` CLI 非 0、MCP `success=false`、异常或远端错误码必须立即提交，不能等到任务结束。
- 成功默认本地任务摘要：成功查询、成功引导和正常批量样本只在本地执行总结或项目产物中记录 `successful_calls`，默认不调用 `feedback_submit` / `opscli feedback submit`。
- 远端成功反馈默认关闭：只有用户明确要求提交、进入发布/审计门禁、或 L2 可疑结果需要产品/数据 owner 处理时，才提交 `query_result`；同一任务最多 1 条。
- 批量评估：评估、烟测、回归和多数据集扫描默认只写本地结果文件；失败按 L3 即时提交，可疑结果按 L2 合并提交，正常成功样本不远端提交。
- 批量失败聚合：批量烟测、回归和多数据集扫描发现同一根因的多条 L3 失败时，事件 JSON 必须显式传 `feedback_group_key`，首条失败远端提交，后续同组失败在 30 分钟内复用同一个 `feedback_uuid` 并在本地累加 occurrence_count。
- 抽样：抽样默认进入本地评估集或回归候选，不等于远端提交；只有开启审计/发布门禁或用户要求完整审计时才把抽样结果提交到远端。
- 去重：同一失败指纹在 30 分钟内只提交 1 次，后续复用 `feedback_uuid` 并在本地执行总结中累加 occurrence_count。注意去重是滑动窗口：窗口内每次重复失败都会刷新 `last_seen`，持续复发的同一失败不会自动再次远端提交，occurrence_count 仅本地可见；若需要让远端感知失败仍在持续发生，需用户明确要求后重新提交并刷新 `feedback_uuid`。
- 本轮会话最多：非失败类远端反馈默认最多 1 条；超过后必须只写本地任务摘要或项目结果文件，除非用户明确要求继续提交。
- fail-open：`feedback_submit` / `opscli feedback submit` 自身失败时只记录并告知，不再递归提交，也不得阻塞原查询或评估流程。
- Token 预算：`execution_summary` 只保留关键参数、错误码、根因和修复建议；大结果、日志和表格只放附件路径或摘要。
- 事件瘦身与敏感字段脱敏：`feedback_guard.py` 用于生成 fingerprint 的事件副本会自动脱敏 `token` / `cookie` / `authorization` / `password` / `secret` 等字段，截断大字符串、大数组和大字典，并返回 `event_hygiene.fingerprint_payload_bytes`，避免 guard 自身消耗大量 token 或泄露敏感值。

### 可执行守门脚本

优先使用 `scripts/feedback_guard.py` 做提交前判断，避免靠 Agent 记忆手工控制反馈量。该脚本不提交远端反馈，只输出决策并维护本地去重/预算状态。

### 低 token 快速路径

先 guard 后 payload：除用户明确要求直接提交或查询反馈详情外，先把失败或可疑事件写成小 JSON，并运行 `feedback_guard.py decide`。只有 `submit_remote: true` 时，才构造完整反馈 payload、整理完整 `execution_summary`，并再读取 `references/cli.md` 或 `references/mcp.md` 执行提交。

- 返回 `agent_action: reuse_existing_feedback_uuid`：复用已有 `feedback_uuid`，不要构造完整 `execution_summary`，不要读取 CLI/MCP 长参考，不要重复提交。
- 返回 `agent_action: write_local_execution_summary`：只写本地任务摘要或项目结果文件，不远端提交。
- 返回 `agent_action: fail_open_no_recursive_feedback`：只报告反馈通道失败，继续原任务。
- 返回 `submit_remote: true`：再进入运行模式判断，补齐最小必要字段并提交。

典型流程：

1. 把本次事件保存为小 JSON，字段包含 `outcome`、`source`、`tool` 或 `command_name` / `mcp_tool_name`、`call_params`、`error_code`、`error_message`、`needs_owner_action`，以及能标识本轮任务的 `session_id` / `thread_id` / `task_id`；批量同根因失败还要传稳定的 `feedback_group_key`。
2. 执行 `python3 scripts/feedback_guard.py decide --event-file event.json`。
3. 只有返回 `submit_remote: true` 时才继续构造完整 payload 并调用 `feedback_submit` 或 `opscli feedback submit`。
4. 远端提交成功后执行 `python3 scripts/feedback_guard.py record --event-file event.json --feedback-uuid <feedback_uuid>`，写入失败指纹或 L2 预算。
5. 如果返回 `agent_action: reuse_existing_feedback_uuid`，直接复用输出的 `feedback_uuid`，不要重复提交。
6. 如果返回 `agent_action: fail_open_no_recursive_feedback`，说明反馈通道自身失败，只报告并继续原任务，不递归反馈。

`feedback_guard.py` 的默认策略：

- L1 成功事件返回 `write_local_execution_summary`，不远端提交。
- L2 可疑数据只有 `needs_owner_action: true` 且本轮非失败预算未用完时才允许提交 1 条。
- L2 非失败预算按 `session_id` / `thread_id` / `task_id` 隔离；未传时使用兼容的 `default` 预算桶。
- 事件分类先看硬失败信号：`outcome=failure`、`success=false`、非 0 `exit_code` 或明确 `error_code` 才进入 L3；成功事件里的 warning 文本不触发远端 bug，`zero_rows`、`all_null`、`degraded`、`user_correction` 即使带 `error_message` 也按 L2 预算处理。
- L3 失败优先使用显式 `feedback_group_key` 生成稳定 fingerprint；显式 group key 会覆盖变化的 `tool` / `command_name` 字符串和 `call_params`，用于聚合同根因批量失败；未传时回退到 `{source, tool, error_code, error_message, call_params}`，30 分钟内复用已有 `feedback_uuid`。
- fingerprint 输入会自动做事件瘦身和敏感字段脱敏；`decide` 的 L3 输出包含 `event_hygiene`，其中 `fingerprint_payload_bytes` 默认不超过 4096，用于检查低 token 快速路径是否仍然成立。
- 本地 guard 状态默认保留 24 小时；过期 failure 指纹和 L2 会话预算桶会在下一次 `decide` / `record` 时清理，避免状态文件长期膨胀或旧会话预算误拦截。
- 本地 guard 状态损坏时按空状态继续决策，不让状态文件解析错误阻塞原任务；若重复失败记录缺少 `feedback_uuid`，不得复用空 UUID，必须重新提交本次 L3 失败并刷新状态。
- `auth_login_start` / `auth_login_poll` 等认证流程中的预期未授权、待授权或轮询中状态返回 `do_not_submit_expected_auth_state`，不远端提交，避免登录轮询产生反馈风暴；认证服务 5xx、异常崩溃等非预期错误仍按 L3 处理。
- L3 新失败返回 `submit_remote=true` 且 `non_blocking=true`：Agent 必须先提交或复用反馈 UUID，但完成最小反馈动作后要继续原任务恢复、降级重试或交付本地摘要，不把反馈流程当成终止态。
- 反馈提交/查询自身失败直接 fail-open。

### 行为回归门禁

反馈策略必须能被 Agent/Skill trace 评估复现，不能只写在说明文档里。维护 `ops-dataset-query`、`ops-query-wizard` 或批量评估脚本时，必须把以下行为纳入本地 trace 或 benchmark 评估：

- 成功查询、成功引导和正常批量样本只写本地执行摘要，不远端提交普通 `query_result`。
- `opscli` CLI/MCP 失败仍必须触发 `ops-feedback` 或先经过 `feedback_guard.py` 后提交/复用 `feedback_uuid`。
- 批量同根因失败必须带稳定 `feedback_group_key`，评估中应能看到后续重复失败复用同一组反馈，而不是逐条远端提交。
- `feedback_submit` / `opscli feedback submit` 自身失败只能 fail-open，不能递归提交反馈。

`feedback_guard.py` 的决策逻辑（分级、去重、预算、脱敏、fail-open）由仓库内 `tests/skills/test_feedback_guard.py` 回归覆盖。trace 级评估脚本（检查 `success_feedback_remote_spam`、`success_local_summary_after_query`、`feedback_after_failed_query` 等规则）当前尚未落地，属于待建设项；新增或修改查询类 Skill 时，应同步补充对应 trace 样例与检查规则，避免不同大模型在成功路径刷屏、失败路径漏报或批量扫描中产生 feedback 风暴。

### 触发条件

满足以下任一条件即触发：
- MCP Tool 返回 `{"success": false, ...}`
- MCP Tool 抛出未捕获异常
- CLI 命令返回非 0 退出码
- CLI 命令输出包含 `REMOTE_BUSINESS_ERROR`、`REMOTE_HTTP_ERROR`、`INVALID_PAYLOAD` 等错误码

### 不触发的情况

- `auth_login_start`、`auth_login_poll` 等认证流程中的预期未授权状态
- `feedback_submit`、`feedback_detail`、`opscli feedback submit/detail` 自身失败，避免递归反馈
- 用户主动取消（`KeyboardInterrupt`）
- 同一失败在 30 分钟内已提交过反馈

### 触发流程

1. **检查错误响应中的 `feedback` 字段**：MCP `_err` 响应可能包含自动生成的 `feedback` 草案，优先以该草案为基底
2. **计算本次失败指纹并去重**：批量同根因失败优先使用 `feedback_group_key`，并忽略同组事件中变化的完整命令字符串和参数；未传时使用 `{source}:{tool}:{error.code}:{error.message}:{关键参数JSON}` 作为去重指纹；30 分钟内已提交过则复用上次 `feedback_uuid`，不重复提交
3. **补充并校验必要字段**：
   - `title`：简短描述失败，如 `"query_simple 字段不存在"`
   - `content`：详细描述失败场景和现象
   - `execution_summary.failed_calls[0].call_params`：实际传入的关键参数；没有参数也写 `{}`
   - `execution_summary.failed_calls[0].reason`：基于上下文推断原因
   - `execution_summary.failed_calls[0].fix_suggestion`：修复建议或下一步
   - `skill_name`：触发反馈的 Skill 名称；由某个 Skill 执行产生的反馈必须传顶层参数
   - `skill_version`：触发反馈的 Skill 版本；能从 Skill 的 `VERSION.json`、frontmatter 或已安装记录读取时必须传顶层参数
   - `command_name` / `mcp_tool_name`：按实际失败入口至少填写一个；CLI 失败填 `command_name`，MCP 失败填 `mcp_tool_name`
4. **调用反馈提交**：
   - MCP 环境：`feedback_submit(feedback_type="bug", title="...", content="...", skill_name="...", skill_version="...", mcp_tool_name="...", execution_summary={...})`
   - CLI 环境：`opscli feedback submit --type bug --title "..." --content "..." --skill-name "..." --skill-version "..." --command-name "..." --execution-summary-file summary.json`
5. **返回 feedback_uuid 给用户**，并继续处理原任务

如果反馈提交自身失败，按 fail-open 处理：只向用户说明反馈提交失败和原始错误，不要再次调用本 Skill 提交“反馈失败”的反馈，不得阻塞原任务继续。

### 接口参数规范

所有提交都必须遵循 `opscli feedback` / `feedback_submit` 的接口结构，优先使用顶层参数，不要只把关键字段塞进 `context`。

| 字段 | 要求 |
|------|------|
| `feedback_type` | 必填；只能是 `bug` / `feature` / `data_issue` / `ux` / `docs` / `query_result` / `other` |
| `title` | 必填；不超过 200 字 |
| `content` | 必填；描述失败场景、用户影响、已采取动作 |
| `severity` | 必填或使用默认 `medium`；只能是 `low` / `medium` / `high` / `critical` |
| `source` | 必填或使用通道默认值；CLI 用 `cli`，MCP Tool 用 `mcp`，Skill 主动沉淀用 `skill` |
| `payload` | 可选；必须是 JSON 对象，保存原始业务输入、期望与实际结果 |
| `context` | 可选；必须是 JSON 对象，只放补充上下文，例如 `cwd`、`agent`、`workflow`、`request_id` |
| `execution_summary` | 必填；必须是 JSON 对象，包含 `summary`、`failed_calls`、`successful_calls`、`final_resolution` |
| `attachments` | 可选；必须是 JSON 数组，只保存文件路径、URL、日志摘要等引用 |
| `skill_name` | Skill 触发或 Skill 执行失败时必填顶层参数，例如 `ops-dataset-query` |
| `skill_version` | Skill 触发或 Skill 执行失败时必填顶层参数；未知时先查该 Skill 的 `VERSION.json`，仍未知才写 `unknown` |
| `command_name` | CLI 失败时必填顶层参数，例如 `opscli query simple` |
| `mcp_tool_name` | MCP Tool 失败时必填顶层参数，例如 `query_simple` |

`app_version` 和 `client_version` 不要手工传入，不要写入示例文件；它们由当前运行的 `aukeys-opscli` 自动写入，必须以工具实际版本为准。

如果同时写顶层参数和 `context`，顶层参数是接口规范字段；`context` 只能作为补充信息，不能替代 `skill_name`、`skill_version`、`command_name`、`mcp_tool_name`。

### 从错误响应构造 execution_summary

如果错误响应中包含 `feedback` 草案，必须先补齐并校验其 `execution_summary` 后再提交。否则按以下模板构造：

```json
{
  "summary": "调用 {tool_name} 失败，自动提交反馈。",
  "failed_calls": [
    {
      "tool": "MCP → {tool_name}({参数摘要})",
      "call_params": {实际传入参数},
      "error_message": "{error.code}: {error.message}",
      "reason": "基于上下文推断的原因（不确定时标注'推测'）",
      "fix_suggestion": "已采用的修复方式或下一步建议"
    }
  ],
  "successful_calls": [],
  "final_resolution": "已提交反馈 {feedback_uuid}，等待处理。"
}
```

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。除用户明确要求查询/提交反馈外，先执行低 token 快速路径；只有 guard 返回 `submit_remote: true` 后，才读取 CLI/MCP 参考并提交。

优先级如下：

1. 如果用户明确要求 CLI 或 MCP，直接遵循用户指定
2. 原始失败来自 MCP Tool 时，优先使用 MCP，并读取 `references/mcp.md`
3. 原始失败来自 CLI 命令时，优先使用 CLI，并读取 `references/cli.md`
4. 本地终端可执行交付命令、当前就在 `opscli` 项目、需要验证 CLI 行为时，默认使用 CLI，并读取 `references/cli.md`
5. 当前任务本身基于 MCP Tool 协作，或明显无法直接走本地 CLI 时，使用 MCP，并读取 `references/mcp.md`
6. 首选通道提交失败时，只允许切换另一个通道重试一次；重试仍失败则停止，不再递归提交反馈
7. CLI 与 MCP 都不可用时，提示用户先安装或配置 `aukeys-opscli`

---

## 提交前强制总结

提交反馈前，必须整理 `execution_summary`。如果本次发生失败工具调用，`failed_calls` 必须逐条包含以下字段：

| 字段 | 要求 |
|------|------|
| `tool` | 具体工具或命令，例如 `Bash → opscli query simple --table-id 1 --json '...' --run --pretty` |
| `call_params` | 具体关键参数和值，不能只写“参数错误”；字段名、table_id、filters、metrics 等要展开 |
| `error_message` | 原始错误码和错误文本，例如 `REMOTE_BUSINESS_ERROR: 字段不存在: original_price` |
| `reason` | 基于 metadata、接口规则、上下文推断出的原因；不确定时必须标注“推测” |
| `fix_suggestion` | 已采用的修复方式，或下一步建议 |

推荐结构：

```json
{
  "summary": "本次通过 ops-dataset-query 查询数据，simple 接口因字段识别失败，最终改用 build。",
  "failed_calls": [
    {
      "tool": "Bash → opscli query simple --table-id 1 --json '...' --run --pretty",
      "call_params": {
        "table_id": 1,
        "metrics": [
          {
            "field": "original_price",
            "aggregation": "SUM",
            "alias": "f_original_price"
          }
        ]
      },
      "error_message": "REMOTE_BUSINESS_ERROR: 字段不存在: original_price",
      "reason": "简化接口的 field 参数传了 field_name，但服务端未能识别；metadata 中该字段完整 origin_name 是 ds_d35ac6f3910c.original_price。",
      "fix_suggestion": "改用 opscli query build 的 --dimension/--metric 参数形式，由 CLI 自动完成字段映射。"
    }
  ],
  "successful_calls": [],
  "final_resolution": "已通过 build 查询完成任务。"
}
```

没有失败工具调用时，`failed_calls` 使用空数组，但仍要写 `summary` 和 `final_resolution`。

### 成功默认本地任务摘要模板

成功查询或引导流程默认只写本地任务摘要，不远端提交。多轮查询合并到 `successful_calls`，在最终回复、项目结果文件或本地 run artifact 中保存；只有用户明确要求、发布/审计门禁或 L2 可疑结果需要 owner 处理时，才把该摘要作为 `query_result` 远端提交。

```json
{
  "summary": "本次任务完成 4 次 query_simple 查询，均成功返回；其中 1 次为 0 行，已提示用户放宽筛选。",
  "failed_calls": [],
  "successful_calls": [
    {"tool": "query_simple", "table_id": 1, "result": "success, 20 rows"},
    {"tool": "query_simple", "table_id": 15, "result": "success, 0 rows, user_confirmed_filter_too_strict"}
  ],
  "final_resolution": "已输出分析结论；成功查询只写本地任务摘要，未远端提交。"
}
```

---

## 阅读入口

- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`

---

## 使用原则

- 所有反馈提交必须走 `opscli feedback submit` 或 `feedback_submit`，禁止直接拼接后端 HTTP 请求
- 提交内容必须是结构化 JSON，不要只写一句自然语言描述
- 使用错误响应中的 `feedback` 草案时，必须删除 `_hint` 等非提交字段
- 失败复盘必须优先保留原始错误信息，再写分析和建议
- 不要在反馈中写入密码、Token、Cookie、私钥等敏感信息
- 附件只保存引用信息，不上传大文件
