# ops-amazon-rufus-or-alexa Skill 改名架构

## 迁移边界

公开 Skill 名称统一为 `ops-amazon-rufus-or-alexa`。底层 Rufus 实现保持原名，形成两层边界：

```text
Skill 标识符: ops-amazon-rufus-or-alexa
    ├─ 模板/安装/升级/题库目录使用新名
    └─ MCP/CLI/Domain 实现继续使用 amazon_rufus_* / amazon-rufus / amazon_rufus
```

## 改动点

- 重命名 `opscli/skills/templates/ops-amazon-rufus-or-alexa/`、`.agents/skills/ops-amazon-rufus-or-alexa/`、`.claude/skills/ops-amazon-rufus-or-alexa/`。
- 更新 `manifest.json` 的注册键和三份 `VERSION.json` 的 `name`。
- 更新安装引导常量与升级白名单/分派条件。
- 更新题库服务的默认路径和错误提示。
- 更新测试夹具、路径断言、安装命令和同步契约。
- 更新所有文档及带旧标识符的产物文件名和内容。

## 一致性策略

整体移动 Skill 目录与相关文档路径，替换时排除已经使用新名称的引用；用 `rg` 检查旧名称与重复后缀，用原文件内容比对确认目录移动完整，并以临时目录验证实际安装、升级和题库读取。

模板与 `.agents` 的主文档、README、工作流和报告格式说明保持一致；题库 reference 的既有差异、`.claude` 原有简版说明、各副本版本与题库内容按原样保留。忽略规则只开放改名后的两个项目安装副本。
