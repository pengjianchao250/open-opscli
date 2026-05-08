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
- 同一失败在 5 分钟内已提交过反馈

### 触发流程

1. **检查错误响应中的 `feedback` 字段**：MCP `_err` 响应可能包含自动生成的 `feedback` 草案，优先以该草案为基底
2. **计算本次失败指纹并去重**：使用 `{source}:{tool}:{error.code}:{error.message}:{关键参数JSON}` 作为同会话去重指纹；5 分钟内已提交过则复用上次 `feedback_uuid`，不重复提交
3. **补充并校验必要字段**：
   - `title`：简短描述失败，如 `"query_simple 字段不存在"`
   - `content`：详细描述失败场景和现象
   - `execution_summary.failed_calls[0].call_params`：实际传入的关键参数；没有参数也写 `{}`
   - `execution_summary.failed_calls[0].reason`：基于上下文推断原因
   - `execution_summary.failed_calls[0].fix_suggestion`：修复建议或下一步
4. **调用反馈提交**：
   - MCP 环境：`feedback_submit(feedback_type="bug", title="...", content="...", execution_summary={...})`
   - CLI 环境：`opscli feedback submit --type bug --title "..." --content "..." --execution-summary-file summary.json`
5. **返回 feedback_uuid 给用户**，并继续处理原任务

如果反馈提交自身失败，只向用户说明反馈提交失败和原始错误，不要再次调用本 Skill 提交“反馈失败”的反馈。

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

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

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
