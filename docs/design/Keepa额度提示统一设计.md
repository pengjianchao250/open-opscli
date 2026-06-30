# Keepa 额度提示统一设计

## 背景

`keepa_run` 与 `seller_sprite_run` 均由 MCP 限额中间件统一包装，成功或限额失败响应顶层已经包含 `quota.limit`、`quota.used`、`quota.remaining` 和 `quota.reset_at`。

当前卖家精灵 Skill 会把该额度快照转换为用户可读提示，Keepa Skill 则明确要求隐藏剩余额度，导致两者用户体验不一致。

## 设计

本次不修改 MCP 接口参数和返回结构，仅调整 Keepa Skill 的展示规范：

1. `keepa_run` 响应顶层存在 `quota` 时，在最终回复末尾提示：
   `今日额度：已用 used / limit，剩余 remaining，重置时间 reset_at`
2. 补充 `keepa_quota_status` 和 `opscli keepa quota-status` 的使用说明，支持用户执行前主动查询额度。
3. `keepa_job_status` 和 `keepa_export` 不重复提示额度，避免轮询和取文件阶段刷屏。
4. 只展示 MCP 每日调用次数；Keepa API Key、账号来源、`tokensLeft`、`tokensConsumed` 等账号级 token 信息继续隐藏。

## 变更范围

- `opscli/skills/templates/ops-keepa/SKILL.md`
- `opscli/skills/templates/ops-keepa/SKILL_MCP.md`
- Keepa MCP Skill 规范回归测试

不修改 `opscli/mcp/quota.py`、`keepa_run` 参数、MCP 返回结构及底层 Keepa token 预检逻辑。

## 验证

1. 测试 `keepa_spec_must_read` 返回的规范包含额度提示模板。
2. 测试规范明确区分 MCP 每日调用额度与 Keepa token 余额。
3. 运行 Keepa MCP、CLI 与 Skill 模板相关测试，确保既有接口行为不变。
