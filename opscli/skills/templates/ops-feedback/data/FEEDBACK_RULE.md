## 【铁律】工具调用失败自动反馈

> 生效范围：所有在 opscli 项目中工作的 AI Agent 会话。

**规则**：任何 `opscli` CLI 命令或 MCP Tool 调用失败后，AI Agent **必须在同一会话中立即调用 `ops-feedback` Skill 提交结构化反馈**，不得跳过、不得等待用户明确指示、不得在回复中仅描述错误而不提交。

**执行顺序**：
1. 工具调用返回 `success: false` 或抛出异常
2. 立即读取 `opscli/skills/templates/ops-feedback/SKILL.md`
3. 按 Skill 规范构造 `execution_summary`，重点提取：
   - `tool`：具体工具或命令
   - `call_params`：实际传入的关键参数
   - `error_message`：原始错误码和错误文本
   - `reason`：基于上下文推断的原因（不确定时标注"推测"）
   - `fix_suggestion`：已采用的修复方式或下一步建议
4. 调用 `feedback_submit`（MCP 模式）或 `opscli feedback submit`（CLI 模式）
5. 将 `feedback_uuid` 返回给用户，并继续处理原任务

**例外情况**（允许不提交反馈）：
- 认证类错误（`auth_login_start`、`auth_login_poll` 等预期内的未授权状态）
- 用户主动取消的操作（`KeyboardInterrupt`）
- 同一失败在 5 分钟内已提交过反馈（凭 `feedback_uuid` 去重）
