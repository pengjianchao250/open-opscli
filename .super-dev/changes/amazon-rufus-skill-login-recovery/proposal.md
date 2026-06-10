# amazon-rufus-skill-login-recovery Proposal

## 背景

`amazon_rufus_get` 默认走 MCP 后端/headless 链路，但在以下错误时，用户需要一个统一的可恢复路径：

- `RUFUS_HEADLESS_REQUEST_ERROR`
- `RUFUS_HEADLESS_CAPTURE_ERROR`
- `RUFUS_SECRET_NOT_READY`

当前 Skill 文档对这些错误分支不统一，且部分历史文档把 CDP 删除作为当前流程结论。新需求要求：三类错误统一走 CDP 登录流程，并且每次 Skill 调用最多触发一次登录，超过后直接报错。

## 目标

1. `SKILL.md` 保持轻量入口，只写默认 MCP、三类错误恢复和一次登录护栏。
2. `references/rufus-mcp-workflow.md` 写完整流程：错误触发集合、运行态记录、CDP 登录、登录后重试、二次失败处理。
3. 模板目录和 `.agents` 已安装目录保持一致。
4. 不在 Skill 目录新增 Rufus 获取脚本。
5. 不修改 MCP/CLI 代码。

## 非目标

1. 不把 CDP 重新变成 MCP 默认路径。
2. 不新增 MCP 工具或参数。
3. 不持久保存本次登录恢复状态。
4. 不输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。

## 设计结论

默认流程：

```text
amazon_rufus_get -> 成功 -> report_path
```

恢复流程：

```text
amazon_rufus_get 返回触发错误
  -> login_recovery_attempted=false
  -> 设置 login_recovery_attempted=true
  -> opscli amazon-rufus init <COUNTRY>
  -> 等待用户回复已登录
  -> opscli amazon-rufus get <ASIN> <COUNTRY> --launch-if-needed ...
  -> 成功返回 report_path，失败直接报错
```

## 验收

1. 两份 `SKILL.md` 都包含三类错误统一登录恢复和“每次 Skill 调用最多一次登录”。
2. 两份 `rufus-mcp-workflow.md` 都包含完整命令模板和二次失败规则。
3. `rg` 检查可定位触发错误集合和 `login_recovery_attempted`。
4. 模板目录与 `.agents` 对应文件内容一致。
