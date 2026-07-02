# ops-amazon-product-data 授权链路与运行路径设计

## 背景

`ops-amazon-product-data` 是面向用户的 Amazon 商品结构化数据 Skill。当前 `SKILL.md` 把 `scrape_do_spec_must_read` 与 `scrape_do_scenarios` 写成通用前置步骤，导致 CLI 使用场景也被要求调用 MCP-only 工具。

代码事实显示：正式 CLI 入口是 `opscli scrape-do ...`；CLI 通过 `ScrapeDoRemoteAdapter` 映射到远端 MCP tools，并由 `McpConfigClient` 使用本地 `opscli auth` 登录态向 OPS 配置接口换取远端 MCP URL/API Key。Agent 不应该要求用户手动提供 API Key，也不应该在用户回复中暴露底层服务商、endpoint、token 或 API Key。

## 目标

更新 `ops-amazon-product-data/SKILL.md`，让未来 Agent 能按运行环境选择正确路径：默认优先正式 CLI，只有 MCP 直连场景才调用 `scrape_do_spec_must_read` 与 `scrape_do_scenarios`。

## 非目标

- 不修改 `opscli scrape-do` 命令实现。
- 不修改远端 MCP tools 实现。
- 不新增 Amazon 商品数据场景。
- 不暴露底层第三方服务商、内部 endpoint 或 API Key。

## 推荐方案：运行路径选择结构

### CLI 路径（默认优先）

当当前环境可执行本地正式命令，且用户未明确要求 MCP 直连时，Skill 应优先指导 Agent 使用 CLI：

1. 先通过 `ops-auth` 的 CLI 模式确认认证状态。
2. 使用 `opscli auth token status` 检查登录态。
3. 未登录或 token 无效时，执行 `opscli auth login` 完成授权。
4. 使用 `opscli scrape-do scenarios` 查看支持场景。
5. 使用 `opscli scrape-do run <scenario> --site <site> --params '<json>'` 执行采集。
6. 需要复核或导出时，使用 `opscli scrape-do job-status <job_id>` 与 `opscli scrape-do export <job_id>`。

CLI 链路说明必须写清楚：CLI 内部会使用本地登录态向 OPS 获取远端 MCP 配置/API Key，然后调用远端 MCP 服务。Agent 不要要求用户传 API Key，不要手动拼接远端 MCP URL。

CLI 路径不要求调用 `scrape_do_spec_must_read` 或 `scrape_do_scenarios`。

### MCP 直连路径

当用户明确要求 MCP，当前宿主只能调用 MCP tools，或 CLI 首次正式调用不可用时，Skill 才进入 MCP 直连路径：

1. 先通过 `ops-auth` 的 MCP 模式确认认证状态。
2. 调用 `auth_is_authenticated()` 检查登录态。
3. 未登录时调用 `auth_mcp_login()` 完成授权。
4. 首次使用当前 MCP 能力时，调用 `scrape_do_spec_must_read()` 与 `scrape_do_scenarios()`。
5. 使用 `scrape_do_run()` 执行采集。
6. 需要复核或导出时，使用 `scrape_do_job_status()` 与 `scrape_do_export()`。

MCP 路径仍然不得要求用户传认证令牌或 API Key。

## 文档结构调整

`SKILL.md` 应调整为以下主要结构：

1. Overview：保持用户视角，称为 Amazon 商品数据接口。
2. 适用场景：保留现有 ASIN、Offer Listing、搜索、评论字段、导出场景。
3. 对用户的表达规则：保留脱敏和隐藏内部信息规则。
4. 运行路径选择：新增 CLI 优先、MCP 直连替代的判断规则。
5. CLI 授权与执行流程：新增正式 CLI 命令流程和 CLI→远端 MCP 配置/API Key 说明。
6. MCP 授权与执行流程：将 `scrape_do_spec_must_read` / `scrape_do_scenarios` 限定为 MCP 直连路径。
7. 场景选择与参数：保留现有 scenario 表和参数规则。
8. 输出文件说明、评论字段说明、示例参数、用户回复模板、常见错误、安全与脱敏：保留并按新路径微调措辞。

## 测试策略

采用文档行为测试，锁定 Skill 的关键说明，避免后续回归：

- `SKILL.md` 必须包含 CLI 优先路径。
- `SKILL.md` 必须包含 `opscli auth token status`、`opscli auth login`、`opscli scrape-do run`。
- `SKILL.md` 必须说明 CLI 使用本地登录态换取远端 MCP 配置/API Key。
- `SKILL.md` 不得把 `scrape_do_spec_must_read` 与 `scrape_do_scenarios` 描述为通用前置步骤。
- `SKILL.md` 必须把 `scrape_do_spec_must_read` 与 `scrape_do_scenarios` 限定在 MCP 直连路径。
- `SKILL.md` 必须包含 MCP 授权检查：`auth_is_authenticated()` 与 `auth_mcp_login()`。

## 错误处理与反馈

- 如果 `opscli` CLI 命令或 MCP Tool 调用失败，遵循项目 AGENTS.md：立即读取 `opscli/skills/templates/ops-feedback/SKILL.md` 并提交结构化反馈。
- 认证类预期状态和用户主动取消按 AGENTS.md 例外处理。
- 用户可见错误摘要保留业务诊断信息，但去掉 token、API Key、本地绝对路径和内部 endpoint。

## 验收标准

- 文档测试先失败，再通过。
- `ops-amazon-product-data/SKILL.md` 明确区分 CLI 与 MCP 直连。
- CLI 路径不再要求 `scrape_do_spec_must_read` / `scrape_do_scenarios`。
- MCP 路径包含认证状态检查与登录动作。
- CLI 路径包含本地登录态换取远端 MCP 配置/API Key 的说明。
- 对用户输出规则继续隐藏底层服务商、内部 endpoint、token 和 API Key。
