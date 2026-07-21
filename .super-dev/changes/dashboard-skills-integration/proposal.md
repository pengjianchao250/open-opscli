# 仪表盘双 Skills 接入提案

## 目标

将 operation-frontend 的仪表盘只读分析和页面编辑 Skill 迁入 opscli 内置模板，并纳入现有安装、发行和测试体系。

## 变更范围

- 新增 `ops-dashboard-data-analysis`，版本 `1.0.4`。
- 新增 `ops-dashboard-ai-bridge`，版本 `1.0.10`。
- 为两项 Skill 提供 `agents/openai.yaml` 展示元数据。
- 完整迁移 Bridge 的三份渐进加载参考文档。
- 新增两个无参数 MCP 规范读取工具。
- 更新内置模板发版清单。
- 增加结构、内容、安装和发行矩阵测试。
- 更新内置 Skill 用户文档与待发布变更记录。

## 架构决策

- 使用仓库强制的 `ops-` 前缀，不保留旧目录名别名。
- 两项 Skill 都是提示词和领域合同，不提供新的 Python 业务模块。
- Dashboard 页面工具仍由 operation-frontend 动态注入。
- 真实数据查询依赖现有 `ops-dataset-query`。
- 通过独立 `opscli.mcp.tools.dashboard` 注册规范读取 Tool，不修改 Query Tool 和 `SkillsUpdater`。
- source、wheel、binary-full 收录；binary-minimal 排除。

## 兼容性

- 无 Dashboard 页面上下文时，Skill 必须停止并提示从仪表盘编辑页进入。
- 安装器不会自动安装兄弟 Skill，文档必须声明 `ops-dataset-query` 前置条件。
- operation-frontend 中旧名称保持不变，本次不修改来源仓库。
- MCP 规范工具只读取文档，不能替代 operation-frontend 注入的页面 Tool。

## 验证

- 目标 pytest 文件全部通过。
- 两个模板可由 `SkillsManager` 发现并安装到临时目录。
- FastMCP 可发现两个规范工具，且返回来源完整的统一响应。
- manifest profile 选择符合冻结矩阵。
- 新增内容不含敏感凭证、直连 HTTP 或本机绝对路径。
- 全量质量检查单独报告既有 manifest 基线问题。
