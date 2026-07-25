# 仪表盘双 Skills 接入调研

## 1. 调研目标

将 `operation-frontend` 中的两份仪表盘领域 Skill 纳入 `open-opscli` 内置模板体系，使其可通过现有 `opscli skills install` 和 MCP `skills_install` 安装，同时保持页面工具、只读查询和发行边界清晰。

来源：

- `E:/code/work/operation-frontend/.agents/skills/dashboard-data-analysis`
- `E:/code/work/operation-frontend/.agents/skills/dashboard-ai-bridge`

调研日期：2026-07-21。

## 2. 来源资产盘点

| 来源 Skill | 文件 | 版本 | 性质 |
|---|---:|---:|---|
| `dashboard-data-analysis` | `SKILL.md`、`agents/openai.yaml`、`data/VERSION.json` | 1.0.3 | 纯提示词，只读分析编排 |
| `dashboard-ai-bridge` | `SKILL.md`、`data/VERSION.json`、3 份 `references/*.md` | 1.0.9 | 纯提示词，页面编辑工具编排 |

两者均无脚本、第三方依赖、账号、Token、绝对路径或直连 HTTP。Bridge 文档包含内部工具名、claim/result 路由、错误码和字段协议，属于运行合同，不是凭证。

## 3. 运行时依赖

两份 Skill 都不提供 `dashboard_*` 工具。实际工具由 `operation-frontend` 页面运行时按 `tool_context` 动态暴露：

- 页面上下文不合法时不向模型提供 Dashboard 工具。
- `manifest_version` 必须与 `dashboard-tools.v1` 匹配。
- 缺少页面上下文时返回 `DASHBOARD_CONTEXT_MISSING`。
- 来源 Bridge 文档引用的 24 个 `dashboard_*` 工具当前都存在于 46 工具 manifest 中。

因此，迁入 `open-opscli` 后能完成“发现、安装、加载规范”，不能让普通 `opscli-mcp` 会话凭空获得仪表盘编辑能力。Skill 必须明确：仅在仪表盘编辑页上下文且 `dashboard_session_get_context` 可用时执行，否则停止并说明入口要求。

真实数据查询依赖 `ops-dataset-query`。现有安装器按单个模板复制，不解析或自动安装兄弟 Skill，需在文档和验收中明确前置条件。

## 4. open-opscli 接入约束

### 4.1 命名

仓库铁律要求内置 Skill 使用 `ops-` 前缀。目标名称确定为：

- `ops-dashboard-data-analysis`
- `ops-dashboard-ai-bridge`

目录名、`SKILL.md` frontmatter `name`、`data/VERSION.json.name` 和跨 Skill 引用必须同步。旧名称继续由 `operation-frontend` 使用；本次不修改来源仓库。

### 4.2 版本

迁移会修改名称、兼容性声明和数据分析策略，因此使用补丁版本：

- `ops-dashboard-data-analysis`：`1.0.4`，`VERSION.json` 写 `v1.0.4`
- `ops-dashboard-ai-bridge`：`1.0.10`，`VERSION.json` 写 `v1.0.10`

仓库发布校验会去掉 `v` 前缀比较，frontmatter 和版本文件仍需语义版本一致。

### 4.3 自动接入能力

`SkillsManager.list_templates()` 会扫描包含 `data/VERSION.json` 的模板；`install()` 会复制到中央存储并链接到各运行时。新增纯本地模板无需修改：

- `opscli/cli.py`
- `opscli/mcp/server.py`
- `opscli/mcp/tools/query.py`
- `SkillsManager` 分发逻辑
- `SkillsUpdater` 远端升级白名单

本需求新增两个只读 MCP 规范工具：

- `dashboard_data_analysis_spec_must_read`：返回只读分析 `SKILL.md`。
- `dashboard_ai_bridge_spec_must_read`：合并返回 Bridge `SKILL.md` 和三份 references，并附完整 `sources`。

工具沿用 `query_spec_must_read` 的无参数、UTF-8 读取和 `_ok/_err` 响应模式，通过独立 `opscli.mcp.tools.dashboard` 模块注册。工具描述必须明确：它们只提供规范，不提供 `dashboard_*` 页面操作能力。

### 4.4 发版准入

`manifest.json` 默认拒绝未知模板。建议两项都采用：

```json
{
  "source": true,
  "wheel": true,
  "binary": false,
  "binary_full": true,
  "tier": "internal"
}
```

Python 发行包和完整二进制可安装；最小二进制不携带仅在运营前端可运行的文档型 Skill。

当前仓库已有与本需求无关的 manifest 基线问题：`ops-methods-card`、`ops-test-form` 目录未声明，`ops-canopy`、`ops-google-trends` 有声明但目录不存在。本次只保证不增加新的清单问题，不扩展修复范围。

## 5. 官方规范研究

[Agent Skills 规范](https://agentskills.io/specification)要求目录至少包含 `SKILL.md`，名称必须与目录一致，推荐通过 `references/` 渐进加载细节，并建议主文档控制在 500 行以内。来源 Bridge 的入口路由加 3 份 references 符合该结构。

[OpenAI Codex Skills 文档](https://developers.openai.com/codex/skills)说明：

- Codex 通过名称、描述和路径做初始发现。
- `agents/openai.yaml` 可定义展示名称、短描述、默认提示词和调用策略。
- Skill 依赖可声明静态 MCP 工具，但本需求的 `dashboard_*` 是动态页面工具，不适合伪装成固定 MCP 依赖。
- 可分发的多 Skill 组合长期可考虑 Plugin；当前仓库已有统一 Skill 安装体系，本期沿用现有机制。

## 6. 内容校准

来源数据分析 Skill 禁止“其他 Skill、项目记忆和 Handoff”，与当前 Dashboard 宿主策略冲突。目标版本调整为：

- 保留只读、禁止页面写、禁止用户 MCP、禁止用户文件产物。
- 允许宿主按普通对话规则使用系统 Skill、项目记忆、Planner、专家和 Handoff。
- 真实查询仍只能通过 `ops-dataset-query`，禁止直连数据库和自行猜查询参数。

Bridge 保留写后 `PASS/FAIL/BLOCKED` 核验、字段来源校验、失败后先读状态再重试等规则。

## 7. 风险与应对

| 风险 | 等级 | 应对 |
|---|---|---|
| 读取 MCP 规范后误以为 opscli 提供 Dashboard 工具 | 高 | tool docstring、frontmatter compatibility、SKILL 失败分支同时声明 |
| 两仓副本长期漂移 | 高 | 标记来源与迁移版本；本期以 open-opscli 为发行镜像，后续同步单独治理 |
| 内部消息桥协议进入发行包 | 中 | `tier=internal`，最小二进制排除；不新增公开 MCP API |
| `ops-dataset-query` 未安装 | 中 | 文档列为前置条件，测试典型安装流程 |
| Dashboard manifest 变更导致静态文档过期 | 中 | 测试冻结关键工具名与 `dashboard-tools.v1` 兼容标记 |
| 新模板遗漏 manifest | 中 | 增加 targeted packaging 测试 |

## 8. 推荐结论

按 `ops-` 新名称迁移两份纯文档 Skill，保留渐进加载结构，补齐运行环境和失败边界；复用通用安装链，并增加两个只读 MCP 规范读取工具。发行范围采用 source/wheel/binary-full，最小二进制排除。
