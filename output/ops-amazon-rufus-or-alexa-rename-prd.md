# ops-amazon-rufus-or-alexa Skill 改名需求

## 用户场景

用户安装、升级或调用 Amazon Rufus/Alexa Skill 时，使用新标识符 `ops-amazon-rufus-or-alexa`，不再依赖旧目录名或旧安装命令。

## 功能要求

1. 模板元数据的 `name` 改为 `ops-amazon-rufus-or-alexa`。
2. 内置模板 manifest、安装后引导、升级分派和题库路径统一使用新标识符。
3. 模板、`.agents`、`.claude` 的名称和目录统一；模板与 `.agents` 的主文档、工作流和报告格式说明保持一致，各副本已有版本和题库内容保留。
4. 相关测试和断言改用新标识符，并覆盖新目录可安装、新目录可升级、新目录可读取题库。
5. 项目内文档、流程图源文件、Super Dev 产物和变更日志中的旧 Skill 标识符全部更新。

## 非目标

- 不改 `amazon_rufus_*` MCP schema。
- 不改 `opscli amazon-rufus` CLI 命令。
- 不改 `opscli/amazon_rufus` Python 包、类名、函数名或服务端接口。
- 不改变题库内容、版本号和登录流程。

## 验收标准

- 全项目扫描旧 Skill 名称与重复追加的后缀，无业务引用残留；搜索排除新名称包含的旧前缀和 Git/虚拟环境缓存。
- 新目录和 manifest 名称存在，旧目录不存在。
- 模板、`.agents`、`.claude` 副本名称同步，安装副本可被 Git 识别。
- 相关 pytest 通过，`git diff --check` 通过。
