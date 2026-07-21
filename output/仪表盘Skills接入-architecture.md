# 仪表盘双 Skills 接入架构

## 1. 架构原则

- 模板负责指令和领域合同，页面宿主负责 `dashboard_*` 工具实现。
- opscli 负责发现、安装、分发，不复制 operation-frontend 的 Bridge 代码。
- 真实数据查询复用 `ops-dataset-query`。
- 纯本地 Skill 不进入远端升级白名单。
- 动态页面工具不能伪装成固定 MCP 依赖。
- MCP 只暴露规范读取工具，页面操作能力仍由 Dashboard 宿主提供。

## 2. 组件关系

```text
opscli 内置模板
  ├─ ops-dashboard-data-analysis
  └─ ops-dashboard-ai-bridge
           │
           ▼
SkillsManager.list_templates / install
           │
           ▼
中央 Skills 存储 + 各 Agent 运行时链接
           │
           ▼
operation-frontend Dashboard AI 会话
  ├─ dashboard_session_*        页面上下文
  ├─ dashboard_editor_*         图表编辑
  ├─ dashboard_drag_*           数据集/字段/筛选配置
  └─ ops-dataset-query          真实业务数据查询

opscli MCP Server
  └─ tools/dashboard.py
       ├─ dashboard_data_analysis_spec_must_read
       └─ dashboard_ai_bridge_spec_must_read
              │
              └─ 只读 templates 中的规范文件
```

普通 CLI/MCP 会话只能完成模板安装和规范加载。只有 operation-frontend 注入合法 `tool_context` 后，Dashboard 工具才可执行。

## 3. 文件映射

| 来源 | 目标 | 改造 |
|---|---|---|
| `dashboard-data-analysis/SKILL.md` | `ops-dashboard-data-analysis/SKILL.md` | 名称、版本、兼容性、策略边界、跨引用 |
| `dashboard-data-analysis/agents/openai.yaml` | 同级目标 | 保留展示信息，更新默认提示词 |
| `dashboard-data-analysis/data/VERSION.json` | 同级目标 | 名称改为 `ops-*`，版本 `v1.0.4` |
| `dashboard-ai-bridge/SKILL.md` | `ops-dashboard-ai-bridge/SKILL.md` | 名称、版本、兼容性和前置检查 |
| `dashboard-ai-bridge/references/*` | 同级目标 | 完整复制，校准 Skill 名称和兼容标记 |
| 无 | `ops-dashboard-ai-bridge/agents/openai.yaml` | 新增 Codex 展示元数据 |
| 无 | `opscli/mcp/tools/dashboard.py` | 新增两个只读规范读取 MCP Tool |

## 4. 激活与执行流程

### 4.1 只读分析

1. Skill 被明确调用或描述匹配。
2. 检查 `dashboard_session_get_context` 是否存在。
3. 读取页面上下文，确认当前数据集和图表。
4. 检查 `ops-dataset-query` 是否可用。
5. 按真实数据查询规范执行只读查询。
6. 输出业务结论，不修改页面，不生成用户文件。

缺少步骤 2 或 4 时停止，说明所需入口或依赖，不降级为猜测分析。

### 4.2 页面编辑

1. 读取 `references/dashboard-operation-standards.md`。
2. 调用 `dashboard_session_get_context`，只使用 `availableTools`。
3. 根据用户目标选择现有图表复用或新增图表。
4. 数据集、字段和筛选只使用工具返回的真实标识。
5. 每个写操作后完成 `PASS/FAIL/BLOCKED` 核验。
6. 需要真实分析时组合 `ops-dataset-query`。
7. 只汇报业务结果，不暴露内部 ID 和桥协议。

## 5. 安装架构

`SkillsManager` 已提供完整通用路径：

```text
模板目录 + VERSION.json
        │
        ├─ list_templates() 自动发现
        │
        └─ install(skill_name)
              ├─ 复制到中央存储
              └─ 链接到 Codex/Claude/OpenCode 等目标目录
```

因此不增加名称分发分支。更新随 opscli 新版本交付，已安装旧模板通过 `opscli skills install <name> --force` 覆盖；不支持 `opscli skills upgrade <name>` 远端升级。

推荐安装顺序：

```powershell
opscli skills install ops-dataset-query
opscli skills install ops-dashboard-data-analysis
opscli skills install ops-dashboard-ai-bridge
```

## 6. MCP 架构

`opscli.mcp.tools.dashboard` 采用与 `query_spec_must_read` 相同的模块级异步函数和批量注册模式：

```text
server.py
  └─ dashboard_tools.register(_telemetry_mcp)
       ├─ dashboard_data_analysis_spec_must_read()
       │    └─ ops-dashboard-data-analysis/SKILL.md
       └─ dashboard_ai_bridge_spec_must_read()
            ├─ ops-dashboard-ai-bridge/SKILL.md
            └─ references/*.md
```

路径统一通过 `get_builtin_templates_dir()` 解析，兼容普通 Python 包、测试覆盖和 PyInstaller。成功响应使用 `_ok()`；缺文件和读取异常使用 `_err(..., tool="MCP → ...")`。两个函数不接收凭证、不调用 QueryManager、不发网络请求。

Bridge 规范按固定顺序合并：入口、操作规范、结果协议、工具流程。响应同时返回主入口 `source` 和所有文件的 `sources`，调用方可审计实际来源。

## 7. 发行架构

manifest 配置：

| Skill | source | wheel | binary | binary_full | tier |
|---|---:|---:|---:|---:|---|
| `ops-dashboard-data-analysis` | true | true | false | true | internal |
| `ops-dashboard-ai-bridge` | true | true | false | true | internal |

该配置保证 Python 发行和完整二进制可安装，同时控制最小二进制体积和能力误导。

## 8. 安全边界

- 数据分析 Skill 只允许读风险页面工具和 `ops-dataset-query`。
- Bridge 写操作必须来自用户明确业务目标，关键参数有歧义时询问。
- 写失败、超时或网络异常后先重读页面状态，禁止盲目重试。
- 不携带凭证、环境地址或真实 claim token。
- 不在普通 MCP 会话宣称 Dashboard 页面能力可用。
- 用户文件、下载链接和办公文档产物保持禁止。
- MCP docstring 明确规范读取不等于页面工具可用。

## 9. 测试架构

新增 `tests/skills/test_dashboard_skills.py`，覆盖：

- 文件结构与 references 完整性。
- 目录、frontmatter、VERSION 名称和版本一致性。
- 跨 Skill 引用和 Dashboard 前置条件。
- 禁止直连 HTTP、敏感查询字段和本机路径。
- `SkillsManager.list_templates()` 自动发现。
- 两个模板通过临时目录完成安装复制。
- manifest profile 选择符合发行矩阵。
- 两个规范读取函数的成功、缺文件和来源顺序。
- FastMCP 工具清单、无参数 Schema 和统一响应结构。

质量验证命令在实现阶段确定，至少包含 targeted pytest、Skill 安装 smoke 和 manifest 检查。全量 manifest 已有四项基线问题，结果需区分新增回归与存量失败。

## 10. 变更边界

不修改 `query.py`、Dashboard 前端工具实现、远端 updater 和包版本。`server.py` 只增加 dashboard 工具模块导入与注册。真实页面操作 Tool、依赖自动安装、双仓自动同步均留待独立需求。
