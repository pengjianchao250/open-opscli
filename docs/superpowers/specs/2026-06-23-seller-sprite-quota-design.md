# Seller Sprite Quota Design

## 背景

当前卖家精灵 MCP 已经对 `seller_sprite_run` 启用了每日限额控制，`run` 成功或失败响应里都会带顶层 `quota` 信息，但这套信息没有形成稳定的用户链路：

- 正式 CLI 只有 `scenarios`、`run`、`job-status`、`export`，无法单独查询今天剩余额度。
- Skill 文档没有要求 Agent 在回答结果时显式提示剩余额度。
- `job_status` 和 `export` 不消耗额度，但文档里没有明确这层边界。

结果是限额机制已经存在，但用户只能在原始 JSON 里被动看到 `quota`，主流程体验不完整。

## 目标

补齐卖家精灵额度展示流程，满足两个场景：

1. 用户执行前可以主动查询今日剩余额度。
2. 用户执行 `seller_sprite_run` 后，回答中默认提示剩余额度。

## 非目标

- 不调整现有基础日限额和长期日加额规则。
- 不改变 `seller_sprite_run` 现有顶层 `quota` 返回契约。
- 不让 `job_status`、`export`、`scenarios` 消耗额度。
- 不把额度信息混入业务 `summary` 文案。

## 方案

### 1. 限额层增加只读快照能力

在 `opscli/mcp/quota.py` 增加读取当前身份额度快照的公共能力。该能力复用现有：

- `QuotaPolicy`
- `QuotaIdentityResolver`
- `SQLiteQuotaStore`

返回结构继续对齐现有 `quota` 字段格式：

- `service`
- `limit`
- `used`
- `remaining`
- `failures`
- `reset_at`

该只读查询只读 SQLite，不执行 `reserve`，因此不会扣减次数。

### 2. 卖家精灵 MCP 增加 quota-status 工具

在 `opscli/mcp/tools/seller_sprite.py` 新增 `seller_sprite_quota_status`：

- 返回当前 MCP 用户的额度快照
- 无法识别用户身份时返回标准错误
- 复用 `quota.py` 的统一计算逻辑

注册后形成新的公开工具，但不纳入 `_quota_wrap` 的消耗名单。

### 3. 正式 CLI 增加 quota-status 命令

在正式 CLI 入口补上：

- `opscli seller-sprite quota-status`

对应链路：

- `opscli/seller_sprite/cli.py`
- `opscli/seller_sprite/remote_adapter.py`

CLI 继续透传远端 MCP 返回 JSON，不在 CLI 层重新拼接额度摘要，避免正式 CLI 和 MCP 返回口径分叉。

### 4. Skill 文档明确额度规则

更新：

- `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`

明确以下规则：

- `seller_sprite_run` 会消耗额度。
- `seller_sprite_scenarios`、`seller_sprite_job_status`、`seller_sprite_export`、`seller_sprite_quota_status` 不消耗额度。
- Agent 在 `seller_sprite_run` 成功或失败后，应在自然语言回复里补一句额度摘要：
  `今日额度：已用 X / Y，剩余 Z，重置时间 reset_at`
- `job_status` 和 `export` 默认不重复提示额度，避免轮询噪音。

## 影响范围

### 修改文件

- `opscli/mcp/quota.py`
- `opscli/mcp/tools/seller_sprite.py`
- `opscli/seller_sprite/remote_adapter.py`
- `opscli/seller_sprite/cli.py`
- `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- `tests/mcp/test_quota.py`
- `tests/mcp/test_seller_sprite_tools.py`
- `tests/seller_sprite/test_remote_adapter.py`
- `tests/seller_sprite/test_cli.py`

### 不修改文件

- 卖家精灵调度器与任务队列表结构
- `seller_sprite_run` 主业务执行流程
- 现有 MCP 全局限额策略配置结构

## 测试策略

采用 TDD：

1. 先为 `quota.py` 写只读快照测试，验证不扣次数、能读 bonus 日加额。
2. 再为 `seller_sprite_quota_status` 写 MCP 层失败测试和成功测试。
3. 再为 `remote_adapter` 与 CLI 写映射测试。
4. 之后补最小实现，直到相关测试全部通过。

## 风险与控制

- 风险：重复造一套 quota 结构，造成 `run` 返回和 `quota_status` 返回字段不一致。
  控制：统一复用 `quota.py` 的快照构造。
- 风险：误把只读查询纳入扣减链路。
  控制：只在 `seller_sprite_run` 上沿用现有 `_quota_wrap` 策略，不为新工具配置 policy。
- 风险：CLI 层单独拼接额度摘要，导致远端返回和正式命令展示不一致。
  控制：CLI 层只透传 JSON，额度摘要规则只写入 Skill 文档。
