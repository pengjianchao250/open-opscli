# ops-amazon-rufus Skill 文档拆分提案

## 背景

`ops-amazon-rufus/SKILL.md` 当前同时承载前置条件、MCP 工具调用、Chrome CDP 排障、远程授权、问题来源、拒答改写、输出隐藏和文件边界。主文档过长，Agent 在执行时需要读取大量非当前任务必要的细则。

## 目标

将 `SKILL.md` 收敛为轻量入口，只保留：

- Skill 定位和触发范围
- 前置条件
- 精简主流程
- references 索引
- 数据文件与文件边界

将 Rufus 获取、MCP 调用、远程授权、登录确认、报告格式等细则拆分到 `references/`。

## 范围

本次修改覆盖：

- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`
- `opscli/skills/templates/ops-amazon-rufus/references/*.md`
- `.agents/skills/ops-amazon-rufus/SKILL.md`
- `.agents/skills/ops-amazon-rufus/README.md`
- `.agents/skills/ops-amazon-rufus/references/*.md`
- 相关文档断言测试

## 非目标

- 不修改 Rufus MCP 工具 schema
- 不修改 `opscli/amazon_rufus` 获取实现
- 不新增 Skill 下的 Python 脚本
- 不改变默认题库 JSON 数据

## 验收标准

1. `SKILL.md` 不再包含 MCP 工具长参数说明或完整远程授权状态机。
2. `references/rufus-mcp-workflow.md` 承载 Rufus 获取与 MCP 调用流程。
3. `references/remote-authorization.md` 承载远程授权偏好、Amazon 登录确认门和敏感信息规则。
4. 既有 `question-templates.md` 与 `rufus-report-formatting.md` 职责不被混写。
5. 模板目录与 `.agents` 已安装目录保持一致。
6. 测试覆盖文档结构和关键规则。
