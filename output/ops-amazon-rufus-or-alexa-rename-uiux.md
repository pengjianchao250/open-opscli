# ops-amazon-rufus-or-alexa Skill 文档与命令体验

## 用户看到的变化

- 安装命令显示：`opscli skills install ops-amazon-rufus-or-alexa`。
- 升级命令显示：`opscli skills upgrade ops-amazon-rufus-or-alexa`。
- Skill 目录显示：`ops-amazon-rufus-or-alexa/`。
- 运行时 MCP 工具和 CLI fallback 文案继续显示现有 `amazon_rufus_*` 与 `opscli amazon-rufus`，保证底层接口兼容。

## 文案规则

主文档、README、题库 reference、安装后 next_steps、测试输出和历史流程材料统一使用新 Skill 名称。涉及底层能力时继续明确写出 Rufus MCP/CLI 名称，避免把 Skill 改名误解成接口改名。

## 回归重点

安装/升级失败提示不能再给出旧命令；题库缺失提示必须指向新目录；三份副本打开后首行 front matter 的 `name` 必须一致。
