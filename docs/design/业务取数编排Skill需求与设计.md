# 业务取数编排 Skill 需求与设计

> 文档日期：2026-08-31  
> Skill 标识：`ops-business-data-orchestrator`  
> 正式源码：`opscli/skills/templates/ops-business-data-orchestrator/`

## 1. 建设背景

业务人员在 Codex 中通过自然语言提出取数需求。为后续搭建个性化看板准备数据时，一个业务主题通常包含多个独立问题，例如总览、趋势、排名、结构、风险和明细。

现有通用能力已经覆盖单个查询：

- `ops-dataset-query` 负责信息明确的正式查询。
- `ops-query-wizard` 负责单查询的澄清和结果纠错。

当前缺口是 Codex 业务层编排：把复合业务主题拆成有限的数据问题，组织使用现有 Skill，并汇总真实查询结果。

## 2. 最终定位

`ops-business-data-orchestrator` 是 Codex 中使用的业务层复合取数编排 Skill。

它负责：

1. 理解业务人员的数据目标。
2. 区分单个查询和复合业务取数需求。
3. 将复合主题拆成有限、互不重复的数据问题。
4. 将清晰问题交给 `ops-dataset-query`。
5. 将模糊、缺参或有歧义的问题交给 `ops-query-wizard`。
6. 将错误结果交给 `ops-query-wizard` 纠错。
7. 汇总每个问题的真实数据范围、结果、限制和状态。

“为看板准备数据”只表示提供后续搭建看板所需的数据，不表示操作 Dashboard 页面。

## 3. 与现有 Skill 的边界

| 用户意图 | 负责 Skill |
| --- | --- |
| 单个明确查询 | `ops-dataset-query` |
| 单个模糊查询或查询纠错 | `ops-query-wizard` |
| 为后续业务使用准备多组数据 | `ops-business-data-orchestrator` |
| 创建或修改当前 Dashboard 页面 | `ops-dashboard-ai-bridge` |
| 分析当前已绑定 Dashboard | `ops-dashboard-data-analysis` |

新 Skill 无需 Dashboard 页面上下文，不调用 `dashboard_session_get_context`，不读取、分析或修改当前看板。

## 4. 硬边界

- 不修改 `ops-dataset-query` 和 `ops-query-wizard`。
- 不直接调用 `opscli query` 或查询 MCP Tool 绕过现有 Skill。
- 不复制底层数据集、字段、公式、筛选和查询执行规则。
- 不保存固定数据集 ID、字段 ID 或认证信息。
- 不创建或修改看板页面、图表、站点、接口或数据库。
- 不建设数据同步、定时任务、部署和发布流程。
- 不考虑已废弃的 `codex-custom-builder`。
- 不根据未执行的查询虚构业务结果。

## 5. 核心工作流

```text
Codex 中的复合业务取数需求
        ↓
识别业务目标与已确认范围
        ↓
判断单个查询或复合主题
        ↓
拆解有限的数据问题清单
        ↓
清晰问题 → ops-dataset-query
模糊问题 → ops-query-wizard
错误结果 → ops-query-wizard 纠错
        ↓
记录每项真实结果与状态
        ↓
按原始业务目标汇总并停止
```

## 6. 任务结构

业务层任务只保存业务问题及真实返回摘要，不保存底层查询实现。详细字段、状态和输出模板见：

- `opscli/skills/templates/ops-business-data-orchestrator/references/orchestration-contract.md`

核心状态包括：

- `pending`
- `running`
- `success`
- `blocked`
- `needs_confirmation`
- `not_run`

部分查询失败时保留成功结果，不用一个总状态覆盖全部问题。

## 7. 项目架构适配

### 7.1 模板发现

`SkillsManager.list_templates()` 自动扫描 `opscli/skills/templates/` 下包含 `data/VERSION.json` 的目录。因此新增模板后无需修改 `manager.py` 或发现器。

### 7.2 安装

`SkillsManager.install()` 会整体复制模板目录，`agents/`、`references/` 和 `data/` 会随 Skill 一起安装。无需新增安装分支。

### 7.3 打包

`setup.py` 的 `package_data` 与 `MANIFEST.in` 已递归包含模板目录。新增 Skill 不需要修改这两个文件，但必须在 `opscli/skills/templates/manifest.json` 声明发行矩阵。

### 7.4 版本

- `SKILL.md` 顶层使用 `version: 0.0.1`。
- `data/VERSION.json` 使用 `v0.0.1`。
- 测试按去除 `v` 前缀后的版本一致性校验。

### 7.5 行为门禁

- 静态 eval 位于 `opscli/skills/evals/cases/ops-business-data-orchestrator.json`。
- 专属测试位于 `tests/skills/test_ops_business_data_orchestrator_skill.py`。

## 8. 验收标准

1. 单个明确查询不会被拆成多个问题。
2. 单个模糊查询直接进入查询向导。
3. 复合业务主题可拆成有限、互不重复的问题。
4. 每个问题都有业务用途和结果类型。
5. 新 Skill 只编排两个现有查询 Skill。
6. 无需 Dashboard 页面上下文。
7. 当前 Dashboard 分析和页面编辑请求不会被新 Skill 截获。
8. 结果只能基于真实查询返回。
9. 部分失败时保留成功结果并标明阻塞项。
10. 回答原始业务目标后停止扩展查询。

## 9. 最终结论

本项目只新增 `ops-business-data-orchestrator`，不修改任何现有 Skill。其职责是：

> 在 Codex 中拆解复合业务取数需求，编排 `ops-dataset-query` 与 `ops-query-wizard`，并汇总真实结果。
