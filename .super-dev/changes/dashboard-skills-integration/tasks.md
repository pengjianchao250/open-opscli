# 仪表盘双 Skills 接入任务

## 1. Skill 模板

- [x] 创建 `ops-dashboard-data-analysis` 目录结构。
- [x] 编写只读分析 `SKILL.md`，加入页面上下文和依赖失败分支。
- [x] 添加 `agents/openai.yaml` 和 `data/VERSION.json`。
- [x] 创建 `ops-dashboard-ai-bridge` 目录结构。
- [x] 编写 Bridge `SKILL.md`，保留渐进加载路由和写后核验门禁。
- [x] 添加 Bridge 展示元数据和版本文件。
- [x] 迁移并校准三份 Bridge reference。

## 2. 发行与文档

- [x] 在 `manifest.json` 声明两项 internal Skill 及发行矩阵。
- [x] 更新 opscli 命令用例手册的内置 Skill 清单和安装示例。
- [x] 更新 Skills 基础开发培训手册的内置清单。
- [x] 更新待发布变更记录。

## 3. 测试

- [x] 增加目录、名称、版本和跨引用一致性测试。
- [x] 增加敏感信息、直连 HTTP 和路径边界测试。
- [x] 增加 `SkillsManager` 发现与安装测试。
- [x] 增加 manifest profile 选择测试。
- [x] 新增 `opscli.mcp.tools.dashboard` 和两个规范读取工具。
- [x] 在 MCP Server 注册 dashboard 工具模块。
- [x] 增加规范读取成功、缺文件和 MCP Schema 测试。
- [ ] 运行 targeted pytest。
- [ ] 运行相关 Skills 和 packaging 回归测试。
- [ ] 运行格式、静态检查和最小安装 smoke。

## 4. 交付检查

- [ ] 审查最终 diff，不包含 `uv.lock` 等用户已有无关修改。
- [ ] 记录既有 manifest 基线问题，避免误判为本次回归。
- [ ] 更新任务状态和交付摘要。
