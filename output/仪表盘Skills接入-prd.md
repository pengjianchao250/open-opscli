# 仪表盘双 Skills 接入 PRD

## 1. 产品目标

让 opscli 用户能够安装仪表盘只读分析与页面编辑编排 Skill，并确保模型只在具备真实 Dashboard 页面工具的上下文中执行对应能力。

## 2. 目标用户

- 在运营系统仪表盘编辑页使用 AI 助手的运营人员。
- 通过 opscli 管理团队内置 Skill 的开发与运维人员。
- 在 Codex、Claude Code 或兼容运行时安装内部 Skill 的工程人员。

## 3. 用户故事

1. 用户可通过 `opscli skills install ops-dashboard-data-analysis` 安装只读分析 Skill。
2. 用户可通过 `opscli skills install ops-dashboard-ai-bridge` 安装页面编辑 Skill。
3. 在仪表盘页面上下文中，模型可按编辑、分析或组合目标选择对应 Skill。
4. 在普通终端或无页面上下文中，Skill 明确停止，不声称能操作仪表盘。
5. 真实数据分析始终复用 `ops-dataset-query`，不直连数据库。

## 4. 功能范围

### 4.1 `ops-dashboard-data-analysis`

- 读取 `dashboard_session_get_context`，确认仪表盘、图表、数据集和可用工具。
- 提取指标、维度、时间、筛选和比较口径。
- 通过 `ops-dataset-query` 执行只读查询。
- 输出趋势、对比、异常、排名、贡献和原因判断。
- 禁止修改图表、数据集、字段、筛选和查询控件。
- 禁止生成用户文件产物。

### 4.2 `ops-dashboard-ai-bridge`

- 路由加载操作规范、结果协议和工具流程。
- 支持新增、修改、删除和配置仪表盘图表。
- 支持数据集、字段、筛选、查询控件配置。
- 每次写操作后执行 `PASS/FAIL/BLOCKED` 核验门禁。
- 分析目标需要真实数据时组合 `ops-dataset-query`。
- 缺少 Dashboard 页面工具时停止执行。

### 4.3 安装与发现

- 两个模板进入 `SkillsManager.list_templates()`。
- CLI 和现有 MCP `skills_install` 均可安装。
- 安装复制完整 `agents/`、`data/`、`references/`。
- 不增加自动安装依赖；文档明确先安装 `ops-dataset-query`。

### 4.4 MCP 规范读取

- `dashboard_data_analysis_spec_must_read` 无参数返回分析 Skill 全文和来源路径。
- `dashboard_ai_bridge_spec_must_read` 无参数返回 Bridge 入口规范与三份 reference 合并全文和来源路径列表。
- 文件缺失或读取失败时返回统一结构化错误，并生成明确的 feedback 草案工具名。
- MCP 工具说明明确区分“读取规范”和“执行页面操作”。

## 5. 非功能要求

- 名称、目录和版本元数据一致。
- 所有文件 UTF-8，无敏感凭证和本机绝对路径。
- 主 `SKILL.md` 保持短小，细节使用 references 渐进加载。
- 不新增 Python/Node 运行依赖。
- 不修改 Query 和远端 Skill 升级逻辑；MCP Server 仅增加 dashboard 规范工具模块注册。
- 最小二进制不包含两项 Skill；source、wheel、binary-full 包含。

## 6. 不在范围

- 在 open-opscli 实现 `dashboard_*` 页面工具。
- 在 open-opscli 实现真实 `dashboard_*` 页面操作 Tool。
- 修改 operation-frontend 的系统提示、技能广场或发布脚本。
- 自动安装兄弟 Skill 依赖。
- 修复现有 manifest 的四项无关基线问题。
- 发布新 opscli 包版本。

## 7. 交付物

```text
opscli/skills/templates/
├── ops-dashboard-data-analysis/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── data/VERSION.json
└── ops-dashboard-ai-bridge/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── data/VERSION.json
    └── references/
        ├── bridge-result-protocol.md
        ├── dashboard-operation-standards.md
        └── tool-flow.md
```

同时更新：

- `opscli/skills/templates/manifest.json`
- `tests/skills/test_dashboard_skills.py`
- `opscli/mcp/tools/dashboard.py`
- `tests/mcp/test_dashboard_tools.py`
- 内置 Skill 用户文档和待发布变更记录

## 8. 验收标准

1. 两个目录名均以 `ops-` 开头。
2. 目录名、frontmatter `name`、`VERSION.json.name` 完全一致。
3. 版本分别为 `1.0.4`/`v1.0.4` 与 `1.0.10`/`v1.0.10`，归一化后一致。
4. 数据分析 Skill 的跨引用使用 `ops-dashboard-ai-bridge`。
5. Bridge 的三份 reference 完整复制，相对链接可读。
6. 两个 Skill 都声明 Dashboard 页面上下文和 `ops-dataset-query` 依赖。
7. 无页面上下文时明确停止，不尝试调用不存在的工具。
8. `SkillsManager.list_templates()` 能发现两项模板。
9. 安装测试确认所有文件被复制，且无 `__pycache__`、`.pyc`、`.pyo`。
10. manifest targeted 测试确认 wheel 和 binary-full 包含两项，binary-minimal 排除。
11. MCP `list_tools()` 可见两个 `dashboard_*_spec_must_read` 工具，输入 Schema 为空对象。
12. 两个 MCP 工具成功返回 `spec`、`source`、`sources`；Bridge `sources` 包含 4 个文件。
13. 文件缺失时返回 `success=false` 和明确工具名，不抛出裸异常。
14. 新增文件不包含真实 Token、账号、URL 凭证或本机绝对路径。
15. 全量测试若仅因既有 manifest 四项基线问题失败，报告中必须单独标识，不归因于本次变更。

## 9. 成功指标

- 两个安装命令均返回成功。
- 新增 targeted tests 全部通过。
- 文档型 Skill 不引入新的运行依赖，MCP 工具清单仅新增两个规范读取工具。
- 在 Dashboard 页面宿主中，已有 24 个文档引用工具名保持与 `dashboard-tools.v1` 合同一致。
