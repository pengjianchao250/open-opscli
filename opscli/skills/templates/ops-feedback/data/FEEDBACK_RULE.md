## 【铁律】工具调用失败自动反馈

> 生效范围：所有在 opscli 项目中工作的 AI Agent 会话。

**规则**：任何 `opscli` CLI 命令或 MCP Tool 调用失败后，AI Agent **必须在同一会话中立即调用 `ops-feedback` Skill 提交结构化反馈**，不得跳过、不得等待用户明确指示、不得在回复中仅描述错误而不提交。该规则只约束失败即时反馈；成功默认本地任务摘要，远端成功反馈默认关闭。

**失败即时反馈**：
- CLI 非 0、MCP `success=false`、抛出异常、远端错误码均视为失败
- 同一失败在 30 分钟内已提交过反馈时复用已有 `feedback_uuid`，不重复提交
- 去重窗口是滑动窗口：窗口内每次重复失败都会刷新 `last_seen` 并只累加本地 occurrence_count，持续复发的同一失败不会自动再次远端提交；需要让远端感知失败仍在持续时，由用户明确要求后重新提交
- 批量失败聚合：批量烟测、回归和多数据集扫描中的同根因 L3 失败必须在事件 JSON 中提供稳定 `feedback_group_key`；首条失败远端提交，后续同组失败复用已有 `feedback_uuid`；显式 group key 会覆盖变化的完整命令字符串和参数，避免每个数据集或参数变体拆成独立反馈
- 本地 guard 状态默认保留 24 小时；过期 failure 指纹和 L2 会话预算桶清理后，不再影响新任务判断
- 本地 guard 状态损坏时按空状态继续决策；重复失败记录缺少 `feedback_uuid` 时不得复用空 UUID，必须重新提交本次失败反馈
- 事件瘦身与敏感字段脱敏：`feedback_guard.py` 生成 fingerprint 前会脱敏 `token` / `cookie` / `authorization` / `password` / `secret` 等字段，截断大日志、大数组和大字典，并在 L3 决策中返回 `event_hygiene.fingerprint_payload_bytes`；默认 fingerprint payload 不超过 4096 bytes
- 事件分类避免误报：成功 warning 不进入 L3；`zero_rows` / `all_null` / `degraded` / `user_correction` 即使带 `error_message` 也按 L2 预算处理，只有硬失败信号进入 L3
- 认证轮询例外：`auth_login_start` / `auth_login_poll` 的预期未授权、待授权或轮询中状态由 guard 返回 `do_not_submit_expected_auth_state`，不提交远端反馈；认证服务异常和非预期错误仍按 L3 处理
- feedback_submit 自身失败时 fail-open：报告反馈提交失败，不递归提交，不阻塞原任务
- L3 新失败 guard 返回 `submit_remote=true` 且 `non_blocking=true`：Agent 仍必须先提交或复用反馈 UUID，但完成该最小动作后应继续主任务恢复、降级重试或交付本地摘要，不把反馈流程当成终止态
- 提交前优先运行 `scripts/feedback_guard.py decide --event-file event.json`；`event.json` 应包含 `session_id` / `thread_id` / `task_id`，批量同根因失败应包含 `feedback_group_key`；远端提交成功后运行 `scripts/feedback_guard.py record --event-file event.json --feedback-uuid <feedback_uuid>`，把失败指纹与会话级预算写入本地状态

**成功与批量场景**：
- 正常成功查询、成功引导、dry-run 和本地评估默认只写本地任务摘要或项目结果文件
- 只有用户明确要求、发布/审计门禁或 0 行/全空/降级/疑似数据问题需要 owner 处理时，才提交非失败类远端反馈
- 批量评估不为正常成功样本逐条提交反馈；失败按铁律即时提交，可疑结果合并后最多提交 1 条
- 非失败类远端反馈预算按 `session_id` / `thread_id` / `task_id` 隔离，避免一次任务耗尽后误伤后续任务

**行为回归门禁**：
- 查询类 Skill 和 Agent trace 评估必须检查成功不远端刷屏、失败不漏反馈、批量失败使用 `feedback_group_key` 聚合、feedback_submit 自身失败 fail-open
- guard 决策逻辑由仓库内 `tests/skills/test_feedback_guard.py` 回归覆盖；trace 级评估脚本（`success_feedback_remote_spam`、`success_local_summary_after_query`、`feedback_after_failed_query` 等规则）当前尚未落地，属于待建设项
- 新增查询 Skill 或批量扫描脚本时，应同步新增 trace 样例，证明不同大模型不会在成功路径提交大量低价值反馈，也不会在失败路径跳过铁律

**执行顺序**：
1. 工具调用返回 `success: false` 或抛出异常
2. 立即读取并遵循 `ops-feedback` Skill
3. 按 Skill 规范构造 `execution_summary`，重点提取：
   - `tool`：具体工具或命令
   - `call_params`：实际传入的关键参数
   - `error_message`：原始错误码和错误文本
   - `reason`：基于上下文推断的原因（不确定时标注"推测"）
   - `fix_suggestion`：已采用的修复方式或下一步建议
4. 调用 `feedback_submit`（MCP 模式）或 `opscli feedback submit`（CLI 模式）
5. 将 `feedback_uuid` 返回给用户，并继续处理原任务；若反馈提交自身失败，只报告该失败，不再递归提交反馈

**例外情况**（允许不提交反馈）：
- 认证类错误（`auth_login_start`、`auth_login_poll` 等预期内的未授权状态）
- `feedback_submit`、`feedback_detail`、`opscli feedback submit/detail` 自身失败，避免递归反馈
- 用户主动取消的操作（`KeyboardInterrupt`）
- 同一失败在 30 分钟内已提交过反馈（按工具名、关键参数、错误码和错误信息去重）
