# 业务取数编排 Skill 落地计划

> 文档日期：2026-08-31  
> 实施范围：新增一个 Codex 业务层取数编排 Skill

## 1. 范围锁定

- 新建 `ops-business-data-orchestrator`。
- `ops-dataset-query` 保持不变。
- `ops-query-wizard` 保持不变。
- `ops-dashboard-ai-bridge` 保持不变。
- `ops-dashboard-data-analysis` 保持不变。
- `codex-custom-builder` 已废弃，不纳入范围。
- 不新增查询脚本、接口、数据库、同步、页面编辑或部署能力。

## 2. 项目集成清单

| 集成点 | 路径 | 动作 |
| --- | --- | --- |
| Skill 入口 | `opscli/skills/templates/ops-business-data-orchestrator/SKILL.md` | 新增 |
| 编排契约 | `opscli/skills/templates/ops-business-data-orchestrator/references/orchestration-contract.md` | 新增 |
| Codex UI | `opscli/skills/templates/ops-business-data-orchestrator/agents/openai.yaml` | 新增 |
| 版本 | `opscli/skills/templates/ops-business-data-orchestrator/data/VERSION.json` | 新增 |
| 发行清单 | `opscli/skills/templates/manifest.json` | 注册内部发行矩阵 |
| 静态评估 | `opscli/skills/evals/cases/ops-business-data-orchestrator.json` | 新增 |
| 自动化测试 | `tests/skills/test_ops_business_data_orchestrator_skill.py` | 新增 |
| 需求设计 | `docs/design/业务取数编排Skill需求与设计.md` | 新增 |
| 落地计划 | `docs/plans/业务取数编排Skill落地计划.md` | 新增 |

## 3. 无需改动的配置

- `opscli/skills/services/manager.py`：模板目录自动发现和整体安装。
- `opscli/skills/discovery/detector.py`：通过 `data/VERSION.json` 自动识别。
- `setup.py`：已递归打包模板文件。
- `MANIFEST.in`：已递归包含模板目录。
- `opscli/skills/sync/updater.py`：本次不增加专用远程升级分支。
- 任何现有 Skill 的 `SKILL.md`、引用、脚本和版本文件。

## 4. 发行策略

该 Skill 仅用于内部业务场景，发行层级设为 `internal`。由于它不依赖 Dashboard 页面工具，并且两个查询依赖均进入现有安装产物，计划进入以下产物：

- source：包含
- wheel：包含
- binary：包含
- binary_full：包含

## 5. 测试矩阵

### 5.1 元数据与安装

- 目录、frontmatter 和 `VERSION.json` 名称及版本一致。
- `agents/openai.yaml` 和编排契约随模板安装。
- `SkillsManager.list_templates()` 可以发现该 Skill。
- `SkillsManager.install()` 可以完整复制模板。

### 5.2 路由边界

- 单个明确查询 → `ops-dataset-query`。
- 单个模糊查询 → `ops-query-wizard`。
- 查询纠错 → `ops-query-wizard` 纠错模式。
- 复合业务取数 → `ops-business-data-orchestrator`。
- 当前 Dashboard 页面编辑 → 不触发。
- 当前 Dashboard 数据分析 → 不触发。

### 5.3 安全与范围

- 禁止直接调用底层查询入口。
- 禁止 Dashboard 页面上下文和页面工具。
- 禁止固定数据集、字段、凭证和本机路径。
- 禁止修改现有依赖 Skill。
- 完成原始目标后停止扩展。

## 6. 验证命令

```powershell
python scripts/skill_dev_loop/run_eval.py --skill ops-business-data-orchestrator --pretty
pytest tests/skills/test_ops_business_data_orchestrator_skill.py -q
pytest tests/skills/test_packaging.py tests/test_setup.py -q
```

## 7. 完成定义

- 模板目录和全部配套文件存在。
- manifest 声明完整且发行矩阵符合内部 Skill 定位。
- 静态 eval 得分达到 `1.0`。
- 专属测试和打包相关测试通过。
- 原临时项目目录在验证成功后清理。
