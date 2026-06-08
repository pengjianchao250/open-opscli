# Amazon Rufus 删除 CDP 与 remote 链路

## 背景

Rufus 默认 MCP 获取已切到 `amazon_rufus_get -> RufusManager.get_backend`，但仓库仍保留 CDP 登录窗口、remote browser state 捕获、CLI CDP 参数和空答案触发登录恢复的分支。用户明确要求彻底删除 CDP，并要求空 `answers` 按正常结果处理。

## 目标

1. MCP 只暴露 `amazon_rufus_get`。
2. CLI 只保留 `opscli amazon-rufus get` 的后端/headless 获取入口。
3. 删除 Rufus CDP/remote 相关公开入口、参数、服务引用和当前流程文档。
4. 空答案正常写报告并返回 `answer_count=0`，不抛 `RUFUS_LOGIN_REQUIRED`。
5. 更新测试、Skill 文档和 `docs/change-log-pending.md`。

## 非目标

1. 不调整默认题库和报告格式。
2. 不重写 headless capture、SSE client 或 secret provider。
3. 不新增替代登录工具或额外配置项。

## 风险与控制

1. CLI 行为会破坏旧 CDP 参数兼容性；通过 help 和单元测试锁定新契约。
2. 删除 remote 工具会影响旧 Agent 编排；通过模板 Skill 和 `.agents` 副本文档同步降低误调用。
3. 空答案返回成功可能改变上层判断；通过报告路径、`answer_count=0` 和敏感字段过滤测试确认结果可消费。
