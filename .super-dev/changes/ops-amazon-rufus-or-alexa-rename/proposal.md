# 将 Amazon Rufus Skill 更名为 ops-amazon-rufus-or-alexa

## 问题

Amazon 商品页助手同时使用 Alexa 和 Rufus 术语，Skill 标识符需要包含两个名称。安装、升级、题库读取、测试和文档必须使用同一名称。

## 方案

把 Skill 的公开标识符、模板目录、已安装副本目录、manifest 注册键、题库路径、安装/升级提示、测试夹具和项目文档统一改为 `ops-amazon-rufus-or-alexa`。底层 MCP、CLI 和 Python 模块继续使用 Rufus 原名，保证实现接口不变。

## 验证

- 全仓搜索旧标识符无命中。
- 新目录和 manifest 注册键存在，旧目录不存在。
- 模板、`.agents`、`.claude` 副本名称同步，模板与 `.agents` 的主文档、README、工作流和报告格式说明一致，各副本已有版本和题库保留。
- 运行 Rufus Skill 升级、题库和安装 CLI 相关 pytest。
- `git diff --check` 通过。
