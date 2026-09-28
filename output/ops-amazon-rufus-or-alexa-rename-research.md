# ops-amazon-rufus-or-alexa Skill 改名研究

## 目标

将内置 Amazon Rufus Skill 的公开标识符统一为 `ops-amazon-rufus-or-alexa`，并清理整个项目对旧 Skill 标识符的引用。

## 调研定位与迁移后路径

- 模板目录为 `opscli/skills/templates/ops-amazon-rufus-or-alexa/`。
- 已安装项目副本为 `.agents/skills/ops-amazon-rufus-or-alexa/` 和 `.claude/skills/ops-amazon-rufus-or-alexa/`。
- `opscli/skills/templates/manifest.json` 注册模板，需同步注册键。
- `opscli/skills/commands/cli.py` 按名称追加安装后登录引导。
- `opscli/skills/services/manager.py` 按名称分派题库升级。
- `opscli/amazon_rufus/services/question_bank.py` 读取 Skill 目录中的题库并生成安装提示。
- `opscli/skills/sync/updater.py` 提供该 Skill 的题库升级入口。
- 测试覆盖安装输出、升级分派、模板同步、题库路径和文档契约。
- `opscli/mcp/tools/amazon_rufus.py`、`opscli/amazon_rufus/` 和 `opscli amazon-rufus` 是底层 Rufus 能力接口，不属于本次 Skill 标识符改名。

## 影响面

全项目精确搜索旧标识符命中源码、测试、模板副本、Super Dev 产物、`output` 文档、变更日志和若干路径名。路径名也需要同步，否则安装、升级、题库读取和文档链接会出现新旧名称分裂。

## 约束

1. 只替换 Skill 标识符 `ops-amazon-rufus-or-alexa`。
2. 保留 MCP 工具名 `amazon_rufus_*`、CLI 子命令 `amazon-rufus` 和 Python 包 `amazon_rufus`。
3. 模板与 `.agents` 的主文档、README、工作流和报告格式说明保持一致；三个目录名称统一，各副本已有题库与版本保留。
4. 不提交、不推送、不部署。
